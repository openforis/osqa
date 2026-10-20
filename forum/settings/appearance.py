from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

from .base import Setting, SettingSet

# Applied by forum/utils/appearance.py ({% appearance_style %} on every public
# page); the admin page adds presets and a live preview
# (osqaadmin/guides/appearance.html).
APPEARANCE_SET = SettingSet('appearance', _('Look and feel'), _(
    "Colours, font and page width of the public pages, and the colour theme visitors get. Pick a preset or your "
    "own colours, check them in the sample, then press Preview to see the whole site with them before you save. "
    "For anything else, use Custom CSS."), 2, can_preview=True)

COLOR = RegexValidator(r'^#[0-9a-fA-F]{6}$', _("Enter a colour as # and six hexadecimal digits, e.g. #2c5aa0."))

THEME_BRAND_COLOR = Setting('THEME_BRAND_COLOR', '#2c5aa0', APPEARANCE_SET, dict(
label = _("Brand colour"),
help_text = _("Links, buttons, the selected tab and highlights. If it is too light for white text or for links, "
              "the site uses a darker shade of it; dark mode gets a lighter one for links."),
widget=forms.TextInput(attrs={'type': 'color', 'class': 'color-input'}),
validators=[COLOR],
keywords = _("color colour theme brand primary links buttons palette"),
example = '#2c5aa0'))

THEME_ACCENT_COLOR = Setting('THEME_ACCENT_COLOR', '#c2410c', APPEARANCE_SET, dict(
label = _("Accent colour"),
help_text = _("The \"Ask a question\" button and other calls to action. It always has white text, so it is "
              "darkened if needed."),
widget=forms.TextInput(attrs={'type': 'color', 'class': 'color-input'}),
validators=[COLOR],
keywords = _("color colour theme secondary ask button palette"),
example = '#c2410c'))

THEME_BACKGROUND = Setting('THEME_BACKGROUND', 'default', APPEARANCE_SET, dict(
label = _("Page background"),
help_text = _("Behind the content boxes, in the light theme."),
widget=forms.Select(choices=(
    ('default', _("Light grey")),
    ('white', _("White")),
    ('tinted', _("A tint of the brand colour")),
)),
keywords = _("color colour background"),
required=False))

THEME_FONT = Setting('THEME_FONT', 'system', APPEARANCE_SET, dict(
label = _("Font"),
help_text = _("Fonts that come with visitors' devices, so nothing is downloaded; each device uses the first "
              "one of the family it has."),
widget=forms.Select(choices=(
    ('system', _("System (each device's interface font)")),
    ('humanist', _("Humanist sans-serif (Calibri, Ubuntu, Gill Sans…)")),
    ('geometric', _("Geometric sans-serif (Avenir, Montserrat, Corbel…)")),
    ('rounded', _("Rounded (SF Rounded, Quicksand, Comfortaa…)")),
    ('serif', _("Serif (Charter, Cambria, Georgia…)")),
)),
keywords = _("typeface typography font family text"),
required=False))

THEME_PAGE_WIDTH = Setting('THEME_PAGE_WIDTH', 'standard', APPEARANCE_SET, dict(
label = _("Page width"),
help_text = _("The widest the content gets on large screens. Phones always use their whole width."),
widget=forms.Select(choices=(
    ('narrow', _("Narrow (960 px)")),
    ('standard', _("Standard (1140 px)")),
    ('wide', _("Wide (1320 px)")),
    ('full', _("Full width of the window")),
)),
keywords = _("layout width wide narrow container"),
required=False))

DARK_MODE = Setting('DARK_MODE', True, APPEARANCE_SET, dict(
label = _("Dark mode"),
help_text = _("Use a dark colour scheme for visitors who choose it or whose device is set to dark mode. Turn it "
              "off if your custom CSS assumes a light background."),
keywords = _("theme dark night colour scheme"),
required=False))

DEFAULT_THEME = Setting('DEFAULT_THEME', 'auto', APPEARANCE_SET, dict(
label = _("Theme for new visitors"),
help_text = _("What visitors get until they choose a theme with the theme switch. Only applies while dark mode "
              "is on."),
widget=forms.Select(choices=(
    ('auto', _("System: follow the device's setting")),
    ('light', _("Light")),
    ('dark', _("Dark")),
)),
keywords = _("theme dark light default colour scheme"),
required=False))
