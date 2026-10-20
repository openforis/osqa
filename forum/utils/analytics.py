"""Google Analytics 4, loaded only after the visitor accepts.

The banner ({% analytics_consent %}, display/analytics_consent.html) asks
every visitor; media/js/osqa.analytics.js remembers the answer in the
first-party cookie COOKIE and fetches gtag.js only after "Accept", so a
visitor who declines or never answers sends nothing to Google. The policy
of security.py allows Google's origins only while a measurement ID is set.
"""
import re

from forum import settings

COOKIE = 'osqa_analytics'

# Google's documented sources for GA4 behind a Content-Security-Policy
# (regional collection servers included).
SCRIPT_SOURCES = 'https://www.googletagmanager.com'
CONNECT_SOURCES = 'https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com'

_MEASUREMENT_ID = re.compile(r'G-[A-Z0-9]{4,20}')


def measurement_id():
    """The GA4 measurement ID ("G-…"), or '' when none is set. Old Universal
    Analytics ("UA-…") keys no longer collect anything and give ''."""
    value = str(settings.GOOGLE_ANALYTICS_KEY or '').strip().upper()
    return value if _MEASUREMENT_ID.fullmatch(value) else ''
