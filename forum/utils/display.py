"""Display preferences: the colour theme (System / Light / Dark) and the
keyboard shortcuts switch.

Members keep them in user.prop.preferences (the dict the preferences page
saves, keys 'theme' and 'keyboard_shortcuts'); the theme is also kept in the
`osqa_theme` cookie, for anonymous visitors, after signing out and on the
pages a service worker saved; visitors who chose nothing get "Theme for new
visitors" (Admin > Look and feel). The theme only applies while "Dark mode"
(same page) is on; without it every page is light.

How a theme reaches the page: {% display_attrs %} writes data-theme (the
resolved theme, "light" or "dark") and data-theme-choice on <html>, and
{% theme_head %} adds an inline script that resolves "auto" from
prefers-color-scheme before the first paint (forum/templatetags/display_tags.py).
"""
from forum import settings

THEMES = ('auto', 'light', 'dark')
THEME_COOKIE = 'osqa_theme'
COOKIE_AGE = 365 * 24 * 3600


def _member_preferences(request):
    """The member's preferences dict, or None for an anonymous visitor."""
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        return user.prop.preferences or {}
    return None


def theme(request):
    """'auto', 'light' or 'dark': what the visitor chose ('light' while the
    site's dark mode is off)."""
    if not settings.DARK_MODE:
        return 'light'
    if request is None:
        return default_theme()
    preferences = _member_preferences(request)
    if preferences and preferences.get('theme') in THEMES:
        return preferences['theme']
    value = request.COOKIES.get(THEME_COOKIE)
    return value if value in THEMES else default_theme()


def default_theme():
    """What visitors get before they choose (Admin > Look and feel)."""
    value = str(settings.DEFAULT_THEME)
    return value if value in THEMES else 'auto'


def shortcuts_enabled(request):
    """Keyboard shortcuts are on unless the member turned them off."""
    preferences = _member_preferences(request) if request is not None else None
    return not preferences or preferences.get('keyboard_shortcuts', True) is not False


def update_preferences(user, **values):
    """Merges `values` into the member's preferences dict (the other keys,
    such as sticky_sorts, are kept)."""
    preferences = dict(user.prop.preferences or {})
    preferences.update(values)
    user.prop.preferences = preferences


def set_theme_cookie(request, response, value):
    response.set_cookie(THEME_COOKIE, value, max_age=COOKIE_AGE, samesite='Lax', secure=request.is_secure())


def etag_part(request):
    """What anonymous pages' ETags must include (forum/utils/conditional.py)."""
    return 'theme=%s' % theme(request)
