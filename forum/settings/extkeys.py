import re

from .base import Setting, SettingSet
from .guides import Section, register, ON, OFF, WARNING
from django.utils.translation import gettext_lazy as _

EXT_KEYS_SET = SettingSet('extkeys', _('External Keys'), _(
    "Keys and IDs from outside services the site can use: sign-in with Google, GitHub or Facebook, spam "
    "protection, AI assistance and statistics. Each service below says whether it is set up, what it does "
    "and how to get its keys; leave a service empty to keep it off."), 100)

GOOGLE_SITEMAP_CODE = Setting('GOOGLE_SITEMAP_CODE', '', EXT_KEYS_SET, dict(
label = _("Google Search Console verification code"),
help_text = _("The content of the HTML tag Google Search Console gives you to prove you own the site, without "
              "the rest of the tag."),
example = 'yN3aBcD4eFgH5iJkL6mNoP7qRsT8uVwX9yZ0aB1cD2e',
keywords = _("sitemap site verification webmaster seo google-site-verification"),
required=False))

GOOGLE_ANALYTICS_KEY = Setting('GOOGLE_ANALYTICS_KEY', '', EXT_KEYS_SET, dict(
label = _("Google Analytics measurement ID"),
help_text = _("The measurement ID of a Google Analytics 4 web data stream. Leave empty for no Analytics."),
example = 'G-ABC123XYZ9',
keywords = _("statistics tracking visitors gtag ga4"),
required=False))


# No longer used: the header always uses the forum's own search (with
# suggestions). Kept, out of the External Keys page, so databases that have a
# value for it still load.
GOOGLE_CSE_ID = Setting('GOOGLE_CSE_ID', '', None, dict(
label = _("Google custom search engine ID"),
help_text = _("No longer used: the search box in the header always uses the site's own search."),
required=False))


MEASUREMENT_ID = re.compile(r'^G-[A-Z0-9]{4,}$')


def analytics_status(values):
    key = str(values.get('GOOGLE_ANALYTICS_KEY') or '').strip()
    if not key:
        return OFF, ''
    if key.upper().startswith('UA-'):
        return WARNING, _("UA- IDs belong to Universal Analytics, which stopped collecting data in 2023. Create a "
                          "Google Analytics 4 property and enter its measurement ID, which starts with G-.")
    if not MEASUREMENT_ID.match(key):
        return WARNING, _("This doesn't look like a measurement ID, which starts with G- (for example G-ABC123XYZ9).")
    return ON, _("Every public page loads Google Analytics.")


def verification_status(values):
    code = str(values.get('GOOGLE_SITEMAP_CODE') or '').strip()
    if not code:
        return OFF, ''
    if '<' in code or '=' in code or ' ' in code:
        return WARNING, _("Enter only the value of content=\"...\" from the tag, not the whole tag.")
    return ON, _("Pages carry the google-site-verification tag. Submit {app_url}/sitemap.xml in Search Console.")


register('extkeys', Section(
    'search-console', _("Google Search Console"), ('GOOGLE_SITEMAP_CODE',),
    summary=_("Proves to Google that you own the site, so you can see how it does in Google Search and submit "
              "its sitemap."),
    steps=(
        _("Open <a href=\"https://search.google.com/search-console\">Google Search Console</a> and add a "
          "<strong>URL prefix</strong> property for <code>{app_url}</code>."),
        _("Choose the <strong>HTML tag</strong> verification method. Google shows a tag like "
          "<code>&lt;meta name=\"google-site-verification\" content=\"<strong>yN3aBcD4…</strong>\" /&gt;</code>."),
        _("Copy only the <code>content</code> value into the field below, save, then press <strong>Verify</strong> "
          "in Search Console."),
        _("Under <strong>Sitemaps</strong>, submit the site's sitemap address."),
    ),
    copy=((_("Sitemap"), '{app_url}/sitemap.xml'),),
    keywords=_("seo sitemap google webmaster verification"),
    status=verification_status, weight=41))

register('extkeys', Section(
    'analytics', _("Google Analytics"), ('GOOGLE_ANALYTICS_KEY',),
    summary=_("Counts visits and shows where visitors come from. Analytics sets cookies, which may need visitors' "
              "consent where you operate."),
    steps=(
        _("In <a href=\"https://analytics.google.com/\">Google Analytics</a>, go to <strong>Admin &gt; Data "
          "streams</strong> and add a <strong>Web</strong> stream for <code>{app_url}</code> (or open the one "
          "you have)."),
        _("Copy its <strong>Measurement ID</strong>, which starts with <code>G-</code>, into the field below "
          "and save."),
        _("Open the site in another browser tab and check that the visit appears in the <strong>Realtime</strong> "
          "report."),
    ),
    keywords=_("statistics tracking gtag ga4 visitors"),
    status=analytics_status, weight=40))


# Sentry error reporting set from the admin (forum/utils/sentry.py). SENTRY_DSN
# on the server (settings_local.py or the environment) wins and also catches
# errors while the site starts; these are used without it.
def _validate_dsn(value):
    from django.core.exceptions import ValidationError
    from forum.utils.sentry import valid_dsn
    if str(value or '').strip() and not valid_dsn(str(value).strip()):
        raise ValidationError(_("Enter the DSN as Sentry shows it: https://<key>@<host>/<project number>."))


ERROR_REPORTING_DSN = Setting('ERROR_REPORTING_DSN', '', EXT_KEYS_SET, dict(
label = _("Sentry DSN"),
help_text = _("The DSN of a Sentry project, from Sentry's <strong>Settings &gt; Projects &gt; Client Keys "
              "(DSN)</strong>."),
example = 'https://0123456789abcdef0123456789abcdef@o123456.ingest.de.sentry.io/4507654321',
keywords = _("sentry errors crashes monitoring bugs exceptions logging"),
validators = [_validate_dsn],
required=False))

ERROR_REPORTING_BROWSER = Setting('ERROR_REPORTING_BROWSER', True, EXT_KEYS_SET, dict(
label = _("Also report errors in visitors' browsers"),
help_text = _("JavaScript errors on the pages, at most 10 an hour from each visitor. The DSN is then visible in "
              "the pages' source, as Sentry intends; set a rate limit on the key in Sentry."),
keywords = _("sentry javascript browser frontend"),
required=False))

ERROR_REPORTING_ENVIRONMENT = Setting('ERROR_REPORTING_ENVIRONMENT', 'production', EXT_KEYS_SET, dict(
label = _("Sentry environment"),
help_text = _("Shown with each error in Sentry, to tell this site from a test copy, e.g. production or staging."),
keywords = _("sentry environment staging production"),
required=False))


def sentry_status(values):
    from forum.utils import sentry
    if sentry.server_configured():
        return ON, _("Reporting with the DSN set on the server (SENTRY_DSN), which also catches errors while the site "
                     "starts. The fields below are not used while it is set.")
    dsn = str(values.get('ERROR_REPORTING_DSN') or '').strip()
    if not dsn:
        return OFF, ''
    if not sentry.sdk_installed():
        return WARNING, _("The sentry-sdk package is not installed on the server: pip install -r requirements.txt.")
    if not sentry.valid_dsn(dsn):
        return WARNING, _("This doesn't look like a DSN, which looks like https://<key>@<host>/<project number>.")
    return ON, _("Errors are reported from now on: each server process starts reporting on its next request. Errors "
                 "from before, and while the site starts or can't reach its database, are only reported with "
                 "SENTRY_DSN set on the server.")


register('extkeys', Section(
    'sentry', _("Sentry error reporting"), ('ERROR_REPORTING_DSN', 'ERROR_REPORTING_BROWSER',
                                             'ERROR_REPORTING_ENVIRONMENT'),
    summary=_("Sends the details of every error on the site (on the server, and optionally in visitors' browsers) "
              "to Sentry, which groups them and emails you, so you hear about problems before members report them. "
              "Passwords, cookies, email and IP addresses are never sent; members are identified by their number "
              "only."),
    steps=(
        _("Create a free account on <a href=\"https://sentry.io/signup/\">sentry.io</a> (or use your own Sentry "
          "server) and create a project of type <strong>Django</strong>."),
        _("Copy its DSN from <strong>Settings &gt; Projects &gt; (your project) &gt; Client Keys (DSN)</strong> into "
          "the field below and save."),
        _("Press <strong>Send a test error</strong>: the test should appear under <strong>Issues</strong> in Sentry "
          "within a minute."),
        _("For complete reporting, also set <code>SENTRY_DSN</code> on the server (environment variable or "
          "settings_local.py) and restart it: only then are errors while the site starts reported too. It "
          "replaces the value here."),
    ),
    actions=((_("Send a test error"), 'admin_sentry_test'),),
    links=(("https://docs.sentry.io/platforms/python/integrations/django/", _("Sentry for Django")),),
    keywords=_("sentry errors crashes monitoring exceptions"),
    status=sentry_status, weight=50))
