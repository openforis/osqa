import os.path
import sys
import warnings

# Third-party deprecation warnings we can't fix (our own code runs clean with
# -W error::DeprecationWarning; see README "Upgrading Django"). Remove each
# filter once the package is updated.
# google-genai 2.31 uses typing._UnionGenericAlias, deprecated in Python 3.14.
warnings.filterwarnings('ignore', message="'_UnionGenericAlias' is deprecated",
                        category=DeprecationWarning, module=r'google\.genai\.')

SITE_ID = 1

# Set SECRET_KEY in settings_local.py or the OSQA_SECRET_KEY environment variable.
SECRET_KEY = os.environ.get('OSQA_SECRET_KEY', '')

CACHE_MAX_KEY_LENGTH = 235

# Django 4.2: MIDDLEWARE_CLASSES → MIDDLEWARE
# Note: SessionMiddleware must come before CsrfViewMiddleware when using CSRF_USE_SESSIONS
MIDDLEWARE = [
    # Request id (X-Request-ID) for logs, responses and Sentry; request metrics.
    'forum.middleware.ops.RequestContextMiddleware',
    'forum.middleware.security.ClientIPMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'forum.middleware.security.SecurityHeadersMiddleware',
    # Skin media, admin media and uploads: answered here, before sessions and users.
    'forum.middleware.static_files.StaticFilesMiddleware',
    'forum.middleware.django_cookies.CookiePreHandlerMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Interface language: the visitor's choice (language switcher) or browser.
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'forum.middleware.extended_user.ExtendedUser',
    # Server-Timing header (db, render, total) with DEBUG, or for staff when SERVER_TIMING is set.
    'forum.middleware.server_timing.ServerTimingMiddleware',
    'forum.middleware.anon_user.ConnectToSessionMessagesMiddleware',
    'forum.middleware.request_utils.RequestUtils',
    'forum.middleware.cancel.CancelActionMiddleware',
    'forum.middleware.admin_messages.AdminMessagesMiddleware',
    'forum.middleware.custom_pages.CustomPagesFallbackMiddleware',
    # Note: django.middleware.transaction.TransactionMiddleware removed (deprecated in Django 1.6, removed in 1.8)
    'forum.middleware.django_cookies.CookiePostHandlerMiddleware',
]

# Django 4.2: Required setting
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

ROOT_URLCONF = 'urls'
APPEND_SLASH = True


FILE_UPLOAD_TEMP_DIR = os.path.join(os.path.dirname(__file__), 'tmp').replace('\\','/')
FILE_UPLOAD_HANDLERS = ("django.core.files.uploadhandler.MemoryFileUploadHandler",
 "django.core.files.uploadhandler.TemporaryFileUploadHandler",)
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# Skin media is served by OSQA itself (/m/...). STATIC_URL is used by Django's
# own admin (/nimda/); OSQA serves those files too (/m/static/admin/...), so
# no collectstatic or web server configuration is needed.
STATIC_URL = '/m/static/'

# OSQA stores naive local datetimes; Django 5.0 changed the default to True.
USE_TZ = False

ALLOW_FILE_TYPES = ('.jpg', '.jpeg', '.gif', '.bmp', '.png', '.tiff')
ALLOW_MAX_FILE_SIZE = 1024 * 1024

# Django 4.2: CSRF token configuration
# Use session-based CSRF tokens to avoid cookie length compatibility issues
# between Django 1.6 (32 chars) and Django 4.2 (64 chars)
CSRF_USE_SESSIONS = True
CSRF_COOKIE_HTTPONLY = False  # Allow JavaScript access if needed

MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# User settings. OSQA_SETTINGS_LOCAL selects a different module, e.g. the test
# suite runs with OSQA_SETTINGS_LOCAL=settings_local_test.
import importlib
_settings_local = importlib.import_module(os.environ.get('OSQA_SETTINGS_LOCAL', 'settings_local'))
globals().update(dict((k, v) for k, v in vars(_settings_local).items() if not k.startswith('_')))

# Cache: the model layer caches objects and query results, so the cache must be
# shared by all worker processes (file or memcached, not the per-process
# default). Settings files written for old OSQA versions set CACHE_BACKEND,
# which Django ignores since 1.3; translate it.
if 'CACHES' not in globals():
    _cache_backend = globals().get('CACHE_BACKEND', 'file://' + os.path.join(os.path.dirname(__file__), 'cache'))
    _scheme, _, _location = _cache_backend.partition('://')
    _location = _location.rstrip('/')
    if _scheme == 'dummy':
        CACHES = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}
    elif _scheme == 'locmem':
        CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
    elif _scheme == 'memcached':
        CACHES = {'default': {'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
                              'LOCATION': _location.split(';')}}
    elif _scheme == 'file':
        CACHES = {'default': {'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
                              'LOCATION': _location, 'OPTIONS': {'MAX_ENTRIES': 10000}}}
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured("Unsupported CACHE_BACKEND %r; define CACHES in settings_local.py" % _cache_backend)

if not SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "SECRET_KEY is not set. Add SECRET_KEY = '...' to settings_local.py or set OSQA_SECRET_KEY; generate one with: "
        "python -c 'from django.core.management.utils import get_random_secret_key as k; print(k())'")

# The file upload dialog reads its result from a hidden same-origin iframe.
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Django 4.2: TEMPLATES configuration
template_loaders = [
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
    'forum.modules.template_loader.module_templates_loader',
    'forum.skins.load_template_source',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(os.path.dirname(__file__), 'forum', 'skins').replace('\\', '/'),
        ],
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.template.context_processors.csrf',
                'django.template.context_processors.i18n',
                'forum.context.application_settings',
                'forum.context.csp_nonce',
                'django.contrib.messages.context_processors.messages',
                'forum.user_messages.context_processors.user_messages',
                'django.contrib.auth.context_processors.auth',
            ],
            'loaders': template_loaders if DEBUG else [
                ('django.template.loaders.cached.Loader', template_loaders)
            ],
        },
    },
]

try:
    if len(FORUM_SCRIPT_ALIAS) > 0:
        APP_URL = '%s/%s' % (APP_URL, FORUM_SCRIPT_ALIAS[:-1])
except NameError:
    pass

app_url_split = APP_URL.split("://")

APP_PROTOCOL = app_url_split[0]
APP_DOMAIN = app_url_split[1].split('/')[0]
APP_BASE_URL = '%s://%s' % (APP_PROTOCOL, APP_DOMAIN)

# Interface languages offered (the language switcher in the footer, or the
# browser's Accept-Language). LANGUAGE_CODE in settings_local.py is the
# default; it must be one of these. URLs are the same in every language.
globals().setdefault('LANGUAGES', [
    ('en', 'English'),
    ('es', 'Español'),
    ('fr', 'Français'),
    ('pt', 'Português'),
])
LOCALE_PATHS = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'forum', 'locale')]

# Security defaults; any of them can be set differently in settings_local.py.
# Passwords follow NIST SP 800-63B (forum/utils/passwords.py): a minimum length
# from the PASSWORD_MIN_LENGTH site setting (at least 8), at most 128
# characters, no composition rules, screened against common passwords, the
# member's own username/email and (site setting PASSWORD_BREACH_CHECK) the
# Have I Been Pwned list of breached passwords.
globals().setdefault('AUTH_PASSWORD_VALIDATORS', [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'forum.utils.passwords.MinimumLengthValidator'},
    {'NAME': 'forum.utils.passwords.MaximumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'forum.utils.passwords.BreachedPasswordValidator'},
])
# Sessions: "Keep me signed in" on the sign-in page keeps the session for
# SESSION_COOKIE_AGE (two weeks); otherwise it ends when the browser closes.
# The cookie is HttpOnly and SameSite=Lax (Django's defaults), Secure on HTTPS.
globals().setdefault('SESSION_COOKIE_AGE', 14 * 24 * 3600)
globals().setdefault('SESSION_COOKIE_HTTPONLY', True)
globals().setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
# New passwords use PBKDF2; the last two only read hashes from the original
# OSQA (salted SHA1 and MD5) and are replaced by PBKDF2 at the next sign-in.
globals().setdefault('PASSWORD_HASHERS', [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
    'forum.utils.hashers.LegacySHA1PasswordHasher',
    'django.contrib.auth.hashers.MD5PasswordHasher',
])
# Number of reverse proxies in front of OSQA (nginx, a load balancer): the
# visitor's IP is then read from X-Forwarded-For and HTTPS from X-Forwarded-Proto.
# Leave it 0 when OSQA is reached directly, or visitors could fake their IP.
TRUSTED_PROXY_COUNT = int(globals().get('TRUSTED_PROXY_COUNT', os.environ.get('OSQA_TRUSTED_PROXIES', 0)))
if TRUSTED_PROXY_COUNT:
    globals().setdefault('SECURE_PROXY_SSL_HEADER', ('HTTP_X_FORWARDED_PROTO', 'https'))
if APP_PROTOCOL == 'https':
    globals().setdefault('SESSION_COOKIE_SECURE', True)
    globals().setdefault('CSRF_COOKIE_SECURE', True)
    globals().setdefault('CSRF_TRUSTED_ORIGINS', [APP_BASE_URL])
    # Sent only on HTTPS responses; tells browsers to use HTTPS for a year.
    globals().setdefault('SECURE_HSTS_SECONDS', 31536000)
    # Redirecting needs to know which requests are HTTPS: directly, or from the proxy header.
    globals().setdefault('SECURE_SSL_REDIRECT', bool(globals().get('SECURE_PROXY_SSL_HEADER')))

# Sentry error reporting (https://docs.sentry.io). SENTRY_DSN reports server
# errors; SENTRY_FRONTEND_DSN reports JavaScript errors in visitors' browsers
# (defaults to SENTRY_DSN; set it to 'off' to turn browser reporting off). Each
# can also come from the environment variable of the same name. Without them,
# a DSN can be set under Admin > External Keys (forum/utils/sentry.py), which
# misses errors while the site starts. Request bodies,
# cookies, IP addresses and emails are never sent; signed-in users are
# identified by their numeric id only.
def _setting(name, default=''):
    return globals()[name] if name in globals() else (os.environ.get(name) or default)

SENTRY_DSN = _setting('SENTRY_DSN')
SENTRY_FRONTEND_DSN = _setting('SENTRY_FRONTEND_DSN', SENTRY_DSN)
if SENTRY_FRONTEND_DSN == 'off':
    SENTRY_FRONTEND_DSN = ''
SENTRY_ENVIRONMENT = _setting('SENTRY_ENVIRONMENT', 'production')
# Share of requests traced for performance (0 to 1); 0 sends errors only.
SENTRY_TRACES_SAMPLE_RATE = float(_setting('SENTRY_TRACES_SAMPLE_RATE', 0) or 0)
SENTRY_RELEASE = _setting('SENTRY_RELEASE')
# Events one visitor (signed-in user or IP address) may send per hour, from the
# server and from their browser each; more are dropped. 0 means no limit.
SENTRY_MAX_EVENTS_PER_VISITOR = int(_setting('SENTRY_MAX_EVENTS_PER_VISITOR', 10) or 0)
if not SENTRY_RELEASE and (SENTRY_DSN or SENTRY_FRONTEND_DSN):
    try:
        import subprocess
        SENTRY_RELEASE = 'osqa@' + subprocess.run(
            ['git', 'rev-parse', '--short=12', 'HEAD'], cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except Exception:
        SENTRY_RELEASE = ''
if SENTRY_DSN:
    from forum.utils.sentry import init_server
    if not init_server(SENTRY_DSN, SENTRY_ENVIRONMENT, SENTRY_RELEASE, SENTRY_TRACES_SAMPLE_RATE):
        print('SENTRY_DSN is set but sentry-sdk is not installed: pip install -r requirements.txt', file=sys.stderr)
# Also without SENTRY_DSN: a DSN set under Admin > External Keys is started by
# this middleware, in each process, on its first request.
try:
    import sentry_sdk  # noqa: F401
except ImportError:
    pass
else:
    MIDDLEWARE.insert(MIDDLEWARE.index('forum.middleware.extended_user.ExtendedUser') + 1,
                      'forum.middleware.sentry.SentryUserMiddleware')

# Prometheus metrics at /metrics (forum/utils/metrics.py): set a long random
# token to switch them on; Prometheus sends it as "Authorization: Bearer <token>".
# Without a token /metrics answers 404.
METRICS_TOKEN = _setting('METRICS_TOKEN')

# Server-Timing header on the responses to staff members (db time and query
# count, template rendering, total; forum/middleware/server_timing.py): set to
# 'staff' (or any value) to profile pages in the browser's developer tools.
# With DEBUG on every response has it.
SERVER_TIMING = _setting('SERVER_TIMING')

# LOG_FORMAT = 'json' (or the environment variable): one JSON object per line
# on standard output instead of the LOGGING above, for containers; see
# forum/utils/logs.py. LOG_LEVEL sets the root level of that configuration.
LOG_FORMAT = str(_setting('LOG_FORMAT', 'text')).lower()
if LOG_FORMAT == 'json':
    from forum.utils.logs import json_logging
    LOGGING = json_logging(str(_setting('LOG_LEVEL', 'INFO')).upper())

FORCE_SCRIPT_NAME = ''

for path in app_url_split[1].split('/')[1:]:
    FORCE_SCRIPT_NAME = FORCE_SCRIPT_NAME + '/' + path

if FORCE_SCRIPT_NAME.endswith('/'):
    FORCE_SCRIPT_NAME = FORCE_SCRIPT_NAME[:-1]

#Module system initialization
MODULES_PACKAGE = 'forum_modules'
MODULES_FOLDER = os.path.join(SITE_SRC_ROOT, MODULES_PACKAGE)

# Python 3: filter() returns iterator, convert to list
MODULE_LIST = list(filter(lambda m: getattr(m, 'CAN_USE', True), [
        __import__('forum_modules.%s' % f, globals(), locals(), ['forum_modules'])
        for f in os.listdir(MODULES_FOLDER)
        if os.path.isdir(os.path.join(MODULES_FOLDER, f)) and
           os.path.exists(os.path.join(MODULES_FOLDER, "%s/__init__.py" % f)) and
           f not in DISABLED_MODULES
]))

# Django 4.2: MIDDLEWARE_CLASSES → MIDDLEWARE
[MIDDLEWARE.extend(
        ["%s.%s" % (m.__name__, mc) for mc in getattr(m, 'MIDDLEWARE_CLASSES', [])]
                          ) for m in MODULE_LIST]

# Add module template loaders to TEMPLATES
[TEMPLATES[0]['OPTIONS']['loaders'].extend(
        ["%s.%s" % (m.__name__, tl) for tl in getattr(m, 'TEMPLATE_LOADERS', [])]
                          ) if isinstance(TEMPLATES[0]['OPTIONS']['loaders'], list) else None for m in MODULE_LIST]


INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.admin',
    'django.contrib.humanize',
    'django.contrib.sitemaps',
    'django.contrib.messages',
    'forum',
]

if DEBUG:
    try:
        import debug_toolbar  # noqa: F401
        # Django 4.2: MIDDLEWARE_CLASSES → MIDDLEWARE
        MIDDLEWARE.append('debug_toolbar.middleware.DebugToolbarMiddleware')
        INSTALLED_APPS.append('debug_toolbar')
    except:
        pass

# Django 4.2: South removed - using Django's built-in migrations
# South was for Django < 1.7, Django 4.2 has native migrations

# Try loading Gunicorn web server
try:
    import gunicorn  # noqa: F401
    INSTALLED_APPS.append('gunicorn')
except ImportError:
    pass

if not DEBUG:
    try:
        import rosetta  # noqa: F401
        INSTALLED_APPS.append('rosetta')
    except:
        pass

AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend',]
