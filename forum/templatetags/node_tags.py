from datetime import datetime, timedelta
import re

from forum.models import Question, Action
from django.template import Template, Context
from django.utils.translation import ngettext, gettext as _
from django.utils.html import strip_tags
from django.utils.encoding import smart_str
from django.utils.safestring import mark_safe
from django.conf import settings as django_settings
from django.urls import reverse
from django import template
from django.db.models import Q
from forum.actions import *
from forum.models import Vote
from forum import settings, REQUEST_HOLDER

register = template.Library()


def _user_vote(user, post):
    """The user's vote value on post (1, -1 or None).

    A question page shows vote state for every post and comment; load all of
    the user's votes under the same question in one query and keep them for
    the rest of the request instead of querying once per post.
    """
    root_id = post.abs_parent_id or post.id
    request = REQUEST_HOLDER.request
    memo = getattr(request, '_osqa_user_votes', None)
    if memo is None:
        memo = {}
        if request is not None:
            request._osqa_user_votes = memo

    key = (user.id, root_id)
    if key not in memo:
        memo[key] = dict(Vote.objects.filter(user=user).filter(Q(node_id=root_id) | Q(node__abs_parent_id=root_id))
                         .values_list('node_id', 'value'))
    return memo[key].get(post.id)

@register.inclusion_tag('node/vote_buttons.html')
def vote_buttons(post, user):
    context = dict(post=post, user_vote='none')

    if user.is_authenticated:
        context['user_vote'] = {1: 'up', -1: 'down', None: 'none'}[_user_vote(user, post)]

    return context

@register.inclusion_tag('node/accept_button.html')
def accept_button(answer, user):
    if not settings.DISABLE_ACCEPTING_FEATURE:
        return {
            'can_accept': user.is_authenticated and user.can_accept_answer(answer),
            'answer': answer,
            'user': user
        }
    else:
        return ''

@register.inclusion_tag('node/wiki_symbol.html')
def wiki_symbol(user, post):
    context = {
        'is_wiki': post.nis.wiki,
        'post_type': post.friendly_name
    }

    if post.nis.wiki:
        if user.can_edit_post(post):
            context['can_edit'] = True
            context['edit_url'] = reverse('edit_' + post.node_type, kwargs={'id': post.id})
        context['by'] = post.nstate.wiki.by.username
        context['at'] = post.nstate.wiki.at

    return context

@register.inclusion_tag('node/favorite_mark.html')
def favorite_mark(question, user):
    try:
        FavoriteAction.objects.get(canceled=False, node=question, user=user)
        favorited = True
    except:
        favorited = False

    return {'favorited': favorited, 'favorite_count': question.favorite_count, 'question': question}

@register.simple_tag
def post_classes(post):
    classes = []

    if post.nis.deleted:
        classes.append('deleted')

    if post.nis.pending_review:
        classes.append('pending-review')

    if post.node_type == "answer":
        if (not settings.DISABLE_ACCEPTING_FEATURE) and post.nis.accepted:
            classes.append('accepted-answer')

        if post.author == post.question.author:
            classes.append('answered-by-owner')

    return " ".join(classes)

def post_control(text, url, command=False, withprompt=False, confirm=False, title="", copy=False, extra_classes=[]):
    classes = (command and "ajax-command" or " ") + (withprompt and " withprompt" or " ") + (confirm and " confirm" or " ") + \
        (copy and " copy" or " ")

    for extra_class in extra_classes:
        classes += " %s" % extra_class

    return {'text': text, 'url': url, 'classes': classes, 'title': title}


moderation_enabled = False
for m in django_settings.MODULE_LIST:
    if m.__name__.endswith('moderation'):
        moderation_enabled = True

@register.inclusion_tag('node/post_controls.html' if not moderation_enabled else "modules/moderation/node/post_controls.html")
def post_controls(post, user):
    controls = []
    menu = []
    post_type = post.node_type

    # Share: the phone's share sheet, or the link copied (osqa.main.js); a plain link without JavaScript.
    if post_type == "question":
        controls.append(post_control(_('share'), post.get_absolute_url(), title=_("Share this question"),
                                     extra_classes=['post-share']))

    # We show the link tool if the post is an Answer. It is visible to Guests too.
    if post_type == "answer":
        # Answer permanent link tool
        controls.append(post_control(_('permanent link'), reverse('answer_permanent_link', kwargs={'id' : post.id,}),
                                     title=_("answer permanent link"), command=True, withprompt=True, copy=True))

        # Users should be able to award points for an answer. Users cannot award their own answers
        if user != post.author and user.is_authenticated and user.reputation > 1:
            controls.append(post_control(_("award points"), reverse('award_points', kwargs={'user_id' : post.author.id,
                                         'answer_id' : post.id}), title=_("award points to %s") % smart_str(post.author.username),
                                         command=True, withprompt=True))

    # The other controls are visible only to authenticated users.
    if user.is_authenticated:
        try:
            edit_url = reverse('edit_' + post_type, kwargs={'id': post.id})
            if user.can_edit_post(post):
                controls.append(post_control(_('edit'), edit_url))
            else:
                # Suggested edits (forum/utils/suggested_edits.py), one pending per post.
                from forum.utils import suggested_edits
                if suggested_edits.can_suggest(user, post):
                    if post.id in suggested_edits.pending_post_ids(post):
                        controls.append(post_control(_('edit pending'), None,
                                                     title=_("An edit is waiting for review"),
                                                     extra_classes=['edit-pending']))
                    else:
                        controls.append(post_control(_('suggest an edit'), reverse('suggest_edit', kwargs={'id': post.id}),
                                                     title=_("Suggest an edit: a reviewer checks it before it appears"),
                                                     extra_classes=['suggest-edit']))
                if post_type == 'question' and user.can_retag_questions():
                    controls.append(post_control(_('retag'), edit_url))
        except:
            pass

        if post_type == 'question':
            if post.nis.closed and user.can_reopen_question(post):
                controls.append(post_control(_('reopen'), reverse('reopen', kwargs={'id': post.id}), command=True))
            elif not post.nis.closed and user.can_close_question(post):
                controls.append(post_control(_('close'), reverse('close', kwargs={'id': post.id}), command=True, withprompt=True))

        if user.can_flag_offensive(post):
            label = _('report')
            
            if user.can_view_offensive_flags(post):
                label =  "%s (%d)" % (label, post.flag_count)


            report_control = post_control(label, reverse('flag_post', kwargs={'id': post.id}),
                    command=True, withprompt=True,
                    title=_("report as offensive (i.e containing spam, advertising, malicious text, etc.)"))

            # Depending on the setting choose where to attach the control
            if settings.REPORT_OFFENSIVE_CONTROL_POSITION.value == "more":
                menu.append(report_control)
            else:
                controls.append(report_control)

        if user.can_delete_post(post):
            if post.nis.deleted:
                controls.append(post_control(_('undelete'), reverse('delete_post', kwargs={'id': post.id}),
                        command=True, confirm=True))
            else:
                controls.append(post_control(_('delete'), reverse('delete_post', kwargs={'id': post.id}),
                        command=True, confirm=True))

        if user.can_delete_post(post):
            menu.append(post_control(_('see revisions'),
                        reverse('revisions',
                        kwargs={'id': post.id}),
                        command=False, confirm=False))

        if settings.WIKI_ON:
            if (not post.nis.wiki) and user.can_wikify(post):
                menu.append(post_control(_('mark as community wiki'), reverse('wikify', kwargs={'id': post.id}),
                            command=True, confirm=True))

            elif post.nis.wiki and user.can_cancel_wiki(post):
                menu.append(post_control(_('cancel community wiki'), reverse('wikify', kwargs={'id': post.id}),
                            command=True, confirm=True))

        if post.node_type == "answer" and user.can_convert_to_comment(post):
            menu.append(post_control(_('convert to comment'), reverse('convert_to_comment', kwargs={'id': post.id}),
                        command=True, withprompt=True))
        
        if post.node_type == "answer" and user.can_convert_to_question(post):
            menu.append(post_control(_('convert to question'), reverse('convert_to_question', kwargs={'id': post.id}),
                        command=False, confirm=True))

        if user.is_superuser or user.is_staff:
            plain_text = strip_tags(post.html)

            char_count = len(plain_text)
            fullStr = plain_text + " "
            left_trimmedStr = re.sub(re.compile(r"^[^\w]+", re.IGNORECASE), "", fullStr)
            cleanedStr = re.sub(re.compile(r"[^\w]+", re.IGNORECASE), " ", left_trimmedStr)
            splitString = cleanedStr.split(" ")
            word_count = len(splitString) - 1

            metrics = mark_safe("<b>%s %s / %s %s</b>" % (char_count, ngettext('character', 'characters', char_count),
                                        word_count, ngettext('word', 'words', word_count)))

            menu.append(post_control(metrics, "#", command=False, withprompt=False))

    return {'controls': controls, 'menu': menu, 'post': post, 'user': user}

def _visible_comments(post):
    """The post's comments (not deleted; held for review only for their
    author and moderators), in display order.

    A question page shows the comments of the question and of every answer:
    load all of them in one query (comments whose parent is the question or
    one of its answers) and keep them, grouped by post, for the rest of the
    request, instead of one query per post. Comment authors are filled from
    the object cache in one round trip.
    """
    from forum.models import Comment
    from forum.models.base import prefetch_cached_fk
    order = '-added_at' if settings.SHOW_LATEST_COMMENTS_FIRST else 'added_at'
    request = REQUEST_HOLDER.request
    if request is None:
        return list(post.comments.public().order_by(order))
    viewer = getattr(request, 'user', None)

    root_id = post.abs_parent_id or post.id
    memo = request.__dict__.setdefault('_osqa_comments', {})
    if root_id not in memo:
        comments = list(Comment.objects.filter(Q(parent_id=root_id) | Q(parent__parent_id=root_id))
                        .visible_to(viewer).order_by(order))
        prefetch_cached_fk(comments, 'author', 'parent')
        grouped = {}
        for comment in comments:
            grouped.setdefault(comment.parent_id, []).append(comment)
        memo[root_id] = grouped
    grouped = memo[root_id]
    if post.id not in grouped and post.id != root_id and post.parent_id != root_id:
        # Not a direct child of the question (abs_parent out of date): ask directly.
        grouped[post.id] = list(post.comments.visible_to(viewer).order_by(order))
    return grouped.get(post.id, [])


def comment_context(c, user, top_scorer=False):
    """The context of one comment in node/comment.html (also used by the live
    question page, forum/views/live.py)."""
    context = {
        'can_delete': user.can_delete_comment(c),
        'can_like': user.can_like_comment(c),
        'can_edit': user.can_edit_comment(c),
        'can_convert': user.can_convert_comment_to_answer(c)
    }

    if top_scorer:
        context['top_scorer'] = True

    if context['can_like']:
        context['likes'] = _user_vote(user, c) == 1

    context['user'] = c.user
    context['comment'] = c.comment
    context['held'] = bool(c.nis.pending_review)
    context.update(dict(c.__dict__))
    return context


def _comments(post, user):
    all_comments = _visible_comments(post)

    if len(all_comments) <= 5:
        top_scorers = all_comments
    else:
        top_scorers = sorted(all_comments, key=lambda c: c.score, reverse=True)[0:5]

    comments = []
    showing = 0
    for c in all_comments:
        top_scorer = c in top_scorers or c.is_reply_to(user)
        if top_scorer:
            showing += 1
        comments.append(comment_context(c, user, top_scorer))

    # Generate canned comments
    canned_comments = []
    for comment in settings.CANNED_COMMENTS:
        t = Template(smart_str(comment))
        c = Context({
            'post' : post,
            'settings' : settings,
        })
        canned_comments.append(t.render(c))

    total = len(all_comments)
    return {
        'comments': comments,
        'canned_comments': canned_comments,
        'post': post,
        'can_comment': user.can_comment(post),
        'max_length': settings.FORM_MAX_COMMENT_BODY,
        'min_length': settings.FORM_MIN_COMMENT_BODY,
        'show_gravatar': settings.FORM_GRAVATAR_IN_COMMENTS,
        'showing': showing,
        'total': total,
        'more_comments_count' : int(total - showing),
        'show_latest_comments_first' : settings.SHOW_LATEST_COMMENTS_FIRST,
        'user': user,
    }

@register.inclusion_tag('node/comments.html')
def comments(post, user):
    return _comments(post, user)

@register.inclusion_tag("node/contributors_info.html", takes_context=True)
def contributors_info(context, node, verb=None):
    return {
        'node_verb': verb and verb or ((node.node_type == "question") and _("asked") or (
                    (node.node_type == "answer") and _("answered") or _("posted"))),
        'node': node,
        'context' : context
    }

@register.inclusion_tag("node/reviser_info.html")
def reviser_info(revision):
    return {'revision': revision}


@register.simple_tag
def post_time(date):
    """A date as relative text ("2 hours ago") in a <time> element that holds
    the exact date and time in `datetime` and in the tooltip."""
    from django.utils import formats
    from django.utils.html import format_html
    from forum.templatetags.extra_tags import diff_date
    if not date:
        return diff_date(date)
    return format_html('<time class="relative-time" datetime="{}" title="{}">{}</time>',
                       date.isoformat(timespec='seconds'), formats.date_format(date, 'DATETIME_FORMAT'),
                       diff_date(date))


@register.simple_tag
def accepted_answer(question):
    """The question's accepted answer (not deleted), or None."""
    if settings.DISABLE_ACCEPTING_FEATURE:
        return None
    return question.accepted_answers.order_by('id').first()


@register.inclusion_tag('node/review_notice.html')
def review_notice(post, user):
    """"Waiting for review" on a post in the first posts review queue: for its
    author while it is held, and for moderators (with a link to the inbox)."""
    from forum.utils import review
    held = bool(post.nis.pending_review)
    moderator = review.is_moderator(user)
    show = (held and (moderator or (user.is_authenticated and user.id == post.author_id))) or \
        (moderator and bool(post.nis.unreviewed))
    return {'show': show, 'held': held, 'moderator': moderator, 'post': post}
