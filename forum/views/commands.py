# -*- coding: utf-8 -*-

import re
import datetime
import json
import logging

from urllib.parse import urlencode

from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.utils.encoding import smart_str
from django.utils.translation import ngettext, gettext as _
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, HttpResponseNotAllowed, HttpResponseNotFound, Http404
from django.shortcuts import get_object_or_404, render

from django.contrib import messages
from forum.utils.antispam import posting_limit_reached, posting_limit_message

from forum.models import *
from forum.utils.decorators import ajax_login_required
from forum.utils.similar import candidate_questions
from forum.utils import html, review
from forum.models.base import prefetch_denormalized
from forum.actions import *
from forum.modules import decorate
from forum import settings

from .decorators import command, prompt, CommandException, RefreshPageCommand

class NotEnoughRepPointsException(CommandException):
    def __init__(self, action, user_reputation=None, reputation_required=None, node=None):
        if reputation_required is not None and user_reputation is not None:
            message = _(
                """Sorry, but you don't have enough reputation points to %(action)s.<br />
                The minimum reputation required is %(reputation_required)d (yours is %(user_reputation)d).
                Please check the <a href='%(faq_url)s'>FAQ</a>"""
            ) % {
                'action': action,
                'faq_url': reverse('faq'),
                'reputation_required' : reputation_required,
                'user_reputation' : user_reputation,
            }
        else:
            message = _(
                """Sorry, but you don't have enough reputation points to %(action)s.<br />Please check the <a href='%(faq_url)s'>faq</a>"""
            ) % {'action': action, 'faq_url': reverse('faq')}
        super(NotEnoughRepPointsException, self).__init__(message)

class CannotDoOnOwnException(CommandException):
    def __init__(self, action):
        super(CannotDoOnOwnException, self).__init__(
                _(
                        """Sorry but you cannot %(action)s your own post.<br />Please check the <a href='%(faq_url)s'>faq</a>"""
                        ) % {'action': action, 'faq_url': reverse('faq')}
                )

class AnonymousNotAllowedException(CommandException):
    def __init__(self, action):
        super(AnonymousNotAllowedException, self).__init__(
                _(
                        """Sorry but anonymous users cannot %(action)s.<br />Please login or create an account <a href='%(signin_url)s'>here</a>."""
                        ) % {'action': action, 'signin_url': reverse('auth_signin')}
                )

class NotEnoughLeftException(CommandException):
    def __init__(self, action, limit):
        super(NotEnoughLeftException, self).__init__(
                _(
                        """Sorry, but you don't have enough %(action)s left for today..<br />The limit is %(limit)s per day..<br />Please check the <a href='%(faq_url)s'>faq</a>"""
                        ) % {'action': action, 'limit': limit, 'faq_url': reverse('faq')}
                )

class CannotDoubleActionException(CommandException):
    def __init__(self, action):
        super(CannotDoubleActionException, self).__init__(
                _(
                        """Sorry, but you cannot %(action)s twice the same post.<br />Please check the <a href='%(faq_url)s'>faq</a>"""
                        ) % {'action': action, 'faq_url': reverse('faq')}
                )


@decorate.withfn(command)
def vote_post(request, id, vote_type):
    if not request.method == 'POST':
        raise CommandException(_("Invalid request"))


    post = get_object_or_404(Node, id=id).leaf
    user = request.user

    if not review.can_view(post, user):
        raise Http404()

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('vote'))

    if user == post.author:
        raise CannotDoOnOwnException(_('vote'))

    # Each direction has its own minimum: an up vote needs REP_TO_VOTE_UP even
    # when REP_TO_VOTE_DOWN is lower (and the other way round).
    can_vote = user.can_vote_up() if vote_type == 'up' else user.can_vote_down()
    if not can_vote:
        reputation_required = int(settings.REP_TO_VOTE_UP) if vote_type == 'up' else int(settings.REP_TO_VOTE_DOWN)
        action_type = _('upvote') if vote_type == 'up' else _('downvote')
        raise NotEnoughRepPointsException(action_type, user_reputation=user.reputation, reputation_required=reputation_required, node=post)

    new_vote_cls = (vote_type == 'up') and VoteUpAction or VoteDownAction
    score_inc = 0

    old_vote = VoteAction.get_action_for(node=post, user=user)

    # The daily limit is on casting votes; taking one back is always allowed.
    if not old_vote and user.get_vote_count_today() >= user.can_vote_count_today():
        raise NotEnoughLeftException(_('votes'), str(user.can_vote_count_today()))

    if old_vote:
        if old_vote.action_date < datetime.datetime.now() - datetime.timedelta(days=int(settings.DENY_UNVOTE_DAYS)):
            raise CommandException(
                    _("Sorry but you cannot cancel a vote after %(ndays)d %(tdays)s from the original vote") %
                    {'ndays': int(settings.DENY_UNVOTE_DAYS),
                     'tdays': ngettext('day', 'days', int(settings.DENY_UNVOTE_DAYS))}
                    )

        old_vote.cancel(ip=request.META['REMOTE_ADDR'])
        score_inc = (old_vote.__class__ == VoteDownAction) and 1 or -1
        vote_type = "none"
    else:
        new_vote_cls(user=user, node=post, ip=request.META['REMOTE_ADDR']).save()
        score_inc = (new_vote_cls == VoteUpAction) and 1 or -1

    response = {
    'commands': {
    'update_post_score': [id, score_inc],
    'update_user_post_vote': [id, vote_type]
    }
    }

    # Counted after the vote (or its cancellation), so the number is what the
    # user can still cast today.
    votes_left = max(0, user.can_vote_count_today() - user.get_vote_count_today())

    if int(settings.START_WARN_VOTES_LEFT) >= votes_left:
        response['message'] = _("You have %(nvotes)s %(tvotes)s left today.") % \
                    {'nvotes': votes_left, 'tvotes': ngettext('vote', 'votes', votes_left)}

    return response

@decorate.withfn(command)
@prompt
def flag_post(request, id):
    if request.method != 'POST':
        return render(request, 'node/report.html', {'types': settings.FLAG_TYPES})

    post = get_object_or_404(Node, id=id)
    user = request.user

    if not review.can_view(post, user):
        raise Http404()

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('flag posts'))

    if user == post.author:
        raise CannotDoOnOwnException(_('flag'))

    if not (user.can_flag_offensive(post)):
        raise NotEnoughRepPointsException(_('flag posts'))

    user_flag_count_today = user.get_flagged_items_count_today()

    if user_flag_count_today >= int(settings.MAX_FLAGS_PER_DAY):
        raise NotEnoughLeftException(_('flags'), str(settings.MAX_FLAGS_PER_DAY))

    try:
        current = FlagAction.objects.get(canceled=False, user=user, node=post)
        raise CommandException(
                _("You already flagged this post with the following reason: %(reason)s") % {'reason': current.extra})
    except ObjectDoesNotExist:
        reason = request.POST.get('prompt', '').strip()

        if not len(reason):
            raise CommandException(_("Reason is empty"))

        FlagAction(user=user, node=post, extra=reason, ip=request.META['REMOTE_ADDR']).save()

    return {'message': _("Thank you for your report. A moderator will review your submission shortly.")}

@decorate.withfn(command)
def like_comment(request, id):
    comment = get_object_or_404(Comment, id=id)
    user = request.user

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('like comments'))

    if user == comment.user:
        raise CannotDoOnOwnException(_('like'))

    if not user.can_like_comment(comment):
        raise NotEnoughRepPointsException( _('like comments'), node=comment)

    like = VoteAction.get_action_for(node=comment, user=user)

    if like:
        like.cancel(ip=request.META['REMOTE_ADDR'])
        likes = False
    else:
        VoteUpCommentAction(node=comment, user=user, ip=request.META['REMOTE_ADDR']).save()
        likes = True

    return {
    'commands': {
    'update_post_score': [comment.id, likes and 1 or -1],
    'update_user_post_vote': [comment.id, likes and 'up' or 'none']
    }
    }

@decorate.withfn(command)
def delete_comment(request, id):
    comment = get_object_or_404(Comment, id=id)
    user = request.user

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('delete comments'))

    if not user.can_delete_comment(comment):
        raise NotEnoughRepPointsException( _('delete comments'))

    if not comment.nis.deleted:
        DeleteAction(node=comment, user=user, ip=request.META['REMOTE_ADDR']).save()

    return {
    'commands': {
    'remove_comment': [comment.id],
    }
    }

@decorate.withfn(command)
def mark_favorite(request, id):
    node = get_object_or_404(Node, id=id)

    if not request.user.is_authenticated:
        raise AnonymousNotAllowedException(_('mark a question as favorite'))

    try:
        favorite = FavoriteAction.objects.get(canceled=False, node=node, user=request.user)
        favorite.cancel(ip=request.META['REMOTE_ADDR'])
        added = False
    except ObjectDoesNotExist:
        FavoriteAction(node=node, user=request.user, ip=request.META['REMOTE_ADDR']).save()
        added = True

    return {
    'commands': {
    'update_favorite_count': [added and 1 or -1],
    'update_favorite_mark': [added and 'on' or 'off']
    }
    }

@decorate.withfn(command)
def comment(request, id):
    post = get_object_or_404(Node, id=id)
    user = request.user

    if not review.can_view(post, user):
        raise Http404()

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('comment'))

    if not request.method == 'POST':
        raise CommandException(_("Invalid request"))

    comment_text = request.POST.get('comment', '').strip()

    if not len(comment_text):
        raise CommandException(_("Comment is empty"))

    if len(comment_text) < settings.FORM_MIN_COMMENT_BODY:
        raise CommandException(_("At least %d characters required on comment body.") % settings.FORM_MIN_COMMENT_BODY)

    if len(comment_text) > settings.FORM_MAX_COMMENT_BODY:
        raise CommandException(_("No more than %d characters on comment body.") % settings.FORM_MAX_COMMENT_BODY)

    if 'id' in request.POST:
        comment = get_object_or_404(Comment, id=request.POST['id'])

        if not user.can_edit_comment(comment):
            if comment.author == user:
                raise CommandException(_("Sorry, a comment can only be edited during the first 60 minutes after it "
                                         "was posted."))
            raise NotEnoughRepPointsException( _('edit comments'))

        comment = ReviseAction(user=user, node=comment, ip=request.META['REMOTE_ADDR']).save(
                data=dict(text=comment_text)).node
    else:
        if not user.can_comment(post):
            from forum.utils.accounts import validation_required
            if validation_required(user, 'comment'):
                raise CommandException(_("Confirm your email address to comment: open the link we emailed you, or "
                                         "%s.") % html.hyperlink(reverse('send_validation_email'),
                                                                 _("send a new link")))
            raise NotEnoughRepPointsException( _('comment'))
        if posting_limit_reached(user, 'comment'):
            raise CommandException(posting_limit_message('comment'))

        comment = CommentAction(user=user, ip=request.META['REMOTE_ADDR']).save(
                data=dict(text=comment_text, parent=post)).node

    if comment.active_revision.revision == 1:
        return {
        **({'message': review.held_notice()} if review.is_held(comment) else {}),
        'commands': {
        'insert_comment': [
                id, comment.id, comment.comment, user.decorated_name, user.get_profile_url(),
                reverse('delete_comment', kwargs={'id': comment.id}),
                reverse('node_markdown', kwargs={'id': comment.id}),
                reverse('convert_comment', kwargs={'id': comment.id}),
                user.can_convert_comment_to_answer(comment),
                bool(settings.SHOW_LATEST_COMMENTS_FIRST)
                ]
        }
        }
    else:
        return {
        'commands': {
        'update_comment': [comment.id, comment.comment]
        }
        }

@decorate.withfn(command)
@prompt
def node_markdown(request, id):
    user = request.user

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('accept answers'))

    node = get_object_or_404(Node, id=id)

    if (node.nis.deleted and not user.can_view_deleted_post(node)) or not review.can_view(node, user):
        raise Http404()

    return HttpResponse(node.active_revision.body, content_type="text/plain")


@decorate.withfn(command)
def accept_answer(request, id):
    if settings.DISABLE_ACCEPTING_FEATURE:
        # Returned, not raised: the command decorator turns exceptions into an
        # "unknown error" reply with status 200.
        return HttpResponseNotFound()

    user = request.user

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('accept answers'))

    answer = get_object_or_404(Answer, id=id)
    question = answer.question

    if not user.can_accept_answer(answer):
        raise CommandException(_("Sorry but you cannot accept the answer"))

    commands = {}

    if answer.nis.accepted:
        answer.nstate.accepted.cancel(user, ip=request.META['REMOTE_ADDR'])
        commands['unmark_accepted'] = [answer.id]
    else:
        if settings.MAXIMUM_ACCEPTED_ANSWERS and (question.accepted_count >= settings.MAXIMUM_ACCEPTED_ANSWERS):
            raise CommandException(ngettext("This question already has an accepted answer.",
                "Sorry but this question has reached the limit of accepted answers.", int(settings.MAXIMUM_ACCEPTED_ANSWERS)))

        if settings.MAXIMUM_ACCEPTED_PER_USER and question.accepted_count:
            accepted_from_author = question.accepted_answers.filter(author=answer.author).count()

            if accepted_from_author >= settings.MAXIMUM_ACCEPTED_PER_USER:
                raise CommandException(ngettext("The author of this answer already has an accepted answer in this question.",
                "Sorry but the author of this answer has reached the limit of accepted answers per question.", int(settings.MAXIMUM_ACCEPTED_PER_USER)))             


        AcceptAnswerAction(node=answer, user=user, ip=request.META['REMOTE_ADDR']).save()

        # If the request is not an AJAX redirect to the answer URL rather than to the home page
        if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
            msg = _("""
              Congratulations! You've accepted an answer.
            """)

            # Notify the user with a message that an answer has been accepted
            messages.info(request, msg)

            # Redirect URL should include additional get parameters that might have been attached
            redirect_url = answer.parent.get_absolute_url() + "?accepted_answer=true&%s" % smart_str(urlencode(request.GET))

            return HttpResponseRedirect(redirect_url)

        commands['mark_accepted'] = [answer.id]

    return {'commands': commands}

@decorate.withfn(command)
def delete_post(request, id):
    post = get_object_or_404(Node, id=id)
    user = request.user

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('delete posts'))

    if not (user.can_delete_post(post)):
        raise NotEnoughRepPointsException(_('delete posts'))

    ret = {'commands': {}}

    if post.nis.deleted:
        post.nstate.deleted.cancel(user, ip=request.META['REMOTE_ADDR'])
        ret['commands']['unmark_deleted'] = [post.node_type, id]
    else:
        DeleteAction(node=post, user=user, ip=request.META['REMOTE_ADDR']).save()

        ret['commands']['mark_deleted'] = [post.node_type, id]

    return ret

def find_original_question(question, value):
    """The question a duplicate points to, from its number or a link to it ('' for none)."""
    value = value.strip()
    if not value:
        return None

    match = re.search(r'(?:^|/)(\d+)(?:[/?#]|$)', value)
    if not match:
        raise CommandException(_("Enter the number of the original question or a link to it."))

    try:
        original = Question.objects.public().get(id=int(match.group(1)))
    except Question.DoesNotExist:
        raise CommandException(_("The original question was not found."))

    # Point at the end of a chain of duplicates rather than at another duplicate.
    if original.duplicate_of:
        original = original.duplicate_of

    if original.id == question.id:
        raise CommandException(_("A question cannot be a duplicate of itself."))
    return original


@decorate.withfn(command)
@prompt
def close(request, id, close):
    if request.method != 'POST':
        if not close:
            return HttpResponseNotAllowed(['POST'])
        return render(request, 'node/close.html', {
            'types': settings.CLOSE_TYPES,
            'can_move_answers': request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff),
        })

    question = get_object_or_404(Question, id=id)
    user = request.user

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('close questions'))

    if question.nis.closed:
        if not user.can_reopen_question(question):
            raise NotEnoughRepPointsException(_('reopen questions'))

        question.nstate.closed.cancel(user, ip=request.META['REMOTE_ADDR'])
    else:
        if not request.user.can_close_question(question):
            raise NotEnoughRepPointsException(_('close questions'))

        reason = request.POST.get('prompt', '').strip()

        if not len(reason):
            raise CommandException(_("Reason is empty"))

        duplicate_of = find_original_question(question, request.POST.get('duplicate_of', ''))
        move_answers = bool(duplicate_of and request.POST.get('move_answers') and (user.is_superuser or user.is_staff))

        CloseAction(node=question, user=user, extra=reason, ip=request.META['REMOTE_ADDR']).save(
            data=dict(duplicate_of=duplicate_of, move_answers=move_answers))

    return RefreshPageCommand()

@decorate.withfn(command)
def wikify(request, id):
    node = get_object_or_404(Node, id=id)
    user = request.user

    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('mark posts as community wiki'))

    if node.nis.wiki:
        if not user.can_cancel_wiki(node):
            raise NotEnoughRepPointsException(_('cancel a community wiki post'))

        if node.nstate.wiki.action_type == "wikify":
            node.nstate.wiki.cancel()
        else:
            node.nstate.wiki = None
    else:
        if not user.can_wikify(node):
            raise NotEnoughRepPointsException(_('mark posts as community wiki'))

        WikifyAction(node=node, user=user, ip=request.META['REMOTE_ADDR']).save()

    return RefreshPageCommand()

@decorate.withfn(command)
@prompt
def convert_to_comment(request, id):
    user = request.user
    answer = get_object_or_404(Answer, id=id)
    question = answer.question

    # Check whether the user has the required permissions
    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_("convert answers to comments"))

    if not user.can_convert_to_comment(answer):
        raise NotEnoughRepPointsException(_("convert answers to comments"))

    if request.method != 'POST':
        description = lambda a: _("Answer by %(uname)s: %(snippet)s...") % {'uname': smart_str(a.author.username),
                                                                            'snippet': a.summary[:10]}
        nodes = [(question.id, _("Question"))]
        [nodes.append((a.id, description(a))) for a in
         question.answers.filter_state(deleted=False).exclude(id=answer.id)]

        return render(request, 'node/convert_to_comment.html', {'answer': answer, 'nodes': nodes})

    try:
        new_parent = Node.objects.get(id=request.POST.get('under', None))
    except:
        raise CommandException(_("That is an invalid post to put the comment under"))

    if not (new_parent == question or (new_parent.node_type == 'answer' and new_parent.parent == question)):
        raise CommandException(_("That is an invalid post to put the comment under"))

    AnswerToCommentAction(user=user, node=answer, ip=request.META['REMOTE_ADDR']).save(data=dict(new_parent=new_parent))

    return RefreshPageCommand()

@decorate.withfn(command)
def convert_comment_to_answer(request, id):
    user = request.user
    comment = get_object_or_404(Comment, id=id)
    parent = comment.parent

    if not parent.question:
        question = parent
    else:
        question = parent.question
    
    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_("convert comments to answers"))

    if not user.can_convert_comment_to_answer(comment):
        raise NotEnoughRepPointsException(_("convert comments to answers"))
    
    CommentToAnswerAction(user=user, node=comment, ip=request.META['REMOTE_ADDR']).save(data=dict(question=question))

    return RefreshPageCommand()

@decorate.withfn(command)
def subscribe(request, id, user=None):
    if user:
        try:
            user = User.objects.get(id=user)
        except User.DoesNotExist:
            raise Http404()

        # Only staff may change another user's subscription.
        if not (request.user.is_authenticated and (request.user == user or request.user.is_a_super_user_or_staff())):
            raise CommandException(_("You do not have the correct credentials to preform this action."))
    else:
        if not request.user.is_authenticated:
            raise AnonymousNotAllowedException(_('subscribe to questions'))
        user = request.user

    question = get_object_or_404(Question, id=id)

    try:
        subscription = QuestionSubscription.objects.get(question=question, user=user)
        subscription.delete()
        subscribed = False
    except:
        subscription = QuestionSubscription(question=question, user=user, auto_subscription=False)
        subscription.save()
        subscribed = True

    return {
        'commands': {
            'set_subscription_button': [subscribed and _('unsubscribe me') or _('subscribe me')],
            'set_subscription_status': ['']
        }
    }

#internally grouped views - used by the tagging system
@ajax_login_required
def mark_tag(request, tag=None, **kwargs):#tagging system
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    action = kwargs['action']
    ts = MarkedTag.objects.filter(user=request.user, tag__name=tag)
    if action == 'remove':
        logging.debug('deleting tag %s' % tag)
        ts.delete()
    else:
        reason = kwargs['reason']
        if len(ts) == 0:
            try:
                t = Tag.objects.get(name=tag)
                mt = MarkedTag(user=request.user, reason=reason, tag=t)
                mt.save()
            except:
                pass
        else:
            ts.update(reason=reason)
    return HttpResponse(json.dumps(''), content_type="application/json")

def matching_tags(request):
    query = request.GET.get('q', '').strip().lower()
    if not query:
        # Crawlers follow these URLs without a query: a 400, not a logged server error.
        return HttpResponseBadRequest(_("Invalid request"), content_type="text/plain")

    possible_tags = list(Tag.active.filter(name__icontains=query))
    listed = set(tag.id for tag in possible_tags)
    # Synonyms ("csv") give their tag, with the synonym as a fourth column:
    # the menu shows "csv → export" and picking it puts in "export".
    synonyms = TagSynonym.objects.filter(source_name__icontains=query, target__used_count__gte=1).exclude(
        target_id__in=listed).select_related('target').order_by('source_name')
    rows, exact = [], []
    for synonym in synonyms:
        if synonym.target_id in listed:
            continue
        listed.add(synonym.target_id)
        tag = synonym.target
        (exact if synonym.source_name == query else rows).append(
            "%s|%s|%s|%s\n" % (tag.id, tag.name, tag.used_count, synonym.source_name))
    tag_output = ''.join(exact + ["%s|%s|%s\n" % (tag.id, tag.name, tag.used_count) for tag in possible_tags] + rows)

    return HttpResponse(tag_output, content_type="text/plain")

def matching_users(request):
    query = request.GET.get('q', '').strip()
    if not query:
        return HttpResponseBadRequest(_("Invalid request"), content_type="text/plain")

    try:
        limit = min(max(int(request.GET.get('limit', 20)), 1), 50)
    except ValueError:
        limit = 20

    # Usernames starting with the query first (for @mention autocomplete), then the rest.
    users = User.objects.filter(is_active=True, username__icontains=query)
    prefix = list(users.filter(username__istartswith=query).order_by('-reputation')[:limit])
    possible_users = prefix + list(users.exclude(id__in=[u.id for u in prefix]).order_by('-reputation')[:limit - len(prefix)])
    output = ''

    for user in possible_users:
        output += ("%s|%s|%s|%s\n" % (user.id, user.decorated_name, user.reputation, user.username))

    return HttpResponse(output, content_type="text/plain")

def related_questions(request):
    if request.POST and request.POST.get('title', None):
        can_rank, questions = Question.objects.search(request.POST['title'])

        if can_rank and isinstance(can_rank, str):
            questions = questions.order_by(can_rank)

        questions = list(questions.public()[0:10])
        if not questions:
            # The default search matches the whole title as one phrase; without
            # a full-text module that rarely finds anything, so match keywords.
            questions = candidate_questions(request.POST['title'])

        # Answer counts for the "Similar questions" panel's markers, in one query each.
        prefetch_denormalized(questions, 'answer_count', 'accepted_count')
        return HttpResponse(json.dumps(
                [dict(title=q.title, url=q.get_absolute_url(), score=q.score, summary=q.summary,
                      answers=q.answer_count, accepted=bool(q.accepted_count))
                 for q in questions]), content_type="application/json")
    else:
        raise Http404()

@decorate.withfn(command)
@prompt
def answer_permanent_link(request, id):
    # Getting the current answer object
    answer = get_object_or_404(Answer, id=id)

    # Getting the current object URL -- the Application URL + the object relative URL
    url = '%s%s' % (settings.APP_BASE_URL, answer.get_absolute_url())

    if request.method != 'POST':
        # Display the template
        return render(request, 'node/permanent_link.html', { 'url' : url, })

    return {
        'commands' : {
            'copy_url' : [request.POST['permanent_link_url'],],
        },
        'message' : _("The permanent URL to the answer has been copied to your clipboard."),
    }

@decorate.withfn(command)
@prompt
def award_points(request, user_id, answer_id):
    user = request.user
    awarded_user = get_object_or_404(User, id=user_id)
    answer = get_object_or_404(Answer, id=answer_id)

    # Users shouldn't be able to award themselves
    if awarded_user.id == user.id:
        raise CannotDoOnOwnException(_("award"))

    # Anonymous users cannot award  points, they just don't have such
    if not user.is_authenticated:
        raise AnonymousNotAllowedException(_('award'))

    if request.method != 'POST':
        return render(request, "node/award_points.html", {
            'user' : user,
            'awarded_user' : awarded_user,
            'reputation_to_comment' : str(settings.REP_TO_COMMENT)
        })
    else:
        try:
            points = int(request.POST.get('points', ''))
        except ValueError:
            points = 0

        # We should check if the user has enough reputation points, otherwise we raise an exception.
        if points <= 0:
            raise CommandException(_("The number of points to award needs to be a positive value."))

        if user.reputation < points:
            raise NotEnoughRepPointsException(_("award"))

        extra = dict(message=request.POST.get('message', ''), awarding_user=request.user.id, value=points)

        # We take points from the awarding user
        AwardPointsAction(user=request.user, node=answer, extra=extra).save(data=dict(value=points, affected=awarded_user))

        return { 'message' : _("You have awarded %(awarded_user)s with %(points)d points") % {'awarded_user' : awarded_user, 'points' : points} }

