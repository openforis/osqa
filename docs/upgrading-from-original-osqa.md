# Moving a forum from the original OSQA to this version

This is the procedure for moving a live forum that runs the **original OSQA**
(Python 2, Django 1.6, South migrations, usually MySQL) to this version
(Python 3.12+, Django 5.2). It is the plan for the Open Foris forum, and it
works for any other OSQA site.

## Why it is a move, not an in-place upgrade

The old database schema (Django 1.6 / South) and the new one (Django 5.2
migrations) differ in column types, removed tables (OpenID, old modules) and
migration history. Django can't migrate that schema directly. Instead:

1. Freeze the old site and dump its MySQL database.
2. Load the dump into a scratch database on the new site's MySQL/MariaDB
   server, next to the new site's freshly migrated, empty database.
3. Copy the data with `manage.py import_original_osqa`. It copies every table
   by column name, so the server converts the character set and the old
   column layout doesn't matter; Python 2 pickled values are copied as they
   are and read by the new code.
4. Check the import.
5. Copy uploaded files, review settings, test, and switch the domain.

The old site stays untouched throughout, so going back is just switching the
domain back. **Rehearse the whole procedure on a copy first**, without
freezing the live site, and time each step: that tells you how long the real
freeze will take.

The import was run on the Open Foris forum (about 4,200 posts, 1,300 users,
17,000 actions) into MySQL 8.4: every table's row count matched, and the
dump, import and search index took under a minute.

---

## 0. Before you start: what to collect from the old server

- [ ] **The old `settings_local.py`:** note `DATABASES`, `APP_URL`,
  `TIME_ZONE`, `LANGUAGE_CODE`, `DISABLED_MODULES` and any custom settings.
  **Keep the same `TIME_ZONE`**: dates are stored in local time, and a
  different zone shifts every date on the site.
- [ ] **Customisations:** custom skin or templates (`forum/skins/<name>/`),
  custom CSS (often stored in the admin, which moves with the database),
  extra modules in `forum_modules/`, code patches (`git diff`, or compare
  with the OSQA release you started from). Templates from the old version
  don't work unchanged; plan to redo any customisation on the new default
  skin, which is responsive.
- [ ] **Uploaded files:** the old `forum/upfiles/` directory (images in posts,
  the site logo).
- [ ] **Scheduled jobs:** the old crontab (`send_email_alerts`, ...).
- [ ] **Social sign-in:** which providers were used. OpenID, Twitter and the
  old Facebook login were removed; Google, GitHub and Facebook now use OAuth
  2.0 and need new app credentials (README, "Social login").
- [ ] **Database facts:** run these on the old database and keep the output
  for checking later:

```sql
SELECT node_type, COUNT(*) FROM forum_node GROUP BY node_type;
SELECT COUNT(*) FROM auth_user;
SELECT COUNT(*) FROM forum_tag;
SELECT COUNT(*) FROM forum_vote;
SELECT COUNT(*) FROM forum_action;
SELECT COUNT(*) FROM forum_award;
SELECT COUNT(*) FROM forum_noderevision;
-- old password formats (see step 7)
SELECT LEFT(password, LOCATE('$', password)) AS hasher, COUNT(*) FROM auth_user GROUP BY hasher;
-- table character sets (see step 2)
SELECT table_name, table_collation FROM information_schema.tables WHERE table_schema = DATABASE();
```

- [ ] **A few test pages:** five or six URLs to compare by eye after the move:
  - a question with accented or non-Latin text (Spanish, French,
    Portuguese…);
  - a question with code blocks;
  - a question with an image;
  - a busy user profile;
  - the tag list.

## 1. Set up the new site (not public yet)

Follow [deployment.md](deployment.md) on the new server or container
platform, up to and including `migrate`, with an empty production database.
Don't register an account and don't point the domain at it yet. Use a
temporary host name (e.g. `forum-new.example.org`) in `ALLOWED_HOSTS` and
`APP_URL` while testing; switch `APP_URL` to the real address at go-live.

Use the old site's `TIME_ZONE` and `LANGUAGE_CODE` in the new `settings_local.py`.

## 2. Freeze the old site and dump the database

1. In the old admin, turn on **maintenance mode**, allowing your own IP
   address, so nobody posts while you copy. (For the rehearsal, skip this.)
2. Dump the database:

```bash
mysqldump --single-transaction --default-character-set=utf8mb4 \
    --ignore-table=osqa.django_session --ignore-table=osqa.forum_mysqlftsindex \
    osqa > osqa-$(date +%F).sql
```

   Sessions and the old search index aren't imported, and the sessions table
   is often the biggest one.

   Old OSQA tables are usually `latin1` (`table_collation` from step 0).
   MySQL converts them to UTF-8 in the dump. Check accented text in the dump
   (`grep` for a word you know, e.g. `grep -o 'Configuraci.n' osqa-*.sql`):

   - `Configuración`: fine, go on.
   - `ConfiguraciÃ³n`: the old site stored UTF-8 bytes in `latin1` columns.
     Dump again with `--default-character-set=latin1`, which writes the bytes
     unchanged, and declare them UTF-8 before loading:

```bash
sed -i -e 's/CHARSET=latin1/CHARSET=utf8mb4/g' -e 's/SET NAMES latin1/SET NAMES utf8mb4/' \
    -e 's/COLLATE=latin1_swedish_ci//g' osqa-YYYY-MM-DD.sql
```

3. Copy the dump to the new database server. It contains personal data
   (emails, password hashes, IP addresses): keep it out of the repository and
   web folders, and delete it when you are done.

## 3. Import into the new database

The new site's database must be freshly migrated and empty: nobody
registered and nothing posted (settings it stored are replaced by the old
site's). If in doubt, drop and recreate it and run `migrate` again. The import needs a
MySQL/MariaDB database for the new site; to end up on PostgreSQL, import into
MySQL first and move the data with `dumpdata --all` / `loaddata`.

```bash
sudo systemctl stop osqa       # nobody may open the new site during the import

# The old forum, in its own database on the same server
mysql -e "CREATE DATABASE osqa_old"
mysql --default-character-set=utf8mb4 osqa_old < osqa-YYYY-MM-DD.sql
mysql -e "GRANT SELECT ON osqa_old.* TO 'osqa'@'localhost'"   # the new site's database user

python manage.py migrate                       # empty, freshly migrated database
python manage.py import_original_osqa --from osqa_old
python manage.py rebuild_search_index
sudo systemctl start osqa
```

`import_original_osqa` prints every table with its row count. It refuses to
run on a database that already has data, and when any table's count differs
from the old one it stops and imports nothing. Columns that only exist in the
new version get their defaults. What's left out: content types and
permissions are recreated by `migrate` (OSQA doesn't use Django permissions),
OpenID tables and the South history are gone, and old sessions are dropped,
so everyone signs in again once.

The search index has to be built after importing (imported posts don't go
through the code that keeps it up to date; until it is built, search falls
back to simple keyword matching). Drop `osqa_old` and the dump when the move
is done.

To repeat the import (a rehearsal, then the real move), drop and recreate both
databases and run the whole block again.

## 4. Check the import

- Compare counts with the numbers from step 0:

```bash
python manage.py shell -c "
from forum.models import User, Question, Answer, Comment, Tag, Vote, Action, Award, NodeRevision
for m in (User, Question, Answer, Comment, Tag, Vote, Action, Award, NodeRevision):
    print(m.__name__, m.objects.count())"
```

  `Tag.objects` hides unused tags; `Tag._base_manager.count()` counts them
  all, like `SELECT COUNT(*) FROM forum_tag`.

- Open your test pages and compare with the old site:
  - accented text;
  - code blocks;
  - images (they appear after step 6);
  - vote counts;
  - accepted answers;
  - comments;
  - user reputation.
- Sign in with a test account's password. If you know a password from the old
  site, try it; old password formats keep working (step 7).
- If something is wrong, fix the cause (usually the dump's character set) and
  repeat steps 2–3.

## 5. Scores and reputation

The import keeps the stored post scores and user reputation. **Admin >
Recalculate scores and reputation** sets every score to the sum of its votes
and every reputation to the sum of the member's reputation history. The two
differ where the old site lost history rows, e.g. users deleted directly in
the database: on the Open Foris forum all scores matched and 9 reputations
differed by a few points. Recalculate if you prefer values that match the
history members see on their profiles; otherwise skip it.

## 6. Uploaded files

Copy the old `forum/upfiles/` into the new site's `forum/upfiles/`: the
server directory, or the mounted volume in Docker and Kubernetes. Make sure
the app's user can read it:

```bash
rsync -a old-server:/path/to/osqa/forum/upfiles/ /srv/osqa/app/forum/upfiles/
```

Image links in posts (`/upfiles/...`) then work unchanged. If the old site
lived under a sub-path (e.g. `example.org/forum/`) and the new one doesn't,
see "Links" in step 9.

## 7. Accounts and passwords: what users will notice

- **Passwords keep working.** Hashes from the old site (PBKDF2, and the salted
  SHA1 of very old accounts) are still checked. They are upgraded to the
  current format at the user's next sign-in.
- **Everyone is signed out once.** Sessions aren't copied.
- **OpenID or Twitter accounts:** users who only signed in with OpenID or
  Twitter have no password. They use "Forgot your password?" to get a sign-in
  link by email, then set a password or connect Google, GitHub or Facebook in
  their account settings.
- **Old email links:** links in emails sent by the old site (validation,
  temporary sign-in) no longer work; users request new ones.
- **New password rules:** new passwords must have at least 8 characters, not be
  common and not be similar to the username. Existing passwords aren't
  affected until they are changed.

Consider a short notice on the old site before the freeze, and a message on
the new site for the first weeks: the announcement bar, under Admin > Header
and footer.

## 8. Review the settings in the new admin

Site settings came across with the database (they are stored in it). Review
these, because the old values may not fit the new version:

- **Email settings:** SMTP server, sender; send a test.
- **External keys:**
  - Create new OAuth apps for Google/GitHub/Facebook sign-in with the new
    callback URLs (README, "Social login").
  - Old Akismet and reCAPTCHA keys still apply if those modules are enabled.
- **Look and feel:**
  - Check the logo and colours, and the custom CSS and header/footer HTML
    against the new responsive skin, at phone width as well.
  - Remove CSS written for the old fixed-width layout if it gets in the way.
- **Custom `<head>` / footer:**
  - Scripts such as analytics must be allowed under Admin > Security > "Extra
    script sources". Otherwise the Content-Security-Policy blocks them, which
    shows up in `log/security.log` and Sentry.
  - Inline `<script>` elements there still run (they get the page's CSP
    nonce), but inline event handlers (`onclick="..."`), `javascript:` links
    and scripts in the sidebar or custom pages don't.
  - Old Google Analytics (`ga.js`) no longer collects data; use Google
    Analytics 4 or another tool.
- **Header search:** the forum's own search is used by default. It finds
  questions by keywords, and by meaning when the AI module is configured.
  The Open Foris forum used a Google Programmable Search engine, which was
  hard-coded. To keep it, enter its ID (`011544878288102132035:auatq0p6-wo`)
  under Admin > External Keys > "Google custom search engine ID".
- **Sidebar:** the old default blocks advertising osqa.net/WebFaction are
  hidden automatically. Check your own blocks.
- **Admin > Security and Members:** the new sign-in, posting and spam
  limits. Defaults are fine for most sites.
- **AI assistance** (optional): see the README's "AI assistance".

## 9. Test, then go live

The full rehearsal list (real email, sign-in providers, search on MySQL,
several app processes) is [staging-checklist.md](staging-checklist.md). At the
least, test on the temporary address:

- [ ] Sign in with an existing account (password), and with Google if configured.
- [ ] Ask, answer and comment; vote; accept an answer.
- [ ] Upload an image.
- [ ] Notification email received, with a working unsubscribe link.
- [ ] Test pages from step 0 match the old site.
- [ ] Search finds old questions.
- [ ] `/healthz` returns `ok`. Sentry receives the test event
      (deployment.md, "After installing").
- [ ] Admin pages open: flagged posts, settings.

Go live:

1. Set `APP_URL` and `ALLOWED_HOSTS` to the real address. Restart the app.
2. Point DNS or the reverse proxy for the real domain at the new site. Get
   the TLS certificate.
3. Set up the scheduled jobs (deployment.md), and **disable the old server's
   cron jobs** so users don't get digests from both.
4. **Links:** question URLs (`/questions/<id>/<slug>`) are unchanged, so
   search engines and links keep working. If the old site lived under a
   sub-path and the new one doesn't, add a redirect at the proxy, e.g. in
   nginx: `location /forum/ { rewrite ^/forum/(.*)$ /$1 permanent; }`.
5. Watch Sentry and `log/` for the first days.

**Going back:** until you shut it down, the old server is unchanged. If
something serious turns up, point the domain back, turn off maintenance mode
there, and fix the problem on the new site at leisure. Content posted on the
new site meanwhile would need to be re-entered, so decide within the first
hours. Keep the old server, read-only, and the dump for a few weeks before
deleting them.

## Time needed

The dump, import, transfer and file copy are mechanical. Most of the time
goes into checking (steps 4, 8 and 9). Plan the freeze for a quiet day,
announce it in advance, and use the rehearsal's timings to size it.
