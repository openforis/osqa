"""The admin's guidance: the admin search, the filter of a settings page, the
External Keys page's per-service setup guides and Admin > Look and feel
(ready-made styles, sample, contrast, what the public pages get).

E2E_SCREENSHOTS=<folder> saves screenshots of the pages, on a desktop and on
a phone in dark mode, for a look by eye."""
import os
import re
from unittest import mock

from forum import settings

from .base import E2ETestCase


class AdminGuidanceTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', reputation=1000, is_superuser=True, is_staff=True)

    def screenshot(self, page, name):
        folder = os.environ.get('E2E_SCREENSHOTS')
        if folder:
            os.makedirs(folder, exist_ok=True)
            page.screenshot(path=os.path.join(folder, '%s-%s.png' % (name, page.device)), full_page=True)

    def test_search_finds_a_setting_and_points_at_it(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/')
        page.fill('#admin-search-q', 'logo')
        with page.expect_navigation():
            page.press('#admin-search-q', 'Enter')
        self.check_page(page)
        first = page.locator('.admin-search-result a').first
        self.assertEqual(first.inner_text(), 'Application logo')
        self.assertEqual(page.locator('.admin-search-result mark').first.inner_text().lower(), 'logo')
        self.screenshot(page, 'search')
        with page.expect_navigation():
            first.click()
        self.check_page(page)
        self.assertTrue(page.url.endswith('/admin/settings/basic/#setting-APP_LOGO'))
        self.assertTrue(page.locator('#setting-APP_LOGO').evaluate('row => row.matches(":target")'))

        # Synonyms, and a word that matches nothing.
        self.visit(page, '/admin/search/?q=color')
        self.assertIn('Brand colour', page.locator('.admin-search-results').inner_text())
        self.visit(page, '/admin/search/?q=zzzzqx')
        self.assertEqual(page.locator('.admin-search-result').count(), 0)
        self.assertIn('0 results', page.locator('.admin-search-count').inner_text())

    def test_moderators_have_no_settings_search(self):
        moderator = self.create_user('moderator', reputation=10, is_staff=True)
        page = self.open(moderator)
        self.visit(page, '/admin/moderation/')
        self.assertEqual(page.locator('#admin-search-q').count(), 0)

    def test_filter_on_a_settings_page(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/email/')
        total = page.locator('.setting-row').count()
        self.assertGreater(total, 5)
        page.fill('#settings-filter', 'subject')
        page.wait_for_selector('.setting-row[hidden]', state='attached')
        shown = page.locator('.setting-row:visible').count()
        self.assertGreater(shown, 0)
        self.assertLess(shown, total)
        page.fill('#settings-filter', 'zzzzqx')
        page.wait_for_selector('.admin-filter-status:has-text("No setting")')
        self.assertEqual(page.locator('.setting-row:visible').count(), 0)
        page.fill('#settings-filter', '')
        page.wait_for_selector('.setting-row[hidden]', state='detached')
        self.assertEqual(page.locator('.setting-row:visible').count(), total)

    def test_external_keys_guides(self):
        # Providers want https redirect addresses (else the status warns).
        self._patch(mock.patch.object(settings, 'APP_URL', 'https://forum.example.org'))
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/extkeys/')
        google = page.locator('#section-google-signin')
        self.assertEqual(google.locator('.admin-status').inner_text(), 'Not set up')
        # The redirect URI to register, with this site's address.
        self.assertEqual(google.locator('.admin-copy input').input_value(),
                         'https://forum.example.org/account/google/done/')
        self.screenshot(page, 'extkeys')

        # Secrets are hidden until asked for.
        secret = page.locator('#id_GOOGLE_CLIENT_SECRET')
        self.assertEqual(secret.get_attribute('type'), 'password')
        toggle = google.locator('.secret-toggle')
        toggle.click()
        self.assertEqual(secret.get_attribute('type'), 'text')
        self.assertEqual(toggle.get_attribute('aria-pressed'), 'true')

        # A client ID that isn't one, then the real thing.
        page.fill('#id_GOOGLE_CLIENT_ID', 'my-project-123')
        page.fill('#id_GOOGLE_CLIENT_SECRET', 'GOCSPX-abcdefghijklmnop')
        with page.expect_navigation():
            page.click('#submit')
        self.check_page(page)
        self.assertEqual(google.locator('.admin-status').inner_text(), 'Check this')
        self.assertIn('.apps.googleusercontent.com', google.locator('.admin-guide-message').inner_text())
        page.fill('#id_GOOGLE_CLIENT_ID', '1234-abc.apps.googleusercontent.com')
        with page.expect_navigation():
            page.click('#submit')
        self.check_page(page)
        self.assertEqual(google.locator('.admin-status').inner_text(), 'Set up')
        # Once set up, the steps are folded away.
        self.assertFalse(google.locator('details').evaluate('d => d.open'))
        self.assertEqual(str(settings.GOOGLE_CLIENT_SECRET), 'GOCSPX-abcdefghijklmnop')

        # The old Universal Analytics IDs get a warning.
        page.fill('#id_GOOGLE_ANALYTICS_KEY', 'UA-1234-5')
        with page.expect_navigation():
            page.click('#submit')
        self.check_page(page)
        analytics = page.locator('#section-analytics')
        self.assertEqual(analytics.locator('.admin-status').inner_text(), 'Check this')

        phone = self.open(self.admin, device='mobile', dark=True)
        self.visit(phone, '/admin/settings/extkeys/')
        self.screenshot(phone, 'extkeys')

    def test_public_api_examples(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/api/')
        page.click('.admin-guide-steps > summary')
        code = page.locator('#api-example-list').inner_text()
        self.assertEqual(code, "curl '%s/api/v1/questions?sort=newest&limit=5'" % settings.APP_URL)
        self.assertIn('-d \'{"title"', page.locator('#api-example-ask').inner_text())
        self.screenshot(page, 'api')

    def test_look_and_feel(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/appearance/')
        self.screenshot(page, 'appearance')
        page.click('.appearance-style-use[data-style="forest"]')
        self.assertEqual(page.input_value('#id_THEME_BRAND_COLOR'), '#2d6a3e')
        self.assertEqual(page.input_value('#id_THEME_STYLE'), 'forest')
        self.assertEqual(page.input_value('#id_THEME_FONT'), 'humanist')
        self.assertEqual(page.input_value('#id_THEME_BACKGROUND'), 'tinted')
        self.assertEqual(page.get_attribute('.appearance-style-use[data-style="forest"]', 'aria-pressed'), 'true')
        self.assertIn('unsaved changes', page.locator('.admin-unsaved-status').inner_text())
        sample = page.locator('.appearance-sample-light')
        self.assertEqual(sample.evaluate('s => s.style.getPropertyValue("--sample-brand")'), '#2d6a3e')
        page.select_option('#id_THEME_FONT', 'serif')
        page.select_option('#id_THEME_PAGE_WIDTH', 'wide')
        with page.expect_navigation():
            page.click('#submit')
        self.check_page(page)

        visitor = self.open()
        self.visit(visitor, '/')
        style = visitor.locator('#appearance-style').inner_text()
        self.assertIn('--brand:#2d6a3e', style)
        self.assertIn('--content-width:1320px', style)
        self.assertIn('#roof{box-shadow:inset 0 4px 0 var(--brand)}', style)  # the style's own rule
        self.assertEqual(visitor.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--brand").trim()'),
                         '#2d6a3e')
        self.assertIn('Charter', visitor.evaluate('getComputedStyle(document.body).fontFamily'))
        self.assertEqual(visitor.locator('meta[name="theme-color"]').first.get_attribute('content'), '#2d6a3e')
        self.screenshot(visitor, 'appearance-site')
        # Dark mode gets a lighter brand colour for links.
        dark = self.open(device='mobile', dark=True)
        self.visit(dark, '/')
        dark_brand = dark.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--brand").trim()')
        self.assertNotEqual(dark_brand, '#2d6a3e')
        self.screenshot(dark, 'appearance-site')

        # A colour too light for white text is darkened, and the page says so.
        page.fill('#id_THEME_BRAND_COLOR', '#ffd166')
        page.dispatch_event('#id_THEME_BRAND_COLOR', 'input')
        self.assertIn('darker', page.locator('#appearance-contrast').inner_text())
        with page.expect_navigation():
            page.click('#submit')
        self.check_page(page)
        self.assertIn('darker', page.locator('#appearance-contrast').inner_text())
        self.visit(visitor, '/')
        used = re.search(r'--brand:(#[0-9a-f]{6})', visitor.locator('#appearance-style').inner_text()).group(1)
        self.assertNotEqual(used, '#ffd166')

        # The theme new visitors get.
        page.select_option('#id_DEFAULT_THEME', 'dark')
        with page.expect_navigation():
            page.click('#submit')
        stranger = self.open()
        self.visit(stranger, '/')
        self.assertEqual(stranger.locator('html').get_attribute('data-theme'), 'dark')

        phone = self.open(self.admin, device='mobile', dark=True)
        self.visit(phone, '/admin/settings/appearance/')
        self.screenshot(phone, 'appearance')

    def test_preview_look_and_feel_before_saving(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/appearance/')
        page.click('.appearance-style-use[data-style="plum"]')
        with page.expect_popup() as popup:
            page.click('#preview')
        preview = popup.value
        preview.wait_for_load_state()
        preview.problems = []
        self.assertIn('--brand:#6b3fa0', preview.locator('#appearance-style').inner_text())
        # Visitors don't see it until it is saved.
        visitor = self.open()
        self.visit(visitor, '/')
        self.assertEqual(visitor.locator('#appearance-style').count(), 0)

    def test_unsaved_changes(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/minrep/')
        bar = page.locator('.admin-savebar')
        self.assertFalse(page.locator('.admin-discard').is_visible())
        page.fill('#id_REP_TO_VOTE_UP', '20')
        page.fill('#id_REP_TO_COMMENT', '60')
        self.assertEqual(page.locator('.admin-unsaved-status').inner_text(), '2 unsaved changes')
        self.assertEqual(page.locator('.setting-row.is-dirty').count(), 2)
        # The save bar stays in view at the bottom of the window.
        box = bar.bounding_box()
        self.assertLessEqual(box['y'] + box['height'], page.viewport_size['height'] + 1)
        self.screenshot(page, 'unsaved')

        # Leaving asks first (the test browser accepts).
        dialogs = []
        page.on('dialog', lambda dialog: dialogs.append(dialog.type))
        self.visit(page, '/admin/')
        self.assertEqual(dialogs, ['beforeunload'])
        self.assertEqual(settings.REP_TO_VOTE_UP.value, settings.REP_TO_VOTE_UP.default)

        # "Undo my changes" puts the page back as loaded.
        self.visit(page, '/admin/settings/minrep/')
        page.fill('#id_REP_TO_VOTE_UP', '20')
        page.click('.admin-discard')
        page.wait_for_selector('.admin-discard', state='hidden')
        self.assertEqual(page.input_value('#id_REP_TO_VOTE_UP'), str(settings.REP_TO_VOTE_UP.default))
        self.assertEqual(page.locator('.setting-row.is-dirty').count(), 0)

        # Saving doesn't ask.
        page.fill('#id_REP_TO_VOTE_UP', '20')
        with page.expect_navigation():
            page.click('#submit')
        self.check_page(page)
        self.assertEqual(dialogs, ['beforeunload'])
        self.assertIn('Minimum reputation config saved: Minimum reputation to vote up changed.',
                      page.locator('.admin_message').all_inner_texts())
        settings.REP_TO_VOTE_UP._temp = None
        self.assertEqual(settings.REP_TO_VOTE_UP.value, 20)

        phone = self.open(self.admin, device='mobile', dark=True)
        self.visit(phone, '/admin/settings/minrep/')
        phone.fill('#id_REP_TO_COMMENT', '60')
        self.screenshot(phone, 'unsaved')

    def test_getting_started_list(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/')
        checklist = page.locator('.admin-checklist')
        self.assertIn('0 of 6 done', checklist.inner_text())
        self.screenshot(page, 'checklist')
        with page.expect_navigation():
            checklist.get_by_role('link', name='Name the site').click()
        self.check_page(page)
        self.assertTrue(page.url.endswith('/admin/settings/basic/#setting-APP_TITLE'))
        page.fill('#id_APP_TITLE', 'Open Foris Support')
        with page.expect_navigation():
            page.click('#submit')
        self.visit(page, '/admin/')
        self.assertIn('1 of 6 done', checklist.inner_text())
        self.assertIn('is-done', checklist.locator('li').first.get_attribute('class'))

        with page.expect_navigation():
            page.get_by_role('button', name='Hide this list').click()
        self.check_page(page)
        self.assertEqual(page.locator('.admin-checklist').count(), 0)
        with page.expect_navigation():
            page.get_by_role('button', name='Show the Getting started list').click()
        self.assertEqual(page.locator('.admin-checklist').count(), 1)

    def test_slash_goes_to_the_search(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/basic/')
        page.locator('body').press('/')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'admin-search-q')
        # Not while typing.
        page.locator('#id_APP_TITLE').press('/')
        self.assertIn('/', page.input_value('#id_APP_TITLE'))
        self.assertEqual(page.evaluate('document.activeElement.id'), 'id_APP_TITLE')

    def test_choosing_a_style_from_the_list(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/appearance/')
        page.select_option('#id_THEME_STYLE', 'midnight')
        self.assertEqual(page.input_value('#id_THEME_BRAND_COLOR'), '#1e3a8a')
        self.assertEqual(page.input_value('#id_DEFAULT_THEME'), 'dark')
        with page.expect_navigation():
            page.click('#submit')
        self.check_page(page)
        self.assertEqual(settings.THEME_STYLE.value, 'midnight')

    def test_every_style_on_the_site(self):
        """Each style applied, as visitors see it (screenshots with E2E_SCREENSHOTS)."""
        from forum.utils import appearance
        alice = self.create_user('alice', reputation=100)
        question = self.create_question(alice, 'How do I export Collect survey data to CSV?', tags='collect export')
        self.create_answer(alice, question)
        for style in appearance.STYLES:
            with self.subTest(style=style.key):
                for setting, value in ((settings.THEME_STYLE, style.key), (settings.THEME_BRAND_COLOR, style.brand),
                                       (settings.THEME_ACCENT_COLOR, style.accent),
                                       (settings.THEME_BACKGROUND, style.background),
                                       (settings.THEME_FONT, style.font), (settings.THEME_PAGE_WIDTH, style.width)):
                    self.set_setting(setting, value)
                visitor = self.open(dark=style.theme == 'dark')
                self.visit(visitor, question.get_absolute_url())
                self.screenshot(visitor, 'style-%s' % style.key)
