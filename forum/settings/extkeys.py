from .base import Setting, SettingSet
from django.utils.translation import gettext_lazy as _

EXT_KEYS_SET = SettingSet('extkeys', _('External Keys'), _("Keys for various external providers that your application may optionally use."), 100)

GOOGLE_SITEMAP_CODE = Setting('GOOGLE_SITEMAP_CODE', '', EXT_KEYS_SET, dict(
label = _("Google sitemap code"),
help_text = _("This is the code you get when you register your site at <a href='https://www.google.com/webmasters/tools/'>Google webmaster central</a>."),
required=False))

GOOGLE_ANALYTICS_KEY = Setting('GOOGLE_ANALYTICS_KEY', '', EXT_KEYS_SET, dict(
label = _("Google Analytics 4 measurement ID"),
help_text = _("The measurement ID of your Google Analytics 4 web stream, starting with G- (Admin > Data streams at <a href='https://analytics.google.com/'>analytics.google.com</a>). Visitors are asked first: Analytics loads only for those who accept. Old Universal Analytics keys (UA-) are ignored."),
required=False))


# No longer used: the header always uses the forum's own search (with
# suggestions). Kept, out of the External Keys page, so databases that have a
# value for it still load.
GOOGLE_CSE_ID = Setting('GOOGLE_CSE_ID', '', None, dict(
label = _("Google custom search engine ID"),
help_text = _("No longer used: the search box in the header always uses the site's own search."),
required=False))
