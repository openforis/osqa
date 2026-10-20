# Setting up a new OSQA forum

This guide covers setting up a new, empty forum on a Linux server, with Docker
Compose, or on another container platform. To move an existing forum from the
original OSQA (Python 2 / Django 1.6), set the new site up with this guide and
then follow [upgrading-from-original-osqa.md](upgrading-from-original-osqa.md).
Before going live with real members, rehearse on a staging copy with
[staging-checklist.md](staging-checklist.md).

## What a forum needs

| Part | What to use | Notes |
|---|---|---|
| Python | 3.12 or newer | The Docker image uses 3.13 |
| Database | MySQL 8 / MariaDB 10.6+ (recommended), PostgreSQL, or SQLite for small or test sites | Create it with `utf8mb4` so every language and emoji can be stored |
| Cache | memcached (recommended), or the file cache | Must be **shared by all worker processes**: posts and users are served from it. Never use the per-process local-memory cache |
| Web server | gunicorn behind nginx, Apache, Caddy or a load balancer that terminates HTTPS | The app speaks plain HTTP on a local port |
| Disk | `forum/upfiles/` (uploaded images, logo), `log/`, `cache/` (with the file cache) | Uploads must persist and be shared if you run several app servers |
| Email | An SMTP server | Entered in the admin (Admin > Email settings), not in files |
| Scheduled jobs | cron, systemd timers or the platform's scheduler | Email digests and daily/weekly summaries (one daily run, e.g. 07:00) and dormant-account clean-up daily; AI jobs if used |
| Optional | Sentry, Prometheus (`/metrics`), Google Gemini (AI features), OAuth apps (Google/GitHub/Facebook sign-in) | |

Everything that changes per site (name, logo, colours, texts, email server,
reputation rules, limits) lives in the database and is edited in the admin at
`/admin/`. Only the database connection, `APP_URL`, `SECRET_KEY` and a few
server settings go in `settings_local.py` or environment variables.

## Settings you will set

Copy `settings_local.py.dist` to `settings_local.py`. The file is never
committed and is mounted into the container in Docker setups. Set:

| Setting | Example | Why |
|---|---|---|
| `DATABASES` | see below | Database connection |
| `APP_URL` | `'https://forum.example.org'` | The public address, without a trailing slash. With `https://`, secure cookies and HSTS are switched on. Passkeys are bound to its host name and work only when the site is opened at this address over HTTPS (or `localhost`) |
| `ALLOWED_HOSTS` | `('forum.example.org',)` | Host names the site answers to |
| `SECRET_KEY` (or env `OSQA_SECRET_KEY`) | a 50-character random string | Signs sessions and links. Generate with `python -c 'from django.core.management.utils import get_random_secret_key as k; print(k())'`. Changing it signs everybody out and makes two-step verification secrets unreadable (members then sign in with a recovery code): to rotate it, put the old key in `SECRET_KEY_FALLBACKS` until members have set up their app again |
| `TRUSTED_PROXY_COUNT` (or env `OSQA_TRUSTED_PROXIES`) | `1` | Number of reverse proxies in front. The visitor's IP and HTTPS are then read from `X-Forwarded-For` / `X-Forwarded-Proto`, and HTTP is redirected to HTTPS. Leave `0` if visitors reach gunicorn directly |
| `CACHES` | memcached, see the `.dist` file | Shared cache |
| `TIME_ZONE` | `'Europe/Rome'` | Dates are stored in this zone. **When moving an existing forum, keep the old value**, or every date shifts |
| `LANGUAGE_CODE` | `'en'` | Interface language |
| `SENTRY_DSN` (optional) | `'https://<key>@o<org>.ingest.sentry.io/<project>'` | Server and browser error reports (see the README) |
| `DISABLED_MODULES` | `['recaptcha', 'project_badges']` | Optional modules to switch off |
| `METRICS_TOKEN` (optional, or env) | a long random string | Turns on Prometheus metrics at `/metrics` (see [Monitoring](#monitoring-with-prometheus)) |
| `LOG_FORMAT` (optional, or env) | `'json'` | One JSON object per line on standard output (see [Logs](#logs-and-request-ids)) |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (optional, or env) | output of `python manage.py generate_vapid_keys` | Browser push notifications (off unless both keys are set; see the README). The private key is a secret; keep the pair, new keys make every device subscribe again. Needs HTTPS and outbound HTTPS to the push services (`fcm.googleapis.com`, `*.push.services.mozilla.com`, `*.push.apple.com`, `*.notify.windows.com`) |
| `BACKUP_DIR`, `BACKUP_KEEP` (optional) | `'/srv/osqa/backups'`, `14` | Where `backup_site` writes and how many archives it keeps (see [Backups](#backups-and-restore)) |

MySQL / MariaDB connection:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'osqa',
        'USER': 'osqa',
        'PASSWORD': '...',
        'HOST': '127.0.0.1',
        'PORT': '3306',
        'CONN_MAX_AGE': 600,
        'OPTIONS': {'charset': 'utf8mb4'},
    }
}
```

Create the database first:

```sql
CREATE DATABASE osqa CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'osqa'@'%' IDENTIFIED BY '...';
GRANT ALL PRIVILEGES ON osqa.* TO 'osqa'@'%';
```

---

## Option A: a Linux server (systemd + nginx)

Commands for Ubuntu 24.04 or Debian 13, whose `python3` is 3.12 or newer.
Debian 12 ships 3.11: install a newer Python (e.g. with `uv` or `pyenv`) or use
Docker. Other distributions need the equivalent packages.

### 1. Packages and user

```bash
sudo apt-get install python3 python3-venv python3-dev build-essential \
    default-libmysqlclient-dev pkg-config nginx memcached git
sudo useradd --system --create-home --home-dir /srv/osqa osqa
sudo -u osqa git clone https://github.com/openforis/osqa.git /srv/osqa/app
```

### 2. Python environment and settings

```bash
cd /srv/osqa/app
sudo -u osqa python3 -m venv /srv/osqa/venv
sudo -u osqa /srv/osqa/venv/bin/pip install -r requirements.txt
sudo -u osqa cp settings_local.py.dist settings_local.py
sudo -u osqa chmod 600 settings_local.py
sudo -u osqa editor settings_local.py        # DATABASES, APP_URL, ALLOWED_HOSTS, SECRET_KEY, TRUSTED_PROXY_COUNT = 1, CACHES
sudo -u osqa mkdir -p log cache tmp forum/upfiles
sudo -u osqa /srv/osqa/venv/bin/python manage.py migrate
```

### 3. gunicorn as a service

`/etc/systemd/system/osqa.service`:

```ini
[Unit]
Description=OSQA forum
After=network.target mysql.service memcached.service

[Service]
User=osqa
Group=osqa
WorkingDirectory=/srv/osqa/app
Environment=SENTRY_ENVIRONMENT=production
ExecStart=/srv/osqa/venv/bin/gunicorn wsgi:application --bind 127.0.0.1:8000 --workers 3 --access-logfile -
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now osqa
curl http://127.0.0.1:8000/healthz      # -> ok
```

A rule of thumb for `--workers` is 2 × CPU cores + 1. The access log goes to
the journal (`journalctl -u osqa`); application and security logs go to
`log/` (rotated at 10 MB).

### 4. nginx with HTTPS

`/etc/nginx/sites-available/osqa` (get a certificate with certbot, e.g.
`sudo certbot --nginx -d forum.example.org`):

```nginx
# Skin media URLs carry a version (?v=<hash of the file>): those never change.
map $arg_v $osqa_media_cache {
    ""      "public, max-age=3600";
    default "public, max-age=31536000, immutable";
}

server {
    listen 80;
    server_name forum.example.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name forum.example.org;
    # ssl_certificate / ssl_certificate_key: added by certbot

    client_max_body_size 5m;          # uploads are limited to 2.5 MB by default

    # Optional: serve uploads and the default skin's files without Python
    # (caching rules: see "Caching and compression" below).
    location /upfiles/ {
        alias /srv/osqa/app/forum/upfiles/;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }
    location /m/default/media/ {
        alias /srv/osqa/app/forum/skins/default/media/;
        add_header Cache-Control $osqa_media_cache;
        gzip on;
        gzip_types text/css application/javascript text/javascript image/svg+xml application/json;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

`TRUSTED_PROXY_COUNT = 1` must match: one proxy (nginx) appends the visitor's
address to `X-Forwarded-For`. With a load balancer in front of nginx, use `2`.

#### Caching and compression

What OSQA sends by itself (when Django serves the files, e.g. without the
optional `alias` locations, behind a CDN, or on a container platform):

| Request | `Cache-Control` | Validation |
|---|---|---|
| Skin media with the current version, `/m/<skin>/media/...?v=<hash>` (every `{% media %}` URL) | `public, max-age=31536000, immutable` | ETag (the hash), Last-Modified |
| Skin media without a version (images referenced from CSS) and Django's admin media (`/m/django_admin/`) | `public, max-age=3600` | ETag / Last-Modified, `304 Not Modified` |
| Skin media with an old version (a page saved before a deploy) | `no-cache` (content of the current file) | ETag |
| Uploads, `/upfiles/...` (a new upload always gets a new name) | `public, max-age=31536000, immutable` | ETag |
| Their AVIF/WebP copies, `/upfiles/_variants/...` (written once) | `public, max-age=31536000, immutable` | ETag |
| The default logo shipped in `forum/upfiles` | `public, max-age=3600` | ETag |
| Question pages for anonymous visitors without a pending message (once their view is counted), and `/feeds/rss/` | `private, no-cache`, `Vary: Cookie, Accept-Language` | ETag, `304 Not Modified` while nothing on the site changed (at most an hour) |
| The JSON API, `/api/v1/...` | `public, no-cache` (`private` with a token), `no-store` for writes; `Vary: Authorization, Origin, Accept-Language` | ETag and `304` on single objects |
| Other pages | none | none |

The version is a hash of the file's content, computed once per process, so
a deploy that changes a file changes its URL and nothing stale is served; the
service worker (`/sw.js`, never cached for long) names its cache after the
same hashes. Requests for files skip the session and user middleware: they
set no cookie and don't vary by cookie, so a CDN or proxy cache may keep them.

Compression: OSQA gzips CSS, JavaScript, SVG and JSON files it serves (when
the browser accepts gzip) and never HTML pages, which carry the CSRF token
(BREACH). gunicorn compresses nothing. nginx compresses only `text/html` by
default (`gzip on;` in the stock `nginx.conf`), proxied pages included: Django
masks the CSRF token differently in every response, its defence against
BREACH, but to keep pages uncompressed add `gzip off;` to `location /`. For
the files nginx serves itself, the `gzip_types` line above compresses the
text ones (`gzip_static on;` would use `.gz` files placed next to them).

If several app servers are updated one at a time, leave `/m/` to OSQA (drop
the `alias` for it): nginx can't tell whether `?v=` matches the file on its
own disk, while OSQA only marks the current version immutable.

#### Images

Every uploaded image is re-encoded (metadata removed, at most
`UPLOAD_MAX_IMAGE_SIDE` pixels) and stored under its own name; OSQA then
writes smaller copies next to it in `upfiles/_variants/`: WebP, and AVIF when
the installed Pillow can write it (`python -c "from PIL import features;
print(features.check('avif'))"`), at 640 and 1280 pixels wide and full width,
plus a small `.json` file with the image's size. Posts show uploads as
`<picture>` elements with those sources and the image's width and height, so
phones download a small modern file and the page doesn't jump while it loads.
`_variants/` is part of the uploads folder: keep it on the same persistent
volume and in the backups. With the nginx `alias` for `/upfiles/` above, nginx
1.21 or older needs `types { image/avif avif; }` in that location (older
`mime.types` files don't list AVIF). Images uploaded before this version get
their copies from `manage.py backfill_image_variants` (see the update steps).

For profiling, `SERVER_TIMING=staff` (environment or `settings_local.py`)
adds a `Server-Timing` header (database time and queries, template
rendering, total) to the pages staff members load; the browser's developer
tools show it under Network > Timing. With `DEBUG` every response has it.

#### Security headers (Content-Security-Policy)

OSQA sends its own `Content-Security-Policy` on every page. Inline scripts
run only with the nonce that policy names, and the nonce is new on every
response, so:

- Don't add a second `Content-Security-Policy` in nginx, Apache, Caddy, a
  CDN or a load balancer (`add_header Content-Security-Policy ...`, Helmet-like
  middleware, "security headers" options). A browser applies every policy it
  gets, and one without this response's nonce blocks the forum's scripts.
- Don't let a proxy or CDN cache HTML pages and serve one copy to several
  visitors: the copy's nonce wouldn't match the header sent with it. Question
  pages are marked `private`, and a `304 Not Modified` carries no policy, so
  the browser keeps the policy stored with its own copy.
- Scripts, styles, fonts, frames or form targets from other origins (analytics,
  widgets, a chat box in the custom `<head>` or footer) go in Admin > Security >
  "Extra script sources", separated by spaces, e.g.
  `https://plausible.io https://cdn.example.org`. They are added to
  `script-src`, `style-src`, `font-src`, `connect-src`, `frame-src` and
  `form-action`. Inline `<script>` elements in the custom `<head>`, header and
  footer get the nonce automatically; inline event handlers (`onclick="..."`)
  never run.
- To try a change first, set `CONTENT_SECURITY_POLICY_REPORT_ONLY = True` in
  `settings_local.py`: blocked items are only reported (security log, Sentry).
  `CONTENT_SECURITY_POLICY = "..."` replaces the whole policy (write `{nonce}`
  where the nonce goes, e.g. `script-src 'self' 'nonce-{nonce}'`).

#### Session and cookie security

With an `https://` `APP_URL`, `settings.py` already sets `SESSION_COOKIE_SECURE`,
`CSRF_COOKIE_SECURE`, HSTS and (behind a trusted proxy) `SECURE_SSL_REDIRECT`.
The defaults to keep, or set in `settings_local.py`:

| Setting | Default | Why |
| --- | --- | --- |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `True` on HTTPS | cookies never sent over plain HTTP |
| `SESSION_COOKIE_HTTPONLY` | `True` | scripts can't read the session cookie |
| `SESSION_COOKIE_SAMESITE` | `'Lax'` | other sites can't send it with their forms |
| `SESSION_COOKIE_AGE` | two weeks | "Keep me signed in"; unticked, the session ends with the browser |
| `CSRF_USE_SESSIONS` | `True` | the CSRF token lives in the session (no csrftoken cookie) |
| `SECURE_HSTS_SECONDS` | one year on HTTPS | browsers use HTTPS only |
| `SESSION_ENGINE` | database | sessions can be listed and deleted; the cached_db engine is faster |

Sign-in gives the session a new key (no session fixation), sign-out is a POST
and deletes the session, and password changes, resets, "sign out of all other
sessions" and cancelled email changes end the account's other sessions. A
reverse proxy must pass `X-Forwarded-Proto` (and set `TRUSTED_PROXY_COUNT`) so
Django knows requests are HTTPS. Password, confirmation and email-change links
are sent by email: set the email settings (Admin > Email) before opening sign-up,
and keep `APP_URL` right, since the links are built from it.

### 5. Scheduled jobs

`crontab -e -u osqa`:

```cron
OSQA=/srv/osqa/app
PY=/srv/osqa/venv/bin/python
# Daily digest and daily/weekly summaries (weekly ones go out on their day from this same
# daily run: no separate weekly line), and clean-up of dormant (bot) and never-confirmed accounts
0 7 * * *   cd $OSQA && $PY manage.py send_email_alerts
45 6 * * *  cd $OSQA && $PY manage.py cleanup_inactive_users
0 7 * * *   cd $OSQA && $PY manage.py remind_unaccepted
# Expertise per tag (who is asked to answer new questions, "Questions for you")
20 5 * * *  cd $OSQA && $PY manage.py refresh_tag_expertise
# Only with the AI module configured:
30 2 * * *  cd $OSQA && $PY manage.py build_knowledge_index
5 * * * *   cd $OSQA && $PY manage.py suggest_answers
```

### 6. First steps on the site

See [After installing](#after-installing) below.

### Updating a server installation

```bash
cd /srv/osqa/app
sudo -u osqa git pull
sudo -u osqa /srv/osqa/venv/bin/pip install -r requirements.txt
sudo -u osqa /srv/osqa/venv/bin/python manage.py migrate
sudo systemctl restart osqa
```

Read the README's "Upgrading an existing installation" notes first. When an
update adds the search index (migration `0013`), also run
`manage.py rebuild_search_index` once after `migrate`. When it adds image
variants ([Images](#images)), run
`manage.py backfill_image_variants --rerender` once (`--dry-run` first shows
what it would do; it can run again at any time and skips what is done):
it writes the AVIF/WebP copies of the existing uploads and renders again the
posts that show them. Take a
database backup before `migrate`, and run `migrate` in a quiet period on large
sites, since some migrations add indexes to big tables.

---

## Option B: Docker Compose

`docker-compose.yml` runs the whole stack from the repository's `Dockerfile`:

| Service | What it does |
|---|---|
| `db` | MySQL 8.4, `utf8mb4`, data in the `db-data` volume |
| `memcached` | the shared cache |
| `migrate` | runs `manage.py migrate` once and exits; `web` and `cron` start after it succeeds |
| `web` | gunicorn on `127.0.0.1:8000` (for a reverse proxy on the host), health check on `/readyz` |
| `cron` | the scheduled commands in `cron/crontab`, run by [supercronic](https://github.com/aptible/supercronic) (pinned and checksum-verified in the image) |

Configuration comes from environment variables, read by
`settings_local_docker.py` (selected with `OSQA_SETTINGS_LOCAL`); there is no
settings file to mount. Uploads (`/app/forum/upfiles`) and `backup_site`
archives (`/app/backups`) are the `uploads` and `backups` volumes. Logs go to
standard output as JSON lines (`docker compose logs web`).

### 1. Configure

```bash
git clone https://github.com/openforis/osqa.git && cd osqa
cp .env.example .env
editor .env      # OSQA_SECRET_KEY, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD, OSQA_APP_URL, OSQA_ALLOWED_HOSTS
```

Generate each secret with
`python3 -c 'from secrets import token_urlsafe; print(token_urlsafe(50))'`.
`OSQA_TRUSTED_PROXIES` defaults to `1`, right for one reverse proxy on the
host. Anything `settings_local_docker.py` doesn't cover can go in a
`settings_local_extra.py` mounted next to it (`/app/settings_local_extra.py`);
it is applied last.

### 2. Build and start

```bash
export SENTRY_RELEASE=osqa@$(git rev-parse --short=12 HEAD)   # optional
docker compose up -d --build
docker compose ps                    # db and web turn "healthy", migrate exits with 0
curl http://127.0.0.1:8000/readyz    # -> ok
```

Put the nginx configuration from Option A in front of `127.0.0.1:8000`; drop
the two optional `alias` locations (OSQA then sends the caching headers
described there itself). Caddy, Traefik or a cloud load balancer work the same
way, as long as they set `X-Forwarded-For` and `X-Forwarded-Proto` (and
ideally `X-Request-ID`, see [Logs](#logs-and-request-ids)).

### 3. Scheduled jobs

The `cron` service runs `cron/crontab` (times in UTC): digests,
dormant-account clean-up, accept reminders and a nightly `backup_site`; the AI
commands are commented out until the AI module is configured. To change the
schedule without rebuilding, mount your own file over `/app/cron/crontab`.
Each run's outcome is exported by `/metrics` (see
[Monitoring](#monitoring-with-prometheus)).

### Updating

```bash
git pull
docker compose up -d --build         # migrate runs again before web and cron restart
# Once, after the update that adds image variants (safe to repeat):
docker compose exec web python manage.py backfill_image_variants --rerender
```

### Moving from the single-service compose file

Earlier versions of `docker-compose.yml` had one `osqa` service that mounted
`settings_local.py` and used a database outside the project. To keep that
setup, either:

- keep your old compose file under another name (`docker compose -f
  docker-compose.old.yml ...`); the image still reads a mounted
  `/app/settings_local.py` when `OSQA_SETTINGS_LOCAL` isn't set; or
- move to the new file: put the values from `settings_local.py` into `.env`,
  and either restore your data into the new `db` service (`backup_site` on the
  old setup, `restore_site` on the new one, see [Backups](#backups-and-restore)),
  or point the services at your existing database with a
  `docker-compose.override.yml` that sets `OSQA_DB_HOST` (and drop `db`
  from `depends_on`).

The image's `osqa` user is now uid/gid 999 (it was assigned automatically
before): if a host directory mounted for uploads isn't writable, `chown -R
999:999` it.

---

## Option C: Kubernetes, Cloud Run and other container platforms

Use the same image. Example manifests are in [`k8s/`](k8s/) (a kustomization):
the web Deployment with probes, its Service, memcached, the migration Job, one
CronJob per scheduled command, PersistentVolumeClaims for uploads and backups,
and the ConfigMap/Secret they read. The database is not included.

```bash
docker build -t registry.example.org/osqa:1.0.0 --build-arg SENTRY_RELEASE=osqa@$(git rev-parse --short=12 HEAD) .
docker push registry.example.org/osqa:1.0.0
editor docs/k8s/configmap.yaml docs/k8s/kustomization.yaml   # APP_URL, hosts, DB host, image
kubectl create namespace osqa
kubectl -n osqa create secret generic osqa-secrets \
    --from-literal=OSQA_SECRET_KEY=... --from-literal=OSQA_DB_PASSWORD=... --from-literal=METRICS_TOKEN=...
kubectl apply -k docs/k8s/
kubectl -n osqa wait --for=condition=complete job/osqa-migrate --timeout=15m
```

Add an Ingress (TLS) for the `osqa` Service. For a new version, push the
image, change `newTag`, delete the finished `osqa-migrate` Job and apply
again (or run the migration from a Helm/Argo CD pre-sync hook).

What changes compared to a server is where state lives:

- **Configuration:** environment variables from the ConfigMap and Secret,
  read by `settings_local_docker.py` (`OSQA_SETTINGS_LOCAL=settings_local_docker`;
  the variables are listed at the top of that file). A variable can also be
  given as `NAME_FILE`, the path of a mounted secret file. Mounting a
  `settings_local.py` at `/app/settings_local.py` still works.
- **Database:** use a managed MySQL/MariaDB or PostgreSQL (Cloud SQL, RDS, Azure Database).
- **Cache:** use a managed or in-cluster **memcached** (Memorystore,
  ElastiCache; `k8s/memcached.yaml`). The file cache doesn't work across
  replicas, and the local-memory cache isn't shared between workers.
- **Uploads:** `/app/forum/upfiles` must be persistent and, with more than one
  replica, shared. Use a ReadWriteMany volume (NFS, Filestore, EFS), or on
  Cloud Run a Cloud Storage volume mount. Container file systems are
  temporary, so without such a volume uploaded images are lost on the next deploy.
- **Logs:** `LOG_FORMAT=json` writes one JSON object per line to standard
  output (see [Logs](#logs-and-request-ids)); the `forum.security` lines stay
  at `INFO`.
- **Health checks:** `GET /healthz` for liveness (process and database) and
  `GET /readyz` for readiness (database and cache). Both answer on any host
  name, also during maintenance, without authentication, with `ok` or a bare
  503.
- **Migrations:** run `python manage.py migrate` as a one-off job
  (`k8s/migrate-job.yaml`, a Helm hook or a Cloud Run job) before each new
  version starts serving.
- **Scheduled jobs:** CronJobs (`k8s/cronjobs.yaml`), or Cloud Scheduler +
  Cloud Run jobs, that run the same image with the commands from
  `cron/crontab`.
- **Proxy count:** the ingress or load balancer is the proxy. Usually
  `OSQA_TRUSTED_PROXIES=1`; count every hop that appends to
  `X-Forwarded-For` (check the platform's documentation, e.g. a Google
  load balancer in front of Cloud Run adds its own entry). The security log's
  `ip=` field shows which address OSQA sees. If it is always the same internal
  address, the count is too low.
- **Resources:** about 3 gunicorn workers per container, with 512 MB to 1 GB of memory.

---

## Monitoring with Prometheus

`/metrics` serves Prometheus metrics in the text format. It is off until
`METRICS_TOKEN` is set (settings_local.py or the environment; a long random
string): without it `/metrics` answers 404, without the header 401, with a
wrong token 403 (logged as `metrics_token_refused` in the security log).

```bash
curl -H "Authorization: Bearer $METRICS_TOKEN" http://127.0.0.1:8000/metrics
```

| Metric | Type | Labels |
|---|---|---|
| `osqa_http_requests_total` | counter | `view` (URL name, `static`, `unmatched`), `method`, `status` (`2xx`...`5xx`) |
| `osqa_http_request_duration_seconds` | histogram | `view` |
| `osqa_users`, `osqa_users_active` | gauge | |
| `osqa_posts` | gauge | `type` (question, answer, comment; not deleted) |
| `osqa_questions_unanswered` | gauge | questions without any answer |
| `osqa_moderation_pending` | gauge | `kind` (`flag`: open user flags, `report`: unresolved automated reports) |
| `osqa_emails_sent_total`, `osqa_emails_failed_total` | counter | |
| `osqa_security_events_total` | counter | `event` (`login_failed`, `login_paused` = a locked-out sign-in, `temp_login_limited`, `permission_denied`, ...) |
| `osqa_cron_last_success_timestamp_seconds`, `osqa_cron_last_failure_timestamp_seconds`, `osqa_cron_last_duration_seconds` | gauge | `command` |
| `osqa_cache_get_hits_total`, `osqa_cache_get_misses_total`, `osqa_cache_evictions_total`, `osqa_cache_items`, `osqa_cache_bytes` | | memcached only |
| `osqa_database_up` | gauge | |

How it works (`forum/utils/metrics.py`):

- **Site-wide totals.** The counters live in the shared cache, so every
  worker and container reports the same totals. Scrape **one** target (the
  Service, the load balancer, or one container), not every pod.
- **Cheap per request.** Requests are counted in memory and added to the cache
  every 5 seconds. Counters restart from zero when memcached restarts;
  `rate()` and `increase()` handle that.
- **Cached database figures.** Database figures are computed at most once a
  minute.
- **Cron runs.** The scheduled commands record their last run in the database
  (`forum/utils/cron.py`; the commands themselves are not changed: a hook on
  Django's `BaseCommand.execute`, enabled from `forum/apps.py`, records the
  commands listed in `CRON_COMMANDS`; by default `send_email_alerts`,
  `remind_unaccepted`, `cleanup_inactive_users`, `build_knowledge_index`,
  `suggest_answers`, `backup_site`, `rebuild_search_index` and
  `refresh_tag_expertise`; `--dry-run`
  runs aren't recorded).

`/metrics` and `/readyz` answer on any host name (Prometheus scrapes pod
addresses) and before the HTTPS redirect, so keep them off the public site in
the reverse proxy:

```nginx
location = /metrics { return 404; }
```

Scrape configuration and example alerts: [`prometheus/prometheus.yml`](prometheus/prometheus.yml)
and [`prometheus/alerts.yml`](prometheus/alerts.yml) (`promtool check rules`
passes). The alerts cover: a scheduled command not completed for 26 hours or
whose last run failed, a 5xx share above 2%, slow pages, email failures,
sign-in attacks, a moderation backlog and the site or database being down.
The core of the scrape job:

```yaml
scrape_configs:
  - job_name: osqa
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/osqa-metrics-token
    static_configs:
      - targets: ['osqa.osqa.svc.cluster.local:80']
```

## Logs and request ids

- **Request ids:** every response carries an `X-Request-ID` header: the
  proxy's own id when it sends one (letters, digits, `.`, `_`, `:`, `-`; at
  most 128 characters), otherwise a new random id. The same id goes into log
  records (`request_id`) and Sentry events (the `request_id` tag). In nginx
  add `proxy_set_header X-Request-ID $request_id;` to `location /`, and
  `$request_id` to its `log_format`, to follow one request from the access
  log to the application log and Sentry.
- **JSON logs:** `LOG_FORMAT = 'json'` in `settings_local.py` (or the
  `LOG_FORMAT` environment variable; the default in containers) replaces
  `LOGGING` with one JSON object per line on standard output, with these
  fields:
  - `time` (UTC);
  - `level`, `logger`, `message`;
  - `request_id`;
  - `user_id` (a number; never a name);
  - `exception` (the traceback, when there is one).

  `LOG_LEVEL` sets the level (default `INFO`).
- **What is masked in JSON logs:** email addresses, IP addresses and
  `password=`/`token=`/`secret=`/`Authorization:`/`sessionid=` values are
  replaced in every logger's message and traceback, except `forum.security`.
  Its lines are the security log and name the IP address, the account and,
  for refused sign-in links, the email address typed (as in the text format).
- **gunicorn's access log** (`--access-logfile -`) stays in gunicorn's own
  format, with client IPs. Leave it out if the proxy logs requests already.
- **Text logs** (the default outside containers) are unchanged:
  `log/django.osqa.log` and `log/security.log`.

## Backups and restore

`manage.py backup_site` writes one archive with everything needed to rebuild
the site, `osqa-backup-YYYYMMDD-HHMMSS.tar.gz`:

- `data.json`: the database contents, as `dumpdata --all` (works with any
  database; content types, permissions, sessions and the admin log are left
  out, as in [upgrading-from-original-osqa.md](upgrading-from-original-osqa.md));
- `upfiles/`: the uploaded files (`UPFILES_FOLDER`);
- `manifest.json`: date, database engine, last applied migration, row counts.

```bash
python manage.py backup_site                       # into BACKUP_DIR (default backups/), keeps BACKUP_KEEP (14)
python manage.py backup_site --output-dir /srv/backups --keep 30
python manage.py backup_site --no-uploads          # database only
docker compose exec cron python manage.py backup_site      # Compose (also nightly from cron/crontab)
```

Archives hold personal data (email addresses, password hashes). They are
written with mode 0600 into a 0700 directory. Copy them off the machine (or
off the volume) regularly. `settings_local.py` / `.env` are not included:
keep them separately, as they hold `SECRET_KEY`. For large forums, the
database's own tool is faster: `mysqldump --single-transaction osqa`
(Compose: `docker compose exec -T db sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction osqa' | gzip > osqa.sql.gz`).

Restoring **replaces all data** in the database the settings point at:

```bash
python manage.py restore_site backups/osqa-backup-20261015-033000.tar.gz --dry-run   # check; changes nothing
python manage.py restore_site backups/osqa-backup-20261015-033000.tar.gz --confirm
```

- **What it does:**
  - checks the archive (no absolute paths, `..` or links);
  - saves the current site as `osqa-pre-restore-*.tar.gz` (unless `--no-safety-backup`);
  - empties the database (`flush`) and loads `data.json`;
  - clears the cache;
  - writes the uploaded files into `UPFILES_FOLDER`. Files not in the archive
    stay; `--no-uploads` skips this step.
- **Code version:** restore with the version of the code the backup was made
  with (the dry run warns when the migrations differ), then update and
  `migrate`.
- **MySQL:** emptying the tables can't be rolled back there, so a failed load
  leaves an empty database: restore the safety backup.
- **Afterwards:** run `manage.py rebuild_search_index` if search results look
  incomplete.
- **Containers:** stop the `web` and `cron` services, or scale the Deployment
  to 0, while restoring, and run the command in a one-off container that
  mounts the uploads and backups volumes, e.g.
  `docker compose run --rm cron python manage.py restore_site /app/backups/... --confirm`.

---

## After installing

1. **Owner account:** open the site and register. The first account becomes the
   site owner (superuser). Do this immediately after the site is reachable.
2. **Admin > Email settings:** SMTP server, sender address, then "test email
   settings". Notifications, sign-in links and digests depend on it.
3. **Admin > Basic settings and look and feel:** site name, description, logo
   and colours; the about, FAQ and privacy page texts.
4. **Admin > Security:** sign-in lockout, posting limits. If you add widgets
   or another analytics tool in the custom `<head>` or footer, list their
   origins under "Extra script sources", or the Content-Security-Policy blocks
   them (Google Analytics needs nothing there: see the next step).
5. **Admin > Users settings:** sign-up protections and dormant-account
   clean-up (defaults are fine for most sites).
6. **Optional:**
   - Admin > External Keys: Google/GitHub/Facebook sign-in (callback URLs in
     the README's "Social login"), Google Analytics 4 measurement ID
     (visitors are asked first; README "Google Analytics").
   - Admin > AI assistance: Gemini key or Vertex AI project.
   - `SENTRY_DSN`.
7. **Check:**
   - `/healthz` and `/readyz` return `ok`.
   - Ask a question, answer it from a second account, and check the
     notification email and its unsubscribe link.
   - Upload an image.
   - With Sentry configured, send a test event and check it arrives:
     `python manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('OSQA test'); sentry_sdk.flush()"`.
     Pages that don't exist (404) are not reported.

Admin pages are at `/admin/`. Django's own model admin is at `/nimda/`, for
superusers.
