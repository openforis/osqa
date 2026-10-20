from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r'^%s$' % 'ai/duplicates/', views.duplicate_check, name='ai_duplicate_check'),
    re_path(r'^%s$' % 'ai/assistant/', views.assistant_answer, name='ai_assistant'),
    re_path(r'^%s$' % 'admin/ai/test/', views.test_connection, name='ai_test_connection'),
]
