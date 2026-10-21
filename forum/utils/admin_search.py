"""The admin search (admin.search, /admin/search/?q=, the search box at the
top of the admin menu): finds settings by their label, help text, name,
keywords (forum/settings/guides.py) and the title of their page and section,
and admin pages (the menu's items) by name.

Every word of the query must match the start of a word (ignoring case and
accents, with a few synonyms such as colour/color); a match in the label counts most, then the
name, the page or section title and keywords, then the help text.
"""
import functools
import re
import unicodedata

from django.urls import reverse
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from forum.settings import guides
from forum.settings.base import Setting

MAX_RESULTS = 60

# Words people search for -> other words that mean the same here.
SYNONYMS = {
    'color': ('colour',), 'colour': ('color',), 'colors': ('colours',), 'colours': ('colors',),
    'login': ('sign-in', 'sign in', 'signin'), 'signin': ('sign-in', 'sign in'), 'logon': ('sign-in', 'sign in'),
    'logout': ('sign out',), 'oauth': ('sign-in',), 'captcha': ('recaptcha',),
    'theme': ('look and feel', 'dark mode', 'colour'), 'css': ('style',), 'style': ('css',),
    'mail': ('email', 'e-mail'), 'email': ('e-mail', 'mail'), 'smtp': ('email',),
    'key': ('keys',), 'apikey': ('api key',), 'token': ('tokens', 'api'),
    'rep': ('reputation',), 'karma': ('reputation',), 'points': ('reputation',),
    'font': ('typeface',), 'width': ('wide',),
}

WEIGHTS = (('label', 6), ('name', 4), ('section', 3), ('keywords', 3), ('page', 2), ('help', 1))


def normalize(text):
    text = unicodedata.normalize('NFKD', str(text or ''))
    return ''.join(c for c in text if not unicodedata.combining(c)).casefold()


def terms(query):
    return [t for t in re.split(r'\s+', normalize(query).strip()) if t][:10]


def variants(term):
    return (term,) + SYNONYMS.get(term, ()) + SYNONYMS.get(term.rstrip('s'), ())


def setting_entries():
    for setting_set in sorted(Setting.sets.values(), key=lambda s: s.weight):
        url = reverse('admin_set', args=[setting_set.name])
        section_of = {}
        for section in guides.sections_for(setting_set.name):
            for name in section.settings:
                section_of.setdefault(name, section)
        for setting in setting_set:
            context = setting.field_context
            section = section_of.get(setting.name)
            help_text = ' '.join(strip_tags(str(context.get('help_text') or '')).split())
            yield {
                'kind': 'setting',
                'label': str(context.get('label') or setting.name),
                'name': setting.name,
                'page': str(setting_set.title),
                'section': str(section.title) if section else '',
                'keywords': ' '.join(str(k) for k in (context.get('keywords'), section and section.keywords) if k),
                'help': help_text,
                'url': '%s#setting-%s' % (url, setting.name),
            }


def page_entries(menu):
    """The admin menu's pages (admin.admin_menu()), the settings pages among them."""
    yield {'kind': 'page', 'label': _("Dashboard"), 'name': '', 'page': '', 'section': '',
           'keywords': 'home community health statistics', 'help': '', 'url': reverse('admin_index')}
    for group in menu:
        for item in group['items']:
            yield {'kind': 'page', 'label': str(item['label']), 'name': '', 'page': str(group['title']),
                   'section': '', 'keywords': '', 'help': '', 'url': item['url']}


@functools.lru_cache(maxsize=256)
def _word_start(text):
    """`text` at the start of a word: "logo" finds "logos", not "catalogue"."""
    return re.compile(r'(?<![0-9a-z])' + re.escape(text))


def score(entry, words):
    fields = dict((field, normalize(entry[field])) for field, _weight in WEIGHTS)
    total = 0
    for word in words:
        best = 0
        patterns = [_word_start(v) for v in variants(word)]
        for field, weight in WEIGHTS:
            if any(p.search(fields[field]) for p in patterns):
                best = max(best, weight)
        if not best:
            return 0
        total += best
    label = fields['label']
    phrase = ' '.join(words)
    if label == phrase or entry['name'].casefold() == phrase.replace(' ', '_'):
        total += 20
    elif label.startswith(phrase):
        total += 5
    if entry['kind'] == 'page':
        total += 2
    return total


def search(query, menu):
    """[(score, entry)] best first, where entry has kind ('setting' or
    'page'), label, name, page, section, help and url."""
    words = terms(query)
    if not words:
        return []
    found = []
    for order, entry in enumerate(list(page_entries(menu)) + list(setting_entries())):
        points = score(entry, words)
        if points:
            found.append((-points, order, entry))
    found.sort(key=lambda f: (f[0], f[1]))
    # Pages listed twice (the menu and a settings page's own entry) once.
    seen, results = set(), []
    for _points, _order, entry in found:
        key = (entry['kind'], entry['url'])
        if key not in seen:
            seen.add(key)
            results.append(entry)
    return results[:MAX_RESULTS]


def mark(text, query):
    """`text` escaped, with the query's words wrapped in <mark>."""
    words = sorted({w for w in re.split(r'\s+', str(query or '').strip()) if len(w) > 1}, key=len, reverse=True)
    if not words:
        return escape(text)
    pattern = re.compile('(%s)' % '|'.join(re.escape(w) for w in words), re.IGNORECASE)
    parts = pattern.split(str(text))
    return mark_safe(''.join('<mark>%s</mark>' % escape(p) if i % 2 else escape(p) for i, p in enumerate(parts)))
