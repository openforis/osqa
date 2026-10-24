from django.urls import re_path, include
from django.conf import settings

urlpatterns = [
    # set_language: the language switcher in the footer
    re_path(r'^i18n/', include('django.conf.urls.i18n')),
    re_path(r'', include('forum.urls')),
]

if 'rosetta' in settings.INSTALLED_APPS:
    urlpatterns = [
        re_path(r'^rosetta/', include('rosetta.urls')),
    ] + urlpatterns

handler400 = 'forum.views.meta.bad_request'
handler404 = 'forum.views.meta.page'
handler500 = 'forum.views.meta.error_handler'
