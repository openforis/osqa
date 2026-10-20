# OSQA, Open Foris edition

OSQA is an open source Q&A site (questions, answers, comments, voting, tags,
reputation, badges and moderation), originally from osqa.net. This is the
edition maintained by [Open Foris](https://openforis.org/) for its support
forum; it runs on **Django 5.2 LTS and Python 3.12+**.

Any organisation can use it for its own Q&A community: the code is free and
open source (GPL v3) at <https://github.com/openforis/osqa>. Follow the setup
below, change the name, logo, colours and texts in the admin, and turn the
optional modules (social login, AI assistance, spam checks) on or off.

## Requirements

- Python 3.12 or newer
- MySQL/MariaDB (default), PostgreSQL or SQLite
- For `mysqlclient`: the MySQL client headers, e.g.
  `apt-get install default-libmysqlclient-dev pkg-config`
- Optional: memcached (recommended cache in production)

## Setup

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt        # requirements-dev.txt adds the debug toolbar

cp settings_local.py.dist settings_local.py
# Edit settings_local.py: DATABASES, APP_URL, ALLOWED_HOSTS and SECRET_KEY.
# Generate a key with:
#   python -c 'from django.core.management.utils import get_random_secret_key as k; print(k())'

venv/bin/python manage.py migrate
venv/bin/python manage.py runserver
```

The first account registered through the site becomes the site owner and
superuser. Site settings (email server, reputation thresholds, ...) are edited
in the admin pages at `/admin/` and stored in the database. The admin has one
layout, built on Django admin's style sheets (light and dark, following the
site's dark mode setting): a header with links back to the site, to the
moderation inbox (with the number of items waiting) and to sign out, and a menu
of every settings page and tool (folded on phones). Settings pages and tools
that modules add appear in the menu by themselves. Django's model admin is at
`/nimda/`.

`SECRET_KEY` can also come from the `OSQA_SECRET_KEY` environment variable; the
site refuses to start without one.

## Production

Step-by-step guides:
- [docs/deployment.md](docs/deployment.md): a new forum on a server (systemd +
  nginx), with Docker Compose, or on Kubernetes / Cloud Run.
- [docs/upgrading-from-original-osqa.md](docs/upgrading-from-original-osqa.md):
  moving a live forum from the original OSQA (Python 2 / Django 1.6).


- WSGI entry point: `wsgi.py` (`gunicorn wsgi:application`); for mod_wsgi copy
  `osqa.wsgi.dist`.
- Cache: the model layer caches objects and query results, so the cache must be
  shared by all worker processes. `settings_local.py.dist` uses a file cache;
  memcached is recommended. The per-process local-memory cache is not suitable.
- HTTPS: with an `https://` `APP_URL`, secure cookies and HSTS are on by default.
  Behind a reverse proxy set `TRUSTED_PROXY_COUNT = 1` (or `OSQA_TRUSTED_PROXIES=1`,
  the docker-compose default): visitor IPs then come from `X-Forwarded-For` and
  HTTP is redirected to HTTPS. See "Security and logging" below.
- Email digests and summaries: run `cron/send_email_alerts` once a day (e.g. at 07:00); it
  also sends the weekly summaries on their day, so weekly needs no cron line of its own.
- Dormant (bot) accounts: run `cron/cleanup_inactive_users` daily (see "Spam sign-ups" below).
- Accept reminders: run `cron/remind_unaccepted` daily (see "Notifications, community health and support dashboard" below).
- Questions for experts: run `cron/refresh_tag_expertise` daily (see "Questions for you" below).
- AI assistant (optional, `ai` module): run `cron/build_knowledge_index` nightly and
  `cron/suggest_answers` hourly (see "AI assistance" below).
- Backups: run `manage.py backup_site` daily; monitoring, JSON logs and restores: see "Operations" below.

### Docker

```bash
cp .env.example .env      # secrets, APP_URL, host names
docker compose up -d --build
```

`docker-compose.yml` runs the full stack: MySQL 8.4, memcached, a one-off
`migrate` step, gunicorn on `127.0.0.1:8000` (put a TLS reverse proxy in front
of it) and a `cron` service running the scheduled commands (`cron/crontab`,
supercronic). Settings come from environment variables
(`settings_local_docker.py`); uploads and backups are volumes. Kubernetes
manifests are in `docs/k8s/`. See [docs/deployment.md](docs/deployment.md).

### Operations

- **Probes:** `/healthz` (process and database) and `/readyz` (database and
  cache) answer `ok` or 503 on any host name.
- **Metrics:** Prometheus metrics at `/metrics` once `METRICS_TOKEN` is set
  (`Authorization: Bearer <token>`; 404 otherwise): requests by view and
  status, latency, posts, unanswered questions, moderation queue, emails
  sent/failed, sign-in failures and lockouts, memcached, and the last
  successful run of each scheduled command. Scrape config and alerts are in
  `docs/prometheus/`.
- **Logs:** `LOG_FORMAT = 'json'` gives one JSON object per line on stdout,
  with emails, IPs and secrets masked outside the security log. Every response
  carries an `X-Request-ID` (the proxy's or a new one); logs and Sentry events
  carry the same id.
- **Backups:** `manage.py backup_site` writes the database and the uploads
  into a timestamped `.tar.gz` and keeps the last `BACKUP_KEEP`.
  `manage.py restore_site <archive> --dry-run`, then `--confirm`, restores one.
- **Profiling:** with `SERVER_TIMING=staff` (environment or
  `settings_local.py`) the pages staff members load carry a `Server-Timing`
  header (database time and number of queries, template rendering, total),
  shown by the browser's developer tools; with `DEBUG` every page has it.

## Administration

Administrators find every setting with the search box at the top of the
admin menu (`/admin/search/`): it matches the setting's label, help text,
name and keywords, the page and section titles, and a few synonyms (colour
and color, login and sign-in...), and links to the setting's row on its page,
highlighted. Settings pages with many settings also have a "Find a setting on
this page" filter.

Pages that need outside accounts explain how to get them. External Keys has
one card per service (sign-in with Google, GitHub and Facebook, reCAPTCHA,
Akismet, Gemini, Google Analytics, Google Search Console) saying whether it is
set up, partly set up or needs checking (for example a Google client ID that
doesn't end in `.apps.googleusercontent.com`, an old `UA-` Analytics ID or a
plain `http://` site address), what it does, the steps on the provider's
site, the redirect address to register with a copy button, and an example of
each value. Secrets are shown as dots until "Show" is pressed. The Public API,
Custom CSS, Header and Footer and `<head>` pages have examples to copy, with
the site's address filled in.

For developers: a page's guidance is data. Register sections with
`forum.settings.guides.register(set_name, Section(...))` (title, settings,
summary, steps, values to copy, links, keywords, a status function, weight),
give a setting `example=` and `keywords=` in its field context, and add
free-form help as the template `osqaadmin/guides/<set name>.html` (code
examples with `{% example %}` from `admin_tags`).

## Languages

The interface is available in English, Spanish, French and Portuguese.
- **Choosing a language:** visitors get their browser's language, and can
  pick another with the switcher in the footer (remembered in a cookie).
- **Settings:**
  - `LANGUAGE_CODE` in `settings_local.py` is the default.
  - `LANGUAGES` limits or extends the list.
- **What stays the same:** URLs are identical in every language.
- **Limits:**
  - Posts aren't translated.
  - Notification emails and admin setting labels use the site's default language.

Updating the translations after changing texts (needs GNU gettext, e.g.
`apt-get install gettext`):

```bash
python manage.py makemessages -l es -l fr -l pt --no-location --no-obsolete \
    --ignore='venv/*' --ignore='docs/*' --ignore='scripts/*' --ignore='forum/tests/*' \
    --ignore='cache/*' --ignore='tmp/*' --ignore='*/media/vendor/*'
# translate the new entries in forum/locale/<lang>/LC_MESSAGES/django.po, then
python manage.py compilemessages
```

Commit both the `.po` and the compiled `.mo` files. To add a language, add
it to `LANGUAGES` and pass `-l <code>` to `makemessages`.
- **Strings defined at import time:** form labels, badge names, header
  links and tab titles must use `gettext_lazy`, imported as `_lazy`, so they
  follow each visitor's language. `makemessages` (overridden in
  `forum/management/commands/makemessages.py`) extracts `_lazy("...")` too.
- **First versions:** the current translations were written with AI
  assistance; a review by native speakers is welcome.

## Search

The search box looks through question titles, tags, question text and answer
text (not comments), with titles weighted highest, and ranks the results by
relevance. Each result shows a snippet of the matching text with the words
marked. The search page explains the operators:

| Query | Finds |
|---|---|
| `csv export` | questions with any of the words; more matches, and matches in the title, rank higher |
| `"survey data"` | the exact phrase |
| `-excel` | leaves out questions with the word (`-"a phrase"` too) |
| `[collect]` or `tag:collect` | only questions with the tag (synonyms work) |
| `is:answered`, `is:unanswered`, `is:accepted` | by answers |
| `user:alice` (`user:"Some Name"`) | questions asked by that person |

Results sort by relevance (default), newest, votes or activity. The page's
**filters** (a sidebar on desktops, a "Filters" dialog on phones) combine with
the words and operators and live in the URL, so a search can be shared,
bookmarked and undone with the back button:

| Parameter | Filter |
|---|---|
| `tags=python csv` | every tag (spaces or several `tags=`; synonyms resolved; suggestions as you type) |
| `status=unanswered`, `answered`, `accepted` | by answers (held or deleted answers don't count) |
| `closed=hide` | leaves out closed questions |
| `date=week`, `month`, `year`, or `date=custom&from=2026-01-01&to=2026-03-31` | when the question was asked |
| `author=alice` | asked by that member (suggestions as you type) |
| `code=1` | the question or one of its answers has a code block |
| `min_score=2` | a score of at least 2 |

Active filters show as chips with a remove link each (operators typed in the
query too) and "Clear all"; the sidebar counts the results per status and
lists their commonest tags (over at most 1000 matches). When a search finds
fewer than 3 questions, "Did you mean" offers a spelling built from tag names
and frequent title words, if it finds more. Results are a list of links:
`j`/`k` move through them and Enter opens one.

The same index serves the MCP `search_forum` tool (arguments `query`, `limit`
and the filters `tags`, `status`, `since`) and "related" searches through
`forum.utils.similar.search_questions(query, limit, filters=None)`, whose
providers are blended (the AI module's semantic search, when configured, is
added to the full-text results; providers without `accepts_filters` have
their results filtered afterwards).

How it works: one `SearchDocument` row per question (`forum/search/`, table
`forum_searchdocument`) holds the plain text, and is updated whenever a
question or one of its answers is posted, edited, deleted or moved. Deleted
questions are removed from it. The full-text index depends on the database:

- **MySQL/MariaDB:** InnoDB `FULLTEXT` indexes (created by migration `0013`),
  queried in natural language mode, and in boolean mode for phrases and
  exclusions. Words shorter than `innodb_ft_min_token_size` (3) and MySQL's
  stopwords are ignored.
- **SQLite:** an FTS5 table kept in step by triggers, ranked with `bm25()`,
  with English stemming. If SQLite was built without FTS5, search falls back
  to keyword matching.
- **PostgreSQL:** `SearchVector`/`SearchRank` computed at query time (no
  extra index; fine for small and medium forums).
- **Anything else** (or if the full-text query fails): keyword matching.

After upgrading to this version, and after importing data, fill the index
once (until then search uses simple keyword matching):

```bash
python manage.py rebuild_search_index
```

Running it again at any time is safe; it rebuilds everything.

## Moderation

Moderators (staff) and administrators find everything that waits for them in
the **moderation inbox** (`/admin/moderation/`): a "moderation" link in the
header shows how many items wait, and the admin menu links to it. The old
Admin > Flagged posts address (`/admin/flagged_posts/`) shows the inbox too.
It lists, as cards with the post, its author (reputation, join date, number
of posts) and why it is there:

- **First posts** waiting for review (see below);
- **Flagged posts**: posts members reported, with each reason;
- **Reported users**: accounts members reported ("report user");
- **AI moderation reports** from the `ai` module.
- **Suggested edits** waiting for review (see below).

One click acts on an item: **Approve** (or **Dismiss** for flags and
reports), **Delete**, **Delete as spam** (a dialog offers to suspend the
author and delete their other posts as well), and **Suspend** the author.
Every action is an ordinary forum action (reputation, activity log, undelete
and unsuspend work as usual), and the last one can be undone from the inbox.
The cards work from the keyboard (j / k move between them) and on a phone.

### Suggested edits

Members who can't edit others' posts yet (below **Admin > Minimum reputation
config > Minimum reputation to edit others posts**) see **suggest an edit**
instead of "edit" on questions and answers. The edit page is the same (title,
tags, body) with a required edit summary and a note that the edit will be
reviewed. A post has at most one pending suggestion (others see "edit
pending"), and a member may suggest **Suggested edits per member per day**
(Admin > Moderation settings, 5 by default; **Suggested edits** turns the
feature off).

Members who may edit others' posts and moderators review them on **Review
suggested edits** (`/review/suggested-edits/`; reviewers get a "review edits"
link with the count in the header, moderators also see them in the inbox): an
inline diff, then **Approve**, **Improve** (edit further, then approve) or
**Reject** with a reason. Approving creates an ordinary revision credited to
the suggester (the reviewer is named in its summary and activity) and gives
them **Rep gain by approved suggested edit** (2, at most **Max rep by
suggested edits**, 1000, in all; Admin > Reputation gains). If the post was
edited since, changes to other fields are kept and a conflicting change
supersedes the suggestion. The suggester gets a notification and an email
(following their email frequency). The last review can be undone.

### Reviewing new members' first posts

Bots that sign up sometimes post spam. To have new members' first posts
reviewed, choose under **Admin > Moderation settings > Review new members'
first posts**:

- **Off** (the default): posts are published at once, as before.
- **Review after publishing**: posts appear at once and are listed in the
  inbox until a moderator approves (or deletes) them.
- **Review before publishing**: posts are held. Until a moderator approves
  them only their author (who sees "Your post will appear once a moderator
  has reviewed it" and a "Waiting for review" badge) and the moderators see
  them: they are left out of question lists, the question page, search,
  feeds, the sitemap, `llms.txt` / `.md` / JSONL / MCP, related questions,
  tag counts, other people's view of the author's profile and the AI index.
  Followers are notified (email and bell) only when the post is approved;
  the author gets an email and a notification when it is approved or removed.
  A reply under a held post is held with it and approved with it.

"Posts to review per member" (1) is how many of a member's posts a moderator
must approve before the next ones are published directly (deleted posts don't
count); "Also review posts by members below this reputation" (0, off) reviews
every post of low-reputation members. Moderators and administrators are never
reviewed. The visibility rules live in `forum/utils/review.py`.

### Moderating tags

Tags drift ("csv" and "csv-export", "earthmap" and "earth-map"). Moderators
(staff) and administrators tidy them from a tag's page with **Manage tag**
(`/tags/<name>/edit/`):

- **Description**: the "tag wiki" shown at the top of the tag's page (an
  excerpt, with the rest behind "Read the full description") and on the tags
  index.
- **Synonyms**: names that stand for the tag. Typed in the tags field (ask,
  edit, retag) they become the tag, tag suggestions show "csv → export", and
  `/tags/<synonym>/` redirects (301) to the tag. The tag's page says "Also
  called: ...". If the name is an existing tag, you are sent to the merge page.
- **Rename**: changes the tag on all its questions; followers, ignored marks
  and synonyms stay with it, and the old name can be kept as a synonym so old
  links keep working.
- **Merge into another tag**: a confirmation page first says what changes
  ("N questions will move", followers, synonyms). Then the questions get the
  target tag (never twice), followers and interesting/ignored marks move (a
  member who had chosen the target keeps that choice), the old tag's synonyms
  point to the target, the old name becomes a synonym of the target and the
  old tag is deleted. **A merge can't be undone.**

Every change is an action, attributed to the moderator, shown in their
activity and in the tag's **History**, where renames, synonyms and
descriptions can be undone. Questions are retagged through a new revision
(earlier revisions keep their tags; the question doesn't move up the "active"
list), deleted questions and posts held for review included; tag counts are
counted again afterwards and the search index is updated. **Tag synonyms**
(`/tag-synonyms/`, linked from the tags index and the admin tools) lists all
synonym → tag pairs, with a form to add one and remove buttons. The rules
live in `forum/utils/tags.py`.

## Notifications, community health and support dashboard

- **Bell:** signed-in users see a bell in the header with their unread
  notifications:
  - answers to questions they ask or follow;
  - comments on their posts;
  - mentions;
  - accepted answers;
  - badges.

  The list is at `/notifications/`. These notifications don't depend on the
  email settings, and opening a question marks its notifications read.
- **Community health:** the admin dashboard (`/admin/`, for moderators and
  administrators) answers "how is the community doing?" for the last 7, 30 or
  90 days (`?days=`), each figure compared with the period before:
  - new questions, answers and comments;
  - questions answered within 24 hours and 7 days, median time to the first
    answer, accepted answers, the unanswered backlog;
  - new members, how many confirmed their email or posted within 7 days,
    active (posted or voted) and returning members;
  - moderation: what waits in the inbox, median times to resolve flags,
    first post reviews and suggested edits, suspensions, AI reports;
  - charts: daily activity, time to first answer, growing tags, top
    answerers and questions by hour of the week, each with a summary
    sentence and its figures as a table.

  Deleted posts, posts held for review and suspended accounts never count;
  the page explains every figure under "How these are counted". Figures are
  cached for 5 minutes ("Refresh now" counts again) and download as CSV
  (`?format=csv`). Code: `forum/utils/community_health.py`.
- **Support dashboard:** at Admin > Support dashboard, linked as "support
  queue" in the header for staff and moderators. It shows, for a period and
  optionally one tag:
  - questions asked;
  - the share answered by someone other than the asker;
  - median time to the first answer;
  - the share with an accepted answer;
  - a per-product-tag table;
  - the queue of unanswered questions, oldest first, with those past the
    response target highlighted;
  - answered questions with no accepted answer.

  Product tags, the response target and reminders are under Admin > Support
  and reminders.
- **Accept reminders:** `manage.py remind_unaccepted` (daily) reminds an asker
  once, by notification and by email, when their question has had an answer
  for 7 days (configurable) and none is accepted. It only looks at questions
  from the last 60 days, so an imported history isn't flooded. There is no
  email if the asker stopped following the question or turned emails off.
- <a id="questions-for-you"></a>**Questions for you (expert routing):** each
  member's expertise per tag comes from their visible answers on others'
  questions (accepted answers weigh most, then votes; answers from the last
  12 months count fully, older ones a quarter), rebuilt daily by
  `manage.py refresh_tag_expertise` and updated when an answer is accepted.
  A newly published question (or a first post once approved) is suggested to
  the few members with the most expertise in its tags, by notification and
  email (as often as they chose), never twice for the same question and at
  most a few times a day per member. Members turn it off in their
  preferences, or say "Not for me" on a question. `/questions/for-you/`
  lists open questions without an accepted answer in their top tags,
  suggested ones first. Settings: Admin > Questions for experts.

### Email frequency

Members choose how often activity emails come (Email settings > "How often
should we email you?"):

- **As it happens** (the default, and what existing members keep): a separate
  email for each new answer, comment, mention, accepted answer, new question in
  a followed tag or new member (admins).
- **Daily summary / Weekly summary**: those emails are held back
  (`PendingEmail` rows, queued by `forum/subscriptions.py` through
  `forum/utils/email_frequency.deliver()`) and `manage.py send_email_alerts`
  sends one summary per member and period, grouped into sections (mentions,
  answers to your questions, answers on questions you follow, comments,
  accepted answers, new questions, new members). Nothing new, no email.
- **Never**: no activity emails.

The per-kind switches still decide which kinds are collected. Mentions stay
immediate unless the member unticks "Send mentions right away"; account
emails (sign-in links, validation) are always immediate. The daily digest of
new questions (`send_digest`) is a separate email, unchanged.

`send_email_alerts` should run once a day. Daily summaries go out on every
run (at most one a day per member); weekly ones on the weekday set in Admin >
Email settings > "Weekly summary day" (Monday by default), or on the next run
if that day's run was missed (`LAST_WEEKLY`). Queued items are removed as they
are sent, so running the command twice sends nothing twice, and after missed
runs a summary covers everything since the member's last one.

Emails sent as things happen have a signed "Get a daily summary instead" link
in the footer, and the unsubscribe page offers "Switch to a weekly summary
instead"; both work without signing in and have an undo button. The summary
itself has "Stop these summaries" and the usual unsubscribe links and
`List-Unsubscribe` header. Preview it under Admin > Email previews.

### Browser push notifications

Members can get the bell's notifications as browser notifications (Web Push),
also when the forum isn't open. It is off, with nothing shown, until the site
has a VAPID key pair:

```bash
python manage.py generate_vapid_keys          # lines for settings_local.py
python manage.py generate_vapid_keys --env    # VAPID_*=... for .env / a Kubernetes Secret
```

Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (secret) and `VAPID_SUBJECT` (a
`mailto:` address or `https:` URL the push services can contact; default
`APP_URL`). Keep the pair: new keys make every device turn notifications on
again. The site must be served over HTTPS.

- **Turning it on:** "Get notifications on this device" on the notifications
  page and in Email settings > "Notifications on your devices". The browser
  asks for permission only when the switch is pressed. Blocked notifications,
  browsers without Web Push, and iPhones/iPads (where it works only once the
  forum is added to the Home Screen and opened from there) get an explanation.
- **What is pushed:** for each new bell notification, if the member ticked
  that kind: answers to my questions, comments on my posts, mentions and
  accepted answers (on by default); answers to followed questions, badges,
  moderator decisions on held posts and accept reminders (off by default).
  Posts held for review push nothing until approved; suspended members get
  nothing.
- **Privacy:** a message holds a short line ("bob answered your question"),
  the question title (plain text, at most 120 characters) and the link
  `/notifications/<id>/` (marks it read, then opens the post), never the text
  of a post or comment. It is encrypted for the browser (RFC 8291) and goes
  through the browser maker's push service (Google, Mozilla, Apple, Microsoft);
  only those services' addresses are accepted (more with the
  `PUSH_SERVICE_HOSTS` setting). Each device is listed in Email
  settings with a Remove button. Signing out, or another member signing in on
  the same browser, stops push there.
- **Delivery:** sent from the action-hook thread with a 5 s timeout; a device
  the push service reports gone (404/410) is deleted, others count failures
  (dropped after 10 in a row). `/metrics` counts `push_sent` and `push_failed`.
  Uses [pywebpush](https://github.com/web-push-libs/pywebpush) (MPL-2.0).

### Live question pages

An open question page follows the thread without reloading: vote counts and
accepted marks change in place, new comments appear with a short highlight,
and new answers and edits wait behind a "2 new answers · Show" banner (read
out politely by screen readers). Someone writing an answer is told when
another answer comes in; their draft is left alone. The page asks
`/questions/<id>/updates/` every 20 seconds while the tab is visible (not
when hidden, after 30 minutes without activity or for search engines); an
unchanged question answers `304 Not Modified` without a database query of
its own, so idle pages cost almost nothing. Behind a proxy or CDN, don't
cache that URL (it is `private, no-cache`).

Saving an edit after someone else changed the post doesn't overwrite their
version: the edit page comes back with your text, who changed the post and a
link to the revisions; saving again replaces their version.

## Security and logging

- **Accounts:** sign-up, confirmation, passwords, sessions and deletion are
  described under [Accounts](#accounts) below.
- **Sign-in:** after 5 wrong passwords an account's password sign-in pauses for
  15 minutes, and one IP address may fail 20 times. The error never says
  whether the username exists; the session gets a new key at sign-in.
- **Passkeys and two-step verification:** on "Passkeys and two-step
  verification" in their settings, members add passkeys (fingerprint, face,
  screen lock or security key; WebAuthn with `webauthn`/py_webauthn) and can turn
  on codes from an authenticator app (TOTP; QR code drawn on the server with
  `segno`) with 10 one-time recovery codes.
  - The sign-in page offers "Sign in with a passkey" (and passkeys in the
    username field's autofill) where the browser supports them. A passkey
    sign-in requires user verification and counts as two-step verification.
  - With an app set up, every other sign-in (password, Google/GitHub/Facebook,
    LDAP, email links) asks for a code before the person is signed in; codes
    are accepted 30 seconds either side, once each, and wrong ones are limited
    like wrong passwords.
  - Turning the app off or making new recovery codes needs a code or the
    password. Administrators can turn it off for a member who lost their phone
    and codes (from the member's settings page).
  - *Require two-step verification for staff* (Admin > Security, off by
    default) sends moderators and administrators without it to set it up when
    they open an admin page (a passkey sign-in also counts).
  - Stored: app secrets encrypted with a key derived from `SECRET_KEY`
    (rotate with `SECRET_KEY_FALLBACKS`), recovery codes as salted SHA-256,
    passkeys' public keys and signature counters. Passkeys work only at
    `APP_URL`'s host over HTTPS (or `localhost`).
- **Posting limits:** questions, answers and comments per user per hour
  (moderators exempt).
- **Headers:** Content-Security-Policy, Permissions-Policy, plus Django's
  nosniff, Referrer-Policy and X-Frame-Options. The policy:
  - scripts only from the site, the Google services OSQA uses (reCAPTCHA,
    Analytics) and the extra sources setting, plus inline `<script>` elements
    that carry the response's nonce: every response gets a new random nonce
    (`request.csp_nonce`, `{{ csp_nonce }}` in templates). Script injected into
    a post or profile has no nonce and doesn't run; there is no
    `'unsafe-inline'` or `'unsafe-eval'` for scripts, and inline event handlers
    (`onclick="…"`) and `javascript:` links are blocked, so templates don't use
    them (`media/js/osqa.behaviors.js` covers confirmations, auto-submitting
    selects and form targets with `data-` attributes);
  - styles still allow `'unsafe-inline'` (the templates use `style=""`
    attributes);
  - no plugins (`object-src 'none'`), `base-uri 'self'`, forms post only to
    the site (`form-action 'self'`), only this site may frame it;
  - inline scripts in the admin's custom `<head>`, header and footer get the
    nonce automatically; scripts in other admin texts (sidebar, custom pages)
    and inline event handlers anywhere don't run.

  Browsers report blocked content to `/csp-report/`, which goes to the security
  log. Add origins for your own analytics or widgets in the admin's extra script
  sources setting (Admin > Security); `CONTENT_SECURITY_POLICY_REPORT_ONLY = True` only reports,
  `CONTENT_SECURITY_POLICY = "…"` replaces the policy (`{nonce}` in it is replaced by
  the response's nonce), and `CONTENT_SECURITY_POLICY = None` turns the header off.
  Django's model admin (`/nimda/`) runs only script files and gets the same policy.
- All the limits above are under Admin > Security.
- **Security log** (`log/security.log`, logger `forum.security`), one line per event:
  - failed and paused sign-ins;
  - passkeys added, removed and used (and counter errors), two-step
    verification turned on or off, wrong codes and recovery codes used;
  - password reset requests and resets, password changes and failed attempts;
  - email confirmations, email change requests, confirmations and cancellations;
  - sign-outs everywhere, sign-ins from new browsers, unconfirmed sign-in attempts;
  - pages refused to signed-in users;
  - permission, reputation and settings changes;
  - maintenance mode;
  - account deletions;
  - blocked content.
- **Moderator actions** (votes, deletions, suspensions, closes, …) stay in the
  actions table with user and IP.
- **Log files:** `settings_local.py.dist` rotates them at 10 MB.
- **Sentry:** set `SENTRY_DSN` (settings or environment) to report server
  errors. Browser JavaScript errors and session health go to
  `SENTRY_FRONTEND_DSN`, which defaults to the same DSN (use a separate
  JavaScript project if you prefer; `off` turns it off).
  - Other settings: `SENTRY_ENVIRONMENT` (default `production`),
    `SENTRY_RELEASE` (default `osqa@<git commit>`; for Docker pass
    `--build-arg SENTRY_RELEASE=...`) and `SENTRY_TRACES_SAMPLE_RATE`
    (performance tracing, default 0).
  - Blocked content (CSP reports) arrives as warnings.
  - Flood protection: each visitor (signed-in user, or IP address) sends at
    most `SENTRY_MAX_EVENTS_PER_VISITOR` events per hour (default 10) from
    the server, and the same number from their browser. The browser count is
    kept in localStorage, so reloading doesn't reset it. Identical repeated
    errors are merged by Sentry's SDK as well. Because the browser DSN is
    public, also set a rate limit on the client key in Sentry
    (Project Settings > Client Keys) to cap deliberate abuse.
  - No request bodies, cookies, IP addresses, emails or log lines with them are
    sent. Signed-in users appear by numeric id only.
  - The browser SDK is self-hosted (`media/vendor/sentry-10.75.3`, see its
    README) and loads before the other scripts.
- **Health check:** `/healthz` returns `ok` when the app and database respond. It
  works on any host name and during maintenance; the Docker image uses it.
- **Dependencies:** CI runs `pip-audit`, and Dependabot proposes updates weekly.

Existing installations: copy the `LOGGING` block from `settings_local.py.dist`
into `settings_local.py` to get rotation and the security log.
Email validation and sign-in links sent before the upgrade stop working, so ask
for a new one.

### Accounts

What members can do with their account, and the settings for it (Admin >
Users settings and Admin > Security). The code is in `forum/utils/accounts.py`.

- **Signing up (double opt-in):** after signing up with an email address and
  password, the member gets a welcome email with a button that confirms the
  address. The link works once, for 48 hours, and only the newest one works
  (a random HMAC-SHA256 token; only its SHA-256 is stored). There is no second
  welcome email after confirming. *Email confirmation for new members*
  decides what happens meanwhile:
  - *they must confirm before they can sign in* (default): signing up shows
    "Check your inbox" (check your email to finish creating your account),
    signing in sends a new link instead, and an address that already has an
    account gets the same answer as a new one (its owner gets a "you already
    have an account" email), so the form tells nobody which addresses are
    registered;
  - *they can sign in at once, but must confirm before asking, answering or
    commenting*: a banner under the header says so, with "Send it again" and
    "Change the address"; a question or answer written before confirming is
    published when the link is opened in the same browser (in this mode the
    sign-up form says when an address is already taken);
  - *not required*: only the actions ticked under "Require email validation
    to..." need a confirmed address (that list applies to every member).

  Members who joined before this existed, the site owner, staff, accounts made
  by administrators or imported, and addresses a sign-in service (Google,
  GitHub, LDAP) has already verified are never asked. Accounts that never
  confirm and never post are deleted by `cleanup_inactive_users` after
  *Delete unconfirmed new accounts after (days)* (7; 0 turns it off). The
  confirmation page works signed out and never signs anyone in; signed-out
  members can ask for a new link with their address (`/account/send-validation/`,
  the same answer for any address).
- **Passwords** follow NIST SP 800-63B: at least *Minimum password length*
  characters (8, never less; 15 is recommended without two-step
  verification), at most 128, any characters, no rules about digits or
  symbols, no expiry. Common passwords and passwords close to the username or
  email are refused; *Refuse passwords found in data breaches* (off by
  default) also checks the Have I Been Pwned list, sending only the first 5
  characters of the password's SHA-1 (k-anonymity, padded answers), and
  accepts the password if the service doesn't answer within 3 seconds. The
  forms list the rules and tick them as the member types, show a strength bar
  and a show-password button, allow pasting and use
  `autocomplete="new-password"` / `"current-password"` for password managers.
  `AUTH_PASSWORD_VALIDATORS` in `settings_local.py` replaces the rules.
- **Changing the password** needs the current one (wrong ones count like wrong
  sign-ins). The other sessions of the account are signed out, this one stays,
  and the member gets a "your password was changed" email (also when an
  administrator sets it).
- **Forgot your password?** emails a link to a page where the member chooses a
  new password; the page answers the same for any address. The link works once,
  for an hour, and stops working when the password changes or the member signs
  in; requests are limited per address and IP address (*Account emails per
  hour*, 3). Opening the link changes nothing (mail scanners open links); with
  two-step verification on, the page also asks for a code (or a recovery code).
  After the reset every session is signed out, the member gets an email and
  signs in with the new password.
- **Signing in:** "Keep me signed in" (ticked by default) keeps the session for
  two weeks (`SESSION_COOKIE_AGE`); unticked, it ends when the browser closes.
  *Email members about sign-ins from a new browser* (off by default) sends an
  email with the time, browser and IP address the first time a browser signs in
  to an account (a random id in a long-lived `osqa_device` cookie; the first
  browser is only remembered).
- **Signing out** is a POST with the CSRF token (`/logout/` and
  `/account/signout/` show a button), so no link or image elsewhere can sign
  people out; "Also sign out on all my other devices" ends every session. The
  security page has "Sign out of all other sessions". Each session remembers
  the account's `session_epoch` from its sign-in; raising it ends the others.
- **Changing the email address:** the account keeps its address until the
  member opens the link sent to the new one (48 hours). The old, confirmed
  address gets a notice with a "Cancel the change" button, which keeps it and
  signs out every session. An administrator's change applies at once and tells
  the old address.
- **Deleting the account** (Your data and account) happens at once after the
  member types their username and their password (and a two-step code if they
  use it; members without a password sign in again first). Profile, email,
  sign-in methods, passkeys, two-step verification, push subscriptions,
  notifications, subscriptions, preferences and sessions are removed, a last
  email confirms it, and posts stay as by "deleted-user-N" (or are deleted:
  *Posts of deleted accounts*). Moderators and administrators can't delete
  their own account; the security log records only the account id.
- **Account emails** (confirmation, reset, password changed, email change,
  new sign-in, deletion) use the email layout, have a plain text part, are
  translatable, appear in Admin > Email previews, never contain a password,
  and are sent whatever the member's notification settings.

## Upgrading an existing installation

- Add `SECRET_KEY` to `settings_local.py` (the old built-in key was public).
  Changing it logs everybody out.
- Sessions are now stored as JSON, so existing sessions are dropped once.
- An old `CACHE_BACKEND = 'file://...'` line keeps working; it is translated
  into `CACHES`.
- Cancelling a vote didn't lower the post score in earlier versions of the
  port; run Admin > Recalculate scores and reputation once to fix stored
  scores.
- Migrations `0003`-`0005` add indexes to large tables (nodes, actions); run
  `migrate` during a quiet period on big sites.
- The OpenID, Twitter, old Facebook, stats, updates and Sphinx modules were
  removed: their services no longer exist (stats/updates reported to the
  defunct osqa.net). Migration `0006` drops the OpenID tables. Users who only
  signed in with one of those providers can request a temporary login link by
  email ("Forgot your password?") and then connect Google, GitHub or Facebook,
  or set a password, from their account settings.
- Migration `0007` hides the two default sidebar blocks (the WebFaction hosting
  advert and "Learn more about OSQA", both pointing at services that no longer
  exist) when they still contain the shipped text; edited blocks are kept.
- Migration `0013` adds the search index (MySQL `FULLTEXT` indexes, an FTS5
  table on SQLite). Run `python manage.py rebuild_search_index` once after
  `migrate` to index the existing questions (see "Search").
- Uploaded images now get AVIF/WebP copies at smaller widths (see "Look and
  feel"). Run `python manage.py backfill_image_variants --rerender` once
  (`--dry-run` shows what it would do; running it again skips what is done)
  to make them for the existing uploads and show them in the existing posts.
- A database created by the old Django 1.6/South version is not migrated in
  place: create a fresh database with `migrate` and import the old data into it
  (next section).

### Upgrading Django

`requirements.txt` pins Django 5.2 LTS (supported until April 2028). The code
also runs on Django 6.0: CI tests it on Python 3.14, where deprecation
warnings are errors, and the models give the same migrations on both versions.
To move a site to 6.0:

1. Use Python 3.12 or newer and check the database versions in the Django 6.0
   release notes (PostgreSQL 14 or newer, for example).
2. Change `Django==5.2.x` to the latest `Django==6.0.x` in `requirements.txt`,
   `pip install -r requirements.txt`, then run `python manage.py migrate`
   (no new migrations are expected) and the tests.
3. Look at the admin pages on a phone: they use Django's admin style sheets,
   which change between versions.

`settings.py` filters a few deprecation warnings that come from third-party
packages; remove a filter once the package no longer needs it. Check for new
warnings in our own code with
`python -W error::DeprecationWarning -W error::PendingDeprecationWarning manage.py test forum.tests`.

## Importing a database from the old OSQA (Django 1.6)

The whole procedure (freeze, dump, import, checks, transfer to MySQL, files,
go-live) is in [docs/upgrading-from-original-osqa.md](docs/upgrading-from-original-osqa.md).
In short:

Load the old site's mysqldump into its own database on the new site's
MySQL/MariaDB server, then copy it into the freshly migrated, empty database:

```bash
mysql -e "CREATE DATABASE osqa_old" && mysql --default-character-set=utf8mb4 osqa_old < <dump>.sql
python manage.py migrate
python manage.py import_original_osqa --from osqa_old   # copies every table by column name
python manage.py rebuild_search_index
```

The import clears the cache when it finishes; clear it yourself (`rm -rf cache/*`
for the default file cache) whenever you replace or edit the database outside
the site, since posts and users are served from the cache. `docs/data-migration-guide.md` describes other approaches (MySQL to
MySQL/PostgreSQL) and how to verify the result; `docs/database-tables.md` lists
the tables.

## Development

`requirements-dev.txt` adds the tools used below to `requirements.txt`:

```bash
pip install -r requirements-dev.txt
ruff check .                      # lint; configuration in pyproject.toml
pip-audit -r requirements.txt -r requirements-dev.txt   # known vulnerabilities
```

- **Lint:** [ruff](https://docs.astral.sh/ruff/) checks pyflakes errors, the
  error-prone pycodestyle rules, part of bugbear and the Python 3 upgrades
  (`pyproject.toml` lists the rules and why some are ignored; migrations and
  vendored code are excluded). `ruff check --fix .` applies the safe fixes.
  CI fails on any finding.
- **Dependencies:** every version is pinned. CI runs `pip-audit` on everything
  `requirements.txt` installs, and Dependabot proposes updates weekly; check
  the changelog before moving a library to a new major version.

## Tests

```bash
pip install -r requirements-dev.txt
OSQA_SETTINGS_LOCAL=settings_local_test python manage.py test forum.tests
```

Always pass the `forum.tests` label.

Browser tests (Playwright) go through every workflow, from anonymous visitor
to administrator, on desktop and phone, and a crawler follows every link each
kind of user can see. `e2e/coverage.py` lists any URL no browser test reaches;
see [e2e/README.md](e2e/README.md):

```bash
python -m playwright install chromium
OSQA_SETTINGS_LOCAL=settings_local_e2e python manage.py test e2e
```

CI (`.github/workflows/tests.yml`) runs `ruff check .`, the
suite (deprecation warnings are errors) and `makemigrations --check` on
Python 3.12 and 3.13 with Django 5.2, and on Python 3.14 with Django 6.0.

## Modules

Optional features live in `forum_modules/` and are switched off with
`DISABLED_MODULES` in `settings_local.py`.

All modules below except the (switched-off) full-text search ones are covered by the test suite.

| Module | What it does | Setup |
|---|---|---|
| `localauth` | Username/password login and registration | - |
| `oauth2auth` | "Sign in with Google / GitHub / Facebook" (OAuth 2.0 / OpenID Connect) | Admin > External Keys; see below |
| `ldapauth` | Login against an LDAP directory | `pip install python-ldap`; LDAP settings in the admin. Disables itself without python-ldap |
| `default_badges` | The standard badges | Thresholds under Admin > Badges |
| `project_badges` | "Bug Buster" badge for questions tagged `bug` | Disabled by default |
| `akismet` | Spam check of new posts with Akismet | Akismet API key in the admin; does nothing without it |
| `ai` | Duplicate question detection and spam/abuse moderation with Google Gemini | Gemini API key or Vertex AI project in the admin; does nothing without one. See below |
| `recaptcha` | reCAPTCHA v2 on registration | Disabled by default; site and secret keys in the admin |
| `exporter` | Full-site XML backup (Admin > Tools > XML data exporter) and restore (XML data importer) | - |
| `sximporter` | Import of a StackExchange data dump (`/admin/sximporter/`) | Old StackExchange 1.0 dump format only |
| `robotstxt` | Editable `/robots.txt` | - |

### Spam sign-ups

Bots that register and never post (often only to put links in their profile)
are handled without any external service; the thresholds are under Admin >
Users settings:

- The sign-up forms have a hidden honeypot field and a signed time stamp:
  forms filled in faster than "Minimum time to fill in the sign-up form"
  (3 seconds) or with the honeypot filled are refused. At most "Sign-ups per
  IP address per hour" (5) accounts are created from one address.
- Below "Reputation for profile links" (25) a user's website and the links in
  their "about me" are plain text and their profile page carries
  `noindex, nofollow`; trusted users' profile links are `rel="nofollow ugc"`.
- `cron/cleanup_inactive_users` (`manage.py cleanup_inactive_users`, run
  daily) deletes accounts older than "Delete dormant accounts after" (15 days)
  that never confirmed their email, have no posts, votes or other activity, and
  haven't logged in or used the site in that time. Staff accounts are never
  deleted; `--dry-run` lists them instead, and 0 days turns it off.
- With the `ai` module configured, Gemini also reviews new and changed
  profiles (website, "about me") of low-reputation users; suspect accounts are
  listed in the moderation inbox, where a moderator suspends the account or
  deletes it (deleting is offered only for accounts without posts).

### AI assistance

The `ai` module uses Google Gemini, either through the Gemini API or through
Vertex AI in your own Google Cloud project. Everything is set up under
Admin > AI assistance > "Connection to Google Gemini":

- **Gemini API**: enter a key from Google AI Studio (or set `GEMINI_API_KEY`
  / `GOOGLE_API_KEY` on the server).
- **Vertex AI**: enter the project ID (and region, default `global`), or set
  `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION`. The server authenticates
  with Application Default Credentials: on Google Cloud the instance's service
  account, elsewhere a service account key in `GOOGLE_APPLICATION_CREDENTIALS`
  or `gcloud auth application-default login`. The account needs the Vertex AI
  User role and the project the Vertex AI API.
- **Connect through**: Automatic (the default) uses Vertex AI when a project
  is set and the key otherwise; choose one to ignore the other (e.g. when the
  server's environment has both).
- **Test connection** tries the values in the form, before saving them: it
  checks the library, where each value comes from (the page or an
  environment variable), the Google Cloud credentials, one JSON answer from
  the text model with the settings the features use and one embedding. Each
  failure is explained with what to do (invalid key, key restrictions, API not
  enabled, missing role, unknown model with the models offered instead, quota,
  network or proxy) and Google's own message; keys are never shown.
- After changing the **embedding model**, the next nightly
  `build_knowledge_index` embeds the whole index again (it records which model
  built it; until then semantic search finds little).

Each feature can be switched off under Admin > AI assistance:

- **Duplicate detection**: while someone types a question title, existing
  questions with matching keywords are sent to Gemini, which picks the ones
  that ask the same thing; the ask page lists them with a one-line reason.
  Results are cached and limited per visitor per hour.
- **Spam and abuse moderation**: new and edited posts by users below a
  reputation threshold (staff are never checked) are reviewed in the
  background. Likely spam, abuse or off-topic posts, and posts Gemini's safety
  filters refuse to read, are listed in the moderation inbox under "AI
  moderation reports", where a moderator dismisses the report or deletes the
  post (also as spam). The AI never hides or deletes anything itself, and a report costs the
  author no reputation.
- **Profile spam review**: new or changed websites and "about me" texts of
  low-reputation users are checked for SEO links and advertising; suspect
  accounts are listed in the same queue (see "Spam sign-ups" above).

- **Assistant and knowledge index**: `manage.py build_knowledge_index`
  (nightly) indexes answered forum threads and the documentation crawled from
  "Documentation to crawl" (default: openforis.org, the Collect Earth Online
  docs, FAO's Open Foris pages, earthmap.org; same site and path only,
  robots.txt respected) with Gemini embeddings; only changed text is
  re-embedded. The ask page offers "Ask the AI assistant first": Gemini
  answers only from the closest threads and pages, citing them.
- **Nothing made up**: an assistant answer or suggestion is shown only when it
  cites at least one forum thread or documentation page and a second Gemini
  check confirms that every statement (steps, setting names, versions...) is
  supported by those sources and that they really address the question;
  otherwise the assistant says it found no clear answer and no suggestion is
  posted. The web at large is not used: add documentation sites to
  "Documentation to crawl" instead.
- **Suggested answers**: `manage.py suggest_answers` (hourly) adds a marked AI
  suggestion with sources to questions unanswered after 24 hours, when the
  forum or the documentation clearly covers them (see above). The asker
  and moderators can mark it helpful or remove it; it isn't an answer, earns
  no reputation and never goes back into the index or the exports.

These features send the text of public posts to Google (nothing else about
the author); say so in your privacy page if you turn them on. The model is
configurable (default `gemini-3.8-flash`; `gemini-3.5-flash-lite` is
cheaper). Without credentials, or if the API is unreachable, the site works as
before.

### Content for AI agents

So other assistants (Gemini, Claude, ChatGPT, in-house agents) can use the
forum and cite it, without the `ai` module:

- `/questions/<id>.md`: a thread as Markdown with metadata (status, score,
  tags, dates), accepted answer first; question pages link it.
- `/llms.txt`: what the site is and how to read it.
- `/export/qa.jsonl`: all answered questions with their answers.
- `/mcp`: a read-only MCP server (Streamable HTTP) with `search_forum` and
  `get_question`; with the knowledge index built, search is semantic.

### JSON API

A versioned public API at `/api/v1/`, documented at `/api/` (linked from the
footer, `llms.txt` and the token page) and described as OpenAPI 3.1 at
`/api/v1/openapi.json`. Both are generated from one registry of endpoints in
`forum/api/` (`core.py` registry and machinery, `endpoints.py`, `schemas.py`,
`openapi.py`), so the docs can't drift from the routes.

- **Read** (no token needed, same visibility as the site): questions (filters
  `tags`, `status`, `since`; `sort` active/newest/votes; cursor pages), one
  question with answers and comments (HTML and Markdown), answers, tags with
  synonyms, members (public fields), search (the search page's filters),
  badges. Lists are `{"data": [...], "next": url|null}` plus a `Link` header;
  single objects carry an `ETag` (304 on `If-None-Match`).
- **Write** with a personal access token (`Authorization: Bearer osqa_...`,
  scope `write`): ask, answer, comment, vote up/down/none, accept/unaccept,
  follow/unfollow. Everything goes through the same Action classes,
  reputation rules, email confirmation, hourly posting limits, spam checks
  and first-posts review as the web site; members a CAPTCHA would be shown to
  must post on the site.
- **Tokens**: Settings > API tokens (`/account/<id>/api-tokens/`): name,
  read or read+write, expiry (30/90/365 days or never), last use; shown once,
  stored as a SHA-256 digest, revocable; administrators can revoke. The API
  never uses the session cookie (no CSRF exposure); suspended accounts'
  tokens are refused; deleting an account deletes its tokens.
- **Errors** are RFC 9457 `application/problem+json` (types listed on `/api/`).
- **Admin > Public API**: turn the API or writes off, rate limits per minute
  (per IP without a token, per token, writes per token; `X-RateLimit-*`
  headers, 429 with `Retry-After`), and the CORS origins allowed to read it
  from browsers (default `*`, GET only, never with credentials).

### Social login

For each provider you want, create an OAuth app and enter its client id and
secret under Admin > External Keys; the button appears on the sign-in page once
both are set. Register this redirect (callback) URI with the provider:

- Google (Google Cloud console > Credentials): `<APP_URL>/account/google/done/`
- GitHub (Settings > Developer settings > OAuth Apps): `<APP_URL>/account/github/done/`
- Facebook (developers.facebook.com, Facebook Login): `<APP_URL>/account/facebook/done/`

Signed-in users can connect more providers from their account's
authentication settings.

## Look and feel

The default skin is responsive (phones, tablets, desktops). Its styles live
in one file, `forum/skins/default/media/style/osqa.css`, drawn with colour
variables (`--brand`, `--accent`, ... at the start of its section 2).

Admin > Look and feel changes the common things without writing CSS:
- **Colours:** pick one of the presets or a brand colour (links, buttons,
  the current tab) and an accent colour (the Ask button). A sample of a
  page in the light and dark themes follows the fields as they change.
  Text stays readable whatever is picked: a colour too light for white
  text or for links (less than 4.5:1, WCAG AA) is darkened, keeping its
  hue, and the page says which shade the site uses; dark mode gets a
  lighter shade for links and a darker one for buttons.
- **Page background** (light grey, white or a tint of the brand colour),
  **font** (system font stacks: nothing is downloaded) and **page width**.
- **Dark mode** on or off, and the **theme for new visitors** (System,
  Light or Dark) until they pick one.

Preview shows the whole site with the new values, to the administrator only,
before saving. The values become a small `<style>` after `osqa.css`
(`{% appearance_style %}`, `forum/utils/appearance.py`); nothing is added
while they are the defaults. For anything else, Admin > Custom CSS is loaded
last and can override any rule or variable, e.g. `:root { --brand: #00704a; }`;
its page lists the variables and examples to copy.

Visitors choose a theme, Light, Dark or System (the default: it follows the
device's dark mode setting), in the footer, and members also from the header.
The choice applies at once, without a flash of the other theme on the next
page, and is kept in an `osqa_theme` cookie and, for members, with their
preferences; the admin pages follow it. Turn dark mode off under Admin > Look
and feel if your custom CSS assumes a light background (the switch then
disappears). In custom CSS, write dark rules as
`:root[data-theme="dark"] .my-class { ... }`: `data-theme` on `<html>` is
always the resolved theme, "light" or "dark". (Rules written for the old
`@media (prefers-color-scheme: dark) { :root[data-color-scheme="auto"] ... }`
still apply while a visitor's theme is System.)

Keyboard shortcuts: `?` lists them, `/` searches, `g` then `h`/`q`/`t`/`u`/`n`
goes to the home page, questions, tags, users or notifications, `a` asks a
question, `j`/`k` move through a list of questions (Enter opens one) or the
posts of a question page (`u`/`d` vote). They never apply while typing, and
members can turn them off in their preferences (this also turns off `j`/`k`
in the moderation inbox).

Accessibility: the pages aim at WCAG 2.2 AA, in both themes and on phones.
`e2e/test_accessibility.py` runs axe-core on them and `e2e/test_wcag22.py`
measures what axe can't: controls of at least 24x24 px (or spaced apart), a
visible focus ring of 3:1 that bars at the bottom of the screen (the live
"Show" banner, the phone's message bar) never cover, no sideways scrolling at
320 px, the text spacing of WCAG 1.4.12, Escape and focus return in dialogs
and menus, and sign-in fields that allow pasting and password managers. Links
inside sentences are underlined. A list or radio button that applies at once
(the search filters, the footer's language) waits for Enter, leaving it or
"Apply filters" when changed with the keyboard, so the arrow keys don't
reload the page at each option. Animations stop with the system's reduced
motion setting.

jQuery 3.7, jQuery UI 1.14 (tag and user suggestions), Flot 4.2
(charts) and highlight.js 11.11 are served from the skin (`media/vendor/`), so
pages load no third-party scripts unless Google search, Analytics or a provider
login is configured. jQuery UI is loaded when a suggestion field is first used
and highlight.js only on pages with code blocks.

Page speed: uploaded images are stored re-encoded (metadata removed) and, next
to them in `upfiles/_variants/`, as WebP and AVIF (when Pillow supports it) at
640 and 1280 pixels wide and full width. Posts show them as `<picture>` with
their width and height, so a phone downloads a small file and nothing jumps
while the page loads; the first image of a question loads first. Avatars,
the logo and the search and sign-in pages reserve their space too.
`e2e/test_web_vitals.py` checks layout shift, largest paint, response time,
interaction delay, and the number and weight of requests of the main pages on
a slow phone connection. Post HTML is sanitized with nh3 and turned into plain text
for emails with html2text.

Admin > "Switch to django style interface" uses Django's own admin stylesheets;
OSQA serves them itself from `/m/django_admin/`, like the skin media under
`/m/`, so no `collectstatic` or web-server configuration is needed.

The header search box uses Google Programmable Search when Admin > External
Keys > "Google custom search engine ID" is set (it defaults to the engine this
fork used before), and the site's own search when it is empty.

### Installable app and offline reading

The forum is a progressive web app: browsers offer to install it (name,
description and short name from Admin > Basic settings; the icon is the
admin's logo when it is an uploaded square image of at least 192 pixels,
otherwise the bundled icons in `media/images/icons/`). A service worker
(`/sw.js`, template `pwa/sw.js`, registered by `media/js/osqa.pwa.js`) keeps
the skin files and the last 50 question, question list and tag pages a visitor
read. Without a connection those pages open from the saved copy with an
"offline" banner, and other pages show `/offline/`, which lists what was saved.
Posting, votes, the admin, account, notification and profile pages are never
cached, and saved pages are forgotten on sign-out or when another user signs
in. Static files are cached under a name that changes with every deploy that
changes them; HTTPS (or localhost) is required.

## Features added in this fork

- Fenced code blocks (```` ```python ````) and syntax highlighting (highlight.js,
  self-hosted) in posts and the editor preview. The preview is rendered by the
  server with the same Markdown pipeline as published posts, so what you see is
  what gets posted.
- `@username` mentions in posts and comments, with autocomplete and an email to
  the mentioned user (controlled by the "mentions me" notification setting).
- Close as duplicate with a link to the original question; moderators can move
  the answers to the original.
- A modern post editor: an accessible toolbar (bold, italic, link, quote,
  inline code, code block with a language, lists, heading, table, image,
  undo/redo, help) with tooltips and keyboard shortcuts (Ctrl/Cmd+B, I, K, E;
  Tab indents lists and code, Escape then Tab leaves the text box), pipe
  tables, @mention suggestions, a live character/word count with the minimum
  length, and the server-rendered preview. Paste or drop images (several at
  once) to upload them; text pasted from web pages, Word or Google Docs is
  converted to Markdown (Ctrl+Shift+V pastes plain text). Drafts of questions
  and answers are saved in the browser until posted.
- schema.org QAPage structured data and OpenGraph/Twitter link previews.
- Tag management for moderators: descriptions, synonyms, rename and merge
  ("Manage tag" on a tag's page; see "Moderating tags").
- Full-text search with relevance ranking, highlighted snippets and operators
  (phrases, exclusions, tags, `is:`, `user:`); see "Search".
- Users can download their data (JSON) and delete their account, which
  anonymises it and keeps their posts (profile menu > "your data and account").
- Optional AI assistance with Google Gemini: duplicate detection while asking, and a
  moderation queue for likely spam (see "AI assistance" above).

## Layout

- `forum/` - the application: models, views, actions, templates (`skins/`),
  settings stored in the database (`forum/settings/`), tests (`forum/tests/`)
- `forum_modules/` - optional modules
- `scripts/` - development helpers (`dev/`)
- `docs/` - database reference and migration guide; `docs/upgrade-history/`
  holds the notes from the Django 1.6 to 4.2 port

## License

See `LICENSE`.
