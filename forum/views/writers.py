# encoding:utf-8
import logging
import os.path
import re

import datetime

from django.urls import reverse
from forum.utils.urls import root_relative_reverse
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseNotAllowed, Http404, JsonResponse
from django.utils.html import *
from django.utils.translation import gettext as _

from django.contrib import messages
from forum.utils.antispam import posting_limit_reached, posting_limit_message

from forum.actions import AskAction, AnswerAction, ReviseAction, RollbackAction, RetagAction, AnswerToQuestionAction, CommentToQuestionAction
from forum.forms import *
from forum.models import *
from forum.models.node import render_markdown
from forum.utils import html, throttle
from forum.utils.images import store_upload, NotAnImage, ImageTooLarge
from forum.http_responses import HttpResponseUnauthorized
from forum.utils import review
from forum.utils import live
from forum.utils import post_versions

from .vars import PENDING_SUBMISSION_SESSION_ATTR

# Longer than any post body the forms accept; the preview refuses anything bigger.
MAX_PREVIEW_LENGTH = 100000


def markdown_preview(request):
    """Renders editor Markdown exactly as a saved post would be rendered."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    text = request.POST.get('text', '')
    if len(text) > MAX_PREVIEW_LENGTH:
        return HttpResponse(status=413)
    return HttpResponse(render_markdown(text) if text.strip() else '', content_type='text/html; charset=utf-8')


def upload(request):
    """Image upload from the editor (image dialog, paste and drop).

    Answers JSON: {"url": "/upfiles/name.png"} on success, otherwise
    {"error": "message for the user"} with status 403 (not allowed), 400
    (not an image, or too many pixels), 413 (too big), 429 (more than
    UPLOADS_PER_HOUR in an hour; staff have no limit) or 500.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    def refused(message, status):
        return JsonResponse({'error': message}, status=status)

    if not request.user.can_upload_files():
        return refused(_('uploading images is limited to users with >60 reputation points'), 403)

    f = request.FILES.get('file-upload')
    file_types = _("allowed file types are 'jpg', 'jpeg', 'gif', 'bmp', 'png', 'tiff', 'webp'")
    if f is None:
        return refused(file_types, 400)

    if os.path.splitext(f.name)[1].lower() not in ('.jpg', '.jpeg', '.gif', '.png', '.bmp', '.tiff', '.ico', '.webp'):
        return refused(file_types, 400)

    # check file size (in bytes) before writing anything to disk
    if f.size > float(settings.ALLOW_MAX_FILE_SIZE) * 1024 * 1024:
        return refused(_("maximum upload file size is %sM") % settings.ALLOW_MAX_FILE_SIZE, 413)

    # Every image that reaches Pillow counts (decoding is the expensive part).
    limit = int(settings.UPLOADS_PER_HOUR or 0)
    if limit > 0 and not (request.user.is_staff or request.user.is_superuser):
        if throttle.count('upload', request.user.pk) >= limit:
            return refused(_("You have uploaded %d images in the last hour, the most you can. Please try again "
                             "later.") % limit, 429)
        throttle.hit('upload', request.user.pk, 3600)

    # The extension is chosen by the client: Pillow decodes the content, and
    # only the re-encoded image (no metadata, downscaled) is written to disk,
    # with its AVIF/WebP copies (forum.utils.images.store_upload).
    try:
        url = store_upload(f, f.name)
    except ImageTooLarge:
        return refused(_('This image has too many pixels. Please upload a smaller image.'), 400)
    except NotAnImage:
        return refused(file_types, 400)
    except Exception:
        logging.exception('File upload failed')
        return refused(_('Error uploading file. Please contact the site administrator. Thank you.'), 500)

    return JsonResponse({'url': url})

def ask(request):
    form = None

    if request.POST:
        if request.session.pop('reviewing_pending_data', False):
            form = AskForm(initial=request.POST, user=request.user)
        elif "text" in request.POST:
            form = AskForm(request.POST, user=request.user)
            if form.is_valid():
                if request.user.is_authenticated and posting_limit_reached(request.user, 'ask'):
                    messages.error(request, posting_limit_message('ask'))
                elif request.user.is_authenticated and request.user.email_valid_and_can_ask():
                    ask_action = AskAction(user=request.user, ip=request.META['REMOTE_ADDR']).save(data=form.cleaned_data)
                    question = ask_action.node
                    post_versions.save(question, request.POST, question.tagname_list())

                    if settings.WIKI_ON and request.POST.get('wiki', False):
                        question.nstate.wiki = ask_action

                    return HttpResponseRedirect(question.get_absolute_url())
                else:
                    request.session[PENDING_SUBMISSION_SESSION_ATTR] = {
                        'POST': request.POST.urlencode(),
                        'data_name': _("question"),
                        'type': 'ask',
                        'submission_url': reverse('ask'),
                        'time': datetime.datetime.now().isoformat()
                    }

                    if request.user.is_authenticated:
                        messages.info(request, _("Your question is pending until you %s.") % html.hyperlink(
                            settings.APP_URL + root_relative_reverse('send_validation_email'), _("validate your email")

                        ))
                        return HttpResponseRedirect(reverse('index'))
                    else:
                        return HttpResponseRedirect(reverse('auth_signin'))
        elif "go" in request.POST:
            form = AskForm({'title': request.POST['q']}, user=request.user)
            
    if not form:
        if request.GET.get('title'):
            # From the search page: "Ask a question" with the search words as its title.
            form = AskForm(initial={'title': request.GET['title'].strip()[:300]}, user=request.user)
        else:
            form = AskForm(user=request.user)

    return render(request, 'ask.html', {
        'form' : form,
        'tab' : 'ask',
        # "Applies to version" (forum/utils/post_versions.py), shown as tags are typed.
        'version_groups': post_versions.form_groups(request.POST.get('tags', '').split(),
                                                    data=request.POST or None, show_all=True),
        })

def convert_to_question(request, id):
    user = request.user

    node_type = request.GET.get('node_type', 'answer')
    if node_type == 'comment':
        node = get_object_or_404(Comment, id=id)
        action_class = CommentToQuestionAction
    else:
        node = get_object_or_404(Answer, id=id)
        action_class = AnswerToQuestionAction

    if not user.can_convert_to_question(node):
        return HttpResponseUnauthorized(request)

    return _edit_question(request, node, template='node/convert_to_question.html', summary=_("Converted to question"),
                           action_class =action_class, allow_rollback=False, url_getter=lambda a: Question.objects.get(id=a.id).get_absolute_url())

def edit_question(request, id):
    question = get_object_or_404(Question, id=id)
    if question.nis.deleted and not request.user.can_view_deleted_post(question):
        raise Http404
    if not review.can_view(question, request.user):
        raise Http404
    if request.user.can_edit_post(question):
        return _edit_question(request, question)
    elif request.user.can_retag_questions():
        return _retag_question(request, question)
    else:
        raise Http404

def _retag_question(request, question):
    if request.method == 'POST':
        form = RetagQuestionForm(question, request.POST)
        if form.is_valid():
            if form.has_changed():
                RetagAction(user=request.user, node=question, ip=request.META['REMOTE_ADDR']).save(data=dict(tagnames=form.cleaned_data['tags']))

            return HttpResponseRedirect(question.get_absolute_url())
    else:
        form = RetagQuestionForm(question)
    return render(request, 'question_retag.html', {
        'question': question,
        'form' : form,
        #'tags' : _get_tags_cache_json(),
    })

def _edit_question(request, question, template='question_edit.html', summary='', action_class=ReviseAction,
                   allow_rollback=True, url_getter=lambda q: q.get_absolute_url(), additional_context=None):
    conflict = None  # changed by someone else since the form was opened (forum/utils/live.py)
    if request.method == 'POST':
        revision_form = RevisionForm(question, data=request.POST)
        if revision_form.is_valid():
            revision = question.revisions.get(revision=revision_form.cleaned_data['revision'])
        else:
            revision = question.active_revision

        if 'select_revision' in request.POST:
            form = EditQuestionForm(question, request.user, revision)
        else:
            form = EditQuestionForm(question, request.user, revision, data=request.POST)

        if not 'select_revision' in request.POST and form.is_valid() and \
                not (conflict := live.edit_conflict(request, question, form)):
            # Stored on the post, not in a revision (forum/utils/post_versions.py).
            post_versions.save(question, request.POST, form.cleaned_data['tags'].split())
            if form.has_changed():
                action = action_class(user=request.user, node=question, ip=request.META['REMOTE_ADDR']).save(data=form.cleaned_data)

                if settings.WIKI_ON:
                    if request.POST.get('wiki', False) and not question.nis.wiki:
                        question.nstate.wiki = action
                    elif question.nis.wiki and (not request.POST.get('wiki', False)) and request.user.can_cancel_wiki(question):
                        question.nstate.wiki = None
            else:
                if not revision == question.active_revision:
                    if allow_rollback:
                        RollbackAction(user=request.user, node=question).save(data=dict(activate=revision))
                    else:
                        pass

            return HttpResponseRedirect(url_getter(question))
    else:
        revision_form = RevisionForm(question)
        form = EditQuestionForm(question, request.user, initial={'summary': summary})

    context = {
        'question': question,
        'revision_form': revision_form,
        'form' : form,
        'version_groups': post_versions.form_groups(
            request.POST.get('tags', '').split() if request.method == 'POST' else question.tagname_list(),
            node=question, data=request.POST if request.method == 'POST' else None, show_all=True),
    }
    context.update(live.edit_context(request, question, conflict))

    if not (additional_context is None):
        context.update(additional_context)

    return render(request, template, context)


def edit_answer(request, id):
    answer = get_object_or_404(Answer, id=id)
    if answer.deleted and not request.user.can_view_deleted_post(answer):
        raise Http404
    elif not review.can_view(answer, request.user):
        raise Http404
    elif not request.user.can_edit_post(answer):
        raise Http404

    conflict = None  # changed by someone else since the form was opened (forum/utils/live.py)
    if request.method == "POST":
        revision_form = RevisionForm(answer, data=request.POST)
        if revision_form.is_valid():
            revision = answer.revisions.get(revision=revision_form.cleaned_data['revision'])
        else:
            revision = answer.active_revision

        if 'select_revision' in request.POST:
            form = EditAnswerForm(answer, request.user, revision)
        else:
            form = EditAnswerForm(answer, request.user, revision, data=request.POST)

        if not 'select_revision' in request.POST and form.is_valid() and \
                not (conflict := live.edit_conflict(request, answer, form)):
            post_versions.save(answer, request.POST, post_versions.question_tag_names(answer))
            if form.has_changed():
                action = ReviseAction(user=request.user, node=answer, ip=request.META['REMOTE_ADDR']).save(data=form.cleaned_data)

                if settings.WIKI_ON:
                    if request.POST.get('wiki', False) and not answer.nis.wiki:
                        answer.nstate.wiki = action
                    elif answer.nis.wiki and (not request.POST.get('wiki', False)) and request.user.can_cancel_wiki(answer):
                        answer.nstate.wiki = None
            else:
                if not revision == answer.active_revision:
                    RollbackAction(user=request.user, node=answer, ip=request.META['REMOTE_ADDR']).save(data=dict(activate=revision))

            return HttpResponseRedirect(answer.get_absolute_url())

    else:
        revision_form = RevisionForm(answer)
        form = EditAnswerForm(answer, request.user)
    return render(request, 'answer_edit.html', {
                              'answer': answer,
                              'revision_form': revision_form,
                              'form': form,
                              'version_groups': post_versions.form_groups(
                                  post_versions.question_tag_names(answer), node=answer,
                                  data=request.POST if request.method == 'POST' else None),
                              **live.edit_context(request, answer, conflict),
                              })

def answer(request, id):
    question = get_object_or_404(Question, id=id)
    if not review.can_view(question, request.user):
        raise Http404
    if question.nis.deleted and not request.user.can_view_deleted_post(question):
        raise Http404

    if request.POST and (question.nis.closed or question.nis.deleted):
        # The page shows no answer form then; a hand-made request is refused too (as by the API).
        messages.error(request, _("This question is closed: it takes no new answers."))
        return HttpResponseRedirect(question.get_absolute_url())

    if request.POST:
        form = AnswerForm(request.POST, request.user)

        if request.session.pop('reviewing_pending_data', False) or not form.is_valid():
            request.session['redirect_POST_data'] = request.POST.urlencode()
            return HttpResponseRedirect(question.get_absolute_url() + '#fmanswer')

        if request.user.is_authenticated and posting_limit_reached(request.user, 'answer'):
            messages.error(request, posting_limit_message('answer'))
            request.session['redirect_POST_data'] = request.POST.urlencode()
            return HttpResponseRedirect(question.get_absolute_url() + '#fmanswer')

        if request.user.is_authenticated and request.user.email_valid_and_can_answer():
            answer_action = AnswerAction(user=request.user, ip=request.META['REMOTE_ADDR']).save(dict(question=question, **form.cleaned_data))
            answer = answer_action.node
            post_versions.save(answer, request.POST, question.tagname_list())

            if settings.WIKI_ON and request.POST.get('wiki', False):
                answer.nstate.wiki = answer_action

            return HttpResponseRedirect(answer.get_absolute_url())
        else:
            request.session[PENDING_SUBMISSION_SESSION_ATTR] = {
                'POST': request.POST.urlencode(),
                'data_name': _("answer"),
                'type': 'answer',
                'submission_url': reverse('answer', kwargs={'id': id}),
                'time': datetime.datetime.now().isoformat()
            }

            if request.user.is_authenticated:
                messages.info(request, _("Your answer is pending until you %s.") % html.hyperlink(
                    settings.APP_URL + root_relative_reverse('send_validation_email'), _("validate your email")
                ))
                return HttpResponseRedirect(question.get_absolute_url())
            else:
                return HttpResponseRedirect(reverse('auth_signin'))

    return HttpResponseRedirect(question.get_absolute_url())


def manage_pending_data(request, action, forward=None):
    pending_data = request.session.pop(PENDING_SUBMISSION_SESSION_ATTR, None)

    if not pending_data:
        raise Http404

    if action == _("cancel"):
        return HttpResponseRedirect(forward or request.META.get('HTTP_REFERER', '/'))
    else:
        if action == _("review"):
            request.session['reviewing_pending_data'] = True

        request.session['redirect_POST_data'] = pending_data['POST']
        return HttpResponseRedirect(pending_data['submission_url'])
