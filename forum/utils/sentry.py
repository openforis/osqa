"""Sentry error reporting.

The DSN comes from the server or from the admin:
- SENTRY_DSN / SENTRY_FRONTEND_DSN (settings_local.py or the environment):
  init_server() is called from settings.py at start, so errors while the site
  starts are reported too. They win over the admin's.
- Without them, Admin > External Keys (ERROR_REPORTING_DSN, _BROWSER,
  _ENVIRONMENT in forum/settings/extkeys.py): each process starts the client
  with ensure_admin_client(), from SentryUserMiddleware on each request and
  before the scheduled commands (forum/utils/cron.py), and restarts or stops it
  when the value changes (within the settings' few seconds of caching).

For the browser: the configuration the page passes to media/js/osqa.sentry.js,
and the origin the Content-Security-Policy must let it send reports to.

One visitor (a signed-in user, or an IP address) sends at most
SENTRY_MAX_EVENTS_PER_VISITOR events an hour, from the server and from their
browser each, so a page failing in a loop can't flood Sentry.
"""
import contextvars
from urllib.parse import urlsplit

from django.conf import settings as djsettings


def init_server(dsn, environment='', release='', traces_sample_rate=0.0, **options):
    """Returns False if sentry-sdk is not installed."""
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import ignore_logger
    except ImportError:
        return False
    sentry_sdk.init(
        dsn=dsn, environment=environment or None, release=release or None,
        traces_sample_rate=traces_sample_rate,
        # No cookies, request bodies, IP addresses or user details;
        # SentryUserMiddleware adds the user's numeric id. That is the SDK's
        # default when neither send_default_pii (deprecated in sentry-sdk
        # 2.7x, so not passed) nor data_collection is given.
        max_request_body_size='never',
        before_send=before_send, **options)
    # Requests for other host names (scanners) are not errors of the forum.
    ignore_logger('django.security.DisallowedHost')
    # The 500 handler's own log entry (with the user and request headers, for
    # the log file) repeats the error Sentry already captured.
    ignore_logger('forum.errors')
    # Security log lines carry IP addresses and usernames; they stay in the log file.
    ignore_logger('forum.security')
    return True


# Who the current request is for: 'user:<id>' or 'ip:<address>' (set by
# SentryUserMiddleware; never sent to Sentry, only used for the limit).
_visitor = contextvars.ContextVar('osqa_sentry_visitor', default=None)


def max_events_per_visitor():
    return int(getattr(djsettings, 'SENTRY_MAX_EVENTS_PER_VISITOR', 10))


def visitor_key(request):
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        return 'user:%s' % user.id
    return 'ip:%s' % request.META.get('REMOTE_ADDR', '')


def set_visitor(request):
    return _visitor.set(visitor_key(request))


def reset_visitor(token):
    _visitor.reset(token)


def before_send(event, hint):
    """Drops the event when this request's visitor already sent the hourly
    maximum. Events from outside a request (commands, cron) are not limited.
    Events from a request carry its id (X-Request-ID) as the request_id tag."""
    from forum.utils.logs import current_request_id
    request_id = current_request_id()
    if request_id:
        tags = event.get('tags')
        if not isinstance(tags, dict):
            tags = event['tags'] = dict(tags or {})
        tags['request_id'] = request_id
    visitor, limit = _visitor.get(), max_events_per_visitor()
    if visitor is None or limit <= 0:
        return event
    try:
        from forum.utils import throttle
        if throttle.hit('sentry-events', visitor, 3600) > limit:
            return None
    except Exception:  # the cache being down must not lose the report
        pass
    return event


def sdk_installed():
    try:
        import sentry_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def valid_dsn(dsn):
    """https://<key>@<host>/<project>, as Sentry shows it."""
    parts = urlsplit(str(dsn or '').strip())
    return bool(dsn_origin(dsn) and parts.username and parts.path.strip('/'))


def server_configured():
    """A DSN set on the server, which wins over the admin's."""
    return bool(getattr(djsettings, 'SENTRY_DSN', '') or getattr(djsettings, 'SENTRY_FRONTEND_DSN', ''))


def admin_config():
    """{'dsn', 'browser', 'environment'} from Admin > External Keys, or None
    when no valid DSN is set there (or the settings can't be read)."""
    try:
        from forum import settings
        dsn = str(settings.ERROR_REPORTING_DSN.value or '').strip()
        if not valid_dsn(dsn):
            return None
        return {'dsn': dsn, 'browser': bool(settings.ERROR_REPORTING_BROWSER.value),
                'environment': str(settings.ERROR_REPORTING_ENVIRONMENT.value or '').strip() or 'production'}
    except Exception:  # no database yet (migrate) or it is down
        return None


_release = {}


def release():
    """SENTRY_RELEASE, or osqa@<git commit> as settings.py works it out."""
    if getattr(djsettings, 'SENTRY_RELEASE', ''):
        return djsettings.SENTRY_RELEASE
    if 'value' not in _release:
        import os
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            _release['value'] = 'osqa@' + subprocess.run(
                ['git', 'rev-parse', '--short=12', 'HEAD'], cwd=root,
                capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        except Exception:
            _release['value'] = ''
    return _release['value']


# The admin DSN this process's client was started with ('' for none).
_admin_client = {'dsn': ''}


def ensure_admin_client(**options):
    """Starts, restarts or stops this process's client to match the admin's
    DSN; nothing while the server sets one. `options` are for init_server()
    (tests pass a transport)."""
    if server_configured():
        return
    config = admin_config()
    dsn = config['dsn'] if config else ''
    if dsn == _admin_client['dsn']:
        return
    if dsn:
        if not init_server(dsn, config['environment'], release(),
                           float(getattr(djsettings, 'SENTRY_TRACES_SAMPLE_RATE', 0) or 0), **options):
            return
    else:
        import sentry_sdk
        sentry_sdk.init()  # a disabled client
    _admin_client['dsn'] = dsn


def server_reporting():
    """Errors on the server are sent to Sentry (from either source)."""
    return bool(getattr(djsettings, 'SENTRY_DSN', '') or _admin_client['dsn'])


def frontend_dsn():
    if server_configured():
        return str(getattr(djsettings, 'SENTRY_FRONTEND_DSN', '') or '').strip()
    config = admin_config()
    return config['dsn'] if config and config['browser'] else ''


def environment():
    if server_configured():
        return getattr(djsettings, 'SENTRY_ENVIRONMENT', '')
    config = admin_config()
    return config['environment'] if config else ''


def dsn_origin(dsn):
    """'https://key@o1.ingest.sentry.io/2' -> 'https://o1.ingest.sentry.io'."""
    parts = urlsplit(dsn)
    if not parts.scheme or not parts.hostname:
        return ''
    port = ':%d' % parts.port if parts.port else ''
    return '%s://%s%s' % (parts.scheme, parts.hostname, port)


def browser_config(request):
    dsn = frontend_dsn()
    if not dsn_origin(dsn):
        return None
    user = getattr(request, 'user', None)
    return {
        'dsn': dsn,
        'environment': environment(),
        'release': release() or None,
        'user': str(user.id) if user is not None and user.is_authenticated else None,
        'maxEvents': max_events_per_visitor(),
    }


def capture_csp_violation(directive, blocked, page):
    """Content blocked by the Content-Security-Policy, as a Sentry warning
    (grouped by directive and blocked address)."""
    if not server_reporting():
        return
    import sentry_sdk
    with sentry_sdk.new_scope() as scope:
        scope.fingerprint = ['csp', directive, blocked]
        scope.set_tag('csp.directive', directive)
        scope.set_context('csp', {'blocked': blocked, 'page': page})
        sentry_sdk.capture_message('CSP blocked %s (%s)' % (blocked or 'inline code', directive), level='warning')
