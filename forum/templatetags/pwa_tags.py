from django import template
from django.urls import reverse
from django.utils.html import format_html

from forum import settings
from forum.templatetags.extra_tags import media
from forum.utils import appearance, display
from forum.views import pwa

register = template.Library()

# The theme-color metas' media for each theme choice (forum/utils/display.py).
THEME_COLOR_MEDIA = {
    'auto': ('(prefers-color-scheme: light)', '(prefers-color-scheme: dark)'),
    'light': ('all', 'not all'),
    'dark': ('not all', 'all'),
}


@register.simple_tag(takes_context=True)
def pwa_head(context):
    """Manifest, theme colours, touch icon and the script that registers the
    service worker (it is told who is signed in, to empty the saved pages
    when that changes)."""
    user = context.get('user')
    user_id = user.pk if user is not None and user.is_authenticated else ''
    if settings.DARK_MODE:
        # Light first, then dark: the theme script (display_tags) switches their media.
        light, dark = THEME_COLOR_MEDIA[display.theme(context.get('request'))]
        theme = format_html(
            '<meta name="theme-color" content="{}" media="{}" />\n        '
            '<meta name="theme-color" content="{}" media="{}" />',
            appearance.theme_color(context.get('request')), light, pwa.THEME_COLOR_DARK, dark)
    else:
        theme = format_html('<meta name="theme-color" content="{}" />', appearance.theme_color(context.get('request')))
    return format_html(
        '{}\n        <link rel="manifest" href="{}" />\n        <link rel="apple-touch-icon" href="{}" />\n        '
        '<script defer src="{}" data-user="{}"></script>',
        theme, reverse('manifest'), pwa.touch_icon_url(), media('/media/js/osqa.pwa.js'), user_id)
