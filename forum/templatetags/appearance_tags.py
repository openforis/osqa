"""Look and feel from the admin (forum/utils/appearance.py).

    {% load appearance_tags %}
    <link href="…/osqa.css" …>{% appearance_style %}

{% appearance_style %} writes the <style> that overrides the skin's CSS
variables (nothing while the settings are the defaults); right after
osqa.css and before Custom CSS. {% appearance_info as info %} gives the
admin page (osqaadmin/guides/appearance.html) the ready-made styles, the colours in
use and the contrast adjustments.
"""
import json

from django import template
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from forum.utils import appearance

register = template.Library()


@register.simple_tag(takes_context=True)
def appearance_style(context):
    css = appearance.css(appearance.current(context.get('request')))
    if not css:
        return ''
    # Not escaped (entities mean nothing inside <style>): only colours parsed
    # as #rrggbb and font stacks and lengths from fixed lists get here.
    return mark_safe('<style id="appearance-style">%s</style>' % css.replace('<', ''))


@register.simple_tag(takes_context=True)
def appearance_info(context):
    values = appearance.current(context.get('request'))
    colours = appearance.palette(values)
    return {
        'styles': [{
            'key': style.key, 'label': style.label, 'description': style.description, 'brand': style.brand,
            'accent': style.accent, 'background': style.background, 'font': style.font, 'width': style.width,
            'theme': style.theme, 'font_stack': appearance.FONTS.get(style.font) or '',
            'page': appearance.page_background(style.brand, style.background),
        } for style in appearance.STYLES],
        'values': values,
        'brand': colours['light'].get('--brand', appearance.DEFAULT_BRAND),
        'accent': colours['light'].get('--accent', appearance.DEFAULT_ACCENT),
        'adjustments': appearance.adjustments(values),
        'fonts_json': json.dumps(dict((k, v or '') for k, v in appearance.FONTS.items())),
        'themes': (('light', _("Light theme")), ('dark', _("Dark theme"))),
        'defaults': {'brand': appearance.DEFAULT_BRAND, 'accent': appearance.DEFAULT_ACCENT},
    }
