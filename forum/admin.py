
#from django.contrib import admin
#from models import *
#
#class AnonymousQuestionAdmin(admin.ModelAdmin):
#    """AnonymousQuestion admin class"""
#
#class NodeAdmin(admin.ModelAdmin):
#    """Question admin class"""
#
#class TagAdmin(admin.ModelAdmin):
#    """Tag admin class"""
#
#class Answerdmin(admin.ModelAdmin):
#    """Answer admin class"""
#
#class CommentAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class VoteAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class FlaggedItemAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class FavoriteQuestionAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class QuestionRevisionAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class AnswerRevisionAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class AwardAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class BadgeAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class ReputeAdmin(admin.ModelAdmin):
#    """  admin class"""
#
#class ActionAdmin(admin.ModelAdmin):
#    """  admin class"""

#class BookAdmin(admin.ModelAdmin):
#    """  admin class"""

#class BookAuthorInfoAdmin(admin.ModelAdmin):
#    """  admin class"""

#class BookAuthorRssAdmin(admin.ModelAdmin):
#    """  admin class"""

#admin.site.register(Node, NodeAdmin)
#admin.site.register(Tag, TagAdmin)
#admin.site.register(QuestionRevision, QuestionRevisionAdmin)
#admin.site.register(AnswerRevision, AnswerRevisionAdmin)
#admin.site.register(Badge, BadgeAdmin)
#admin.site.register(Award, AwardAdmin)
#admin.site.register(Action, ActionAdmin)
#admin.site.register(Book, BookAdmin)
#admin.site.register(BookAuthorInfo, BookAuthorInfoAdmin)
#admin.site.register(BookAuthorRss, BookAuthorRssAdmin)


# Django's model admin (/nimda/) signs nobody in itself: its login page would
# skip OSQA's two-step verification, sign-in lockout and session bookkeeping.
# It sends people to OSQA's sign-in instead, and admits only staff whose
# session OSQA signed in (login_and_forward() records the session epoch only
# after the second factor) and who have two-step verification when staff must.
from urllib.parse import quote

from django.contrib import admin as _admin
from django.http import HttpResponseRedirect
from django.urls import reverse


def _osqa_session(request):
    from forum.utils import accounts
    return accounts.EPOCH_SESSION_KEY in request.session and accounts.session_valid(request, request.user)


def _osqa_sign_in(request, extra_context=None):
    """Django admin's login page: OSQA's sign-in, or why the signed-in
    member can't come in."""
    from django.contrib.auth import logout
    from forum.http_responses import HttpResponseUnauthorized
    from forum.utils import two_factor
    from forum.views.auth import clean_next
    user = request.user
    if user.is_authenticated and _osqa_session(request):
        if user.is_active and user.is_staff and two_factor.staff_must_set_up(request):
            from forum.views.security import _security_url
            return HttpResponseRedirect(_security_url(user))
        return HttpResponseUnauthorized(request)
    if user.is_authenticated:
        logout(request)  # a session OSQA didn't sign in: start over there
    target = clean_next(request.GET.get('next') or reverse('admin:index'))
    return HttpResponseRedirect('%s?next=%s' % (reverse('auth_signin'), quote(target)))


_django_has_permission = _admin.site.has_permission


def _has_permission(request):
    from forum.utils import two_factor
    return _django_has_permission(request) and _osqa_session(request) and not two_factor.staff_must_set_up(request)


_admin.site.login = _osqa_sign_in
_admin.site.has_permission = _has_permission
