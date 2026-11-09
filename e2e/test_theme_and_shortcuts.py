"""The theme switch (Light / Dark / System: footer for everyone, header menu
for members) and the keyboard shortcuts (osqa.theme.js, osqa.shortcuts.js,
forum/utils/display.py).

Theme: "System" follows the emulated colour scheme, also when it changes; a
choice applies without reloading, survives a reload for anonymous visitors
(cookie) and members (preferences, also in a fresh browser), the first paint
is already right (data-theme and the page background are checked when the
DOM is ready), the admin follows the choice, and charts and highlighted
code take the theme's colours.
Shortcuts: "?" opens an accessible dialog (axe, focus kept inside, Escape
closes and gives the focus back), "/", "g" + letter and "a" navigate, j / k
and Enter on lists, j / k and u on a question page, nothing happens while
typing or with Ctrl/Alt, and a member can turn them off."""
from django.urls import reverse

from forum.models import User

from .base import E2ETestCase
from . import test_accessibility
from .test_question_page import QUESTION_BODY

LIGHT_BG = 'rgb(245, 247, 250)'  # osqa.css --background
DARK_BG = 'rgb(13, 17, 23)'

# What the page looked like the moment the DOM was ready (before any deferred script).
FIRST_PAINT = '''() => {
    document.addEventListener('DOMContentLoaded', () => {
        window.__firstPaint = {theme: document.documentElement.getAttribute('data-theme'),
                               background: getComputedStyle(document.body).backgroundColor};
    });
}'''


# Closes the dialog and moves the focus at once, as a member who presses
# Escape and goes straight on does: the dialog's close event comes after, and
# must not pull the focus back to where the dialog was opened.
CLOSE_AND_MOVE_ON = '''([dialog, target]) => {
    document.querySelector(dialog).close();
    document.querySelector(target).focus();
    return new Promise(resolve => setTimeout(resolve, 100));
}'''

class ThemeTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=200)
        self.bob = self.create_user('bob', reputation=500)
        self.question = self.create_question(self.alice, 'How do I read Collect CSV dates as dates in R?',
                                             body=QUESTION_BODY)

    def open_watched(self, user=None, **options):
        page = self.open(user, **options)
        page.add_init_script(script='(%s)()' % FIRST_PAINT)
        return page

    def first_paint(self, page):
        return page.evaluate('window.__firstPaint')

    def theme(self, page):
        return page.evaluate('''() => ({theme: document.documentElement.getAttribute('data-theme'),
            choice: document.documentElement.getAttribute('data-theme-choice'),
            background: getComputedStyle(document.body).backgroundColor,
            scheme: document.querySelector('meta[name="color-scheme"]').content})''')

    def assertTheme(self, page, theme, choice):
        state = self.theme(page)
        self.assertEqual((state['theme'], state['choice']), (theme, choice))
        self.assertEqual(state['background'], DARK_BG if theme == 'dark' else LIGHT_BG)

    def test_system_default_follows_the_colour_scheme(self):
        for dark in (False, True):
            page = self.open_watched(dark=dark)
            self.visit(page, '/')
            self.assertEqual(self.first_paint(page), {'theme': 'dark' if dark else 'light',
                                                      'background': DARK_BG if dark else LIGHT_BG})
            self.assertTheme(page, 'dark' if dark else 'light', 'auto')
            self.assertEqual(self.theme(page)['scheme'], 'light dark')
            self.assertEqual(page.input_value('#theme-select'), 'auto')
        # The device setting changes while the page is open.
        page.emulate_media(color_scheme='light')
        page.wait_for_function("() => document.documentElement.getAttribute('data-theme') === 'light'")
        self.assertTheme(page, 'light', 'auto')

    def test_anonymous_choice_applies_at_once_and_persists(self):
        page = self.open_watched(dark=False)
        self.visit(page, self.question.get_absolute_url())
        page.wait_for_selector('.post-body pre code.hljs .hljs-string')
        string_colour = "getComputedStyle(document.querySelector('.post-body .hljs-string')).color"
        light_string = page.evaluate(string_colour)
        page.evaluate('window.__samePage = true')

        page.select_option('#theme-select', 'dark')
        page.wait_for_function("() => document.documentElement.getAttribute('data-theme') === 'dark'")
        self.assertTrue(page.evaluate('window.__samePage'), 'the page reloaded')
        self.assertTheme(page, 'dark', 'dark')
        self.assertEqual(self.theme(page)['scheme'], 'dark')
        self.assertNotEqual(page.evaluate(string_colour), light_string, 'code highlighting kept its light colours')
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.post-body .hljs-string')).color"),
                         'rgb(165, 214, 255)')  # --hl-string in dark mode
        self.assertEqual(page.evaluate('''[...document.querySelectorAll('meta[name="theme-color"]')]
            .map(m => m.media).join(',')'''), 'not all,all')
        self.wait_for_ajax(page)
        page.wait_for_load_state('networkidle')
        cookies = {c['name']: c['value'] for c in page.context.cookies()}
        self.assertEqual(cookies.get('osqa_theme'), 'dark')

        page.reload()
        self.check_page(page)
        self.assertEqual(self.first_paint(page), {'theme': 'dark', 'background': DARK_BG})
        self.assertEqual(page.input_value('#theme-select'), 'dark')

        # Light on a dark device, then back to following the device.
        page.emulate_media(color_scheme='dark')
        page.select_option('#theme-select', 'light')
        page.wait_for_function("() => document.documentElement.getAttribute('data-theme') === 'light'")
        self.assertTheme(page, 'light', 'light')
        page.wait_for_load_state('networkidle')
        page.reload()
        self.check_page(page)
        self.assertEqual(self.first_paint(page), {'theme': 'light', 'background': LIGHT_BG})
        page.select_option('#theme-select', 'auto')
        page.wait_for_function("() => document.documentElement.getAttribute('data-theme') === 'dark'")
        self.assertTheme(page, 'dark', 'auto')
        self.check_page(page)

    def test_member_choice_follows_them(self):
        page = self.open_watched(self.bob, dark=False)
        self.visit(page, '/')
        page.click('.theme-menu summary')
        page.wait_for_selector('.theme-menu-panel', state='visible')
        page.click('.theme-menu-option:has-text("Dark")')
        page.wait_for_function("() => document.documentElement.getAttribute('data-theme') === 'dark'")
        self.assertTheme(page, 'dark', 'dark')
        # Every switch on the page shows the choice; the icon is the moon.
        self.assertEqual(page.input_value('#theme-select'), 'dark')
        self.assertTrue(page.is_visible('.theme-menu .theme-icon-dark'))
        self.assertFalse(page.is_visible('.theme-menu .theme-icon-auto'))
        # Escape closes the menu and puts the focus back on its button.
        page.keyboard.press('Escape')
        self.assertFalse(page.evaluate("document.querySelector('.theme-menu').open"))
        self.assertTrue(page.evaluate("document.activeElement.matches('.theme-menu summary')"))
        page.wait_for_load_state('networkidle')
        self.check_page(page)
        self.assertEqual(User.objects.get(id=self.bob.id).prop.preferences.get('theme'), 'dark')

        # Another browser (no cookie), on a light device.
        other = self.open_watched(self.bob, dark=False)
        self.visit(other, '/')
        self.assertEqual(self.first_paint(other), {'theme': 'dark', 'background': DARK_BG})
        self.assertTrue(other.is_checked('.theme-menu input[value="dark"]'))

    def test_admin_follows_the_choice(self):
        admin = self.create_user('admin', reputation=1000, is_staff=True, is_superuser=True)
        admin.prop.preferences = {'theme': 'dark'}
        page = self.open(admin, dark=False)
        for path in (reverse('admin_index'), reverse('admin_moderation')):
            self.visit(page, path)
            self.assertEqual(page.evaluate("document.documentElement.getAttribute('data-theme')"), 'dark')
            # Django's dark palette (body) and OSQA's (header).
            self.assertEqual(page.evaluate("getComputedStyle(document.body).backgroundColor"), 'rgb(18, 18, 18)')
            self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('header')).backgroundColor"),
                             'rgb(23, 34, 53)')
        admin.prop.preferences = {'theme': 'light'}
        page = self.open(admin, dark=True)
        self.visit(page, reverse('admin_index'))
        self.assertEqual(page.evaluate("getComputedStyle(document.body).backgroundColor"), 'rgb(255, 255, 255)')
        self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('header')).backgroundColor"),
                         'rgb(27, 51, 88)')

    def test_charts_follow_the_theme(self):
        from forum.actions import VoteUpAction
        self._as_request(self.bob)
        VoteUpAction(user=self.bob, node=self.question, ip='127.0.0.1').save()
        page = self.open(self.bob, device='mobile', dark=False)
        alice = User.objects.get(id=self.alice.id)
        self.visit(page, reverse('user_reputation', kwargs={'id': alice.id, 'slug': alice.username}))
        page.wait_for_selector('#diagram canvas')
        line = "jQuery('#diagram').data('plot').getOptions().colors[0]"
        self.assertEqual(page.evaluate(line), '#2c5aa0')
        page.select_option('#theme-select', 'dark')
        page.wait_for_function("() => jQuery('#diagram').data('plot') && jQuery('#diagram').data('plot').getOptions().colors[0] === '#79b0ff'")
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('#diagram .flot-svg text')).fill"),
                         'rgb(155, 167, 180)')  # --muted in dark mode
        page.wait_for_load_state('networkidle')
        self.check_page(page)


class ShortcutsTest(E2ETestCase):
    axe = test_accessibility.AccessibilityTest.axe

    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=200)
        self.bob = self.create_user('bob', reputation=500)
        self.first = self.create_question(self.alice, 'Exporting a Collect survey to Excel', days_ago=2)
        self.second = self.create_question(self.alice, 'Can SEPAL process Sentinel-2 time series?', days_ago=1)
        self.question = self.create_question(self.alice, 'How do I read Collect CSV dates as dates in R?')
        self.answer = self.create_answer(self.bob, self.question)
        self.other_answer = self.create_answer(self.alice, self.question, 'Another answer, long enough to be posted.')

    def path(self, page):
        return page.url[len(self.live_server_url):]

    def active(self, page):
        return page.evaluate('''() => { const el = document.activeElement;
            return el.id || el.className || el.tagName; }''')

    def test_dialog(self):
        for device, dark in (('desktop', False), ('mobile', True)):
            page = self.open(self.bob, device=device, dark=dark)
            self.visit(page, '/')
            # On a phone the header's tabs give way to the tab bar.
            start = 'nav_questions' if device == 'desktop' else 'app-bar-questions'
            page.focus('#' + start)
            page.keyboard.press('Shift+?')
            page.wait_for_selector('#shortcuts-dialog[open]')
            self.assertTrue(page.evaluate("document.activeElement.matches('#shortcuts-dialog .shortcuts-close')"))
            dialog_text = page.inner_text('#shortcuts-dialog')
            for text in ('Keyboard shortcuts', 'Search', 'Go to your notifications', 'Next or previous question',
                         'Vote the post up or down', 'your preferences'):
                self.assertIn(text, dialog_text)
            failures = self.axe(page)
            self.assertEqual(failures, [], '%s:\n%s' % (device, '\n'.join(failures)))
            # Tab and Shift+Tab stay inside (close button, preferences link).
            for key in ('Tab', 'Tab', 'Tab', 'Shift+Tab', 'Shift+Tab', 'Shift+Tab'):
                page.keyboard.press(key)
                self.assertTrue(page.evaluate("document.getElementById('shortcuts-dialog').contains(document.activeElement)"),
                                'the focus left the dialog after %s' % key)
            page.keyboard.press('Escape')
            self.assertFalse(page.evaluate("document.getElementById('shortcuts-dialog').open"))
            self.assertEqual(self.active(page), start)
            # The close button.
            page.keyboard.press('?')
            page.click('#shortcuts-dialog .shortcuts-close')
            self.assertFalse(page.evaluate("document.getElementById('shortcuts-dialog').open"))
            self.check_page(page)

        anonymous = self.open()
        self.visit(anonymous, '/')
        anonymous.keyboard.press('?')
        anonymous.wait_for_selector('#shortcuts-dialog[open]')
        self.assertIn('Members can turn them off', anonymous.inner_text('#shortcuts-dialog'))
        self.assertNotIn('notifications', anonymous.inner_text('#shortcuts-dialog'))

    def test_closing_leaves_a_focus_that_moved_on_alone(self):
        page = self.open(self.bob)
        self.visit(page, '/questions/')
        page.focus('#nav_questions')
        page.keyboard.press('?')
        page.wait_for_selector('#shortcuts-dialog[open]')
        page.evaluate(CLOSE_AND_MOVE_ON, ['#shortcuts-dialog', '.theme-menu > summary'])
        self.assertTrue(page.evaluate("document.activeElement.matches('.theme-menu > summary')"),
                        'the focus went back to %s' % self.active(page))
        self.check_page(page)

    def test_navigation_keys(self):
        page = self.open(self.bob)
        self.visit(page, '/')
        for keys, path in ((['g', 'q'], '/questions/'), (['g', 't'], '/tags/'), (['g', 'u'], '/users/'),
                           (['g', 'n'], '/notifications/'), (['g', 'h'], '/'), (['a'], '/questions/ask/')):
            with page.expect_navigation():
                for key in keys:
                    page.keyboard.press(key)
            self.assertEqual(self.path(page), path)
            self.check_page(page)
        self.visit(page, '/tags/')
        page.keyboard.press('/')
        self.assertEqual(self.active(page), 'keywords')
        # "g" then a key that means nothing: nothing happens, and "g" expires.
        self.visit(page, '/tags/')
        page.keyboard.press('g')
        page.keyboard.press('x')
        page.keyboard.press('q')
        page.wait_for_timeout(300)
        self.assertEqual(self.path(page), '/tags/')

    def test_question_list_j_k_enter(self):
        page = self.open(self.bob, device='mobile', dark=True)
        self.visit(page, '/questions/?sort=newest')
        titles = page.eval_on_selector_all('.question-row h2 a', 'links => links.map(a => a.textContent.trim())')
        current = '''() => { const el = document.querySelector('.is-kbd-current');
            return el && document.activeElement === el ? el.querySelector('h2 a').textContent.trim() : null; }'''
        page.keyboard.press('j')
        self.assertEqual(page.evaluate(current), titles[0])
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.is-kbd-current')).outlineStyle"), 'solid')
        page.keyboard.press('j')
        self.assertEqual(page.evaluate(current), titles[1])
        page.keyboard.press('k')
        page.keyboard.press('k')
        self.assertEqual(page.evaluate(current), titles[0])
        page.keyboard.press('j')
        with page.expect_navigation():
            page.keyboard.press('Enter')
        self.assertEqual(self.path(page), self.second.get_absolute_url())
        self.check_page(page)

    def test_question_page_j_k_and_vote(self):
        page = self.open(self.alice)
        self.visit(page, self.question.get_absolute_url())
        current = "() => document.activeElement.classList.contains('is-kbd-current') ? document.activeElement.id : null"
        page.keyboard.press('j')
        self.assertEqual(page.evaluate(current), 'question-table')
        page.keyboard.press('j')
        posts = page.eval_on_selector_all('.question-page .post', 'posts => posts.map(p => p.id)')
        self.assertEqual(page.evaluate(current), posts[1])
        page.keyboard.press('k')
        self.assertEqual(page.evaluate(current), 'question-table')
        # Bob's answer, voted up with "u".
        while page.evaluate(current) != 'answer-container-%d' % self.answer.id:
            page.keyboard.press('j')
        page.keyboard.press('u')
        self.settle(page)
        self.assertEqual(page.get_attribute('#post-%d-upvote' % self.answer.id, 'aria-pressed'), 'true')
        self.check_page(page)

    def test_nothing_while_typing_or_with_modifiers(self):
        page = self.open(self.bob)
        self.visit(page, '/questions/')
        page.click('#keywords')
        page.keyboard.type('gq?ja')
        self.assertEqual(page.input_value('#keywords'), 'gq?ja')
        self.assertFalse(page.evaluate("document.getElementById('shortcuts-dialog').open"))
        self.assertEqual(self.path(page), '/questions/')
        page.evaluate('document.activeElement.blur()')
        page.keyboard.press('Alt+j')
        page.keyboard.press('Control+j')
        self.assertIsNone(page.evaluate("document.querySelector('.is-kbd-current')"))
        # A contenteditable element counts as a text field too.
        page.evaluate('''() => { const el = document.createElement('div');
            el.contentEditable = 'true'; el.id = 'editable'; document.body.appendChild(el); el.focus(); }''')
        page.keyboard.type('?')
        self.assertFalse(page.evaluate("document.getElementById('shortcuts-dialog').open"))
        self.check_page(page)

    def test_turning_them_off(self):
        page = self.open(self.bob)
        url = reverse('user_preferences', kwargs={'id': self.bob.id, 'slug': 'bob'})
        self.visit(page, url)
        self.assertTrue(page.is_checked('#id_keyboard_shortcuts'))
        page.uncheck('#id_keyboard_shortcuts')
        with page.expect_navigation():
            page.click('.settings-actions input[type=submit]')
        self.check_page(page)
        self.assertFalse(page.is_checked('#id_keyboard_shortcuts'))
        self.assertIs(User.objects.get(id=self.bob.id).prop.preferences.get('keyboard_shortcuts'), False)

        self.visit(page, '/questions/')
        self.assertEqual(page.evaluate("document.documentElement.getAttribute('data-shortcuts')"), 'off')
        self.assertEqual(page.locator('#shortcuts-dialog').count(), 0)
        page.keyboard.press('?')
        page.keyboard.press('j')
        page.keyboard.press('/')
        page.keyboard.press('g')
        page.keyboard.press('q')
        page.wait_for_timeout(300)
        self.assertNotEqual(self.active(page), 'keywords')
        self.assertIsNone(page.evaluate("document.querySelector('.is-kbd-current')"))
        self.assertFalse(page.is_visible('#searchBar .searchbox-kbd'))

        # And back on.
        self.visit(page, url)
        page.check('#id_keyboard_shortcuts')
        with page.expect_navigation():
            page.click('.settings-actions input[type=submit]')
        self.visit(page, '/')
        page.keyboard.press('?')
        page.wait_for_selector('#shortcuts-dialog[open]')
        self.check_page(page)
