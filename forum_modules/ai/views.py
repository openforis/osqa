from django.core.cache import cache
from django.http import HttpResponseNotAllowed, JsonResponse

from .client import is_configured
from .duplicates import find_duplicates
from .settings import AI_DUPLICATE_DETECTION, AI_DUPLICATE_CHECKS_PER_HOUR, AI_ASSISTANT, AI_ASSISTANT_PER_HOUR


def enabled():
    return is_configured() and bool(AI_DUPLICATE_DETECTION)


def rate_limiter(request, name='dup', per_hour=None):
    """Counts uncached requests per user (or IP) in an hourly window."""
    who = request.user.id if request.user.is_authenticated else request.META.get('REMOTE_ADDR', '')
    key = 'ai-%s-rate:%s' % (name, who)
    limit = AI_DUPLICATE_CHECKS_PER_HOUR if per_hour is None else per_hour

    def may_call_api():
        used = cache.get(key, 0)
        if used >= int(limit):
            return False
        if used:
            cache.incr(key)
        else:
            cache.set(key, 1, 3600)
        return True

    return may_call_api


def duplicate_check(request):
    """Existing questions that ask the same thing as the title being written."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    title = ' '.join(request.POST.get('title', '').split())[:300]
    body = request.POST.get('text', '')[:5000]
    if not enabled() or len(title) < 15 or len(title.split()) < 3:
        return JsonResponse({'duplicates': []})

    duplicates = find_duplicates(title, body, rate_limiter(request))
    return JsonResponse({'duplicates': [{
        'id': question.id,
        'title': question.title,
        'url': question.get_absolute_url(),
        'answers': question.answer_count,
        'accepted': question.accepted_count > 0,
        'reason': reason,
    } for question, reason in duplicates]})


def assistant_answer(request):
    """An AI answer, with sources, to the question being written on the ask page."""
    import hashlib
    from .assistant import answer_question

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    title = ' '.join(request.POST.get('title', '').split())[:300]
    body = request.POST.get('text', '')[:5000]
    if not (is_configured() and bool(AI_ASSISTANT)):
        return JsonResponse({'error': 'unavailable'}, status=404)
    if len(title) < 15:
        return JsonResponse({'error': 'title'}, status=400)

    key = 'ai-assistant:' + hashlib.sha1(('%s|%s' % (title.lower(), body.strip())).encode('utf-8')).hexdigest()
    result = cache.get(key)
    if result is None:
        if not rate_limiter(request, 'assistant', AI_ASSISTANT_PER_HOUR)():
            return JsonResponse({'error': 'limit'}, status=429)
        result = answer_question(title, body)
        if result is None:
            return JsonResponse({'error': 'failed'}, status=503)
        result = {'insufficient': result['insufficient'], 'html': str(result['html']), 'sources': result['sources']}
        cache.set(key, result, 3600)
    return JsonResponse(result)


def test_connection(request):
    """Admin > AI assistance > "Test connection": tries the connection values
    of the settings form (posted, not saved) and explains what fails. The form
    posts here with fetch() and shows the fragment; without JavaScript the
    result is a page of its own."""
    from django.shortcuts import redirect, render
    from django.urls import reverse
    from forum.views.admin import admin_page_wrapper, super_user_required
    from . import diagnostics

    @super_user_required
    def view(request):
        if request.method != 'POST':
            return redirect(reverse('admin_set', args=['ai']))
        context = {'result': diagnostics.run_test(diagnostics.form_values(request.POST))}
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return render(request, 'modules/ai/test_result.html', context)
        return admin_page_wrapper(lambda request: ('modules/ai/test_page.html', context), request)

    return view(request)
