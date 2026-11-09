import math
from collections import OrderedDict
from django import template
from django.core.paginator import Paginator, EmptyPage
from django.utils.html import escape
from django.http import Http404
from django.utils.encoding import smart_str
from urllib.parse import quote as urlquote
from django.utils.safestring import mark_safe
from django.utils.html import strip_tags

def generate_uri(querydict, exclude=None):
    all = []

    for k, l in querydict.lists():
        if (not exclude) or (k not in exclude):
            all += ["%s=%s" % (k, escape(urlquote(strip_tags(v)))) for v in l]

    return "&".join(all)

class SortBase:
    def __init__(self, label, description=''):
        self.label = label
        self.description = description

class SimpleSort(SortBase):
    def __init__(self, label, order_by, description=''):
        super() .__init__(label, description)
        self.order_by = order_by

    def _get_order_by(self):
        return isinstance(self.order_by, (list, tuple)) and self.order_by or [self.order_by]

    def apply(self, objects):
        if self.order_by:
            return objects.order_by(*self._get_order_by())

        return objects

class PaginatorContext:
    visible_page_range = 5
    outside_page_range = 1

    base_path = None

    def __init__(self, id, sort_methods=None, default_sort=None, force_sort = None,
                 pagesizes=None, default_pagesize=None, prefix=''):
        self.id = id
        if sort_methods:
            self.has_sort = True
            self.sort_methods = OrderedDict(sort_methods)

            if not default_sort:
                default_sort = sort_methods[0][0]

            self.default_sort = default_sort
        else:
            self.has_sort = False


        if pagesizes:
            self.has_pagesize = True
            self.pagesizes = pagesizes

            if not default_pagesize:
                self.default_pagesize = pagesizes[int(math.ceil(float(len(pagesizes)) / 2)) - 1]
            else:
                self.default_pagesize = default_pagesize
        else:
            self.has_pagesize = False

        self.force_sort = force_sort
        self.prefix = prefix

    def preferences(self, request):
        # A copy: callers modify it, and set_preferences() compares it with the
        # stored value to avoid a write on every page view.
        if request.user.is_authenticated:
            if request.user.prop.pagination:
                preferences = request.user.prop.pagination.get(self.id, {})
            else:
                preferences = {}
        else:
            preferences = request.session.get('paginator_%s%s' % (self.prefix, self.id), {})

        return dict(preferences)

    def set_preferences(self, request, preferences):
        if request.user.is_authenticated:
            all_preferences = dict(request.user.prop.pagination or {})
            if all_preferences.get(self.id, {}) == preferences:
                return
            all_preferences[self.id] = preferences
            request.user.prop.pagination = all_preferences
        else:
            key = 'paginator_%s%s' % (self.prefix, self.id)
            if request.session.get(key, {}) != preferences:
                request.session[key] = preferences

    def pagesize(self, request, session_prefs=None):
        # `is None`: an empty dict is the caller's, to be filled and saved.
        if session_prefs is None:
            session_prefs = self.preferences(request)


        if self.has_pagesize:
            if request.GET.get(self.PAGESIZE, None):
                try:
                    pagesize = int(request.GET[self.PAGESIZE])
                except ValueError:
                    raise Http404()

                session_prefs[self.PAGESIZE] = pagesize
            else:
                pagesize = session_prefs.get(self.PAGESIZE, self.default_pagesize)

            if pagesize not in self.pagesizes:
                pagesize = self.default_pagesize
        else:
            pagesize = 30

        return pagesize

    def page(self, request):
        try:
            return int(request.GET.get(self.PAGE, "1").strip())
        except ValueError:
            raise Http404()

    def sort(self, request, session_prefs=None):
        # `is None`: an empty dict is the caller's, to be filled and saved.
        if session_prefs is None:
            session_prefs = self.preferences(request)

        sort = None
        sticky = request.user.is_authenticated and request.user.prop.preferences and request.user.prop.preferences.get('sticky_sorts', False)

        if self.has_sort:
            if request.GET.get(self.SORT, None):
                sort = request.GET[self.SORT]

                if sticky:
                    session_prefs[self.SORT] = sort
            else:
                sort = self.force_sort or (sticky and session_prefs.get(self.SORT, None)) or self.default_sort

            if sort not in self.sort_methods:
                sort = self.default_sort

        return sort

    def sorted(self, objects, request, session_prefs=None):
        sort = self.sort(request, session_prefs)

        if sort:
            objects = self.sort_methods[sort].apply(objects)

        return sort, objects

    @property
    def PAGESIZE(self):
        return self.prefix and "%s_%s" % (self.prefix, 'pagesize') or 'pagesize'

    @property
    def PAGE(self):
        return self.prefix and "%s_%s" % (self.prefix, 'page') or 'page'

    @property
    def SORT(self):
        return self.prefix and "%s_%s" % (self.prefix, 'sort') or 'sort'

page_numbers_template = template.loader.get_template('paginator/page_numbers.html')
page_sizes_template = template.loader.get_template('paginator/page_sizes.html')
sort_tabs_template = template.loader.get_template('paginator/sort_tabs.html')

def paginated(request, paginators, tpl_context):
    if len(paginators) == 2 and isinstance(paginators[0], str):
        paginators = (paginators,)

    for list_name, context in paginators:
        tpl_context[list_name] = _paginated(request, tpl_context[list_name], context)

    return tpl_context

def _paginated(request, objects, context):
    session_prefs = context.preferences(request)

    pagesize = context.pagesize(request, session_prefs)
    page = context.page(request)
    sort, objects = context.sorted(objects, request, session_prefs)

    paginator = Paginator(objects, pagesize)

    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        # A page past the end (old links, crawlers): a 404, which Django already logs as a warning.
        raise Http404()

    if context.base_path:
        base_path = context.base_path
    else:
        base_path = request.path
        get_params = generate_uri(request.GET, (context.PAGE, context.PAGESIZE, context.SORT))

        if get_params:
            base_path += "?" + get_params

    url_joiner = "?" in base_path and "&amp;" or "?"


    def get_page():
        object_list = page_obj.object_list

        #if hasattr(object_list, 'lazy'):
        #    return object_list.lazy()
        return object_list
    paginator.page = get_page()

    total_pages = paginator.num_pages

    if total_pages > 1:

        total_pages = paginator.num_pages

        has_previous = page > 1
        has_next = page < total_pages

        range_start = page - context.visible_page_range // 2
        range_end = page + context.visible_page_range // 2

        if range_start < 1:
            range_end = context.visible_page_range
            range_start = 1

        if range_end > total_pages:
            range_start = total_pages - context.visible_page_range + 1
            range_end = total_pages
            if range_start < 1:
                range_start = 1

        page_numbers = []

        if sort:
            url_builder = lambda n: mark_safe("%s%s%s=%s&amp;%s=%s" % (escape(base_path), url_joiner, context.SORT, sort, context.PAGE, n))
        else:
            url_builder = lambda n: mark_safe("%s%s%s=%s" % (escape(base_path), url_joiner, context.PAGE, n))

        if range_start > (context.outside_page_range + 1):
            page_numbers.append([(n, url_builder(n)) for n in range(1, context.outside_page_range + 1)])
            page_numbers.append(None)
        elif range_start > 1:
            page_numbers.append([(n, url_builder(n)) for n in range(1, range_start)])

        page_numbers.append([(n, url_builder(n)) for n in range(range_start, range_end + 1)])

        if range_end < (total_pages - context.outside_page_range):
            page_numbers.append(None)
            page_numbers.append([(n, url_builder(n)) for n in range(total_pages - context.outside_page_range + 1, total_pages + 1)])
        elif range_end < total_pages:
            page_numbers.append([(n, url_builder(n)) for n in range(range_end + 1, total_pages + 1)])

        page_numbers_context = {
            'has_previous': has_previous,
            'previous_url': has_previous and url_builder(page - 1) or None,
            'has_next': has_next,
            'next_url': has_next and url_builder(page + 1) or None,
            'current': page,
            'page_numbers': page_numbers
        }

        paginator.page_numbers_context = page_numbers_context

        def page_nums():
            # Django 2.0+: template.render() requires dict, not Context
            return page_numbers_template.render(page_numbers_context)

        # Call the function immediately to get the rendered string
        paginator.page_numbers = page_nums()
    else:
        paginator.page_numbers = ''

    if pagesize:
        def page_sizes():
            if sort:
                url_builder = lambda s: mark_safe("%s%s%s=%s&amp;%s=%s" % (escape(base_path), url_joiner, context.SORT, sort, context.PAGESIZE, s))
            else:
                url_builder = lambda s: mark_safe("%s%s%s=%s" % (escape(base_path), url_joiner, context.PAGESIZE, s))

            sizes = [(s, url_builder(s)) for s in context.pagesizes]

            # Django 2.0+: template.render() requires dict, not Context
            return page_sizes_template.render({
                'current': pagesize,
                'sizes': sizes
            })

        # Call the function immediately to get the rendered string
        paginator.page_sizes = page_sizes()
    else:
        paginator.page_sizes = ''

    if sort:
        def sort_tabs():
            url_builder = lambda s: mark_safe("%s%s%s=%s" % (escape(base_path), url_joiner, context.SORT, s))
            sorts = [(n, s.label, url_builder(n), strip_tags(s.description)) for n, s in context.sort_methods.items()]

            for name, label, url, descr in sorts:
                paginator.__dict__['%s_sort_link' % name] = smart_str(url)

            # Django 2.0+: template.render() requires dict, not Context
            return sort_tabs_template.render({
                'current': sort,
                'sorts': sorts,
                'sticky': session_prefs.get('sticky_sort', False)
            })
        paginator.sort_tabs = sort_tabs()
        paginator.sort_description = mark_safe(context.sort_methods[sort].description)
        paginator.current_sort = sort
    else:
        paginator.sort_tabs = paginator.sort_description = ''
        paginator.current_sort = ''

    context.set_preferences(request, session_prefs)
    objects.paginator = paginator
    return objects
