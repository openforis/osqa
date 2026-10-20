from django.utils.translation import gettext_lazy as _

from forum.settings import EXT_KEYS_SET
from forum.settings.base import Setting
from forum.settings.forms import SecretInput
from forum.settings.guides import Section, register, keys_status, WARNING

RECAPTCHA_PUB_KEY = Setting('RECAPTCHA_PUB_KEY', '', EXT_KEYS_SET, dict(
label = _("reCAPTCHA site key"),
help_text = _("The public key of a reCAPTCHA v2 \"I'm not a robot\" checkbox key pair."),
example = '6LcAbCdEAAAAAFgHiJkLmNoPqRsTuVwXyZ0123456',
keywords = _("captcha robot spam bot google"),
required=False))

RECAPTCHA_PRIV_KEY = Setting('RECAPTCHA_PRIV_KEY', '', EXT_KEYS_SET, dict(
label = _("reCAPTCHA secret key"),
help_text = _("The secret key of the same pair. Keep it secret."),
widget=SecretInput(),
keywords = _("captcha robot spam bot google password"),
required=False))


def recaptcha_status(values):
    state = keys_status(values, ('RECAPTCHA_PUB_KEY', 'RECAPTCHA_PRIV_KEY'),
                        _("Fill in both keys: with only one the check fails for everybody."),
                        _("New members and members with little reputation tick \"I'm not a robot\" when they "
                          "post."))
    site_key = str(values.get('RECAPTCHA_PUB_KEY') or '').strip()
    if site_key and site_key == str(values.get('RECAPTCHA_PRIV_KEY') or '').strip():
        return WARNING, _("The site key and the secret key are the same; the secret key is the second one Google "
                          "shows.")
    return state


register('extkeys', Section(
    'recaptcha', _("reCAPTCHA"), ('RECAPTCHA_PUB_KEY', 'RECAPTCHA_PRIV_KEY'),
    summary=_("Stops spam bots: posting asks members with little reputation to prove they are human."),
    steps=(
        _("Open the <a href=\"https://www.google.com/recaptcha/admin/create\">reCAPTCHA admin console</a> and "
          "register a new site."),
        _("Choose <strong>Challenge (v2)</strong> and <strong>\"I'm not a robot\" Checkbox</strong>; v3 and "
          "invisible keys don't work here."),
        _("Add your site's domain (the host name of <code>{app_url}</code>, without https://), and "
          "<code>localhost</code> if you also test on your own computer."),
        _("Copy the <strong>site key</strong> and the <strong>secret key</strong> into the fields below and save."),
    ),
    links=(("https://developers.google.com/recaptcha/docs/display", _("Google: reCAPTCHA v2 checkbox")),),
    keywords=_("captcha robot spam bot"),
    status=recaptcha_status, weight=20))
