"""Guidance on the admin's settings pages (osqaadmin/set.html).

A settings page can be split into sections, each with a status ("set up",
"partly set up", "not set up", "check this"), what it is for, step-by-step
instructions, an example and links. Settings of the page that no section
lists are shown last, as before. Sections also feed the admin search
(forum/utils/admin_search.py) with their titles and keywords.

    from forum.settings.guides import Section, register

    register('extkeys', Section(
        'recaptcha', _("reCAPTCHA"), ('RECAPTCHA_PUB_KEY', 'RECAPTCHA_PRIV_KEY'),
        summary=_("Asks new members to prove they are human."),
        steps=(_("Open the reCAPTCHA admin console..."), ...),
        links=(("https://www.google.com/recaptcha/admin", _("reCAPTCHA admin console")),),
        status=lambda values: ...))

Steps and summaries are HTML (translated texts written here, never user
input); "{app_url}" in them and in `copy` values is replaced by the site's
address. A page can also have a free-form guide template,
osqaadmin/guides/<set name>.html, shown above its form (modules may ship
their own in their templates folder).

Extra keys a Setting's field_context may carry for the form (they are not
passed to the form field): `example` (shown under the help text) and
`keywords` (found by the admin search only).
"""

# Keys of Setting.field_context that are guidance, not form field arguments.
FIELD_EXTRAS = ('example', 'keywords')

# Status values a section's status function returns, with (state, message).
ON, PARTIAL, OFF, WARNING = 'on', 'partial', 'off', 'warning'

SECTIONS = {}


class Section:
    def __init__(self, key, title, settings, summary='', steps=(), copy=(), links=(),
                 keywords='', status=None, extra=None, weight=100):
        self.key = key
        self.title = title
        self.settings = tuple(settings)
        self.summary = summary
        self.steps = tuple(steps)
        # (label, value) pairs shown with a copy button, e.g. a redirect URI.
        self.copy = tuple(copy)
        self.links = tuple(links)
        self.keywords = keywords
        # values (a dict of setting name -> current value) -> (state, message) or None.
        self.status = status
        # request -> HTML shown after the section's settings (e.g. a test button), or None.
        self.extra = extra
        # Lower comes first on the page.
        self.weight = weight

    def __repr__(self):
        return '<Section %s>' % self.key


def register(set_name, section):
    """Adds (or replaces, by key) a section of a settings page."""
    sections = SECTIONS.setdefault(set_name, [])
    sections[:] = [s for s in sections if s.key != section.key] + [section]
    return section


def sections_for(set_name):
    return sorted(SECTIONS.get(set_name, ()), key=lambda s: s.weight)


def configured(*values):
    """How many of `values` are filled in (non-blank)."""
    return sum(1 for v in values if str(v or '').strip())


def keys_status(values, names, partial_message, on_message=''):
    """The usual status of a provider that needs every one of `names`: on,
    partial (some filled in) or off."""
    filled = configured(*[values.get(n) for n in names])
    if filled == len(names):
        return ON, on_message
    if filled:
        return PARTIAL, partial_message
    return OFF, ''
