from django.contrib.syndication.views import Feed, add_domain
from django.utils.encoding import smart_str
from django.utils.translation import gettext as _
from django.utils.safestring import mark_safe
from forum import settings
from forum.modules import decorate
from forum.utils.pagination import generate_uri

@decorate(add_domain, needs_origin=False)
def add_domain(domain, url, *args, **kwargs):
    return "%s%s" % (settings.APP_BASE_URL, url)

class BaseNodeFeed(Feed):
    def __init__(self, request, title, description, url):
        self._title = "%s" % smart_str(title)
        self._description = mark_safe("%s" % smart_str(description))
        self._url = url

    def title(self):
        return "%s" % smart_str(self._title)

    def link(self):
        return self._url

    def description(self):
        return "%s" % smart_str(self._description)

    def item_title(self, item):
        return "%s" % smart_str(item.title)

    def item_description(self, item):
        return "%s" % smart_str(item.html)

    def item_link(self, item):
        return item.leaf.get_absolute_url()

    def item_author_name(self, item):
        return "%s" % smart_str(item.author.username)

    def item_author_link(self, item):
        return item.author.get_profile_url()

    def item_pubdate(self, item):
        return item.added_at


class RssQuestionFeed(BaseNodeFeed):
    def __init__(self, request, question_list, title, description):
        url = request.path + "?" + generate_uri(request.GET, ('page', 'pagesize', 'sort'))
        super().__init__(request, title, description, url)

        self._question_list = question_list

    def item_categories(self, item):
        return item.tagname_list()

    def _items(self):
       return self._question_list

    def items(self):
        return self._items()[:30]

class RssAnswerFeed(BaseNodeFeed):
    def __init__(self, request, question, include_comments=False):
        super().__init__(
            request, _("Answers to: %s") % smart_str(question.title),
            question.html,
            question.get_absolute_url()
        )
        self._question = question
        self._include_comments = include_comments

    def _items(self):
        from forum.utils import review
        if self._include_comments:
            # Not the comments on a deleted or held answer either.
            qs = self._question.all_children.exclude(review.hidden_q('parent__'))
        else:
            qs = self._question.answers

        return qs.public().order_by('-added_at')

    def items(self):
        return self._items()[:30]

    def item_title(self, item):
        if item.node_type == "answer":
            return _("Answer by %s") % smart_str(item.author.username)
        else:
            return _("Comment by %(cauthor)s on %(pauthor)s's %(qora)s") % dict(
                cauthor=smart_str(item.author.username),
                pauthor=smart_str(item.parent.author.username),
                qora=(item.parent.node_type == "answer" and _("answer") or _("question"))
            )
