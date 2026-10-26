from . import startup  # noqa: F401  (registers modules, hooks and UI)

import os.path
from forum import settings
from django.urls import re_path, include
from django.conf import settings as djsettings
from django.contrib import admin
from forum import views as app
from forum.views import api as api_views
from forum.sitemap import OsqaSitemap, index as sitemap_index, sitemap_section_index, sitemap
from django.utils.translation import gettext_lazy as _lazy
from django.shortcuts import redirect

# Django 1.7+: admin.autodiscover() is automatic, no longer needed
# admin.autodiscover()

sitemaps = {
    'questions': OsqaSitemap
}

APP_PATH = os.path.dirname(__file__)

# Choose the user urls pattern
if bool(settings.INCLUDE_ID_IN_USER_URLS.value):
    core_user_urls_prefix = r'^%s(?P<id>\d+)/(?P<slug>.*)'
else:
    core_user_urls_prefix = r'^%s(?P<slug>.*)'

core_urls = [
    re_path(r'^$', app.readers.index, name='index'),
    #re_path(r'^%s(.*)' % 'nimda/', admin.site.urls),
    #re_path(r'^%s(.*)' % 'nimda/', include(admin.site.urls)),
    re_path(r'^nimda/', admin.site.urls),


    re_path(r'^sitemap.xml$', sitemap_index, {'sitemaps': sitemaps}),
    re_path(r'^llms\.txt$', app.agents.llms_txt, name='llms_txt'),
    re_path(r'^export/qa\.jsonl$', app.agents.qa_export, name='qa_export'),
    re_path(r'^mcp/?$', app.agents.mcp, name='mcp'),
    # The JSON API (forum/api/): docs, /api/v1/ endpoints and personal access tokens.
    re_path(r'^api/$', api_views.docs, name='api_docs'),
    re_path(r'^api/v1/', include('forum.api.urls')),
    re_path(r'^account/(?P<id>\d+)/api-tokens/$', api_views.tokens_page, name='user_api_tokens'),
    re_path(r'^account/(?P<id>\d+)/api-tokens/(?P<token_id>\d+)/revoke/$', api_views.revoke_token,
            name='user_api_token_revoke'),
    re_path(r'^%s(?P<token>[\w:.-]+)/$' % 'unsubscribe/', app.email_prefs.email_unsubscribe, name='email_unsubscribe'),
    re_path(r'^%s$' % 'help/email/', app.email_prefs.email_help, name='email_help'),
    re_path(r'^%s(?P<tag>[^/]+)/$' % 'follow-tag/', app.email_prefs.follow_tag, name='follow_tag'),
    re_path(r'^ai-suggestions/(?P<id>\d+)/(?P<verdict>helpful|remove)/$', app.agents.ai_suggestion_feedback, name='ai_suggestion_feedback'),
    re_path(r'^sitemap-(?P<section>.+)-(?P<page>\d+)\.xml$', sitemap, {'sitemaps': sitemaps}, name="sitemap_section_page"),
    re_path(r'^sitemap-(?P<section>.+)\.xml$', sitemap_section_index, {'sitemaps': sitemaps}, name="sitemap_section_index"),

    re_path(r'^favicon\.ico$', app.meta.favicon),
    re_path(r'^manifest\.webmanifest$', app.pwa.manifest, name='manifest'),
    re_path(r'^sw\.js$', app.pwa.service_worker, name='service_worker'),
    re_path(r'^offline/$', app.pwa.offline, name='offline'),
    re_path(r'^push/subscribe/$', app.push.subscribe, name='push_subscribe'),
    re_path(r'^push/unsubscribe/$', app.push.unsubscribe, name='push_unsubscribe'),
    re_path(r'^push/settings/$', app.push.push_settings, name='push_settings'),
    re_path(r'^preferences/theme/$', app.display.set_theme, name='set_theme'),
    re_path(r'^cstyle\.css$', app.meta.custom_css, name='custom_css'),

    re_path(r'^m/django_admin/(?P<path>.*)$', app.meta.django_admin_media, name='django_admin_media'),
    re_path(r'^m/static/admin/(?P<path>.*)$', app.meta.django_admin_media, name='django_admin_static'),
    re_path(r'^m/(?P<skin>\w+)/media/(?P<path>.*)$', app.meta.media , name='osqa_media'),
    re_path(r'^upfiles/(?P<path>.*)$', app.meta.uploaded_file, name='uploaded_file'),

    re_path(r'^%s$' % 'faq/', app.meta.static, {'content': settings.FAQ_PAGE_TEXT, 'title': _lazy('FAQ')}, name='faq'),
    re_path(r'^%s$' % 'about/', app.meta.static, {'content': settings.ABOUT_PAGE_TEXT, 'title': _lazy('About')}, name='about'),
    re_path(r'^%s$' % 'markdown_help/', app.meta.markdown_help, name='markdown_help'), re_path(r'^opensearch\.xml$', app.meta.opensearch, name='opensearch'),
    re_path(r'^opensearch\.xml$', app.meta.opensearch, name='opensearch'),
    re_path(r'^%s$' % 'privacy/', app.meta.privacy, name='privacy'),
    re_path(r'^csp-report/$', app.meta.csp_report, name='csp_report'),
    re_path(r'^notifications/$', app.inbox.notification_list, name='notifications'),
    re_path(r'^notifications/(?P<id>\d+)/$', app.inbox.notification_open, name='notification_open'),
    re_path(r'^notifications/read/$', app.inbox.notification_mark_all_read, name='notifications_read'),
    re_path(r'^notifications/count/$', app.inbox.notification_count, name='notifications_count'),
    re_path(r'^%s$' % 'logout/', app.meta.logout, name='logout'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('answers/', 'edit/'), app.writers.edit_answer, name='edit_answer'),
    re_path(r'^%s(?P<id>\d+)/$' % 'revisions/', app.readers.revisions, name='revisions'),
    re_path(r'^posts/(?P<id>\d+)/suggest-edit/$', app.suggested_edits.suggest_edit, name='suggest_edit'),
    re_path(r'^posts/(?P<id>\d+)/confirm-version/$', app.post_versions.confirm_version, name='confirm_version'),
    re_path(r'^review/suggested-edits/$', app.suggested_edits.review_page, name='suggested_edits'),
    re_path(r'^review/suggested-edits/undo/$', app.suggested_edits.undo, name='suggested_edit_undo'),
    re_path(r'^review/suggested-edits/(?P<id>\d+)/$', app.suggested_edits.review_action, name='suggested_edit_review'),
    re_path(r'^review/suggested-edits/(?P<id>\d+)/improve/$', app.suggested_edits.improve, name='suggested_edit_improve'),
    re_path(r'^%s$' % 'questions/', app.readers.questions, name='questions'),
    re_path(r'^%s%s$' % ('questions/', 'ask/'), app.writers.ask, name='ask'),
    re_path(r'^%s%s$' % ('questions/', 'related_questions/'), app.commands.related_questions, name='related_questions'),

    re_path(r'^%s%s$' % ('questions/', 'unanswered/'), app.readers.unanswered, name='unanswered'),
    # Before user_questions, which would take "for-you/<id>/decline/" for a user's list.
    re_path(r'^questions/for-you/$', app.for_you.questions_for_you, name='questions_for_you'),
    re_path(r'^questions/for-you/(?P<id>\d+)/decline/$', app.for_you.decline_answer_request,
            name='answer_request_decline'),
    re_path(r'^%s(?P<mode>[\w\-]+)/(?P<user>\d+)/(?P<slug>.*)/$' % 'questions/', app.readers.user_questions, name='user_questions'),


    re_path(r'^%s(?P<id>\d+)/%s$' % ('questions/', 'edit/'), app.writers.edit_question, name='edit_question'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('questions/', 'close/'), app.commands.close, kwargs=dict(close=True), name='close'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('questions/', 'reopen/'), app.commands.close, kwargs=dict(close=False), name='reopen'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('questions/', 'answer/'), app.writers.answer, name='answer'),
    re_path(r'^%s(?P<action>\w+)/$' % 'pending-data/', app.writers.manage_pending_data, name='manage_pending_data'),

    re_path(r'^%s(?P<id>\d+)/(?P<vote_type>[a-z]+)/' % 'vote/', app.commands.vote_post, name='vote_post'),
    re_path(r'^%s(?P<id>\d+)/$' % 'like_comment/', app.commands.like_comment, name='like_comment'),
    re_path(r'^%s(?P<id>\d+)/' % 'comment/', app.commands.comment, name='comment'),
    re_path(r'^%s(?P<id>\d+)/$' % 'delete_comment/', app.commands.delete_comment, name='delete_comment'),
    re_path(r'^%s(?P<id>\d+)/$' % 'convert_comment/', app.commands.convert_comment_to_answer, name='convert_comment'),
    re_path(r'^%s(?P<id>\d+)/$' % 'accept_answer/', app.commands.accept_answer, name='accept_answer'),
    re_path(r'^%s(?P<id>\d+)/$' % 'answer_link/', app.commands.answer_permanent_link, name='answer_permanent_link'),
    re_path(r'^%s(?P<id>\d+)/$' % 'mark_favorite/', app.commands.mark_favorite, name='mark_favorite'),
    re_path(r'^%s%s(?P<user_id>\d+)/%s(?P<answer_id>\d+)/$' % ('award_points/', 'user/', 'answer/'), app.commands.award_points, name='award_points'),

    re_path(r'^%s(?P<id>\d+)/' % 'flag/', app.commands.flag_post, name='flag_post'),
    re_path(r'^%s(?P<id>\d+)/' % 'delete/', app.commands.delete_post, name='delete_post'),
    re_path(r'^%s(?P<id>\d+)/(?P<user>\d+)?$' % 'subscribe/', app.commands.subscribe, name='subscribe'),
    re_path(r'^%s(?P<id>\d+)/$' % 'subscribe/', app.commands.subscribe, name='subscribe_simple'),
    re_path(r'^%s' % 'matching_tags/', app.commands.matching_tags, name='matching_tags'),
    re_path(r'^%s' % 'matching_users/', app.commands.matching_users, name='matching_users'),
    re_path(r'^%s(?P<id>\d+)/' % 'node_markdown/', app.commands.node_markdown, name='node_markdown'),
    re_path(r'^%s(?P<id>\d+)/' % 'convert/', app.commands.convert_to_comment, name='convert_to_comment'),
    re_path(r'^%s(?P<id>\d+)/' % 'convert_to_question/', app.writers.convert_to_question,name='convert_to_question'),
    re_path(r'^%s(?P<id>\d+)/' % 'wikify/', app.commands.wikify, name='wikify'),

    re_path(r'^%s(?P<id>\d+)/(?P<slug>[\w-]*)$' % 'question/', redirect, {'url': '/questions/%(id)s/%(slug)s'}),
    re_path(r'^%s(?P<id>\d+)\.md$' % 'questions/', app.agents.question_md, name='question_markdown'),
    re_path(r'^%s(?P<id>\d+)/updates/$' % 'questions/', app.live.question_updates, name='question_updates'),
    re_path(r'^%s(?P<id>\d+)/?$' % 'questions/', app.readers.question, name='question'),
    re_path(r'^%s(?P<id>\d+)/(?P<slug>.*)/(?P<answer>\d+)$' % 'questions/', app.readers.question),
    re_path(r'^%s(?P<id>\d+)/(?P<slug>.*)$' % 'questions/', app.readers.question, name='question'),


    re_path(r'^%s$' % 'tags/', app.readers.tags, name='tags'),
    re_path(r'^%s(?P<tag>[^/]+)/%s$' % ('tags/', 'edit/'), app.tags.tag_edit, name='tag_edit'),
    re_path(r'^%s(?P<tag>[^/]+)/%s$' % ('tags/', 'merge/'), app.tags.tag_merge, name='tag_merge'),
    re_path(r'^%s$' % 'tag-synonyms/', app.tags.tag_synonyms, name='tag_synonyms'),
    re_path(r'^%s(?P<tag>.*)/$' % 'tags/', app.readers.tag, name='tag_questions'),
    re_path(r'^%s%s(?P<tag>[^/]+)/$' % ('mark-tag/','interesting/'), app.commands.mark_tag, kwargs={'reason':'good','action':'add'}, name='mark_interesting_tag'),
    re_path(r'^%s%s(?P<tag>[^/]+)/$' % ('mark-tag/','ignored/'), app.commands.mark_tag, kwargs={'reason':'bad','action':'add'}, name='mark_ignored_tag'),
    re_path(r'^%s(?P<tag>[^/]+)/$' % 'unmark-tag/', app.commands.mark_tag, kwargs={'action':'remove'}, name='mark_ignored_tag'),

    re_path(r'^%s$' % 'users/', app.users.users, name='users'),
    # re_path(r'^%s$' % 'online_users/', app.users.online_users, name='online_users'),

    re_path(r'^%s(?P<id>\d+)/(?P<slug>.*)/%s$' % ('users/', 'edit/'), app.users.edit_user, name='edit_user'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('users/', 'award/'), app.users.award_points, name='user_award_points'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('users/', 'suspend/'), app.users.suspend, name='user_suspend'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('users/', 'report/'), app.users.report_user, name='user_report'),
    re_path(r'^%s(?P<id>\d+)/%s(?P<action>[a-z]+)/(?P<status>[a-z]+)/$' % ('users/', 'powers/'), app.users.user_powers, name='user_powers'),
    re_path((core_user_urls_prefix + '/%s$') % ('users/', 'subscriptions/'), app.users.user_subscriptions, name='user_subscriptions'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('account/', 'data/'), app.account.account_data, name='user_account_data'),
    re_path(r'^%s(?P<id>\d+)/%s%s$' % ('account/', 'data/', 'export/'), app.account.export_data, name='user_export_data'),
    re_path(r'^%s(?P<id>\d+)/%s%s$' % ('account/', 'data/', 'delete/'), app.account.delete_account, name='user_delete_account'),
    re_path(r'^%s(?P<id>\d+)/(?P<slug>.*)/%s$' % ('users/', 'preferences/'), app.users.user_preferences, name='user_preferences'),
    re_path(r'^%s(?P<id>\d+)/(?P<slug>.*)/%s$' % ('users/', 'favorites/'), app.users.user_favorites, name='user_favorites'),
    re_path(r'^%s(?P<id>\d+)/(?P<slug>.*)/%s$' % ('users/', 'reputation/'), app.users.user_reputation, name='user_reputation'),
    re_path(r'^%s(?P<id>\d+)/(?P<slug>.*)/%s$' % ('users/', 'votes/'), app.users.user_votes, name='user_votes'),
    re_path(r'^%s(?P<id>\d+)/(?P<slug>.*)/%s$' % ('users/', 'recent/'), app.users.user_recent, name='user_recent'),
    re_path(core_user_urls_prefix % 'users/', app.users.user_profile, name='user_profile'),
    re_path(r'^%s$' % 'badges/', app.meta.badges, name='badges'),
    re_path(r'^%s(?P<id>\d+)/(?P<slug>[\w-]+)?$' % 'badges/', app.meta.badge, name='badge'),
    # (r'^admin/doc/' % _('admin/doc'), include('django.contrib.admindocs.urls')),

    re_path(r'^%s$' % 'upload/', app.writers.upload, name='upload'),
    re_path(r'^%s$' % 'preview/', app.writers.markdown_preview, name='markdown_preview'),
    re_path(r'^%s$' % 'search/', app.search.search, name='search'),
    re_path(r'^search/suggest/$', app.search.suggest, name='search_suggest'),
    re_path(r'^%s$' % 'contact/', app.meta.feedback, name='feedback'),

    re_path(r'^i18n/', include('django.conf.urls.i18n')),

    re_path(r'^%s%s$' % ('account/', 'signin/'), app.auth.signin_page, name='auth_signin'),
    re_path(r'^%s%s$' % ('account/', 'signout/'), app.auth.signout, name='user_signout'),
    re_path(r'^%s(?P<provider>\w+)/%s$' % ('account/', 'signin/'), app.auth.prepare_provider_signin, name='auth_provider_signin'),
    re_path(r'^%s(?P<provider>\w+)/%s$' % ('account/', 'done/'), app.auth.process_provider_signin, name='auth_provider_done'),
    re_path(r'^%s%s$' % ('account/', 'register/'), app.auth.external_register, name='auth_external_register'),
    re_path(r'^%s%s(?P<user>\d+)/(?P<code>.+)/$' % ('account/', 'validate/'), app.auth.validate_email, name='auth_validate_email'),
    re_path(r'^%s%s$' % ('account/', 'tempsignin/'), app.auth.request_temp_login, name='auth_request_tempsignin'),
    re_path(r'^%s%s(?P<user>\d+)/(?P<code>.+)/$' % ('account/', 'tempsignin/'), app.auth.temp_signin, name='auth_tempsignin'),
    re_path(r'^%s(?P<id>\d+)/%s$' % ('account/', 'authsettings/'), app.auth.auth_settings, name='user_authsettings'),
    re_path(r'^%s%s(?P<id>\d+)/%s$' % ('account/', 'providers/', 'remove/'), app.auth.remove_external_provider, name='user_remove_external_provider'),
    re_path(r'^%s%s%s$' % ('account/', 'providers/', 'add/'), app.auth.signin_page, name='user_add_external_provider'),
    re_path(r'^%s%s$' %('account/', 'send-validation/'), app.auth.send_validation_email, name='send_validation_email'),
    # Account lifecycle (forum/utils/accounts.py).
    re_path(r'^account/check-email/$', app.auth.check_email, name='auth_check_email'),
    re_path(r'^account/email/confirm/(?P<user>\d+)/(?P<code>[\w$-]+)/$', app.auth.confirm_email_change, name='auth_confirm_email_change'),
    re_path(r'^account/email/cancel/(?P<user>\d+)/(?P<code>[\w$-]+)/$', app.auth.cancel_email_change, name='auth_cancel_email_change'),
    re_path(r'^account/email/pending/$', app.auth.pending_email_change, name='auth_pending_email'),
    re_path(r'^account/sessions/signout-others/$', app.auth.signout_others, name='auth_signout_others'),
    # Passkeys and two-step verification (forum/views/security.py).
    re_path(r'^account/(?P<id>\d+)/security/$', app.security.security_page, name='user_security'),
    re_path(r'^account/(?P<id>\d+)/security/two-step/disable/$', app.security.totp_disable, name='two_factor_disable'),
    re_path(r'^account/security/two-step/$', app.security.totp_setup, name='two_factor_setup'),
    re_path(r'^account/security/recovery-codes/$', app.security.recovery_codes, name='two_factor_recovery_codes'),
    re_path(r'^account/two-step/$', app.security.verify, name='auth_two_factor'),
    re_path(r'^account/passkeys/register/options/$', app.security.passkey_register_options, name='passkey_register_options'),
    re_path(r'^account/passkeys/register/$', app.security.passkey_register, name='passkey_register'),
    re_path(r'^account/passkey-signin/options/$', app.security.passkey_auth_options, name='passkey_auth_options'),
    re_path(r'^account/passkey-signin/$', app.security.passkey_auth, name='passkey_auth'),
    re_path(r'^account/passkeys/(?P<id>\d+)/remove/$', app.security.passkey_remove, name='passkey_remove'),
    # "Confirm it's you" before sensitive changes (forum/utils/sudo.py).
    re_path(r'^account/confirm/$', app.security.confirm_identity, name='auth_confirm_identity'),
    re_path(r'^account/confirm/passkey/options/$', app.security.confirm_passkey_options,
            name='auth_confirm_passkey_options'),
    re_path(r'^account/confirm/passkey/$', app.security.confirm_passkey, name='auth_confirm_passkey'),
    re_path(r'^account/confirm/(?P<user>\d+)/(?P<code>[\w$-]+)/$', app.security.confirm_identity_link,
            name='auth_confirm_identity_link'),


    re_path(r'^%s$' % 'admin/', app.admin.dashboard, name='admin_index'),
    # The admin used to have two layouts; old "switch" links go to the dashboard.
    re_path(r'^%s%s$' % ('admin/', 'switch_interface/'), app.admin.interface_switch, name='admin_switch_interface'),
    re_path(r'^admin/search/$', app.admin.search, name='admin_search'),
    re_path(r'^admin/sentry-test/$', app.admin.sentry_test, name='admin_sentry_test'),
    re_path(r'^%s%s$' % ('admin/', 'statistics/'), app.admin.statistics, name='admin_statistics'),
    re_path(r'^%s%s$' % ('admin/', 'denormalize/'), app.admin.recalculate_denormalized, name='admin_denormalize'),
    re_path(r'^%s%s$' % ('admin/', 'go_bootstrap/'), app.admin.go_bootstrap, name='admin_go_bootstrap'),
    re_path(r'^%s%s$' % ('admin/', 'go_defaults/'), app.admin.go_defaults, name='admin_go_defaults'),
    re_path(r'^%s%s$' % ('admin/', 'maintenance/'), app.admin.maintenance, name='admin_maintenance'),
    # The old Flagged posts page shows the moderation inbox (links in old emails keep working).
    re_path(r'^%s%s$' % ('admin/', 'flagged_posts/'), app.moderation.inbox, name='admin_flagged_posts'),
    re_path(r'^admin/moderation/$', app.moderation.inbox, name='admin_moderation'),
    re_path(r'^admin/moderation/post/(?P<id>\d+)/$', app.moderation.act_on_post, name='admin_moderation_post'),
    re_path(r'^admin/moderation/user/(?P<id>\d+)/$', app.moderation.act_on_user, name='admin_moderation_user'),
    re_path(r'^admin/moderation/undo/$', app.moderation.undo, name='admin_moderation_undo'),
    re_path(r'^%s%s$' % ('admin/', 'support/'), app.admin.support_dashboard, name='admin_support'),
    re_path(r'^admin/email-previews/$', app.admin.email_previews, name='admin_email_previews'),
    re_path(r'^admin/email-previews/(?P<kind>[\w-]+)/$', app.admin.email_previews, name='admin_email_preview'),
    re_path(r'^%s%s(?P<id>\d+)/$' % ('admin/', 'moderation_reports/'), app.admin.resolve_moderation_report, name='admin_resolve_moderation_report'),
    re_path(r'^%s%s$' % ('admin/', 'static_pages/'), app.admin.static_pages, name='admin_static_pages'),

    re_path(r'^%s%s%s$' % ('admin/', 'static_pages/', 'new/'), app.admin.edit_page, name='admin_new_page'),
    re_path(r'^%s%s%s(?P<id>\d+)/$' % ('admin/', 'static_pages/', 'edit/'), app.admin.edit_page, name='admin_edit_page'),
    re_path(r'^%s%s%s(?P<id>\d+)/$' % ('admin/', 'static_pages/', 'delete/'), app.admin.delete_page, name='admin_delete_page'),

    re_path(r'^%s%s(?P<name>\w+)/$' % ('admin/', 'tools/'), app.admin.tools_page, name='admin_tools'),

    re_path(r'^%s%s(?P<set_name>\w+)/$' % ('admin/', 'settings/'), app.admin.settings_set, name='admin_set'),

    re_path(r'%s%s' % ('admin/', 'test_email_settings/'), app.admin.test_email_settings, name='test_email_settings'),

    re_path(r'^feeds/rss[/]?$', app.readers.feed, name='latest_questions_feed'),

]

from forum.modules import get_modules_script

module_patterns = get_modules_script('urls')

urlpatterns = []

for pattern_file in module_patterns:
    pattern = getattr(pattern_file, 'urlpatterns', None)
    if pattern:
        urlpatterns += pattern

module_defined = {}

for t in urlpatterns:
    if hasattr(t, 'name') and t.name:
        module_defined[t.name] = True

core_defined = []

for u in core_urls:
    if not(hasattr(u, 'name') and u.name and (u.name in module_defined)):
        core_defined.append(u)

urlpatterns += core_defined

# Django Debug Toolbar URLs
if djsettings.DEBUG:
    try:
        import debug_toolbar
        from forum.utils.static_files import serve_file
        # Its CSS and JS live under STATIC_URL, which only Django's (unused) staticfiles app would serve.
        toolbar_media = os.path.join(os.path.dirname(debug_toolbar.__file__), 'static', 'debug_toolbar')
        urlpatterns = [
            re_path(r'^__debug__/', include(debug_toolbar.urls)),
            re_path(r'^m/static/debug_toolbar/(?P<path>.*)$', serve_file, {'document_root': toolbar_media}),
        ] + urlpatterns
    except ImportError:
        pass

