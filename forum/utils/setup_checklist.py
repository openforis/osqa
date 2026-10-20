"""The "Getting started" list on the admin dashboard (superusers): the few
settings a new site needs, each done or not, with a link to where it is set.
Hidden for good with the list's button (SETUP_CHECKLIST_HIDDEN) and not shown
once everything is done."""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from forum import settings


def _value(name):
    setting = getattr(settings, name, None)
    return '' if setting is None else setting.value


def _changed(name):
    setting = getattr(settings, name, None)
    return setting is not None and setting.value != setting.default


def _filled(*names):
    return any(str(_value(name) or '').strip() for name in names)


def _url(set_name, anchor=''):
    return reverse('admin_set', args=[set_name]) + (anchor and '#' + anchor)


def items():
    """[{'key', 'title', 'hint', 'done', 'optional', 'url'}] in the order to do them."""
    return [
        dict(key='name', title=_("Name the site"), done=_changed('APP_TITLE') or _changed('APP_SHORT_NAME'),
             hint=_("Its title and short name appear in the header, the browser tab and emails."),
             url=_url('basic', 'setting-APP_TITLE')),
        dict(key='email', title=_("Set up sending email"), done=_filled('EMAIL_HOST'),
             hint=_("Sign-up confirmations, password resets and notifications need it. Test it from the same page."),
             url=_url('email', 'setting-EMAIL_HOST')),
        dict(key='logo', title=_("Upload your logo"), done=_changed('APP_LOGO') or _changed('APP_FAVICON'),
             hint=_("And the small icon browsers show in tabs."), url=_url('basic', 'setting-APP_LOGO')),
        dict(key='look', title=_("Choose the colours"),
             done=any(_changed(n) for n in ('THEME_BRAND_COLOR', 'THEME_ACCENT_COLOR', 'THEME_FONT',
                                            'THEME_PAGE_WIDTH', 'THEME_BACKGROUND')) or bool(_value('USE_CUSTOM_CSS')),
             hint=_("Pick a preset or your own colours under Look and feel."), url=_url('appearance')),
        dict(key='about', title=_("Write the About page"), done=_changed('ABOUT_PAGE_TEXT'),
             hint=_("Say what the site is for and who answers."), url=_url('about')),
        dict(key='spam', title=_("Turn on spam protection"),
             done=_filled('RECAPTCHA_PUB_KEY', 'WORDPRESS_API_KEY', 'GEMINI_API_KEY', 'AI_VERTEX_PROJECT')
             or str(_value('FIRST_POSTS_MODERATION') or 'off') != 'off',
             hint=_("reCAPTCHA, Akismet or AI review under External Keys, or reviewing new members' first posts "
                    "under Moderation settings."), url=_url('extkeys')),
        dict(key='signin', title=_("Let members sign in with Google, GitHub or Facebook"), optional=True,
             done=_filled('GOOGLE_CLIENT_ID', 'GITHUB_CLIENT_ID', 'FACEBOOK_APP_ID'),
             hint=_("Optional: fewer passwords to remember, and confirmed email addresses."),
             url=_url('extkeys', 'section-google-signin')),
    ]


def checklist():
    """None when hidden or finished, else {'items', 'done', 'total'}."""
    if settings.SETUP_CHECKLIST_HIDDEN:
        return None
    entries = items()
    for entry in entries:
        entry.setdefault('optional', False)
    required = [e for e in entries if not e['optional']]
    if all(e['done'] for e in required):
        return None
    return {'items': entries, 'done': sum(1 for e in required if e['done']), 'total': len(required)}
