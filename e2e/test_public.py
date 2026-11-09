"""What anonymous visitors (and search engines, agents) can see."""
import re

from .base import E2ETestCase


class PublicPagesTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=200)
        self.bob = self.create_user('bob', reputation=50)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?',
                                             tags='collect export')
        self.answer = self.create_answer(self.bob, self.question,
                                         'Use the **CSV export** in the Collect designer:\n\n```\nFile > Export\n```')
        self.create_comment(self.alice, self.answer, 'Thanks, @bob, that worked for me.')
        self.unanswered = self.create_question(self.bob, 'Can SEPAL process Sentinel-2 time series?', tags='sepal')

    PAGES = [
        '/', '/questions/', '/questions/?sort=newest', '/questions/?sort=mostvoted', '/questions/?sort=hottest',
        '/questions/unanswered/', '/tags/', '/tags/collect/', '/users/', '/badges/', '/faq/', '/about/', '/privacy/',
        '/search/?q=export', '/search/?q=collect&t=tag', '/search/?q=bob&t=user', '/account/signin/',
        '/account/local/register/', '/help/email/', '/questions/ask/',
    ]

    def test_pages_on_desktop_phone_and_dark_mode(self):
        pages = self.PAGES + [self.question.get_absolute_url(), self.unanswered.get_absolute_url(),
                              self.alice.get_profile_url()]
        for device, dark in (('desktop', False), ('mobile', True)):
            page = self.open(device=device, dark=dark)
            for path in pages:
                with self.subTest(device=device, path=path):
                    self.visit(page, path)

    def test_phone_tab_bar_and_avatar_fallback(self):
        page = self.open(device='mobile', dark=True)
        page.route('**gravatar.com/**', lambda route: route.fulfill(status=404, body=''))
        for path, current in (('/', 'Questions'), ('/tags/', 'Tags'), ('/users/', 'Users'), ('/badges/', None)):
            with self.subTest(path=path):
                self.visit(page, path)
                # On a phone the tab bar at the bottom replaces the header's tabs and Ask button.
                self.assertFalse(page.locator('#nav').is_visible())
                bar = page.locator('nav.app-bar')
                box = bar.bounding_box()
                self.assertAlmostEqual(box['y'] + box['height'], page.viewport_size['height'], delta=1)
                self.assertEqual(bar.locator('.app-bar-label').all_inner_texts(),
                                 ['Questions', 'Tags', 'Ask', 'Users', 'More'])
                self.assertEqual(bar.locator('[aria-current=page] .app-bar-label').all_inner_texts(),
                                 [current] if current else [])
                # The end of the page scrolls up from under the bar.
                page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                end = page.locator('#ground .footer-osqa').bounding_box()
                self.assertLessEqual(end['y'] + end['height'], box['y'] + 1)
        # More opens the menu sheet: the focus moves into it, Escape closes it
        # and gives the focus back; so does a tap on the backdrop.
        more, sheet = page.locator('#app-more'), page.locator('#app-more-sheet')
        more.click()
        self.assertTrue(sheet.is_visible())
        self.assertEqual(more.get_attribute('aria-expanded'), 'true')
        self.assertTrue(sheet.evaluate('el => el.contains(document.activeElement)'))
        self.assertIn('Sign in', sheet.inner_text())
        page.keyboard.press('Escape')
        page.wait_for_function("document.getElementById('app-more').getAttribute('aria-expanded') === 'false'")
        self.assertFalse(sheet.is_visible())
        self.assertEqual(page.evaluate('document.activeElement.id'), 'app-more')
        more.click()
        page.mouse.click(195, 40)
        self.assertFalse(sheet.is_visible())
        more.click()
        with page.expect_navigation():
            sheet.get_by_role('link', name='Unanswered').click()
        self.assertTrue(page.url.endswith('/questions/unanswered/'), page.url)
        # Not on wider screens: the header keeps its tabs there.
        desktop = self.open()
        self.visit(desktop, '/')
        self.assertFalse(desktop.locator('nav.app-bar').is_visible())
        self.assertTrue(desktop.locator('#nav_ask').is_visible())
        # Avatars that can't be loaded show the initial, not a broken image.
        self.visit(page, self.question.get_absolute_url())
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_function("() => [...document.querySelectorAll('img.gravatar')].every("
                               "img => img.classList.contains('gravatar-fallback') && img.complete && img.naturalWidth > 0)")
        self.assertGreater(page.locator('img.gravatar.gravatar-fallback').count(), 0)
        self.check_page(page)

    def test_question_page_content(self):
        page = self.open()
        self.visit(page, self.question.get_absolute_url())
        self.assertIn('How do I export Collect survey data to CSV?', page.locator('h1').first.inner_text())
        self.assertEqual(page.locator('.answer').count(), 1)
        self.assertIn('File > Export', page.locator('.answer pre').inner_text())
        self.assertEqual(page.locator('.comment').count(), 1)
        # Anonymous visitors get the sign-in prompt instead of voting.
        page.locator('#post-%d-upvote' % self.answer.id).click()
        self.wait_for_ajax(page)
        self.assertTrue(page.locator('.dialog, .notify, .error').first.is_visible() or
                        page.url.endswith('/account/signin/'))
        self.check_page(page)

    def test_search_and_tags(self):
        page = self.open()
        self.visit(page, '/')
        page.fill('#keywords', 'export')
        page.locator('#searchBar button[type=submit]').click()
        page.wait_for_load_state()
        self.assertIn('/search/', page.url)
        self.assertIn('How do I export Collect survey data to CSV?', page.locator('#search-results h2 a').all_inner_texts())
        self.check_page(page)

        self.visit(page, '/tags/')
        page.get_by_role('link', name='sepal', exact=True).first.click()
        page.wait_for_load_state()
        self.assertIn('Can SEPAL process Sentinel-2 time series?', page.content())
        self.check_page(page)

    def test_machine_readable_endpoints(self):
        page = self.open()
        for path, expected in (('/questions/%d.md' % self.question.id, 'How do I export Collect survey data'),
                               ('/llms.txt', 'How do I export'), ('/export/qa.jsonl', 'export'),
                               ('/feeds/rss/', 'export'), ('/sitemap.xml', 'sitemap'), ('/healthz', 'ok')):
            with self.subTest(path=path):
                response = page.request.get(self.url(path))
                self.assertEqual(response.status, 200, path)
                self.assertIn(expected, response.text())

    def test_sitemap_leads_to_every_question(self):
        # As a search engine reads it: the index, each section, its pages.
        page = self.open()
        self.visit(page, '/')
        fetch = '''async path => { const r = await fetch(path); return [r.status, await r.text()]; }'''

        def locations(path):
            status, text = page.evaluate(fetch, path)
            self.assertEqual(status, 200, path)
            return [loc.split('://', 1)[-1].split('/', 1)[-1] for loc in re.findall(r'<loc>([^<]+)</loc>', text)]

        questions = []
        for section in locations('/sitemap.xml'):
            for sitemap_page in locations('/' + section):
                questions += locations('/' + sitemap_page)
        for question in (self.question, self.unanswered):
            self.assertIn(question.get_absolute_url().lstrip('/'), questions)
        self.check_page(page)

    def test_not_found_page(self):
        page = self.open()
        response = page.goto(self.url('/questions/999999/'))
        self.assertEqual(response.status, 404)
        page.problems.clear()  # the 404 response itself is logged by the browser

    def test_language_switcher(self):
        page = self.open(locale='es-ES')
        self.visit(page, '/')
        self.assertEqual(page.get_attribute('html', 'lang'), 'es')
        with page.expect_navigation():
            page.select_option('#language-select', 'fr')
        self.assertEqual(page.get_attribute('html', 'lang'), 'fr')
        self.visit(page, '/questions/?sort=mostvoted')
        self.assertEqual(page.get_attribute('html', 'lang'), 'fr')
