# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OSQA is an open source Q&A system. It provides Stack Overflow-like functionality including questions, answers, comments, voting, badges, reputation points, and user moderation.

It runs on Django 5.2 LTS and Python 3.12+; it was ported from Django 1.6 / Python 2 (notes in `docs/upgrade-history/`). See `README.md`, `docs/deployment.md` (new forums: server, Docker, Kubernetes), `docs/upgrading-from-original-osqa.md` (moving a live old forum: load its mysqldump into a scratch database on the same MySQL server, then `manage.py import_original_osqa --from <db>` copies every table by column name) and `docs/staging-checklist.md` (rehearsal on real data before going live). Old password hashes are read by `forum.utils.hashers.LegacySHA1PasswordHasher` and upgraded on sign-in; full-text search is built in (`forum/search/`; the old `mysqlfulltext`/`pgfulltext` modules were removed).

## Core Architecture

### Model Hierarchy

The application uses a polymorphic node system as the foundation:

- **Node** (`forum/models/node.py`): Base model for all content types
  - Questions, Answers, and Comments all inherit from Node
  - Uses `node_type` field to distinguish types
  - Implements a "leaf" pattern where queries return the specific subclass
  - State management through `NodeState` and `NodeStateDict`
  - Revision tracking via `NodeRevision`

Key models:
- `Question`, `Answer`, `Comment`: Content types extending Node
- `User` (`forum/models/user.py`): Extended Django auth user with reputation
- `Tag` (`forum/models/tag.py`): Question categorization
- `Action` (`forum/models/action.py`): Tracks all user actions (votes, edits, etc.)

### Views Organization

Views are organized by responsibility in `forum/views/`:
- `readers.py`: Read-only views (question list, question detail, user profiles)
- `writers.py`: Content creation/editing (ask question, post answer, upload)
- `commands.py`: AJAX commands for user actions (vote, accept, flag, delete)
- `auth.py`: Authentication and user management
- `admin.py`: Administrative interfaces
- `meta.py`: Static pages and error handlers

### Module System

OSQA has a pluggable module system in `forum_modules/`:
- Modules are auto-discovered from directories with `__init__.py`
- Each module can provide middleware, template loaders, and settings
- Modules can be disabled via `DISABLED_MODULES` in settings
- Available modules: see the table in `README.md` (authentication, badges, spam checks, backup/import, full-text search)

### Settings System

Settings are defined in `forum/settings/`:
- Each file defines related settings grouped into `SettingSet` objects
- Settings are stored in the database and can be modified at runtime
- Base Django settings in `settings.py`, overridden by `settings_local.py`
- Key settings modules: `basic.py`, `email.py`, `minrep.py` (minimum reputation), `repgain.py` (reputation gains), `voting.py`

### Actions System

All user interactions are tracked as Action objects (`forum/actions/`):
- Actions trigger reputation changes, notifications, and badges
- Actions can be canceled/undone
- Actions update node states (e.g., accepted answers, deleted content)

## Development Commands

### Setup and Installation

1. Copy and configure settings:
```bash
cp settings_local.py.dist settings_local.py
# Edit settings_local.py with database credentials and APP_URL
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Database setup:
```bash
python manage.py migrate
```

### Running the Application

Development server:
```bash
python manage.py runserver
```

Production: `gunicorn wsgi:application` (see `wsgi.py`, `Dockerfile`), or mod_wsgi with `osqa.wsgi.dist`

### Database Migrations

Django migrations live in `forum/migrations/`. After changing models run
`python manage.py makemigrations forum`; CI fails if a migration is missing.
Action subclasses are proxy models on the single `forum_action` table.

### Management Commands

Email alerts (used by cron):
```bash
python manage.py send_email_alerts
```

## Key Configuration Files

- `settings.py`: Core Django settings with module discovery
- `settings_local.py`: Local overrides (database, APP_URL, DEBUG, caching)
- `urls.py`: Root URL configuration (delegates to `forum/urls.py`)
- `forum/urls.py`: Main application URL routing
- `requirements.txt`: Python dependencies

## Important Implementation Details

### Node Type System

When querying nodes, use the manager methods to get the correct subclass:
- `Node.objects.get(id=x)` returns the leaf (Question, Answer, or Comment)
- Each subclass has its own manager that filters by `node_type`
- Parent/child relationships are maintained through the `parent` field

### Template System

- Skins are in `forum/skins/` (default skin is configurable)
- Template loaders check: filesystem → app directories → module templates → skins
- Django template engine with custom tags in `forum/templatetags/`; a custom `Node.render()` must return a string
- The default skin is responsive and its public pages load one style sheet, `media/style/osqa.css` (plus, when enabled, the admin's custom CSS; the sign-in pages add `auth.css`; jQuery UI's is loaded with its script on demand), linked first in `<head>` before any script. Its numbered sections are in cascade order (legacy base, then the modern layout with the colour variables and the phone breakpoint at 640px, then profile, ask, lists, search box, accessibility/print, editor, profile menu, Markdown help): add rules to the section they belong to, not at the top. Check new UI at 390px width as well as desktop, and in dark mode (colours come from the variables; every dark rule is written once as `:root[data-theme="dark"] …`, never in a `prefers-color-scheme` media query: `data-theme` on `<html>` is the resolved theme of the theme switch, written by `{% display_attrs %}` and, for System, by the nonce'd inline script of `{% theme_head %}` before the first paint (`forum/templatetags/display_tags.py`, choice in `forum/utils/display.py`: `user.prop.preferences['theme']` / cookie `osqa_theme`, view `set_theme`, `media/js/osqa.theme.js`); scripts that draw with theme colours redraw on the `osqa:themechange` document event). `python e2e/css_coverage.py` finds rules no page uses and no template/JS/Python references (`--prune` removes them; then run `e2e.test_visual`)
- Accessibility target is WCAG 2.2 AA (README "Look and feel"): `e2e/test_accessibility.py` (axe) and `e2e/test_wcag22.py` (measured: targets >= 24x24 px or spaced, Tab never ends under a fixed/sticky bar (give such bars `scroll-padding` on `html`, as osqa.css section 7 does for the live banner and the phone message bar), focus ring 3:1 (fields show it in their border), reflow at 320px, 1.4.12 text spacing, dialogs take the focus, close with Escape and give it back); underline links inside sentences (shared rule in section 2); a control that applies on `change` (`data-autosubmit`, search filters) must not do so for a keyboard change, which waits for Enter/blur or the Apply button (`osqa.behaviors.js`, `osqa.searchpage.js`); add new pages to `Wcag22Test.all_pages()`
- The admin has one layout, `osqaadmin/base.html` (Django admin's CSS + `media/style/admin.css`, dark with `DARK_MODE` and the same `data-theme`, which Django's CSS follows too); its menu is data (`admin_menu()` in `forum/views/admin.py`: new SettingSets go under "Other settings", tools via `admin_tools_page`/`TOOL_LINKS`), pages fill the blocks `subtitle` (title and heading), `pagename` (breadcrumb), `description`, `adminjs`, `admincontent`; `/admin/switch_interface/` only redirects to the dashboard.
- JavaScript runs on jQuery 3.7 (self-hosted in `media/vendor/`): use `.on()` delegation, `.prop()` for checked/disabled and `.val()` for values; there is no compatibility shim (old APIs such as `$.handleError`, `.live()` or `$.browser` are gone, and `.bind()`/`$.trim()` are deprecated); uploads use `fetch` + `FormData` with the `X-CSRFToken` header and the JSON reply of `upload` (`{url}` or `{error}` with 400/403/413/429 (`UPLOADS_PER_HOUR` per member, staff exempt; sides over `images.MAX_SIDE` or more than `MAX_PIXELS` are refused from the header, before decoding); the server re-encodes every image with Pillow in `forum/utils/images.py`: EXIF orientation applied, all metadata dropped, longest side at most `UPLOAD_MAX_IMAGE_SIDE`, BMP/TIFF/ICO stored as PNG; `store_upload()` also writes the variants, see Performance), as in `osqa.editor.js` (`OsqaEditor.uploadFile`) and `osqa.paste.js`; tag/user suggestions use `$.fn.osqaAutocomplete` (`osqa.autocomplete.js`; it loads jQuery UI on the first focus of a field, `window.osqaJqueryUI()` returns a promise of it for other widgets such as the award points slider: never include jQuery UI in a page template) and charts `osqaTimeChart()` (`osqa.charts.js`, Flot 4)

### Content features

- Post HTML is rendered once per revision (`Node.rendered()` → `forum.models.node.render_markdown()`, stored in `body`; the editor preview POSTs to `markdown_preview`, which uses the same function): fenced code (`normalize_fences`) and pipe tables (`align=""`, never `style`), then `forum/utils/mentions.py` links `@username`, `forum.utils.images.pictures()` wraps images of our uploads in `<picture>` (AVIF/WebP sources + width/height) and `lazy_images()` adds `loading="lazy"`; `forum.utils.html.sanitize_html` (nh3) holds the tag/attribute allow-list; notifications read mention ids from `data-user` attributes, which the sanitizer never accepts from user HTML
- Post editor (`compose/editor.html` + `compose/toolbar.html` (toolbar, code language menu, link/image `<dialog>`s moved out of the form), `compose/editor_scripts.html`; also the answer form in `question.html`): `media/js/osqa.editor.js` owns `textarea#editor` (`textarea.osqaEditor`): change text only through `editor.apply()`/`replaceSelection()`/`insertBlock()` (own undo history, fires `input` with `event.osqaEditor` for drafts/preview/count), toolbar is one tab stop with arrow keys and `aria-pressed`, shortcuts Ctrl/Cmd+B/I/K/E/Z/Y, Tab indents lists/code (Esc then Tab leaves), Enter continues lists; preview = debounced fetch to `markdown_preview`; `osqa.paste.js` uploads pasted/dropped images with an `![Uploading name…]()` placeholder and converts rich HTML with the self-written `osqa.htmltomd.js` (never inserts HTML; Ctrl+Shift+V and pastes in code stay plain); `osqa.mentions.js` does @mentions; help in `markdown_help.html#md-editor`; e2e `test_editor.py`
- A question closed as a duplicate keeps `{'duplicate_of': id}` in `Node.extra` (`Question.duplicate_of`)
- `TagSynonym` maps tag names to tags; `TagNamesField` resolves synonyms when tags are entered; moderators manage tags in `forum/views/tags.py` (`/tags/<name>/edit/`, `/tags/<name>/merge/`, `/tag-synonyms/`) with the rules in `forum/utils/tags.py` (`can_manage_tags()`; rename/merge retag through new revisions without bumping activity, recount `used_count`, move `MarkedTag`s, merged names become synonyms) and Actions in `forum/actions/tag.py` (undo except merge); `matching_tags` rows found through a synonym carry it as a 4th column
- Search (`forum/search/`, view `forum/views/search.py`, template `search.html`): one `SearchDocument` per question (title, tags, plain text of body and answers) updated from `Node.save()`/`delete()`; full-text index per database from migration 0013 (MySQL FULLTEXT, SQLite FTS5 + triggers, Postgres SearchVector at query time, else keyword LIKE); `manage.py rebuild_search_index` after upgrading/importing; operators parsed in `search/query.py`; snippets are built from plain text and escaped with only `<mark>` added; `full_text_questions` is the first of `similar.SEARCH_PROVIDERS` (results blended by reciprocal rank fusion); filters in the URL (`forum/search/filters.py` `SearchFilters`: tags/status/closed/date+from/to/author/code/min_score, applied in SQL by `engine.search(query, filters=, skip=)`, shared by the MCP `search_forum` args tags/status/since and `similar.search_questions(..., filters)`), chips with remove URLs (`query.operators` spans, `without_operators()`), facets over at most `engine.FACET_CAP` matches (`matched_rows`/`status_facets`/`tag_facets`), "did you mean" in `search/spelling.py` (cached vocabulary); every control has `form="search-form"`, `media/js/osqa.searchpage.js` (autosubmit on desktop, `<dialog>` at <=960px, drops empty params); results are `.question-row` items (j/k) with titles marked via `text.mark()`; tests `forum/tests/test_search_filters.py` (incl. budgets), e2e `test_search_page.py`
- Security: `forum/middleware/security.py` (`ClientIPMiddleware` first: real IP from `X-Forwarded-For` when `TRUSTED_PROXY_COUNT` > 0, `/healthz`; `SecurityHeadersMiddleware`: CSP + Permissions-Policy, extra origins in the `CSP_EXTRA_SOURCES` setting; script-src is 'self' + a per-response nonce, no 'unsafe-inline' (styles keep it): inline scripts need nonce="{{ csp_nonce }}" (context processor `forum.context.csp_nonce`, `request.csp_nonce`; HTML loaded by AJAX into dialogs must carry no scripts); no inline event handlers or `javascript:` URLs, use `media/js/osqa.behaviors.js` data attributes (`data-confirm`, `data-autosubmit`, `data-form-target`) or a JS file; `forum/tests/test_csp.py` checks templates); sign-in lockout in `forum/views/auth.py`, account email limits in `forum/utils/accounts.py` (counters in `forum/utils/throttle.py`); hourly posting limits `antispam.posting_limit_reached()`; DB settings in `forum/settings/security.py`; `SetPasswordForm` runs `AUTH_PASSWORD_VALIDATORS`; `ValidationHash` is HMAC-SHA256 keyed with `SECRET_KEY`. Log security events with `forum.utils.security_log.event()` (logger `forum.security`), never passwords or tokens
- Sentry (`forum/utils/sentry.py`): `init_server()` from settings.py when `SENTRY_DSN` is set (no PII; loggers `forum.security` and `forum.errors` are kept out of Sentry because their lines carry IPs and usernames), `SentryUserMiddleware` adds the user id and sets the visitor for `before_send`, which drops events past `SENTRY_MAX_EVENTS_PER_VISITOR` per hour (the browser applies the same cap in `osqa.sentry.js`); `{% sentry_browser %}` (first in `<head>` of `base_content.html` and the admin base) loads the self-hosted bundle and `media/js/osqa.sentry.js` when `SENTRY_FRONTEND_DSN` is set, and the CSP `connect-src` gets the DSN's origin
- Operations (`docs/deployment.md` Monitoring/Logs/Backups): first middleware `forum.middleware.ops.RequestContextMiddleware` (X-Request-ID in responses, logs and Sentry tags; request counts/latency buffered per process and flushed to the shared cache, `forum/utils/metrics.py`); `/readyz` and token-protected `/metrics` (`METRICS_TOKEN`, 404 when unset) are answered by `ClientIPMiddleware` (`forum/views/ops.py`); count rare events with `metrics.count()` (emails in `forum/utils/mail.py`, every `security_log.event()`); `LOG_FORMAT=json` uses `forum/utils/logs.py` (masks emails/IPs/secrets except `forum.security`); `forum/apps.py` hooks `BaseCommand.execute` to record last runs of `CRON_COMMANDS` in KeyValue `ops.cron.<name>` (`forum/utils/cron.py`; no edits to the commands); `backup_site`/`restore_site` (`forum/utils/backup.py`); containers: `settings_local_docker.py` (env vars), `docker-compose.yml` (db, memcached, migrate, web, cron via supercronic + `cron/crontab`), `docs/k8s/`, `docs/prometheus/`
- Translations: `forum/locale/{es,fr,pt}` (.po and compiled .mo committed), `LocaleMiddleware` + footer switcher (`set_language`); URL patterns use plain strings (never `_()`), strings evaluated at import time use `gettext_lazy as _lazy`; after changing texts run makemessages/compilemessages (README "Languages")
- Email frequency (`forum/utils/email_frequency.py`): `SubscriptionSettings.email_frequency` (i as it happens / d daily / w weekly / n never, `mentions_immediate`); `forum/subscriptions.py` sends activity emails through `deliver()`, which emails now or queues `PendingEmail` rows; `send_email_alerts` (daily cron) calls `send_summaries()` (template `notifications/summary.html`, weekly on the `WEEKLY_SUMMARY_DAY` setting, `LAST_WEEKLY` catch-up, rows claimed before sending); unsubscribe tokens with scopes `daily`/`weekly` switch frequency (footer "Get a daily summary instead", unsubscribe-page weekly alternative, undo)
- First posts review + moderation inbox: `FIRST_POSTS_MODERATION` (off/after/before, Admin > Moderation settings) puts new members' posts in node state `pending_review` (held: hidden) or `unreviewed` (published) via `QueueForReviewAction`, released by `ApprovePostAction` (undoable); anything shown to others must use `forum/utils/review.py` (`Node.objects.public()` / `.visible_to(user)`, `review.can_view()`, `hidden_q()`), held posts are not `is_notifiable` and `forum/subscriptions.py`/`notifications.py` replay their hooks on approval (author notices in `forum/review_notices.py`); inbox `/admin/moderation/` (`forum/views/moderation.py`: first posts, flags, reported users, AI reports; `/admin/flagged_posts/` shows it too)
- Live question page (`forum/utils/live.py`, view `forum/views/live.py`, `{% live_updates %}` in `live_tags.py`, `media/js/osqa.live.js`): polls `/questions/<id>/updates/?since=<page token>` every 20 s while visible (stops when hidden/idle, backs off on errors, none for crawlers); the JSON snapshot (visible answers/comments with `active_revision_id`, score, accepted) has a two-part ETag `"<cache stamps>-<snapshot hash>"` (unchanged site: 304 with no query of the view's, else one `forum_node` query); `?posts=<ids>` renders `node/answer.html`/`node/comment.html` for the viewer (keep post markup in those includes and their `data-rev`); the script inserts comments at once, counts new answers/edits in the "Show" banner, re-inits widgets via `window.osqaInitPostWidgets`; edit pages post `base_revision` (`compose/revision.html`) and `live.edit_conflict()` refuses saving over a newer revision
- Suggested edits (`forum/utils/suggested_edits.py`, views `forum/views/suggested_edits.py`, model `SuggestedEdit`): members below `REP_TO_EDIT_OTHERS` get "suggest an edit" (`/posts/<id>/suggest-edit/`, the edit templates with `suggesting`; summary required, one pending per post, `SUGGESTED_EDITS_PER_DAY`); reviewers (that reputation or staff, never their own) use `/review/suggested-edits/` (header link `SuggestedEditsLink`) or the inbox's "Suggested edits" section (shared `suggested_edits/_actions.html`); approving is `SuggestedEditAction` (a `ReviseAction` whose user is the suggester and `real_user` the reviewer; `REP_GAIN_BY_SUGGESTED_EDIT` capped by `MAX_REP_BY_SUGGESTED_EDITS`), rejecting `RejectSuggestedEditAction` (reason from `REJECT_REASONS`), both undoable; a conflicting edit supersedes (hook in `forum/review_notices.py`, rechecked on approval); the suggester is told via `Notification` kinds `edit_approved`/`edit_rejected` and `deliver()` (`notifications/suggested_edit.html`)
- Expert routing / "Questions for you" (`forum/utils/expertise.py`, hooks in `forum/expert_routing.py`, view `forum/views/for_you.py`, models `TagExpertise`/`AnswerRequest` in `forum/models/expertise.py`): expertise per member and tag comes from visible answers on others' questions (`max(0, 1 + 0.5 × votes clipped to −2…10) + 3 if accepted`, answers older than 365 days ×0.25, active members only), rebuilt by `manage.py refresh_tag_expertise` (daily, in `CRON_COMMANDS`/`cron/crontab`/k8s) and updated for the answerer only by the `AcceptAnswerAction` hook (`refresh_user()`); the `AskAction` hook (and `ApprovePostAction` via `replay_on_approval`) runs `route_question()` once per question: top `EXPERT_ROUTING_MAX_EXPERTS` by expertise summed over its tags whose best tag ≥ `EXPERT_ROUTING_MIN_SCORE`, never the asker, inactive members, members who answered or were already asked (one `AnswerRequest` per member and question), turned it off (`user.prop.preferences['answer_requests']`, preferences page / unsubscribe scope `answer_requests`) or got `EXPERT_ROUTING_DAILY_CAP` routed requests in 24 h; each gets `Notification` kind `answer_request` (text `"<answers>:<tag>"`, `request_reason`; push kind `answer_request`) and `notifications/answer_request.html` through `deliver()` (`PendingEmail` kind `answer_request`, summary section); answering marks the request answered, "Not for me" (`answer_request_decline`, POST command view) declines it (or records a declined `routed=False` row for a merely listed question); `/questions/for-you/` (header tab `MemberPageTab` FOR_YOU, signed-in only) lists `public()` open questions without an accepted answer in the member's top 10 tags, pending requests first (`.for-you-item` around the shared `.question-row`, osqa.css section 5); settings `forum/settings/routing.py` (Admin > Questions for experts); tests `forum/tests/test_expert_routing.py` (incl. query budget), `test_query_budgets.test_for_you_page`, e2e `test_expert_routing.py`
- Version-aware posts (`forum/utils/post_versions.py`, models `TagVersion`/`NodeVersion` in `forum/models/version.py`, migration 0024): moderators keep a tag's ordered versions (one `is_current`) in the Versions section of `/tags/<name>/edit/` (`add_version`/`remove_version` (refused while posts use it)/`move_version`/`set_current_version` in `forum/utils/tags.py`, recorded as `TagVersionAction`, history only; rename keeps them, merge moves them after the target's own and remaps posts, a post with both keeps the target's); ask/answer/edit forms show "Applies to version" (`compose/versions.html`, fields `version_<tag id>`, `form_groups()`/`save()`, `media/js/osqa.versions.js` shows a tag's select while it is in the tags field), stored on the post, not in revisions, and not in suggested edits; `{% post_versions %}`/`{% question_version_chips %}`/`{% list_version_chips %}` (`version_tags.py`, `node/post_versions.html` in `node/answer.html`) show chips, the "may be outdated" notice and "Still works in <current>" for `can_edit_post` (POST `/posts/<id>/confirm-version/`, `forum/views/post_versions.py`, `ConfirmVersionAction` in `forum/actions/version.py`, undo by the confirmer or a moderator restores the previous confirmation); queries: one cached catalogue of all versions (`catalog()`, cleared by `invalidate()` on version, tag-name or synonym changes), `for_thread()` one query per question page, lists via `prefetch_cached(after=(post_versions.prefetch,))`, none when `POST_VERSIONS` (View settings) is off or no versions exist; `version=` search filter (`SearchFilters`, `version_q()`, API `/search`, MCP `search_forum`), API `PostVersion` objects in `versions` of Question/Answer, "Applies to:" lines in `/questions/<id>.md`; tests `forum/tests/test_post_versions.py` (incl. budgets), e2e `test_post_versions.py`
- In-site notifications: `Notification` rows created by hooks in `forum/notifications.py` (independent of email prefs), bell = `ui.Include('inbox/bell.html')` in the header registry, views in `forum/views/inbox.py`; support dashboard `admin.support_dashboard` (`/admin/support/`, staff) with figures in `forum/utils/support.py`, `manage.py remind_unaccepted` (one `QuestionReminder` per question)
- Community health = the admin dashboard (`admin.dashboard`, `/admin/`, staff; site status for superusers only): figures in `forum/utils/community_health.py` (`compute()`: ~13 aggregate queries, no per-row queries; `figures()` caches them per period (`?days=7|30|90`) for 5 min in the shared cache, POST `refresh` recomputes; `?format=csv`); what counts is `posts()` (not deleted/held, not under a hidden question, author `is_active`) and the docstring, shown on the page under "How these are counted"; labels are added at render time (`tiles()`, `summaries()`), never cached; template `osqaadmin/health.html` (every chart: summary sentence + table in `<details>`), `osqaTimeChart()` takes several series `[{label, data}]` coloured `--chart-1..3` (admin.css `--osqa-chart-*`); tests `forum/tests/test_community_health.py` (incl. query budget), e2e `test_health_dashboard.py`
- Browser push (`forum/utils/push.py`, off unless `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`; `manage.py generate_vapid_keys`): `notify()` passes new `Notification`s to `push.send_notifications()` (per-kind choices in `user.prop.push_kinds`, inactive users and held posts skipped, payload = short title + question title + `/notifications/<id>/`, never post text; 404/410 deletes the `PushSubscription`); endpoints `/push/subscribe/`, `/push/unsubscribe/` (JSON) and `/push/settings/` (`forum/views/push.py`, push-service hosts allow-listed), switch `{% push_switch %}`/`{% push_settings %}` + `media/js/osqa.push.js` (permission asked only on click), `push`/`notificationclick` in `pwa/sw.js`; tests patch `forum.utils.push.webpush`
- Passkeys + two-step verification (`forum/models/two_factor.py`, logic in `forum/utils/two_factor.py` and `forum/utils/passkeys.py`, views `forum/views/security.py`, page `/account/<id>/security/`, JS `media/js/osqa.passkeys.js`): `login_and_forward()` sends members with TOTP on to `/account/two-step/` with a signed pending marker in the session (pass `two_factor_method=` only after a second factor; a passkey sign-in counts), codes checked with `two_factor.check_code()` (±1 step, no replay, throttled, security-logged), TOTP secrets Fernet-encrypted with a key derived from `SECRET_KEY` (+ `SECRET_KEY_FALLBACKS`), recovery codes salted SHA-256; WebAuthn via py_webauthn with RP id/origin from `APP_URL`, single-use expiring challenge in the session; `TWO_FACTOR_REQUIRED_FOR_STAFF` is enforced by `super_user_required`/`staff_user_required`; tests use `SoftAuthenticator` (`forum/tests/test_two_factor.py`) and e2e the CDP virtual authenticator
- Account lifecycle (`forum/utils/accounts.py`, views in `forum/views/auth.py`/`account.py`, README "Accounts"): sign-up double opt-in sets `User.email_confirmation_required` (never for the site owner, staff, admin-made/imported users or provider-verified emails; existing rows default False), `EMAIL_CONFIRMATION_MODE` signin (default: confirm before signing in; sign-up answers the same for a taken address and emails its owner) / post (sign in, no ask/answer/comment) / off; tests that only need a signed-in new member set the mode to post, checked by `accounts.validation_required(user, item)` (also the legacy `REQUIRE_EMAIL_VALIDATION_TO`), banner `{% confirm_banner %}` (`account_tags.py`); one-time links are `ValidationHash` (stored as SHA-256 digests, `validate(..., consume=False)` for pages that only show a form; types email 48 h, newemail/emailcancel 48 h, pwreset 60 min bound to password hash + last_login), dead links answer 410; own email changes stay pending in `user.prop.pending_email` until confirmed, the old address gets a cancel link (POST cancels + signs out everywhere + revokes the API tokens); "forgot password" (`/account/tempsignin/...`) shows a set-password form (+ TOTP code when enabled), never signs in; `accounts.password_changed()` after every new password (other sessions out, security email); sessions store `osqa_epoch` = `User.session_epoch` at sign-in (`accounts.signed_in()` in `login_and_forward`, checked in `ExtendedUser`; `sign_out_everywhere()`), "Keep me signed in" = `remember`; sign-out is POST only; `NEW_DEVICE_SIGNIN_EMAIL` uses the `osqa_device` cookie; deletion re-authenticates (password, TOTP, or a sign-in within 15 min), refuses staff, emails, anonymises (`delete_user_account()`, `ACCOUNT_DELETION_POSTS`); password rules in `forum/utils/passwords.py` (`PASSWORD_MIN_LENGTH` ≥ 8, max 128, optional HIBP range check `PASSWORD_BREACH_CHECK`, fail-open) and `osqa.password.js` (meter, rule ticks via `data-rule`); account emails `auth/*_email.html` are in `email_samples.KINDS`; account email limits use `accounts.over_limit()` (`PASSWORD_RESETS_PER_HOUR`); `cleanup_inactive_users` also deletes `antispam.unconfirmed_users()` (`UNCONFIRMED_ACCOUNT_DAYS`); tests `forum/tests/test_account_lifecycle.py`, e2e `test_account_lifecycle.py`
- "Confirm it's you" (sudo mode, `forum/utils/sudo.py`): changing the own email address, adding a passkey, setting up/turning off two-step verification (incl. an admin turning it off for a member), new recovery codes, creating API tokens and removing the last sign-in method need a sign-in or re-authentication within `REAUTH_MINUTES` (session key `accounts.AUTH_TIME_SESSION_KEY`, `accounts.recently_signed_in()` / `mark_reauthenticated()`); guard a view with `@sudo_required` or `refused = require_recent_auth(request, next_url, json=)` (nothing is saved and POSTs are not replayed: the member comes back to `next`, checked by `sudo.safe_next()`, and sends the form again; JSON callers get `{error, redirect}`); the page `/account/confirm/` (`security.confirm_identity`, `auth/confirm_identity.html`) takes the password (sign-in pause), a code (`two_factor.check_code`), a passkey (`passkeys.reauth_options()`/`authenticate(..., user=)`) or, without password and two-step, a 15-minute single-use emailed link that works only in the signed-in browser; the inline code/password of the security page's forms counts too; test helpers `login()`/e2e `open()` count as a recent sign-in (`recent=False` for an old one). Security notices `accounts.security_notice()` (`auth/security_change_email.html`: passkey added, two-step on/off, recovery codes, API token) are always sent; e2e `test_confirm_identity.py`
- Bot defences live in `forum/utils/antispam.py`: `BotTrapMixin` (honeypot + signed time stamp; sign-up templates render `{{ form1.bot_traps }}`, tests post `form_token=self.signup_token()`), the per-IP sign-up limit, `links_trusted()` for profile links, and `dormant_users()` for `manage.py cleanup_inactive_users`; `User.last_seen` is updated hourly by the `ExtendedUser` middleware
- Installable app (`forum/views/pwa.py`): `/manifest.webmanifest`, `/sw.js` (template `pwa/sw.js`, caching rules in its header comment: versioned skin media (`?v=`) cache-first, other skin media stale-while-revalidate, question/list/tag pages network-first in the bounded `osqa-pages-v1` cache, never personal or mutating URLs) and `/offline/`; `{% pwa_head %}` adds manifest/theme-color/touch icon and `media/js/osqa.pwa.js` (registration, offline banner, clears saved pages when the signed-in user changes); e2e `test_offline.py`
- Keyboard shortcuts (`media/js/osqa.shortcuts.js`, dialog `display/shortcuts_dialog.html` opened with `?`, included only when on): `/`, `g h/q/t/u/n`, `a`, `j`/`k` (+ Enter on lists, `u`/`d` on question pages); ignored while typing, with Ctrl/Alt/Meta or with another dialog open; members turn them off in preferences (`preferences['keyboard_shortcuts']`, `<html data-shortcuts="off">`, also honoured by the `/` of `osqa.searchbox.js` and the moderation inbox's `j`/`k` in `osqa.moderation.js`); e2e `test_theme_and_shortcuts.py`
- Agent access (`forum/views/agents.py`): `/questions/<id>.md`, `/llms.txt`, `/export/qa.jsonl` and a hand-written read-only MCP endpoint `/mcp` (JSON-RPC; tools `search_forum`, `get_question`); `forum.utils.similar.search_questions()` takes pluggable `SEARCH_PROVIDERS` (the AI module registers semantic search)
- JSON API `/api/v1/` (`forum/api/`, docs page `/api/` + token page in `forum/views/api.py`): one registry (`@endpoint` in `endpoints.py`, machinery in `core.py`, JSON Schemas in `schemas.py`) generates the URL patterns (`api/urls.py`), the OpenAPI 3.1 document (`openapi.py`, `/api/v1/openapi.json`) and the docs page, so add an endpoint only there; auth is a personal access token only (`ApiToken`, `forum/models/api.py`: SHA-256 digest stored, shown once, scopes read/write, expiry; `Authorization: Bearer`), the session cookie is never used (dispatch is csrf_exempt, `request.user` comes from the token, messages discarded, no greeting/session); reads use `visible_to()`/`review.can_view()`, writes the same Actions/permission checks/`posting_limit_reached()`/`validation_required()` as `writers.py`/`commands.py` (CAPTCHA users refused, spam via module handler `api_is_spam`); errors raise `core.Problem(slug)` (RFC 9457, slugs in `PROBLEMS`); lists `{data, next}` + Link with keyset cursors (`core.page`), single objects ETag/304; per-minute rate limits via `throttle.hit`, CORS for GET from `API_CORS_ORIGINS`; settings in `forum/settings/api.py` (Admin > Public API); tests `forum/tests/test_api.py` (incl. schema checks of responses and query budgets), e2e `test_api.py`
- AI knowledge and assistant: `KnowledgeChunk` (forum threads and crawled docs with float32 embeddings) built by `manage.py build_knowledge_index` (`forum_modules/ai/knowledge.py`, `crawler.py`); `assistant.answer_question()` answers only from retrieved chunks with `[n]` citations and returns 'insufficient' unless it cites a source and a second `ask_model` check finds every statement supported (no web search: nothing that can't be verified); `AISuggestion` rows (from `manage.py suggest_answers`) are shown via `{% ai_suggestion %}` on question pages and are never answers, indexed or exported
- `forum_modules/ai` uses Google Gemini (`google-genai`; Gemini API key or Vertex AI project): every call goes through `client.ask_model()` (JSON-schema output; returns None on any failure so callers degrade to no AI, or `BLOCKED` when the safety filters refuse); tests patch `forum_modules.ai.client.get_client`. Moderation hooks create `ModerationReport` rows (core model, resolved in the moderation inbox) and never hide or delete posts; `forum/utils/similar.py` holds the keyword question matching used by duplicate detection and `related_questions`

### Caching

- `CACHES` must be shared by all worker processes (file cache by default, memcached recommended); `settings.py` translates an old `CACHE_BACKEND` string
- Models use `CachedManager` and `CachedQuerySet`; `get()` uses the per-object cache only for a bare pk lookup
- Cache keys are generated with `_generate_cache_key` method
- Lists: `queryset.prefetch_cached(fks=('author',), counts=('answer_count',))` fills foreign keys from the object cache and DenormalizedField counts with one grouped query per page (`load_cached()`, `prefetch_cached_fk()`, `prefetch_denormalized()` in `forum/models/base.py`, same cache entries as the one-by-one paths); question-page comments load once per request (`node_tags._visible_comments`); query budgets (cold and warm cache) in `forum/tests/test_query_budgets.py`, raise one only with a reason
- HTTP caching (`forum/utils/static_files.py`, table in `docs/deployment.md`): `{% media %}` adds `?v=<content hash>` and that version is served `immutable`, other file requests get 1 h + ETag/304, `/upfiles/` is immutable; `StaticFilesMiddleware` answers file URLs before session/user middleware (no cookies); CSS/JS/SVG/JSON gzipped, never HTML (BREACH); the service worker version uses the same hashes; anonymous question pages and the feed get ETags from `forum/utils/conditional.py`; post images get `loading="lazy"` in `render_markdown()` (`lazy_images()`, never from user HTML), except the question body's first image near the top (`|priority_image` filter in `question.html`: `fetchpriority="high"`, the usual LCP element)
- Performance (Core Web Vitals): `e2e/test_web_vitals.py` (helpers `e2e/web_vitals.py`) loads the main pages cold on a 390px phone over slow 4G with the CPU slowed 4x and asserts CLS < 0.05, LCP < 2.5 s, TTFB, INP and per-page request/byte ceilings (`E2E_VITALS_REPORT=file` writes the table); give images, avatars, embeds and anything shown by a script its size or reserved space before the first paint (a nonce'd inline script right after an element may unhide it, as `search.html` and `auth/passkey_signin.html` do), keep non-essential scripts `defer` and load heavy libraries on demand (`osqa.highlight.js` loads highlight.js only when a code block exists; jQuery UI as above); jQuery, `osqa.csrf.js` and `osqa.main.js` stay blocking because inline template scripts and the admin's custom head use them. Upload variants (`forum/utils/images.py`): next to each canonical upload `UPFILES_FOLDER/_variants/<name>.<width>w.avif|webp` (640/1280 and full width, AVIF only when `features.check('avif')`) and `<name>.json` (size, widths per format), written once by `store_upload()`/`write_variants()` and served immutable; `manage.py backfill_image_variants [--dry-run] [--rerender]` after upgrading or importing; `{% logo_size %}` gives the header logo its size; `Server-Timing` (db/render/total) comes from `forum/middleware/server_timing.py` with DEBUG, or for staff when the `SERVER_TIMING` Django setting/env var is set

### Authentication

Authentication providers are modules (`forum/authentication/` collects their `*AuthConsumer` / `*AuthContext` classes; names ending in `AbstractAuthConsumer` are skipped):
- `localauth`: Standard username/password
- `oauth2auth`: Google, GitHub and Facebook via the OAuth 2.0 authorization code flow; keys in Admin > External Keys, a provider is shown only when its context's `is_enabled()` is true
- `ldapauth`: LDAP integration (needs python-ldap)

### User Interface Registry

The `forum/registry.py` and `forum/modules/ui.py` system registers UI elements:
- Header links, footer links, user menu items
- Modules can extend the UI through the registry
- Visibility controls (anonymous, authenticated, superuser)

## Testing

Smoke tests live in `forum/tests/` and run against SQLite using `settings_local_test.py`:
```bash
OSQA_SETTINGS_LOCAL=settings_local_test python manage.py test forum.tests
```
- Always pass the `forum.tests` label.
- `forum.tests.base.OSQATestCase` clears the cache, runs action hooks inline
  and captures outgoing email in `self.sent_mail`.
- CI (`.github/workflows/tests.yml`) runs the suite and `makemigrations --check` (Django 5.2 on Python 3.12/3.13, Django 6.0 on 3.14).
  The suite runs with `-W error::DeprecationWarning -W error::PendingDeprecationWarning`: code must work on both Django versions without version checks;
  filter third-party warnings only, in `settings.py` with a comment (README "Upgrading Django")
- Lint: `ruff check .` (pinned in `requirements-dev.txt`, rules and per-file ignores in `pyproject.toml`; CI runs it); dependency audit: `pip-audit -r requirements.txt -r requirements-dev.txt`
- Browser tests: `OSQA_SETTINGS_LOCAL=settings_local_e2e python manage.py test e2e` (Playwright on Django's live server, file SQLite DB; `e2e/base.py` fails a test on 5xx, JS/console errors, CSP blocks and sideways scrolling at 390px; `test_crawl.py` follows every link per role; `python e2e/coverage.py` lists URL patterns no browser test reaches; `E2E_DB_NAME` gives parallel runs their own DB; see `e2e/README.md`). Add one when changing a user-facing workflow or adding a URL

## Common Pitfalls

1. **Settings Import**: Always import from `forum import settings`, not `django.conf import settings`, to get OSQA's runtime-configurable settings

2. **Node Queries**: Remember to use `.leaf` or model-specific managers to get the correct subclass

3. **Module Conflicts**: Check `DISABLED_MODULES` in `settings_local.py` if modules aren't loading

4. **Cache Issues**: Clear cache directory during development if seeing stale data

5. **Database**: This codebase uses MySQL by default; other databases may require adjustments to full-text search modules

6. **Metaclasses**: Use `class X(Base, metaclass=M)`; a `__metaclass__` attribute is silently ignored by Python 3 and breaks node types, denormalized counts, action proxies and badges

7. **Command views**: `@decorate.withfn(command)` views only accept POST; mark a view `@prompt` if it renders a form on GET (and act only on POST). `media/js/osqa.csrf.js` sends the CSRF token from `<meta name="csrf-token">` with every AJAX request

8. **HTML in descriptions**: `forum.utils.html.hyperlink()`/`buildtag()` escape their text; escape any other user text interpolated into `Action.describe()` output, which templates render with `|safe`, and into `messages.*()` texts (flash messages are shown unescaped by `base_content.html`)

9. **Sessions are JSON**: store only JSON-serializable values (e.g. `QueryDict.urlencode()`, ISO datetimes)

10. **Line endings**: several files (this one, `requirements.txt`, `settings_local.py.dist`, many templates) use CRLF; preserve them when editing
