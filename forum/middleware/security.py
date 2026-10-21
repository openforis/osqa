"""Request and response handling for running safely behind a proxy.

ClientIPMiddleware (first in MIDDLEWARE): behind a reverse proxy REMOTE_ADDR is
the proxy; with TRUSTED_PROXY_COUNT = n it is replaced by the address the
n-th proxy from the right saw in X-Forwarded-For, so sign-up limits, sign-in
lockouts, action IPs and the maintenance allow-list see the real visitor.
It also answers /healthz (liveness), /readyz (database and cache, see
forum/views/ops.py) and /metrics (Prometheus, token-protected) before host
checks, sessions and maintenance mode, so Docker, Kubernetes, a load balancer
or Prometheus can reach them on any host name or pod address.

SecurityHeadersMiddleware adds Content-Security-Policy and Permissions-Policy.
Scripts run only from this site, the listed origins, or an inline <script>
carrying the response's nonce: before the view runs, the middleware puts a new
random nonce in request.csp_nonce (the `csp_nonce` template variable, from
forum.context.csp_nonce), templates write <script nonce="{{ csp_nonce }}">,
and the header names the same nonce. Script injected into a post or profile
has no nonce, and inline event handlers (onclick=...) and javascript: URLs
never run, so templates attach behaviour from JavaScript files instead.
Styles still allow 'unsafe-inline' (style="" attributes are everywhere).

A 304 Not Modified response has no Content-Type, so it gets no policy and the
browser keeps the one stored with its copy of the page, whose nonce matches.
Responses cached as a whole (cache_page) must not contain inline scripts.
"""
import secrets

from django.conf import settings as djsettings
from django.db import connection
from django.http import HttpResponse
from django.urls import reverse

# reCAPTCHA (forum_modules/recaptcha) loads from these.
GOOGLE = 'https://www.google.com https://www.gstatic.com'
# Google Analytics 4 (gtag.js): the script, and where it sends hits.
ANALYTICS = ('https://www.googletagmanager.com https://*.google-analytics.com '
             'https://*.analytics.google.com')

PERMISSIONS_POLICY = 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()'


class ClientIPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        proxies = int(getattr(djsettings, 'TRUSTED_PROXY_COUNT', 0))
        if proxies:
            forwarded = [ip.strip() for ip in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if ip.strip()]
            if forwarded:
                request.META['REMOTE_ADDR'] = forwarded[-min(proxies, len(forwarded))]
        # Probes may be configured with a trailing slash (AWS load balancers, for one).
        path = request.path_info.rstrip('/')
        if path == '/healthz':
            return health(request)
        if path in ('/readyz', '/metrics'):
            from forum.views.ops import ENDPOINTS
            return ENDPOINTS[path](request)
        return self.get_response(request)


def health(request):
    """200 'ok' when the database answers, 503 otherwise."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        return HttpResponse('database unavailable\n', status=503, content_type='text/plain')
    return HttpResponse('ok\n', content_type='text/plain')


def new_nonce():
    return secrets.token_urlsafe(18)


def content_security_policy(request, nonce=None):
    """The policy for this response. A CONTENT_SECURITY_POLICY string in the
    Django settings replaces it; '{nonce}' in it is replaced by the nonce."""
    from forum import settings
    nonce = nonce or getattr(request, 'csp_nonce', None) or new_nonce()
    configured = getattr(djsettings, 'CONTENT_SECURITY_POLICY', '')
    if configured is None:
        return None
    if configured:
        return configured.replace('{nonce}', nonce)
    from forum.utils.sentry import frontend_dsn, dsn_origin
    extra = ' '.join(str(settings.CSP_EXTRA_SOURCES).split())
    with_extra = lambda sources: ('%s %s' % (sources, extra)).strip()
    sentry = dsn_origin(frontend_dsn())  # where browser errors are reported
    policy = [
        "default-src 'self'",
        # No 'unsafe-inline': inline scripts need the nonce. No 'strict-dynamic'
        # either, so scripts that scripts add (reCAPTCHA's, Analytics) are
        # allowed by origin, as Google documents for reCAPTCHA without nonces.
        "script-src " + with_extra("'self' 'nonce-%s' %s %s" % (nonce, GOOGLE, ANALYTICS)),
        "style-src " + with_extra("'self' 'unsafe-inline' %s https://fonts.googleapis.com" % GOOGLE),
        "font-src " + with_extra("'self' data: https://fonts.gstatic.com"),
        "connect-src " + with_extra(("'self' %s %s %s" % (GOOGLE, ANALYTICS, sentry)).strip()),
        "frame-src " + with_extra("'self' %s" % GOOGLE),
        # Posts may show images from anywhere.
        "worker-src 'self'",  # the service worker (/sw.js)
        "manifest-src 'self'",
        "img-src * data: blob:",
        "media-src *",
        "object-src 'none'",
        "base-uri 'self'",
        # Forms post only here (sign-in with Google/GitHub/Facebook starts from
        # links, not forms, so the redirect to the provider is not affected).
        "form-action " + with_extra("'self'"),
        "frame-ancestors 'self'",
        "report-uri " + reverse('csp_report'),
    ]
    if request.is_secure():
        policy.append('upgrade-insecure-requests')
    return '; '.join(policy)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = new_nonce()
        response = self.get_response(request)
        if response.get('Content-Type', '').startswith('text/html'):
            policy = content_security_policy(request, request.csp_nonce)
            if policy:
                header = 'Content-Security-Policy-Report-Only' if \
                    getattr(djsettings, 'CONTENT_SECURITY_POLICY_REPORT_ONLY', False) else 'Content-Security-Policy'
                response.headers.setdefault(header, policy)
        response.headers.setdefault('Permissions-Policy', PERMISSIONS_POLICY)
        return response
