from forum.settings.base import Setting, SettingSet
from django.forms.widgets import Textarea
from django.utils.translation import gettext_lazy as _
from forum.settings import APP_URL

ROBOTS_SET = SettingSet('robots', _('robots.txt'), _("What the robots.txt file tells search engines and other crawlers."), 3000)

ROBOTS_FILE = Setting('ROBOTS_FILE',
"""Sitemap: %s/sitemap.xml

User-Agent: *
Disallow: /accounts/
Disallow: /users/
Disallow: /revisions/
Disallow: /search
Disallow: /matching_tags
Disallow: /*sort=
""" % APP_URL, ROBOTS_SET, dict(
label = "Robots.txt file",
help_text = """
The robots.txt file search engine spiders will see.
""",
widget=Textarea(attrs={'rows': '20'})))
