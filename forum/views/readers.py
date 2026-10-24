# encoding:utf-8
import datetime
import logging
from urllib.parse import unquote
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect, Http404, HttpResponsePermanentRedirect
from django.core.paginator import Paginator, EmptyPage, InvalidPage
from django import template
from django.utils.html import *
from urllib.parse import quote as urlquote
from django.db.models import Q, Count
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.urls import reverse
from django.template.defaultfilters import slugify
from django.utils.safestring import mark_safe

from forum import settings as django_settings
from forum.utils.html import hyperlink
from forum.utils.diff import textDiff as htmldiff
from forum.utils import pagination
from forum.forms import *
from forum.models import *
from forum.actions import QuestionViewAction
from forum import notifications
from forum.http_responses import HttpResponseUnauthorized
from forum.feed import RssQuestionFeed, RssAnswerFeed
from forum.utils.pagination import generate_uri
from forum.utils import conditional
from forum.utils import review
from forum.utils import post_versions
from forum.utils.tags import can_manage_tags

from . import decorators

class HottestQuestionsSort(pagination.SortBase):
    def apply(self, questions):
        return questions.extra(select={'new_child_count': '''
            SELECT COUNT(1)
                FROM forum_node fn1
                WHERE fn1.abs_parent_id = forum_node.id
                    AND fn1.id != forum_node.id
                    AND NOT(fn1.state_string LIKE '%%(deleted)%%')
                    AND NOT(fn1.state_string LIKE '%%(pending_review)%%')
                    AND added_at > %s'''
            },
            select_params=[ (datetime.datetime.now() - datetime.timedelta(days=2))
                .strftime('%Y-%m-%d')]
        ).order_by('-new_child_count', 'last_activity_at')

class UnansweredQuestionsSort(pagination.SortBase):
    def apply(self, questions):
        # Not 'answer_count': Django would assign it to the read-only Question.answer_count property.
        return questions.extra(select={'visible_answer_count': '''
            SELECT COUNT(1)
                FROM forum_node fn1
                WHERE fn1.abs_parent_id = forum_node.id
                    AND fn1.id != forum_node.id
                    AND fn1.node_type='answer'
                    AND NOT(fn1.state_string LIKE '%%(deleted)%%')
                    AND NOT(fn1.state_string LIKE '%%(pending_review)%%')'''
            }).order_by('visible_answer_count', 'last_activity_at')

class QuestionListPaginatorContext(pagination.PaginatorContext):
    def __init__(self, id='QUESTIONS_LIST', prefix='', pagesizes=(15, 30, 50), default_pagesize=30):
        super (QuestionListPaginatorContext, self).__init__(id, sort_methods=(
            ('active', pagination.SimpleSort(_('active'), '-last_activity_at', _("Most <strong>recently updated</strong> questions"))),
            ('newest', pagination.SimpleSort(_('newest'), '-added_at', _("most <strong>recently asked</strong> questions"))),
            ('hottest', HottestQuestionsSort(_('hottest'), _("most <strong>active</strong> questions in the last 24 hours</strong>"))),
            ('mostvoted', pagination.SimpleSort(_('most voted'), '-score', _("most <strong>voted</strong> questions"))),
            ('unanswered', UnansweredQuestionsSort('unanswered', "questions with no answers")),
        ), pagesizes=pagesizes, default_pagesize=default_pagesize, prefix=prefix)

class AnswerSort(pagination.SimpleSort):
    def apply(self, answers):
        if not settings.DISABLE_ACCEPTING_FEATURE:
            return answers.order_by(*(['-marked'] + list(self._get_order_by())))
        else:
            return super(AnswerSort, self).apply(answers)

class AnswerPaginatorContext(pagination.PaginatorContext):
    def __init__(self, id='ANSWER_LIST', prefix='', default_pagesize=10):
        super (AnswerPaginatorContext, self).__init__(id, sort_methods=(
            ('active', AnswerSort(_('active answers'), '-last_activity_at', _("most recently updated answers/comments will be shown first"))),
            ('oldest', AnswerSort(_('oldest answers'), 'added_at', _("oldest answers will be shown first"))),
            ('newest', AnswerSort(_('newest answers'), '-added_at', _("newest answers will be shown first"))),
            ('votes', AnswerSort(_('popular answers'), ('-score', 'added_at'), _("most voted answers will be shown first"))),
        ), default_sort='votes', pagesizes=(5, 10, 20), default_pagesize=default_pagesize, prefix=prefix)

class TagPaginatorContext(pagination.PaginatorContext):
    def __init__(self):
        super (TagPaginatorContext, self).__init__('TAG_LIST', sort_methods=(
            ('name', pagination.SimpleSort(_('by name'), 'name', _("sorted alphabetically"))),
            ('used', pagination.SimpleSort(_('by popularity'), '-used_count', _("sorted by frequency of tag use"))),
        ), default_sort='used', pagesizes=(30, 60, 120))
    

def feed(request):
    etag = conditional.anonymous_page_etag(request, 'feed', shows_messages=False)
    response = conditional.not_modified(request, etag)
    if response is not None:
        return response
    return conditional.finish(_latest_questions_feed(request), etag)


def _latest_questions_feed(request):
    return RssQuestionFeed(
                request,
                Question.objects.public().order_by('-last_activity_at'),
                settings.APP_TITLE + _(' - ')+ _('latest questions'),
                settings.APP_DESCRIPTION)(request)

@decorators.render('index.html')
def index(request):
    paginator_context = QuestionListPaginatorContext()
    paginator_context.base_path = reverse('questions')
    return question_list(request,
                         Question.objects.all(),
                         base_path=reverse('questions'),
                         feed_url=reverse('latest_questions_feed'),
                         paginator_context=paginator_context)

@decorators.render('questions.html', 'unanswered', _lazy('unanswered'), weight=400)
def unanswered(request):
    return question_list(request,
                         Question.objects.exclude(id__in=Question.objects.filter(children__marked=True).distinct()).exclude(marked=True),
                         _('open questions without an accepted answer'),
                         None,
                         _("Unanswered Questions"))

@decorators.render('questions.html', 'questions', _lazy('questions'), weight=0)
def questions(request):
    return question_list(request,
                         Question.objects.all(),
                         _('questions'))

@decorators.render('questions.html')
def tag(request, tag):
    name = unquote(tag)
    # One query: a synonym's page redirects to its tag, a tag lists its synonyms ("Also called").
    synonyms = list(TagSynonym.objects.filter(Q(source_name=name) | Q(target__name=name)).select_related('target'))
    for synonym in synonyms:
        if synonym.source_name == name:
            return HttpResponsePermanentRedirect(synonym.target.get_absolute_url())

    try:
        tag = Tag.active.get(name=name)
    except Tag.DoesNotExist:
        raise Http404

    # Getting the questions QuerySet
    questions = Question.objects.filter(tags__id=tag.id)

    if request.method == "GET":
        user = request.GET.get('user', None)

        if user is not None:
            try:
                questions = questions.filter(author=User.objects.get(username=user))
            except User.DoesNotExist:
                raise Http404

    # The extra tag context we need to pass
    tag_context = {
        'tag' : tag,
        'tag_synonyms': [synonym.source_name for synonym in sorted(synonyms, key=lambda s: s.source_name)],
        'can_manage_tags': can_manage_tags(request.user),
    }

    # The context returned by the question_list function, contains info about the questions
    question_context = question_list(request,
                         questions,
                         mark_safe(_(u'questions tagged <span class="tag">%(tag)s</span>') % {'tag': tag}),
                         None,
                         mark_safe(_(u'Questions Tagged With %(tag)s') % {'tag': tag}),
                         False)

    # If the return data type is not a dict just return it
    if not isinstance(question_context, dict):
        return question_context

    question_context = dict(question_context)

    # Create the combined context
    # Python 3: Use dict unpacking instead of adding dict.items()
    context = {**question_context, **tag_context}

    return context

@decorators.render('questions.html', 'questions', tabbed=False)
def user_questions(request, mode, user, slug):
    user = get_object_or_404(User, id=user)

    if mode == 'asked-by':
        questions = Question.objects.filter(author=user)
        description = _("Questions asked by %s")
    elif mode == 'answered-by':
        # Answers held for review only count for those who may see them.
        answers = Answer.objects.filter(author=user).visible_to(request.user)
        questions = Question.objects.filter(id__in=answers.values('parent_id'))
        description = _("Questions answered by %s")
    elif mode == 'subscribed-by':
        if not (request.user.is_superuser or request.user == user):
            return HttpResponseUnauthorized(request)
        # user.subscriptions holds Nodes; the list needs Questions (answer counts).
        questions = Question.objects.filter(id__in=user.subscriptions.values('id'))

        if request.user == user:
            description = _("Questions you subscribed %s")
        else:
            description = _("Questions subscribed by %s")
    else:
        raise Http404


    return question_list(request, questions,
                         mark_safe(description % hyperlink(user.get_profile_url(), user.username)),
                         page_title=description % user.username)

def question_list(request, initial,
                  list_description=_lazy('questions'),
                  base_path=None,
                  page_title=_lazy("All Questions"),
                  allowIgnoreTags=True,
                  feed_url=None,
                  paginator_context=None,
                  show_summary=None,
                  feed_sort=('-added_at',),
                  feed_req_params_exclude=('page', 'pagesize', 'sort'),
                  extra_context={}):

    if show_summary is None:
        show_summary = bool(settings.SHOW_SUMMARY_ON_QUESTIONS_LIST)

    # Posts held for review: only their authors and the moderators see them.
    questions = initial.visible_to(request.user)

    if request.user.is_authenticated and allowIgnoreTags:
        questions = questions.filter(~Q(tags__id__in = request.user.marked_tags.filter(user_selections__reason = 'bad')))

    if page_title is None:
        page_title = _("Questions")

    if request.GET.get('type', None) == 'rss':
        questions = questions.public()
        if feed_sort:
            questions = questions.order_by(*feed_sort)
        return RssQuestionFeed(request, questions, page_title, list_description)(request)

    keywords =  ""
    if request.GET.get("q"):
        keywords = request.GET.get("q").strip()

    #answer_count = Answer.objects.filter_state(deleted=False).filter(parent__in=questions).count()
    #answer_description = _("answers")

    if not feed_url:
        req_params = generate_uri(request.GET, feed_req_params_exclude)

        if req_params:
            req_params = '&' + req_params

        feed_url = request.path + "?type=rss" + req_params

    context = {
        # Per row: who was active last (from the object cache) and the answer
        # counts, loaded for the shown page in one go instead of per question.
        'questions' : questions.distinct().prefetch_cached(fks=('last_activity_by',),
                                                           counts=('answer_count', 'accepted_count'),
                                                           after=(post_versions.prefetch,)),
        'questions_count' : questions.count(),
        'keywords' : keywords,
        'list_description': list_description,
        'base_path' : base_path,
        'page_title' : page_title,
        'tab' : 'questions',
        'feed_url': feed_url,
        'show_summary' : show_summary,
    }
    context.update(extra_context)

    return pagination.paginated(request,
                               ('questions', paginator_context or QuestionListPaginatorContext()), context)


@decorators.render('tags.html', 'tags', _lazy('tags'), weight=100)
def tags(request):
    stag = ""
    tags = Tag.active.all()

    if request.method == "GET":
        stag = request.GET.get("q", "").strip()
        if stag:
            tags = tags.filter(name__icontains=stag)

    return pagination.paginated(request, ('tags', TagPaginatorContext()), {
        "tags" : tags,
        "stag" : stag,
        "keywords" : stag,
        "can_manage_tags": can_manage_tags(request.user),
    })

def update_question_view_times(request, question):
    # JSON-serialized session: string keys and ISO datetimes.
    last_seen_in_question = request.session.get('last_seen_in_question', {})

    last_seen = last_seen_in_question.get(str(question.id), None)

    if (not last_seen) or (datetime.datetime.fromisoformat(last_seen) < question.last_activity_at):
        QuestionViewAction(question, request.user, ip=request.META['REMOTE_ADDR']).save()
        last_seen_in_question[str(question.id)] = datetime.datetime.now().isoformat()
        request.session['last_seen_in_question'] = last_seen_in_question

def match_question_slug(id, slug):
    slug_words = slug.split('-')
    qs = Question.objects.filter(title__istartswith=slug_words[0])

    for q in qs:
        if slug == urlquote(slugify(q.title)):
            return q

    return None

def answer_redirect(request, answer):
    pc = AnswerPaginatorContext()

    sort = pc.sort(request)

    if sort == _('oldest'):
        filter = Q(added_at__lt=answer.added_at)
    elif sort == _('newest'):
        filter = Q(added_at__gt=answer.added_at)
    elif sort == _('votes'):
        filter = Q(score__gt=answer.score) | Q(score=answer.score, added_at__lt=answer.added_at)
    else:
        raise Http404()

    count = answer.question.answers.visible_to(request.user).filter(Q(marked=True) | filter).count()
    pagesize = pc.pagesize(request)

    page = count // pagesize
    
    if count % pagesize:
        page += 1
        
    if page == 0:
        page = 1

    return HttpResponseRedirect("%s?%s=%s&focusedAnswerId=%s#%s" % (
        answer.question.get_absolute_url(), 'page', page, answer.id, answer.id))

@decorators.render("question.html", 'questions')
def question(request, id, slug='', answer=None):
    try:
        question = Question.objects.get(id=id)
    except:
        if slug:
            question = match_question_slug(id, slug)
            if question is not None:
                return HttpResponseRedirect(question.get_absolute_url())

        raise Http404()

    if question.nis.deleted and not request.user.can_view_deleted_post(question):
        raise Http404

    if not review.can_view(question, request.user):
        raise Http404

    if request.GET.get('type', None) == 'rss':
        return RssAnswerFeed(request, question, include_comments=request.GET.get('comments', None) == 'yes')(request)

    if answer:
        answer = get_object_or_404(Answer, id=answer)

        if (question.nis.deleted and not request.user.can_view_deleted_post(question)) or answer.question != question:
            raise Http404

        if not review.can_view(answer, request.user):
            raise Http404

        if answer.marked:
            return HttpResponsePermanentRedirect(question.get_absolute_url())

        return answer_redirect(request, answer)

    if settings.FORCE_SINGLE_URL and (slug != slugify(question.title)):
        return HttpResponsePermanentRedirect(question.get_absolute_url())

    # Conditional GET for anonymous visitors whose view of this question is
    # already counted (see forum.utils.conditional for what the ETag covers).
    etag = None
    last_seen = request.session.get('last_seen_in_question', {}).get(str(question.id)) \
        if not request.user.is_authenticated else None
    if not request.POST and last_seen and question.last_activity_at and \
            datetime.datetime.fromisoformat(last_seen) >= question.last_activity_at:
        etag = conditional.anonymous_page_etag(request, 'question', question.id)
        response = conditional.not_modified(request, etag)
        if response is not None:
            return response

    if request.POST:
        answer_form = AnswerForm(request.POST, user=request.user)
    else:
        answer_form = AnswerForm(user=request.user)

    # Authors and the question itself (each answer's parent) from the object
    # cache in one round trip for the shown page.
    answers = request.user.get_visible_answers(question).prefetch_cached(fks=('author', 'parent'))

    update_question_view_times(request, question)

    if request.user.is_authenticated:
        notifications.mark_question_read(request.user, question)
        try:
            subscription = QuestionSubscription.objects.get(question=question, user=request.user)
        except:
            subscription = False
    else:
        subscription = False
    try:
        focused_answer_id = int(request.GET.get("focusedAnswerId", None))
    except (TypeError, ValueError):
        focused_answer_id = None

    return pagination.paginated(request, ('answers', AnswerPaginatorContext()), {
    "question" : question,
    "answer" : answer_form,
    "answers" : answers,
    "similar_questions" : question.get_related_questions(),
    "subscription": subscription,
    "embed_youtube_videos" : settings.EMBED_YOUTUBE_VIDEOS,
    "focused_answer_id" : focused_answer_id,
    # The answer form's "Applies to version" selects (forum/utils/post_versions.py).
    "version_groups": post_versions.form_groups(question.tagname_list(), data=request.POST or None),
    "_etag": etag,
    })


REVISION_TEMPLATE = template.loader.get_template('node/revision.html')

def revisions(request, id):
    post = get_object_or_404(Node, id=id).leaf

    # Same rule as the question page: deleted posts (or posts under a deleted
    # question) are only visible to users allowed to see deleted content.
    for node in (post, post.abs_parent):
        if node is not None and node.nis.deleted and not request.user.can_view_deleted_post(node):
            raise Http404()
    if not review.can_view(post, request.user):
        raise Http404()

    revisions = list(post.revisions.order_by('revised_at'))
    rev_ctx = []

    for i, revision in enumerate(revisions):
        # Django 4.2: Template.render() expects a dict, not a Context object
        rev_ctx.append(dict(inst=revision, html=template.loader.get_template('node/revision.html').render({
        'title': revision.title,
        'html': revision.html,
        'tags': revision.tagname_list(),
        })))

        if i > 0:
            rev_ctx[i]['diff'] = mark_safe(htmldiff(rev_ctx[i-1]['html'], rev_ctx[i]['html']))
        else:
            rev_ctx[i]['diff'] = mark_safe(rev_ctx[i]['html'])

        if not (revision.summary):
            rev_ctx[i]['summary'] = _('Revision n. %(rev_number)d') % {'rev_number': revision.revision}
        else:
            rev_ctx[i]['summary'] = revision.summary

    rev_ctx.reverse()

    return render(request, 'revisions.html', {
    'post': post,
    'revisions': rev_ctx,
    })



