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
