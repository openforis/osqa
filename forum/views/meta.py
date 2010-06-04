import os
from itertools import groupby
from django.shortcuts import render_to_response, get_object_or_404
from django.core.urlresolvers import reverse
from django.template import RequestContext, loader
from django.http import HttpResponseRedirect, HttpResponse
from django.views.static import serve
from forum import settings
from forum.forms import FeedbackForm
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext as _
from django.db.models import Count
from forum.utils.forms import get_next_url
from forum.models import Badge, Award, User
from forum.badges.base import BadgesMeta
from forum import settings
from forum.utils.mail import send_template_email
import re

def favicon(request):
    return HttpResponseRedirect(str(settings.APP_FAVICON))

def static(request, title, content):
    return render_to_response('static.html', {'content' : content, 'title': title}, context_instance=RequestContext(request))

def media(request, skin, path):
    return serve(request, "%s/media/%s" % (skin, path), 
                 document_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),'skins').replace('\\','/'))

def markdown_help(request):
    # md = markdown.Markdown([SettingsExtension({})])
    # text = md.convert(settings.FAQ_PAGE_TEXT.value)

    return render_to_response('markdown_help.html', context_instance=RequestContext(request))


def opensearch(request):   
    return render_to_response('opensearch.html', {'settings' : settings}, context_instance=RequestContext(request))
    

def feedback(request):
    if request.method == "POST":
        form = FeedbackForm(request.POST)
        if form.is_valid():
            context = {'user': request.user}

            if not request.user.is_authenticated:
                context['email'] = form.cleaned_data.get('email',None)
            context['message'] = form.cleaned_data['message']
            context['name'] = form.cleaned_data.get('name',None)
            context['ip'] = request.META['REMOTE_ADDR']

            recipients = User.objects.filter(is_superuser=True)
            send_template_email(recipients, "notifications/feedback.html", context)
            
            msg = _('Thanks for the feedback!')
            request.user.message_set.create(message=msg)
            return HttpResponseRedirect(get_next_url(request))
    else:
        form = FeedbackForm(initial={'next':get_next_url(request)})

    return render_to_response('feedback.html', {'form': form}, context_instance=RequestContext(request))
feedback.CANCEL_MESSAGE=_('We look forward to hearing your feedback! Please, give it next time :)')

def privacy(request):
    return render_to_response('privacy.html', context_instance=RequestContext(request))

def logout(request):
    return render_to_response('logout.html', {
        'next' : get_next_url(request),
    }, context_instance=RequestContext(request))

def badges(request):
    badges = [b.ondb for b in sorted(BadgesMeta.by_id.values(), lambda b1, b2: cmp(b1.name, b2.name))]
    
    if request.user.is_authenticated():
        my_badges = Award.objects.filter(user=request.user).values('badge_id').distinct()
    else:
        my_badges = []

    return render_to_response('badges.html', {
        'badges' : badges,
        'mybadges' : my_badges,
    }, context_instance=RequestContext(request))

def badge(request, id, slug):
    badge = Badge.objects.get(id=id)
    awards = list(Award.objects.filter(badge=badge).order_by('user', 'awarded_at'))
    award_count = len(awards)
    
    awards = sorted([dict(count=len(list(g)), user=k) for k, g in groupby(awards, lambda a: a.user)],
                    lambda c1, c2: c2['count'] - c1['count'])

    return render_to_response('badge.html', {
        'award_count': award_count,
        'awards' : awards,
        'badge' : badge,
    }, context_instance=RequestContext(request))

