# Staging checklist: try this version with real data before going live

The automated tests run on SQLite with every outside service faked: email is
captured, Google/GitHub/Facebook/LDAP/Gemini/push are mocked. This checklist
covers what they can't: a real MySQL (or PostgreSQL) server, real email, real
sign-in providers, HTTPS, several app processes sharing one cache, and a copy
of your forum's data.

Set up a staging site that is as close to production as you can make it: the
same database server version, the same cache (memcached), gunicorn with
several workers behind the same proxy, and a real HTTPS address
(e.g. `staging.forum.example.org`). Keep it private (proxy password or IP
allow-list) and make sure it can't email real members by accident (see
step 3).

Tick each box; write down anything odd with the page address and the time
(the `X-Request-ID` response header helps find it in the logs).

## 1. Install and import

- [ ] Server or containers set up as in [deployment.md](deployment.md),
      option A, B or C. `SECRET_KEY` is new (not the production one).
- [ ] `python manage.py checkinstall` reports no problems.
- [ ] A copy of the live data is imported:
  - **From the original OSQA:** steps 0–6 of
    [upgrading-from-original-osqa.md](upgrading-from-original-osqa.md)
    (load the dump next to the new database, `import_original_osqa`,
    check, copy `forum/upfiles/`).
  - **From an earlier install of this version:** `manage.py backup_site` on
    production and `manage.py restore_site` on staging
    ([deployment.md, Backups and restore](deployment.md#backups-and-restore)).
- [ ] `python manage.py migrate` runs to the end. Note how long it takes:
      migrations add indexes to big tables, and production needs the same
      quiet period.
- [ ] Row counts match production (the `shell` snippet in step 4 of the
      upgrading guide).
- [ ] One-off jobs, in this order, each timed:
  ```bash
  python manage.py shell -c "from django.core.cache import cache; cache.clear()"
  python manage.py rebuild_search_index
  python manage.py backfill_image_variants --dry-run   # what it will do
  python manage.py backfill_image_variants --rerender
  python manage.py refresh_tag_expertise          # expert routing
  ```
- [ ] Admin > Recalculate scores and reputation (only when coming from the
      original OSQA).

## 2. Database and search (MySQL/MariaDB or PostgreSQL)

- [ ] Search finds old questions by a word from the title, from the body and
      from an answer; the best match comes first.
- [ ] Accented words and words in other languages are found
      (`configuração`, `año`); a phrase in quotes and `-word` work.
- [ ] Filters on the results page (tag, accepted/unanswered, date, author)
      narrow the results; the counts beside them look right.
- [ ] A misspelt word offers "Did you mean ...".
- [ ] A new question becomes searchable straight away; an edited title is
      found by its new words.
- [ ] Short words (fewer than 3 letters on MySQL, `innodb_ft_min_token_size`)
      are expected to be ignored: check this doesn't hide something your
      members search for often (README, "Search").
- [ ] Pages feel quick with real data: question list, a long question, tag
      page, user profile, search. With `SERVER_TIMING=1` set (staff only) the
      browser's network panel shows database and render time per page.
- [ ] The database's slow query log shows nothing over 1 s while you click
      around.

## 3. Email (the most important part)

Point staging at a test mailbox first, for example a Mailpit/MailHog
container or a provider's sandbox, so imported members get nothing. Only
switch to the real SMTP server with an allow-list or for the last check.

- [ ] Admin > Email settings > "test email settings" arrives.
- [ ] Admin > Email previews: every kind renders; spot-check them in a
      phone mail app and in dark mode.
- [ ] **Sign-up:** a new account gets the confirmation email; the link
      confirms and signs in; before confirming, signing in asks to confirm
      first (stricter mode, `EMAIL_CONFIRMATION_MODE` = signin). Signing up
      again with the same address sends its owner a notice instead.
- [ ] **Forgot password:** the link opens a set-password form, works once,
      expires after 60 minutes; the old password stops working; a security
      email is sent.
- [ ] **Change email:** the new address gets a confirmation link, the old one
      a cancel link; until confirmed the old address stays in use.
- [ ] **Notifications:** answer a followed question from a second account:
      the email arrives, links point at the staging address (`APP_URL`), and
      "unsubscribe" works in one click.
- [ ] **Daily summary:** set a member to daily, post something, run
      `python manage.py send_email_alerts`; one summary arrives.
- [ ] **Expert routing:** after `refresh_tag_expertise`, ask a question in a
      busy tag from a test account: the members with the best answers in
      that tag (test accounts only, see above) get "You might know the
      answer"; "Questions for you" lists it; "Not for me" removes it. Check
      Admin > Questions for experts suits your community (how many members
      are asked, daily cap).
- [ ] Deliverability on the real server: SPF, DKIM and DMARC pass
      (Gmail "Show original"); messages don't land in spam.

## 4. Signing in

- [ ] Sign in with an imported account's existing password (old hashes are
      upgraded on sign-in).
- [ ] Google, GitHub, Facebook: create staging OAuth apps with the callback
      URLs from the README ("Social login"), then sign up, sign in and connect
      a second provider to an existing account.
- [ ] LDAP, if used: sign in with a directory account; a wrong password is
      refused.
- [ ] **Passkeys** (need HTTPS and the right `APP_URL`): add one on
      /account/&lt;id&gt;/security/, sign out, sign in with it, on a phone
      and on a laptop.
- [ ] **Two-step verification:** turn it on with an authenticator app, sign
      in with a code and with a recovery code; turn it off.
- [ ] "Keep me signed in", sign out, "sign out everywhere"; deleting a test
      account asks to confirm, removes its profile, and treats its posts as
      set under Admin > Members ("Posts of deleted accounts").
- [ ] Repeated wrong passwords lock the sign-in for a while and show up in
      `log/security.log`.
- [ ] Behind the proxy, `log/security.log` shows the visitors' real IPs, not
      the proxy's (`TRUSTED_PROXY_COUNT`).

## 5. Posting and moderation

- [ ] Ask, answer, comment, edit, vote, accept, flag; undo a vote.
- [ ] Editor: toolbar, preview, paste a screenshot, drag an image in, paste
      formatted text from a web page or Word; a code block is highlighted.
- [ ] Old posts with images show them (AVIF/WebP for uploads after the
      backfill; the network panel shows the `_variants/` files).
- [ ] Live updates: with the question open in two browsers, a new comment
      appears in the other within about 20 s.
- [ ] A new member's first post goes to Admin > Moderation as configured.
- [ ] Suggested edit from a low-reputation account; approve it as a
      moderator.
- [ ] Tag rename and merge on a test tag.
- [ ] Versions: on the tag page of a product (e.g. collect) add its
      versions and mark the current one; ask with "Applies to version"; an
      answer for an older version shows the "may be outdated" notice and
      "Still works in …" confirms it; search with the version filter.

## 6. Several processes, cache and jobs

- [ ] With gunicorn running 2 or more workers, settings changed in the admin
      apply on every page load within a minute (shared cache, not a
      per-process one).
- [ ] `/healthz` and `/readyz` return `ok`; `/metrics` answers with the
      `METRICS_TOKEN` and 404 without it.
- [ ] The scheduled jobs from deployment.md run (`cron/crontab` in Docker):
      `/metrics` shows `osqa_cron_last_success_timestamp_seconds` for each.
- [ ] Sentry, if configured, receives the test event (deployment.md,
      "After installing"); JavaScript errors from the browser arrive too.
- [ ] `backup_site`, then `restore_site` into a scratch database, works.

## 7. Look, devices and languages

- [ ] Your logo, colours, custom CSS and header/footer HTML look right at
      phone width and in dark mode.
- [ ] Analytics or other scripts in the custom `<head>` load (allowed under
      Admin > Security > "Extra script sources"); the browser console shows
      no Content-Security-Policy errors.
- [ ] Spanish, French and Portuguese: switch in the footer; a native speaker
      reads the main pages and one email in each.
- [ ] Install the site as an app on a phone; open a question offline.
- [ ] Browser push, if `VAPID_*` keys are set: turn it on, get a notification
      for an answer, tap it.
- [ ] Keyboard only: sign in, ask a question and search without the mouse.

## 8. Optional modules

- [ ] AI module: `build_knowledge_index` finishes; the ask page suggests
      answers with sources; `suggest_answers` creates suggestions shown on
      unanswered questions.
- [ ] Akismet / reCAPTCHA keys work if those modules are enabled.
- [ ] API: create a token on the API page, call
      `/api/v1/questions` with `Authorization: Bearer <token>`.

## Before going live

- [ ] Everything above is ticked or has an agreed workaround.
- [ ] The timings of `migrate`, `rebuild_search_index` and
      `backfill_image_variants` are known, and the freeze is planned around
      them.
- [ ] Members are told what will change: everyone signs in once more; links
      in old emails (password reset, confirmation) stop working; new members
      confirm their email before signing in.
- [ ] Staging is switched off or kept private, its OAuth apps and test
      mailbox removed, and the imported copy of the data deleted.

Then follow step 9 of the upgrading guide ("Test, then go live") or the
"Updating" section of deployment.md for production.
