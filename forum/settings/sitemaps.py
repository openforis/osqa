from .base import Setting, SettingSet
from django.utils.translation import gettext_lazy as _

SITEMAP_SET = SettingSet('sitemap', _('Sitemap'), _("The sitemap search engines read to find the questions."), 2000)

QUESTIONS_SITEMAP_LIMIT = Setting('QUESTIONS_SITEMAP_LIMIT', 2500, SITEMAP_SET, dict(
label = _("Questions Sitemap Limit"),
help_text = _("The questions limit per page for the Questions Sitemap.")))

QUESTIONS_SITEMAP_CHANGEFREQ = Setting('QUESTIONS_SITEMAP_CHANGEFREQ', 'daily', SITEMAP_SET, dict(
label = _("Questions Sitemap Change Fraquence"),
help_text = _("Used in the Questions Sitemap <changefreq> tag and specifies the content change frequency.")))
