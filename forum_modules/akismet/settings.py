from django.utils.translation import gettext_lazy as _

from forum.settings.base import Setting
from forum.settings.extkeys import EXT_KEYS_SET
from forum.settings.forms import SecretInput
from forum.settings.guides import Section, register, keys_status
from forum.settings.minrep import MIN_REP_SET

WORDPRESS_API_KEY = Setting('WORDPRESS_API_KEY', '', EXT_KEYS_SET, dict(
label = _("Akismet API key"),
help_text = _("Your Akismet API key (it used to be called the WordPress API key)."),
widget=SecretInput(),
keywords = _("spam filter wordpress"),
required=False))

REP_FOR_NO_SPAM_CHECK = Setting('REP_FOR_NO_SPAM_CHECK', 750, MIN_REP_SET, dict(
label = _("Minimum reputation to not have your posts checked"),
help_text = _("The minimum reputation a user must have so that when they post a question, answer or comment it is not checked for spam.")))


register('extkeys', Section(
    'akismet', _("Akismet spam filter"), ('WORDPRESS_API_KEY',),
    summary=_("Sends new questions, answers and comments of members with little reputation to Akismet, which "
              "refuses the ones it knows as spam. If Akismet can't be reached, posts are accepted."),
    steps=(
        _("Get a key on <a href=\"https://akismet.com/pricing/\">akismet.com</a>: the free personal plan is for "
          "non-commercial sites, other sites need a paid plan."),
        _("Find the key under <strong>Account &gt; API keys</strong> (or in the welcome email), paste it below "
          "and save."),
        _("Choose who is checked with \"Minimum reputation to not have your posts checked\" in the minimum "
          "reputation settings; staff are never checked."),
    ),
    links=(("https://akismet.com/developers/", _("Akismet developer documentation")),),
    keywords=_("spam filter wordpress"),
    status=lambda values: keys_status(values, ('WORDPRESS_API_KEY',), '',
                                      _("Posts of members below the reputation threshold are checked.")), weight=21))
