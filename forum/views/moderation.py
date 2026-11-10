"""The moderation inbox (/admin/moderation/, staff): everything waiting for a
moderator in one place, with one-click actions.

- First posts to review (FIRST_POSTS_MODERATION, forum/utils/review.py)
- Flagged posts (members' "report" on a post: FlagAction)
- Reported users (members' "report user": ReportAction)
- AI moderation reports (ModerationReport, e.g. from forum_modules/ai)
- Suggested edits (forum/utils/suggested_edits.py; reviewed through
  forum/views/suggested_edits.py, as on the public review page)

Every action goes through the Action system (ApprovePostAction, DeleteAction,
SuspendAction, cancelling flags), so reputation, the activity log and undo
work as everywhere else. The last action can be undone from the inbox.
"""
from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.html import escape
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

from forum.actions import ApprovePostAction, DeleteAction, SuspendAction
from forum.models import Action, ModerationReport, Node, User
from forum.models.base import load_cached, prefetch_cached_fk
from forum.utils import review, security_log

from .admin import moderation_page, staff_user_required

FILTERS = ('all', 'review', 'flags', 'users', 'ai', 'edits')
SECTION_SIZE = 50
UNDO_SESSION_KEY = 'moderation_undo'
UNDOABLE = ('approvepost', 'delete', 'suspend', 'suggestededit', 'rejectsuggestededit')


def inbox_url(show=None):
    url = reverse('admin_moderation')
    return '%s?show=%s' % (url, show) if show and show != 'all' else url


def _next_url(request):
    target = request.POST.get('next') or ''
    return target if target.startswith(reverse('admin_moderation')) else inbox_url()


def _ip(request):
    return request.META.get('REMOTE_ADDR', '')


# -- the page -----------------------------------------------------------------

def _authors_info(user_ids):
    """{user id: {'posts': n, 'approved': n}} for the authors on the page, in two grouped queries."""
    info = {uid: {'posts': 0, 'approved': 0} for uid in user_ids}
    if not user_ids:
        return info
    posts = Node.objects.filter(author_id__in=user_ids, node_type__in=review.POST_TYPES)
    for row in posts.values('author_id').annotate(n=Count('id')):
        info[row['author_id']]['posts'] = row['n']
    for row in posts.exclude(review.queued_q()).exclude(state_string__contains=review.DELETED_MARK) \
            .values('author_id').annotate(n=Count('id')):
        info[row['author_id']]['approved'] = row['n']
    return info


def _review_reason(node, author_info):
    from forum import settings
    if node.parent_id and (review.is_held(node.parent) or (node.abs_parent_id and review.is_held(node.abs_parent))):
        return _("Posted under a post that is waiting for review")
    min_rep = int(settings.FIRST_POSTS_REVIEW_MIN_REP or 0)
    count = int(settings.FIRST_POSTS_REVIEW_COUNT or 0)
    if author_info['approved'] < count or not min_rep:
        return _("One of the first posts of a new member")
    return _("The author has less than %(rep)d reputation") % {'rep': min_rep}


def _review_items():
    queue = review.review_queue()
    total = queue.count()
    nodes = [n.leaf for n in queue[:SECTION_SIZE]]
    prefetch_cached_fk(nodes, 'author', 'parent')
    info = _authors_info(list({n.author_id for n in nodes}))
    items = [{'node': n, 'author': n.author, 'author_info': info[n.author_id], 'held': review.is_held(n),
              'reason': _review_reason(n, info[n.author_id])} for n in nodes]
    return items, total


def _flag_items():
    groups = {}
    for flag in review.open_flags().order_by('-action_date')[:500]:
        groups.setdefault(flag.node_id, []).append(flag)
    node_ids = list(groups)[:SECTION_SIZE]
    nodes = load_cached(Node, node_ids)
    flags = [f for nid in node_ids for f in groups[nid]]
    prefetch_cached_fk(flags, 'user')
    prefetch_cached_fk(list(nodes.values()), 'author', 'parent')
    info = _authors_info(list({n.author_id for n in nodes.values()}))
    items = [{'node': nodes[nid], 'author': nodes[nid].author, 'author_info': info[nodes[nid].author_id],
              'flags': groups[nid]} for nid in node_ids if nid in nodes]
    return items, len(groups)


def _user_items():
    reports = review.open_user_reports()
    users = load_cached(User, list(reports)[:SECTION_SIZE])
    for actions in reports.values():
        prefetch_cached_fk(actions, 'user')
    info = _authors_info(list(users))
    items = [{'account': users[uid], 'author_info': info[uid], 'reports': reports[uid]}
             for uid in list(reports)[:SECTION_SIZE] if uid in users]
    return items, len(reports)


def _ai_items():
    reports = ModerationReport.open_reports()
    total = reports.count()
    reports = list(reports[:SECTION_SIZE])
    for report in reports:
        if report.node_id:
            report.post = report.node.leaf
    authors = {r.post.author_id for r in reports if r.node_id} | {r.user_id for r in reports if r.user_id}
    info = _authors_info(list(authors))
    for report in reports:
        report.author_info = info.get(report.post.author_id if report.node_id else report.user_id)
    return reports, total


@moderation_page
def inbox(request):
    show = request.GET.get('show', 'all')
    if show not in FILTERS:
        show = 'all'
    counts = review.inbox_counts()
    context = {'show': show, 'counts': counts, 'mode': review.mode(), 'filters': [
        ('all', _("Everything"), counts['total']),
        ('review', _("First posts"), counts['review']),
        ('flags', _("Flagged posts"), counts['flags']),
        ('users', _("Reported users"), counts['users']),
        ('ai', _("AI moderation reports"), counts['ai']),
        ('edits', _("Suggested edits"), counts.get('edits', 0)),
    ], 'inbox_url': request.get_full_path()}
    if show in ('all', 'review'):
        context['review_items'], context['review_total'] = _review_items()
    if show in ('all', 'flags'):
        context['flag_items'], context['flag_total'] = _flag_items()
    if show in ('all', 'users'):
        context['user_items'], context['user_total'] = _user_items()
    if show in ('all', 'ai'):
        context['moderation_reports'], context['ai_total'] = _ai_items()
    if show in ('all', 'edits'):
        from forum.utils import suggested_edits
        from .suggested_edits import edit_items
        context['edit_items'], context['edit_total'] = edit_items(request.user, SECTION_SIZE)
        context['edit_reasons'] = suggested_edits.REJECT_REASONS
    # Real counts of what is shown (the header's are cached for a minute).
    fresh = {'review': context.get('review_total'), 'flags': context.get('flag_total'),
             'users': context.get('user_total'), 'ai': context.get('ai_total'),
             'edits': context.get('edit_total')}
    if None not in fresh.values() and dict(counts, total=None) != dict(fresh, total=None):
        review.invalidate_counts()
    context['empty'] = not any(context.get(k) for k in ('review_items', 'flag_items', 'user_items',
                                                        'moderation_reports', 'edit_items'))
    undo = request.session.get(UNDO_SESSION_KEY)
    context['undo'] = undo if isinstance(undo, dict) and undo.get('ids') else None
    return 'osqaadmin/moderation_inbox.html', context


# -- acting -------------------------------------------------------------------

def _remember(request, actions, label):
    ids = [a.id for a in actions if a is not None and a.action_type in UNDOABLE]
    if ids:
        request.session[UNDO_SESSION_KEY] = {'ids': ids, 'label': label}
    else:
        request.session.pop(UNDO_SESSION_KEY, None)


def _resolve_reports(node_ids, moderator, resolution):
    for report in ModerationReport.objects.filter(node_id__in=node_ids, resolved_at=None):
        report.resolve(moderator, resolution)


def _dismiss_flags(node, moderator, ip):
    flags = list(Action.objects.filter(node=node, action_type='flag', canceled=False))
    for flag in flags:
        flag.leaf.cancel(moderator, ip=ip)
    return len(flags)


def suspend_author(request, account, reason=None):
    """Suspends `account` indefinitely (never staff); returns the SuspendAction or None."""
    if account.is_staff or account.is_superuser or account.is_suspended():
        return None
    action = SuspendAction(user=request.user, ip=_ip(request)).save(data={
        'bantype': 'indefinitely', 'publicmsg': reason or _('Spam account'), 'suspended': account})
    security_log.event('account_suspended', request, account=account, via='moderation inbox')
    return action


def delete_post(request, node, reason=''):
    if node.nis.deleted:
        return None
    return DeleteAction(user=request.user, node=node, ip=_ip(request), extra=reason).save()


def delete_as_spam(request, node, account, suspend=True, purge=True):
    """Deletes `node` (if any) as spam; optionally suspends `account` and
    deletes its other posts. Returns (actions, number of posts deleted)."""
    actions = []
    if suspend:
        actions.append(suspend_author(request, account))  # first: a suspended author isn't emailed
    nodes = [node] if node is not None else []
    if purge and not (account.is_staff or account.is_superuser):
        others = Node.objects.filter(author=account, node_type__in=review.POST_TYPES).exclude(
            state_string__contains=review.DELETED_MARK).order_by('-id')
        nodes += [n.leaf for n in others if node is None or n.id != node.id]
    deleted = [a for a in (delete_post(request, n, 'spam') for n in nodes) if a is not None]
    _resolve_reports([n.id for n in nodes], request.user, 'deleted')
    actions += deleted
    review.invalidate_counts()
    return actions, len(deleted)


@require_POST
@staff_user_required
def act_on_post(request, id):
    """Approve, delete, delete as spam, suspend the author, or dismiss (flags and reports)."""
    node = get_object_or_404(Node, id=id).leaf
    author = node.author
    action = request.POST.get('action')
    done = []

    if action == 'approve':
        if review.is_queued(node):
            done.append(ApprovePostAction(user=request.user, node=node, ip=_ip(request)).save())
        _resolve_reports([node.id], request.user, 'dismissed')
        messages.info(request, _("The post is approved."))
    elif action == 'delete':
        done.append(delete_post(request, node))
        _resolve_reports([node.id], request.user, 'deleted')
        messages.info(request, _("The post has been deleted."))
    elif action == 'spam':
        suspend, purge = bool(request.POST.get('suspend_author')), bool(request.POST.get('delete_other_posts'))
        done, count = delete_as_spam(request, node, author, suspend=suspend, purge=purge)
        text = ngettext("%(count)d post deleted as spam.", "%(count)d posts deleted as spam.", count) % {'count': count}
        if suspend and author.is_suspended():
            text += ' ' + _("The account %s has been suspended.") % escape(author.username)
        messages.info(request, text)
    elif action == 'suspend':
        done.append(suspend_author(request, author, _('Bad behaviour')))
        messages.info(request, _("The account %s has been suspended.") % escape(author.username))
    elif action == 'dismiss':
        count = _dismiss_flags(node, request.user, _ip(request))
        _resolve_reports([node.id], request.user, 'dismissed')
        messages.info(request, ngettext("%(count)d flag dismissed; the post stays.",
                                        "%(count)d flags dismissed; the post stays.", count) % {'count': count})
    else:
        messages.error(request, _("Unknown action."))
        return HttpResponseRedirect(_next_url(request))

    _remember(request, done, action)
    review.invalidate_counts()
    return HttpResponseRedirect(_next_url(request))


@require_POST
@staff_user_required
def act_on_user(request, id):
    """A reported account: dismiss the reports, suspend it, or suspend it and delete its posts."""
    account = get_object_or_404(User, id=id)
    action = request.POST.get('action')
    done = []
    if action in ('suspend', 'spam') and (account.is_staff or account.is_superuser):
        messages.error(request, _("Moderators and administrators can't be suspended from here."))
        return HttpResponseRedirect(_next_url(request))
    if action == 'suspend':
        done.append(suspend_author(request, account, _('Reported by members')))
        messages.info(request, _("The account %s has been suspended.") % escape(account.username))
    elif action == 'spam':
        done, count = delete_as_spam(request, None, account, suspend=True, purge=True)
        messages.info(request, _("The account %s has been suspended.") % escape(account.username) + ' ' + ngettext(
            "%(count)d post deleted as spam.", "%(count)d posts deleted as spam.", count) % {'count': count})
    elif action != 'dismiss':
        messages.error(request, _("Unknown action."))
        return HttpResponseRedirect(_next_url(request))
    else:
        messages.info(request, _("The reports about %s have been dismissed.") % escape(account.username))
    # Handled either way: the reports leave the inbox (cancelled, by this moderator).
    for report in review.open_user_reports().get(account.id, []):
        report.cancel(request.user, ip=_ip(request))
    _remember(request, done, action)
    review.invalidate_counts()
    return HttpResponseRedirect(_next_url(request))


@require_POST
@staff_user_required
def undo(request):
    """Cancels the actions of the last inbox action (approve, delete, suspend)."""
    remembered = request.session.pop(UNDO_SESSION_KEY, None) or {}
    actions = Action.objects.filter(id__in=remembered.get('ids') or [], action_type__in=UNDOABLE, canceled=False)
    count = 0
    for action in sorted(actions, key=lambda a: -a.id):
        action.leaf.cancel(request.user, ip=_ip(request))
        count += 1
    if count:
        messages.info(request, _("Undone."))
    review.invalidate_counts()
    return HttpResponseRedirect(_next_url(request))
