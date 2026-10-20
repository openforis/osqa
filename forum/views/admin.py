from datetime import datetime, timedelta
import json
import time

from django.views.decorators.http import require_POST, require_http_methods
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.http import HttpResponseRedirect, HttpResponse, Http404
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.db import models
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils.html import escape
from django.utils.text import Truncator
from django.utils.safestring import mark_safe

from django.contrib import messages

from forum.http_responses import HttpResponseUnauthorized
from forum.settings.base import Setting
from forum.forms import MaintenanceModeForm, PageForm, CreateUserForm
from forum.settings.forms import SettingsSetForm
from forum.settings import guides
from forum.utils import pagination, html
from forum.utils import security_log
from forum.utils import review
from forum.views.security import require_staff_two_factor
from forum.utils.mail import send_template_email
from forum.models import Question, Answer, User, Node, Action, Page, NodeState, Tag, ModerationReport
from forum.models.node import NodeMetaClass
from forum.actions import NewPageAction, EditPageAction, PublishAction, DeleteAction, UserJoinsAction, CloseAction
from forum import settings

TOOLS = {}
# Admin pages with a URL of their own (url name, label), listed with the tools.
TOOL_LINKS = []

def super_user_required(fn):
    # Staff who must use two-step verification (Admin > Security) set it up first.
    @require_staff_two_factor
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            return fn(request, *args, **kwargs)
        else:
            return HttpResponseUnauthorized(request)

    return wrapper

def staff_user_required(fn):
    @require_staff_two_factor
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
            return fn(request, *args, **kwargs)
        else:
            return HttpResponseUnauthorized(request)

    return wrapper

# The admin menu's fixed groups of settings pages (SettingSet names); every
# other set is listed under "Other settings", so a module's new set shows up
# without changes here.
MENU_SETTINGS = (
    ('basic-sets-menu', _lazy("Basic settings"), ('basic', 'users', 'email', 'paths', 'urls', 'extkeys')),
    ('workflow-sets-menu', _lazy("Workflow settings"), ('repgain', 'minrep', 'voting', 'accept', 'badges')),
    ('forum-sets-menu', _lazy("Forum settings"), ('form', 'view', 'moderation')),
    ('look-sets-menu', _lazy("Look and feel"), ('appearance', 'css', 'headandfoot', 'head')),
    ('pages-sets-menu', _lazy("Static content"), ('about', 'faq', 'sidebar')),
)


def _menu_item(request, url, label, **extra):
    current = request.path == url or (url != reverse('admin_index') and request.path.startswith(url))
    return dict(extra, url=url, label=label, current=current)


def admin_menu(request, unsaved, counts=None):
    """The admin menu as data: [{'id', 'title', 'items': [{'url', 'label',
    'current', 'unsaved', 'count'}]}]. Moderators (staff) get the moderation
    pages only; superusers every settings page and tool, including the tools
    modules register (admin_tools_page, TOOL_LINKS)."""
    item = lambda url, label, **extra: _menu_item(request, url, label, **extra)
    groups = [{'id': 'moderation-menu', 'title': _("Moderation"), 'items': [
        item(reverse('admin_moderation'), _("Moderation inbox"), count=(counts or {}).get('total')),
        item(reverse('admin_support'), _("Support dashboard")),
        item(reverse('admin_email_previews'), _("Email previews")),
    ]}]
    if not request.user.is_superuser:
        return groups

    def set_item(s):
        return item(reverse('admin_set', args=[s.name]), s.title, unsaved=s.name in unsaved)

    fixed = set()
    for group_id, title, names in MENU_SETTINGS:
        fixed.update(names)
        items = [set_item(Setting.sets[name]) for name in names if name in Setting.sets]
        if group_id == 'pages-sets-menu':
            items.insert(0, item(reverse('admin_static_pages'), _("Custom Pages")))
        groups.append({'id': group_id, 'title': title, 'items': items})
    others = sorted([s for s in Setting.sets.values() if s.name not in fixed], key=lambda s: s.weight)
    groups.append({'id': 'other-sets-menu', 'title': _("Other settings"), 'items': [set_item(s) for s in others]})
    groups.append({'id': 'tools-menu', 'title': _("Tools"), 'items': [
        item(reverse('admin_maintenance'), _("Maintenance mode")),
        item(reverse('admin_statistics'), _("Statistics")),
    ] + [item(url, label) for url, label in admin_tools()]})
    return [g for g in groups if g['items']]


def admin_tools():
    """(url, label) of the tools: admin_tools_page() views and TOOL_LINKS."""
    return [(reverse('admin_tools', args=[name]), fn.label) for name, fn in TOOLS.items()] + \
           [(reverse(url_name), label) for url_name, label in TOOL_LINKS]


def admin_page_wrapper(fn, request, *args, **kwargs):
    res = fn(request, *args, **kwargs)
    if isinstance(res, HttpResponse):
        return res

    template, context = res
    # Templates of older modules extend `basetemplate`; there is one layout.
    context['basetemplate'] = "osqaadmin/base.html"
    context['allsets'] = Setting.sets
    context['othersets'] = sorted(
            [s for s in Setting.sets.values() if s.name not in
             {name for _id, _title, names in MENU_SETTINGS for name in names}],
            key=lambda s: s.weight)
    context['tools'] = admin_tools()

    # Pages that need the whole width (the node manager) leave the menu out.
    context.setdefault('hide_navigation', False)

    unsaved = request.session.get('previewing_settings', {})
    context['unsaved'] = set([getattr(settings, s).set.name for s in unsaved.keys() if hasattr(settings, s)])
    context['moderation_counts'] = counts = review.inbox_counts()
    context['admin_menu'] = admin_menu(request, context['unsaved'], counts)

    return render(request, template, context)

def admin_page(fn):
    @super_user_required
    def wrapper(request, *args, **kwargs):
        return admin_page_wrapper(fn, request, *args, **kwargs)

    return wrapper

def moderation_page(fn):
    @staff_user_required
    def wrapper(request, *args, **kwargs):
        return admin_page_wrapper(fn, request, *args, **kwargs)

    return wrapper

def admin_tools_page(name, label):    
    def decorator(fn):
        fn = admin_page(fn)
        fn.label = label
        TOOLS[name] = fn

        return fn
    return decorator

class ActivityPaginatorContext(pagination.PaginatorContext):
    def __init__(self):
        super (ActivityPaginatorContext, self).__init__('ADMIN_RECENT_ACTIVITY', pagesizes=(20, 40, 80), default_pagesize=40)

@moderation_page
def dashboard(request):
    """Community health (forum/utils/community_health.py) for moderators and
    administrators, then the site status (administrators) and recent activity.
    ?days= picks the period, ?format=csv downloads the figures, and a POST with
    `refresh` recomputes them instead of using the cached ones."""
    from forum.utils import community_health as health
    days = health.parse_days(request.GET.get('days'))
    if request.method == 'POST' and 'refresh' in request.POST:
        health.figures(days, refresh=True)
        return HttpResponseRedirect('%s?days=%d' % (reverse('admin_index'), days))

    data = health.figures(days)
    groups = health.tiles(data, review.inbox_counts())
    charts = health.chart_data(data)
    if request.GET.get('format') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="community-health-%dd-%s.csv"' % (
            days, data['computed_at'].strftime('%Y-%m-%d'))
        health.write_csv(response, data, groups, charts)
        return response

    context = {
        'health': data,
        'health_groups': groups,
        'health_charts': charts,
        'health_headline': health.headline(groups, data),
        'health_periods': health.PERIODS,
        'health_cache_minutes': health.CACHE_SECONDS // 60,
        'recent_activity': get_recent_activity(),
    }
    if request.user.is_superuser:
        context.update(settings_pack=str(settings.SETTINGS_PACK), statistics=get_statistics())
    return ('osqaadmin/dashboard.html', pagination.paginated(
        request, ("recent_activity", ActivityPaginatorContext()), context))

@admin_page
def search(request):
    """Settings and admin pages matching ?q= (forum/utils/admin_search.py)."""
    from forum.utils import admin_search
    query = request.GET.get('q', '').strip()[:100]
    menu = admin_menu(request, set())
    results = admin_search.search(query, menu) if query else []
    for result in results:
        result['label_html'] = admin_search.mark(result['label'], query)
        result['help_html'] = admin_search.mark(Truncator(result['help']).chars(220), query) if result['help'] else ''
    return 'osqaadmin/search.html', {'query': query, 'results': results}

def interface_switch(request):
    """The old "switch admin layout" link (there is one layout now): bookmarks
    land on the dashboard."""
    return HttpResponseRedirect(reverse('admin_index'))

@admin_page
def statistics(request):
    today = datetime.now()
    last_month = today - timedelta(days=30)

    last_month_questions = Question.objects.filter_state(deleted=False).filter(added_at__gt=last_month
                                                                               ).order_by('added_at').values_list(
            'added_at', flat=True)

    last_month_n_questions = Question.objects.filter_state(deleted=False).filter(added_at__lt=last_month).count()
    qgraph_data = json.dumps([
    (time.mktime(d.timetuple()) * 1000, i + 1 + last_month_n_questions)
    for i, d in enumerate(last_month_questions)
    ])

    last_month_users = User.objects.filter(date_joined__gt=last_month
                                           ).order_by('date_joined').values_list('date_joined', flat=True)

    last_month_n_users = User.objects.filter(date_joined__lt=last_month).count()

    ugraph_data = json.dumps([
    (time.mktime(d.timetuple()) * 1000, i + 1 + last_month_n_users)
    for i, d in enumerate(last_month_users)
    ])

    return 'osqaadmin/statistics.html', {
    'graphs': [
            {
            'id': 'questions_graph',
            'caption': _("Questions Graph"),
            'data': qgraph_data
            }, {
            'id': 'userss_graph',
            'caption': _("Users Graph"),
            'data': ugraph_data
            }
            ]
    }

@admin_page
def tools_page(request, name):
    if not name in TOOLS:
        raise Http404

    return TOOLS[name](request)


@admin_page
def settings_set(request, set_name):
    set = Setting.sets.get(set_name, {})
    current_preview = request.session.get('previewing_settings', {})

    if set is None:
        raise Http404

    if request.POST:
        form = SettingsSetForm(set, data=request.POST, files=request.FILES)

        if form.is_valid():
            if 'preview' in request.POST:
                current_preview.update(form.cleaned_data)
                request.session['previewing_settings'] = current_preview

                return HttpResponseRedirect(reverse('index'))
            else:
                for s in set:
                    current_preview.pop(s.name, None)

                request.session['previewing_settings'] = current_preview

                if not 'reset' in request.POST:
                    changed = [name for name in form.changed_data if name in form.fields]
                    form.save()
                    security_log.event('settings_changed', request, set=set_name, fields=','.join(changed))
                    messages.info(request, _("'%s' settings saved succesfully") % set_name)

                    if set_name in ('minrep', 'badges', 'repgain'):
                        settings.SETTINGS_PACK.set_value("custom")

                return HttpResponseRedirect(reverse('admin_set', args=[set_name]))
    else:
        form = SettingsSetForm(set, unsaved=current_preview)

    sections, others = guide_sections(set, form)
    return 'osqaadmin/set.html', {
    'form': form,
    'markdown': set.markdown,
    'sections': sections,
    'other_rows': form.as_table(others) if sections else None,
    'guide_template': guide_template(set.name),
    'app_url': str(settings.APP_URL).rstrip('/'),
    }


STATUS_LABELS = {
    guides.ON: _lazy("Set up"),
    guides.PARTIAL: _lazy("Partly set up"),
    guides.OFF: _lazy("Not set up"),
    guides.WARNING: _lazy("Check this"),
}


def with_app_url(text):
    """A guide's HTML text (forum/settings/guides.py) with {app_url} filled in."""
    return mark_safe(str(text).replace('{app_url}', escape(str(settings.APP_URL).rstrip('/'))))


def guide_sections(setting_set, form):
    """The sections of a settings page, ready for osqaadmin/set.html, and the
    names of the settings no section lists."""
    values = dict((s.name, s.value) for s in setting_set)
    sections, listed = [], set()
    for section in guides.sections_for(setting_set.name):
        names = [n for n in section.settings if n in form.fields and n not in listed]
        if not names:
            continue
        listed.update(names)
        state, message = section.status(values) if section.status else (None, '')
        sections.append({
            'key': section.key, 'title': section.title, 'summary': with_app_url(section.summary),
            'state': state, 'state_label': STATUS_LABELS.get(state, ''),
            # Plain text (it may quote a setting's value).
            'message': with_app_url(escape(str(message))) if message else '',
            'steps': [with_app_url(step) for step in section.steps],
            'copy': [(label, str(value).replace('{app_url}', str(settings.APP_URL).rstrip('/')))
                     for label, value in section.copy],
            'links': section.links,
            'rows': form.as_table(names),
        })
    return sections, [n for n in form.fields if n not in listed]


def guide_template(set_name):
    """osqaadmin/guides/<set name>.html when there is one."""
    name = 'osqaadmin/guides/%s.html' % set_name
    try:
        get_template(name)
    except TemplateDoesNotExist:
        return None
    return name

@super_user_required
def get_default(request, set_name, var_name):
    set = Setting.sets.get(set_name, None)
    if set is None: raise Http404

    setting = dict([(s.name, s) for s in set]).get(var_name, None)
    if setting is None: raise Http404

    setting.to_default()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return HttpResponse(setting.default)
    else:
        return HttpResponseRedirect(reverse('admin_set', kwargs={'set_name': set_name}))


def get_recent_activity():
    return Action.objects.order_by('-action_date')

def get_flagged_posts():
    return Action.objects.filter(canceled=False, action_type="flag").order_by('-action_date')[0:30]

def get_statistics():
    return {
    'total_users': User.objects.all().count(),
    'users_last_24': User.objects.filter(date_joined__gt=(datetime.now() - timedelta(days=1))).count(),
    'total_questions': Question.objects.filter_state(deleted=False).count(),
    'questions_last_24': Question.objects.filter_state(deleted=False).filter(
            added_at__gt=(datetime.now() - timedelta(days=1))).count(),
    'total_answers': Answer.objects.filter_state(deleted=False).count(),
    'answers_last_24': Answer.objects.filter_state(deleted=False).filter(
            added_at__gt=(datetime.now() - timedelta(days=1))).count(),
    }

@super_user_required
@require_POST
def go_bootstrap(request):
#todo: this is the quick and dirty way of implementing a bootstrap mode
    try:
        from forum_modules.default_badges import settings as dbsets
        dbsets.POPULAR_QUESTION_VIEWS.set_value(100)
        dbsets.NOTABLE_QUESTION_VIEWS.set_value(200)
        dbsets.FAMOUS_QUESTION_VIEWS.set_value(300)
        dbsets.NICE_ANSWER_VOTES_UP.set_value(2)
        dbsets.NICE_QUESTION_VOTES_UP.set_value(2)
        dbsets.GOOD_ANSWER_VOTES_UP.set_value(4)
        dbsets.GOOD_QUESTION_VOTES_UP.set_value(4)
        dbsets.GREAT_ANSWER_VOTES_UP.set_value(8)
        dbsets.GREAT_QUESTION_VOTES_UP.set_value(8)
        dbsets.FAVORITE_QUESTION_FAVS.set_value(1)
        dbsets.STELLAR_QUESTION_FAVS.set_value(3)
        dbsets.DISCIPLINED_MIN_SCORE.set_value(3)
        dbsets.PEER_PRESSURE_MAX_SCORE.set_value(-3)
        dbsets.CIVIC_DUTY_VOTES.set_value(15)
        dbsets.PUNDIT_COMMENT_COUNT.set_value(10)
        dbsets.SELF_LEARNER_UP_VOTES.set_value(2)
        dbsets.STRUNK_AND_WHITE_EDITS.set_value(10)
        dbsets.ENLIGHTENED_UP_VOTES.set_value(2)
        dbsets.GURU_UP_VOTES.set_value(4)
        dbsets.NECROMANCER_UP_VOTES.set_value(2)
        dbsets.NECROMANCER_DIF_DAYS.set_value(30)
        dbsets.TAXONOMIST_USE_COUNT.set_value(5)
    except:
        pass

    settings.REP_TO_VOTE_UP.set_value(0)
    settings.REP_TO_VOTE_DOWN.set_value(15)
    settings.REP_TO_FLAG.set_value(15)
    settings.REP_TO_COMMENT.set_value(0)
    settings.REP_TO_LIKE_COMMENT.set_value(0)
    settings.REP_TO_UPLOAD.set_value(0)
    settings.REP_TO_CREATE_TAGS.set_value(0)
    settings.REP_TO_CLOSE_OWN.set_value(60)
    settings.REP_TO_REOPEN_OWN.set_value(120)
    settings.REP_TO_RETAG.set_value(150)
    settings.REP_TO_EDIT_WIKI.set_value(200)
    settings.REP_TO_EDIT_OTHERS.set_value(400)
    settings.REP_TO_CLOSE_OTHERS.set_value(600)
    settings.REP_TO_DELETE_COMMENTS.set_value(400)
    settings.REP_TO_VIEW_FLAGS.set_value(30)

    settings.INITIAL_REP.set_value(1)
    settings.MAX_REP_BY_UPVOTE_DAY.set_value(300)
    settings.REP_GAIN_BY_UPVOTED.set_value(15)
    settings.REP_LOST_BY_DOWNVOTED.set_value(1)
    settings.REP_LOST_BY_DOWNVOTING.set_value(0)
    settings.REP_GAIN_BY_ACCEPTED.set_value(25)
    settings.REP_GAIN_BY_ACCEPTING.set_value(5)
    settings.REP_LOST_BY_FLAGGED.set_value(2)
    settings.REP_LOST_BY_FLAGGED_3_TIMES.set_value(30)
    settings.REP_LOST_BY_FLAGGED_5_TIMES.set_value(100)

    settings.SETTINGS_PACK.set_value("bootstrap")

    messages.info(request, _('Bootstrap mode enabled'))
    return HttpResponseRedirect(reverse('admin_index'))

@super_user_required
@require_POST
def go_defaults(request):
    for setting in Setting.sets['badges']:
        setting.to_default()
    for setting in Setting.sets['minrep']:
        setting.to_default()
    for setting in Setting.sets['repgain']:
        setting.to_default()

    settings.SETTINGS_PACK.set_value("default")

    messages.info(request, ('All values reverted to defaults'))
    return HttpResponseRedirect(reverse('admin_index'))


@super_user_required
@require_POST
def recalculate_denormalized(request):
    for n in Node.objects.all():
        n = n.leaf
        n.score = n.votes.aggregate(score=models.Sum('value'))['score']
        if not n.score: n.score = 0
        n.save()

    for u in User.objects.all():
        # Sum() of no rows is None; users without reputation history have 0.
        u.reputation = u.reputes.aggregate(reputation=models.Sum('value'))['reputation'] or 0
        u.save()

    messages.info(request, _('All values recalculated'))
    return HttpResponseRedirect(reverse('admin_index'))

@admin_page
def maintenance(request):
    if request.POST:
        if 'close' in request.POST or 'adjust' in request.POST:
            form = MaintenanceModeForm(request.POST)

            if form.is_valid():
                settings.MAINTAINANCE_MODE.set_value({
                'allow_ips': form.cleaned_data['ips'],
                'message': form.cleaned_data['message']})
                security_log.event('maintenance_on', request, allow_ips=','.join(form.cleaned_data['ips']))

                if 'close' in request.POST:
                    message = _('Maintenance mode enabled')
                else:
                    message = _('Settings adjusted')

                messages.info(request, message)

                return HttpResponseRedirect(reverse('admin_maintenance'))
        elif 'open' in request.POST:
            settings.MAINTAINANCE_MODE.set_value(None)
            security_log.event('maintenance_off', request)
            messages.info(request, _("Your site is now running normally"))
            return HttpResponseRedirect(reverse('admin_maintenance'))
    else:
        form = MaintenanceModeForm(initial={'ips': request.META['REMOTE_ADDR'],
                                            'message': _('Currently down for maintenance. We\'ll be back soon')})

    return ('osqaadmin/maintenance.html', {'form': form, 'in_maintenance': settings.MAINTAINANCE_MODE.value is not None
                                           })


@require_POST
@staff_user_required
def resolve_moderation_report(request, id):
    """Dismiss an automated report, or act on it: delete the reported post
    (also as spam: suspend the author and delete their other posts), suspend
    its author, or suspend / delete the reported account. Used by the AI
    reports in the moderation inbox (forum/views/moderation.py)."""
    from forum.views import moderation
    report = get_object_or_404(ModerationReport, id=id)
    resolution = request.POST.get('resolution')
    done_url = moderation._next_url(request)
    done = []

    if report.node_id:
        node = report.node.leaf
        if resolution == 'delete':
            done.append(moderation.delete_post(request, node))
            messages.info(request, _("The post has been deleted."))
            resolution = 'deleted'
        elif resolution == 'spam':
            suspend, purge = bool(request.POST.get('suspend_author')), bool(request.POST.get('delete_other_posts'))
            done, count = moderation.delete_as_spam(request, node, node.author, suspend=suspend, purge=purge)
            messages.info(request, _("The post has been deleted."))
            resolution = 'deleted'
        elif resolution == 'suspend':
            done.append(moderation.suspend_author(request, node.author))
            messages.info(request, _("The account %s has been suspended.") % node.author.username)
            resolution = 'suspended'
        else:
            resolution = 'dismissed'
        reports = ModerationReport.objects.filter(node=report.node, resolved_at=None)
    else:
        target = report.user
        if target.is_staff or target.is_superuser:
            resolution = 'dismissed'
        if resolution == 'delete_account':
            if Node.objects.filter(author=target).exists():
                messages.error(request, _("This account has posts; suspend it instead."))
                return HttpResponseRedirect(done_url)
            messages.info(request, _("The account %s has been deleted.") % target.username)
            security_log.event('account_deleted', request, account=target, via='moderation report')
            target.delete()  # also removes its reports
            review.invalidate_counts()
            return HttpResponseRedirect(done_url)
        if resolution == 'suspend':
            done.append(moderation.suspend_author(request, target))
            messages.info(request, _("The account %s has been suspended.") % target.username)
            resolution = 'suspended'
        else:
            resolution = 'dismissed'
        reports = ModerationReport.objects.filter(user=target, resolved_at=None)

    if resolution == 'dismissed':
        messages.info(request, _("The report has been dismissed."))
    for open_report in reports:
        open_report.resolve(request.user, resolution)

    moderation._remember(request, done, resolution)
    review.invalidate_counts()
    return HttpResponseRedirect(done_url)

@admin_page
def static_pages(request):
    pages = Page.objects.all()

    return ('osqaadmin/static_pages.html', {
    'pages': pages,
    })

@admin_page
def edit_page(request, id=None):
    if id:
        page = get_object_or_404(Page, id=id)
    else:
        page = None

    if request.POST:
        form = PageForm(page, request.POST)

        if form.is_valid():
            if form.has_changed():
                if not page:
                    page = NewPageAction(user=request.user, ip=request.META['REMOTE_ADDR']).save(data=form.cleaned_data
                                                                                                 ).node
                else:
                    EditPageAction(user=request.user, node=page, ip=request.META['REMOTE_ADDR']).save(
                            data=form.cleaned_data)

            if ('publish' in request.POST) and (not page.published):
                PublishAction(user=request.user, node=page, ip=request.META['REMOTE_ADDR']).save()
            elif ('unpublish' in request.POST) and page.published:
                page.nstate.published.cancel(ip=request.META['REMOTE_ADDR'])

            return HttpResponseRedirect(reverse('admin_edit_page', kwargs={'id': page.id}))

    else:
        form = PageForm(page)

    if page:
        published = page.published
    else:
        published = False

    return ('osqaadmin/edit_page.html', {
    'page': page,
    'form': form,
    'published': published
    })

@super_user_required
@require_POST
def delete_page(request, id=None):
    page = get_object_or_404(Page, id=id)
    page.delete()
    return HttpResponseRedirect(reverse('admin_static_pages'))

@admin_tools_page('createuser', _lazy("Create new user"))
def create_user(request):
    if request.POST:
        form = CreateUserForm(request.POST)

        if form.is_valid():
            user_ = User(username=form.cleaned_data['username'], email=form.cleaned_data['email'])
            user_.set_password(form.cleaned_data['password1'])

            if not form.cleaned_data.get('validate_email', False):
                user_.email_isvalid = True

            user_.save()
            UserJoinsAction(user=user_, ip=request.META['REMOTE_ADDR']).save()
            security_log.event('account_created_by_admin', request, account=user_)

            messages.info(request, _("New user created sucessfully. %s.") % html.hyperlink(
                    user_.get_profile_url(), _("See %s profile") % user_.username, target="_blank"))

            return HttpResponseRedirect(reverse("admin_tools", kwargs={'name': 'createuser'}))
    else:
        form = CreateUserForm()

    return ('osqaadmin/createuser.html', {
        'form': form,
    })

class NodeManagementPaginatorContext(pagination.PaginatorContext):
    def __init__(self, id='QUESTIONS_LIST', prefix='', default_pagesize=100):
        super (NodeManagementPaginatorContext, self).__init__(id, sort_methods=(
            ('added_at', pagination.SimpleSort('added_at', '-added_at', "")),
            ('added_at_asc', pagination.SimpleSort('added_at_asc', 'added_at', "")),
            ('author', pagination.SimpleSort('author', '-author__username', "")),
            ('author_asc', pagination.SimpleSort('author_asc', 'author__username', "")),
            ('score', pagination.SimpleSort('score', '-score', "")),
            ('score_asc', pagination.SimpleSort('score_asc', 'score', "")),
            ('act_at', pagination.SimpleSort('act_at', '-last_activity_at', "")),
            ('act_at_asc', pagination.SimpleSort('act_at_asc', 'last_activity_at', "")),
            ('act_by', pagination.SimpleSort('act_by', '-last_activity_by__username', "")),
            ('act_by_asc', pagination.SimpleSort('act_by_asc', 'last_activity_by__username', "")),
        ), pagesizes=(default_pagesize,), force_sort='added_at', default_pagesize=default_pagesize, prefix=prefix)

@admin_tools_page("nodeman", _lazy("Bulk management"))
def node_management(request):
    if request.POST:
        params = pagination.generate_uri(request.GET, ('page',))

        if "save_filter" in request.POST:
            filter_name = request.POST.get('filter_name', _('filter'))
            params = pagination.generate_uri(request.GET, ('page',))
            current_filters = settings.NODE_MAN_FILTERS.value
            current_filters.append((filter_name, params))
            settings.NODE_MAN_FILTERS.set_value(current_filters)

        elif r"execute" in request.POST:
            selected_nodes = request.POST.getlist('_selected_node')

            if selected_nodes and request.POST.get('action', None):
                action = str(request.POST['action'])
                selected_nodes = Node.objects.filter(id__in=selected_nodes)

                message = _("No action performed")

                if action == 'delete_selected':
                    for node in selected_nodes:
                        if node.node_type in ('question', 'answer', 'comment') and (not node.nis.deleted):
                            DeleteAction(user=request.user, node=node, ip=request.META['REMOTE_ADDR']).save()

                    message = _("All selected nodes marked as deleted")

                if action == 'undelete_selected':
                    for node in selected_nodes:
                        if node.node_type in ('question', 'answer', 'comment') and (node.nis.deleted):
                            node.nstate.deleted.cancel(ip=request.META['REMOTE_ADDR'])

                    message = _("All selected nodes undeleted")

                if action == "close_selected":
                    for node in selected_nodes:
                        if node.node_type == "question" and (not node.nis.closed):
                            CloseAction(node=node.leaf, user=request.user, extra=_("bulk close"), ip=request.META['REMOTE_ADDR']).save()

                    message = _("Selected questions were closed")

                if action == "hard_delete_selected":
                    ids = [n.id for n in selected_nodes]

                    for id in ids:
                        try:
                            node = Node.objects.get(id=id)
                            node.delete()
                        except:
                            pass

                    message = _("All selected nodes deleted")

                messages.info(request, message)

                params = pagination.generate_uri(request.GET, ('page',))
                
            return HttpResponseRedirect(reverse("admin_tools", kwargs={'name': 'nodeman'}) + "?" + params)


    nodes = Node.objects.all()

    text = request.GET.get('text', '')
    text_in = request.GET.get('text_in', 'body')

    authors = request.GET.getlist('authors')
    tags = request.GET.getlist('tags')

    type_filter = request.GET.getlist('node_type')
    state_filter = request.GET.getlist('state_type')
    state_filter_type = request.GET.get('state_filter_type', 'any')

    if type_filter:
        nodes = nodes.filter(node_type__in=type_filter)

    # Plain DISTINCT: distinct('state_type') is DISTINCT ON, PostgreSQL only.
    state_types = NodeState.objects.filter(node__in=nodes).order_by().values_list('state_type', flat=True).distinct()
    state_filter = [s for s in state_filter if s in state_types]

    if state_filter:
        if state_filter_type == 'all':
            nodes = nodes.all_states(*state_filter)
        else:
            nodes = nodes.any_state(*state_filter)

    if (authors):
        nodes = nodes.filter(author__id__in=authors)
        authors = User.objects.filter(id__in=authors)

    if (tags):
        nodes = nodes.filter(tags__id__in=tags)
        tags = Tag.objects.filter(id__in=tags)

    if text:
        text_in = request.GET.get('text_in', 'body')
        filter = None

        if text_in == 'title' or text_in == 'both':
            filter = models.Q(title__icontains=text)

        if text_in == 'body' or text_in == 'both':
            sec_filter = models.Q(body__icontains=text)
            if filter:
                filter = filter | sec_filter
            else:
                filter = sec_filter

        if filter:
            nodes = nodes.filter(filter)

    node_types = [(k, n.friendly_name) for k, n in NodeMetaClass.types.items()]

    return ('osqaadmin/nodeman.html', pagination.paginated(request, ("nodes", NodeManagementPaginatorContext()), {
    'nodes': nodes,
    'text': text,
    'text_in': text_in,
    'type_filter': type_filter,
    'state_filter': state_filter,
    'state_filter_type': state_filter_type,
    'node_types': node_types,
    'state_types': state_types,
    'authors': authors,
    'tags': tags,
    'hide_navigation': True
    }))

@super_user_required
@require_http_methods(['GET', 'HEAD', 'POST'])
def test_email_settings(request):
    """Sends a test email to the administrator, only on a POST (CSRF-protected).

    The email settings page posts here with AJAX and shows the returned
    fragment; a direct visit gets a page that explains the test and offers the
    button instead of sending anything."""
    user = request.user
    context = {'user': user, 'tested': False}

    if request.method == 'POST':
        errors = send_template_email([user,], 'osqaadmin/mail_test.html', { 'user' : user })
        context.update(tested=True, errors=errors, hints=_email_error_hints(errors))
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return render(request, 'osqaadmin/test_email_settings.html', context)

    return admin_page_wrapper(lambda request: ('osqaadmin/test_email_page.html', context), request)


def _email_error_hints(errors):
    """Plain-language advice for the SMTP errors people usually hit."""
    text = ' '.join(errors)
    hints = []
    if 'AUTH extension not supported' in text:
        hints.append(_("The server only accepts a sign-in over an encrypted connection: tick \"Use TLS\" "
                       "(with port 587)."))
    if 'SMTPAuthenticationError' in text or 'Username and Password not accepted' in text:
        hints.append(_("The user name or password was refused. Gmail needs an App Password "
                       "(myaccount.google.com/apppasswords), not the normal account password."))
    if 'WRONG_VERSION_NUMBER' in text or 'SMTPServerDisconnected' in text:
        hints.append(_("Port 465 (SSL from the start) is not supported: use port 587 with \"Use TLS\" ticked."))
    if any(s in text for s in ('timed out', 'getaddrinfo failed', 'Name or service not known', 'refused')) \
            and 'Recipients' not in text:
        hints.append(_("The email server could not be reached: check the host name and port, and that the "
                       "firewall allows outgoing connections to it."))
    return hints


SUPPORT_PERIODS = (30, 90, 365, 0)


@moderation_page
def support_dashboard(request):
    """Unanswered questions and response times, overall and per product tag."""
    from forum.utils import support
    try:
        days = int(request.GET.get('days', 30))
    except ValueError:
        days = 30
    if days not in SUPPORT_PERIODS:
        days = 30
    tag = request.GET.get('tag', '').strip() or None

    now = datetime.now()
    target = int(settings.SUPPORT_RESPONSE_TARGET_HOURS)
    unanswered = list(support.unanswered_queue(days, tag))
    for question in unanswered:
        question.waiting_hours = (now - question.added_at).total_seconds() / 3600.0
        question.overdue = question.waiting_hours > target
    unaccepted = support.unaccepted_queue(days, tag)
    for question in unaccepted:
        question.waiting_hours = (now - question.first_answer_at).total_seconds() / 3600.0

    rows = []
    for name in support.support_tags():
        row = support.summary(support.period_questions(days, name))
        row['tag'] = name
        rows.append(row)

    return ('osqaadmin/support.html', {
        'days': days,
        'periods': SUPPORT_PERIODS,
        'tag': tag,
        'overall': support.summary(support.period_questions(days, tag)),
        'tag_rows': rows,
        'tag_names': [row['tag'] for row in rows],
        'unanswered': unanswered,
        'unaccepted': unaccepted,
        'target_hours': target,
        'reminder_days': int(settings.ACCEPT_REMINDER_DAYS),
    })


@staff_user_required
def email_previews(request, kind=None):
    """Every kind of email the site sends, rendered with the real templates and
    sample data for the admin who is looking. ?format=html or ?format=text
    returns that part of one email by itself (the HTML one is shown in a frame)."""
    from forum.utils import email_samples

    if kind is not None and kind not in email_samples.KINDS:
        raise Http404()

    fmt = request.GET.get('format')
    if kind is not None and fmt in ('html', 'text'):
        email = email_samples.render(kind, request.user)
        if fmt == 'text':
            return HttpResponse(email['text'], content_type='text/plain; charset=utf-8')
        return HttpResponse(email['html'], content_type='text/html; charset=utf-8')

    def page(request):
        if kind is None:
            kinds = []
            for slug, (name, audience, template, sample) in email_samples.KINDS.items():
                kinds.append({'slug': slug, 'name': name, 'audience': audience,
                              'subject': email_samples.render(slug, request.user)['subject']})
            return ('osqaadmin/email_previews.html', {'kinds': kinds})

        name, audience, template, sample = email_samples.KINDS[kind]
        email = email_samples.render(kind, request.user)
        return ('osqaadmin/email_preview.html', {
            'kind': kind, 'name': name, 'audience': audience, 'template': template, 'email': email,
            'list_unsubscribe': email['headers'].get('List-Unsubscribe', ''),
        })

    return admin_page_wrapper(page, request)
