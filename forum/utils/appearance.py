"""Look and feel from the admin (Admin > Look and feel, forum/settings/appearance.py).

The default skin takes its colours, font and page width from CSS variables
(osqa.css section 2, and "Dark mode" for the dark ones). css() turns the
settings into overrides of those variables, which {% appearance_style %}
(forum/templatetags/appearance_tags.py) puts in a <style> right after
osqa.css, so Custom CSS still wins. Nothing is written while every setting
has its default.

Colours stay readable whatever is picked (WCAG 2.2 AA, 4.5:1 for text): the
brand colour is darkened, keeping its hue, until links on the page
background and white button text are readable, the accent colour until
white text is; dark mode gets a lighter brand colour for links and a darker
one for buttons, worked out the same way. adjustments() says what was
changed, for the admin page.
"""
import colorsys
import functools
import re

from django.utils.translation import gettext_lazy as _

from forum import settings

DEFAULT_BRAND = '#2c5aa0'
DEFAULT_ACCENT = '#c2410c'
WHITE = '#ffffff'
BLACK = '#000000'
# osqa.css --surface / --background, light and dark.
LIGHT_SURFACE, LIGHT_BACKGROUND = WHITE, '#f5f7fa'
DARK_SURFACE, DARK_BACKGROUND = '#161b22', '#0d1117'
TEXT_RATIO = 4.5

HEX = re.compile(r'^#?([0-9a-fA-F]{6})$')

class Style:
    """A ready-made style: values for the Look and feel fields (filled in
    by the admin page; saved like any other value) and, while THEME_STYLE
    names it, a few rules of its own (`css`: corners, header, headings),
    written after the colour variables. `css` is fixed text written here,
    drawn with the skin's variables so dark mode follows."""
    def __init__(self, key, label, description, brand, accent, background='default', font='system',
                 width='standard', theme=None, css=''):
        self.key, self.label, self.description = key, label, description
        self.brand, self.accent, self.background, self.font, self.width = brand, accent, background, font, width
        # The theme for new visitors it suggests (None: leave the setting alone).
        self.theme = theme
        self.css = css


SQUARE = ('input[type="submit"],input[type="button"],button,.submit,a.button,.button,input[type="text"],'
          'input[type="search"],input[type="email"],input[type="password"],textarea,select{border-radius:2px}')
ROUND = ('input[type="submit"],input[type="button"],button,.submit,a.button,.button{border-radius:999px}'
         '.post-tag,.tags a{border-radius:999px}')
BRAND_STRIPE = '#roof{box-shadow:inset 0 4px 0 var(--brand)}'
SERIF_HEADINGS = ("h1,h2,h3,.question-hyperlink,#question-title{font-family:Charter,'Bitstream Charter',"
                  "'Sitka Text',Cambria,Georgia,serif}")

# The styles offered on the admin page, in this order. Every one passes the
# contrast checks unchanged (forum/tests/test_admin_guidance.py).
STYLES = (
    Style('classic', _('Classic'), _("The skin as it comes: blue links and buttons, an orange Ask button."),
          DEFAULT_BRAND, DEFAULT_ACCENT),
    # Open Foris: the palette of the Open Foris Support site (its logo and its
    # #996666 links, scripts/dev/create_openforis_demo_data.py), a brand
    # stripe on the header and a rounded logo.
    Style('openforis', _('Open Foris'), _("Muted red-brown from the Open Foris Support site, with a teal accent "
                                          "and a brand stripe on the header."),
          '#8f5a5a', '#17798f', background='tinted', font='humanist',
          css=BRAND_STRIPE + ':root{--info-border:#e6d5d5;--border-strong:#d9c6c6}'
              ':root[data-theme="dark"]{--info-border:#553a3a;--border-strong:#5e4a4a}'
              '#logo img{border-radius:6px}'),
    Style('forest', _('Forest'), _("Deep green and amber on a green-tinted page, in a friendly sans-serif."),
          '#2d6a3e', '#b45309', background='tinted', font='humanist', css=BRAND_STRIPE),
    Style('ocean', _('Ocean'), _("Teal and orange on white, in a geometric sans-serif."),
          '#0f6e78', '#c2410c', background='white', font='geometric'),
    Style('editorial', _('Editorial'), _("Ink and red on white, serif text, a narrow column and square corners: "
                                         "reads like a newspaper."),
          '#1f3a5f', '#b91c1c', background='white', font='serif', width='narrow', css=SQUARE + SERIF_HEADINGS),
    Style('plum', _('Plum'), _("Purple and pink with a rounded font and pill-shaped buttons and tags."),
          '#6b3fa0', '#be185d', font='rounded', css=ROUND + ':root{--radius:14px}'),
    Style('midnight', _('Midnight'), _("Navy and green; new visitors get the dark theme."),
          '#1e3a8a', '#047857', font='geometric', theme='dark', css=BRAND_STRIPE),
    Style('minimal', _('Minimal'), _("Greys only, white page, no shadows and square corners: the content comes "
                                     "first."),
          '#374151', '#111827', background='white', width='wide',
          css=SQUARE + ':root{--shadow:none;--radius:2px}'),
    Style('crimson', _('Crimson'), _("A university look: crimson with a blue accent and serif headings."),
          '#a61e2e', '#1d4ed8', background='white', css=SERIF_HEADINGS + BRAND_STRIPE),
    Style('earth', _('Earth'), _("Clay brown and teal on a warm tinted page, with rounded buttons."),
          '#8f5a3c', '#17798f', background='tinted', font='humanist', css=ROUND),
)
STYLES_BY_KEY = dict((style.key, style) for style in STYLES)

# Font stacks of fonts that come with the visitor's system (nothing is downloaded).
FONTS = {
    'system': None,  # osqa.css --font
    'humanist': "Seravek, 'Gill Sans Nova', Ubuntu, Calibri, 'DejaVu Sans', source-sans-pro, sans-serif",
    'geometric': "Avenir, Montserrat, Corbel, 'URW Gothic', source-sans-pro, sans-serif",
    'rounded': "ui-rounded, 'Hiragino Maru Gothic ProN', Quicksand, Comfortaa, Manjari, 'Arial Rounded MT', "
               "'Arial Rounded MT Bold', Calibri, source-sans-pro, sans-serif",
    'serif': "Charter, 'Bitstream Charter', 'Sitka Text', Cambria, Georgia, serif",
}

WIDTHS = {'narrow': '960px', 'standard': None, 'wide': '1320px', 'full': '100%'}

BACKGROUNDS = ('default', 'white', 'tinted')


# ---- Colour arithmetic ------------------------------------------------------

def parse(value):
    """'#rrggbb' (lower case) or None."""
    match = HEX.match(str(value or '').strip())
    return '#' + match.group(1).lower() if match else None


def rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def to_hex(channels):
    return '#' + ''.join('%02x' % max(0, min(255, int(round(c)))) for c in channels)


def luminance(color):
    def linear(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a, b, share):
    """`a` with `share` (0..1) of `b` mixed in."""
    return to_hex(x + (y - x) * share for x, y in zip(rgb(a), rgb(b)))


def with_lightness(color, lightness):
    h, _l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in rgb(color)))
    return to_hex(c * 255 for c in colorsys.hls_to_rgb(h, max(0.0, min(1.0, lightness)), s))


def lightness(color):
    return colorsys.rgb_to_hls(*(c / 255.0 for c in rgb(color)))[1]


def readable(color, against, ratio=TEXT_RATIO, lighter=False):
    """`color` with its lightness moved (down, or up when `lighter`) until it
    has `ratio` contrast with every colour in `against`; hue kept."""
    def ok(c):
        return all(contrast(c, other) >= ratio for other in against)
    if ok(color):
        return color
    start = lightness(color)
    for step in range(1, 101):
        candidate = with_lightness(color, start + step / 100.0 if lighter else start - step / 100.0)
        if ok(candidate):
            return candidate
    return WHITE if lighter else BLACK


# ---- Settings to CSS --------------------------------------------------------

def current(request=None):
    """The look and feel settings, with the values the administrator is
    previewing (Preview on the admin page) for them."""
    from forum.templatetags.extra_filters import or_preview
    value = (lambda s: or_preview(s, request)) if request is not None else (lambda s: s.value)
    return {
        'brand': parse(value(settings.THEME_BRAND_COLOR)) or DEFAULT_BRAND,
        'accent': parse(value(settings.THEME_ACCENT_COLOR)) or DEFAULT_ACCENT,
        'background': str(value(settings.THEME_BACKGROUND)),
        'font': str(value(settings.THEME_FONT)),
        'width': str(value(settings.THEME_PAGE_WIDTH)),
        'style': str(value(settings.THEME_STYLE)),
    }


def palette(values):
    """{'light': {variable: colour}, 'dark': {...}} for the colours that
    differ from the skin's own."""
    return _palette(values['brand'], values['accent'], values['background'])


@functools.lru_cache(maxsize=32)
def _palette(brand, accent, background):
    light, dark = {}, {}
    if brand != DEFAULT_BRAND:
        page_brand = readable(brand, (LIGHT_SURFACE, LIGHT_BACKGROUND))
        light.update({
            '--brand': page_brand,
            '--brand-dark': with_lightness(page_brand, lightness(page_brand) - 0.1),
            '--brand-soft': mix(brand, WHITE, 0.9),
            '--info-border': mix(brand, WHITE, 0.78),
        })
        dark_link = readable(brand, (DARK_SURFACE, DARK_BACKGROUND), lighter=True)
        button = readable(brand, (WHITE,))
        dark.update({
            '--brand': dark_link,
            '--brand-dark': readable(with_lightness(dark_link, lightness(dark_link) + 0.1),
                                     (DARK_SURFACE, DARK_BACKGROUND), lighter=True),
            '--brand-soft': mix(brand, DARK_BACKGROUND, 0.8),
            '--info-border': mix(brand, DARK_BACKGROUND, 0.55),
            '--button-bg': button,
            '--button-bg-hover': with_lightness(button, lightness(button) - 0.06),
        })
    if accent != DEFAULT_ACCENT:
        button = readable(accent, (WHITE,))
        light.update({
            '--accent': button,
            '--accent-dark': with_lightness(button, lightness(button) - 0.08),
            '--accent-soft': mix(accent, WHITE, 0.92),
        })
        dark.update({
            '--accent': button,
            '--accent-dark': with_lightness(button, lightness(button) - 0.06),
            '--accent-soft': mix(accent, DARK_BACKGROUND, 0.8),
        })
    if background != 'default':
        light['--background'] = page_background(brand, background)
    return {'light': light, 'dark': dark}


def page_background(brand, background):
    """The light theme's page background for THEME_BACKGROUND."""
    if background == 'white':
        return WHITE
    if background == 'tinted':
        return mix(brand, WHITE, 0.955)
    return LIGHT_BACKGROUND


def css(values):
    """The CSS that applies `values`, or '' when they are the defaults."""
    colours = palette(values)
    root = dict(colours['light'])
    if FONTS.get(values['font']):
        root['--font'] = FONTS[values['font']]
    if WIDTHS.get(values['width']):
        root['--content-width'] = WIDTHS[values['width']]
    rules = []
    style = STYLES_BY_KEY.get(values.get('style'))
    if root:
        rules.append(':root{%s}' % ''.join('%s:%s;' % item for item in root.items()))
    if colours['dark']:
        rules.append(':root[data-theme="dark"]{%s}' % ''.join('%s:%s;' % item for item in colours['dark'].items()))
    if style is not None and style.css:
        rules.append(style.css)
    return '\n'.join(rules)


def adjustments(values):
    """[(what, picked, used)] where a picked colour was changed for contrast."""
    changes = []
    colours = palette(values)
    if values['brand'] != DEFAULT_BRAND and colours['light']['--brand'] != values['brand']:
        changes.append(('brand', values['brand'], colours['light']['--brand']))
    if values['accent'] != DEFAULT_ACCENT and colours['light']['--accent'] != values['accent']:
        changes.append(('accent', values['accent'], colours['light']['--accent']))
    return changes


def theme_color(request=None):
    """The light theme-color of the browser's interface (pwa_tags)."""
    return palette(current(request))['light'].get('--brand', DEFAULT_BRAND)
