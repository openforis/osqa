"""The admin's guidance: guided settings pages (forum/settings/guides.py),
the admin search (forum/utils/admin_search.py) and Look and feel
(forum/utils/appearance.py)."""
from unittest import mock

from forum import settings
from forum.settings.base import Setting
from forum.settings.forms import SettingsSetForm
from forum.settings.guides import OFF, ON, PARTIAL, WARNING
from forum.utils import admin_search, appearance

from .base import OSQATestCase
from .test_antispam import SettingMixin


class GuidedSettingsTest(SettingMixin, OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(self.admin)

    def section(self, response, key):
        return dict((s['key'], s) for s in response.context['sections'])[key]

    def test_every_settings_page_renders(self):
        for name in Setting.sets:
            with self.subTest(set=name):
                self.assertEqual(self.client.get('/admin/settings/%s/' % name).status_code, 200)

    def test_external_keys_sections_and_status(self):
        response = self.client.get('/admin/settings/extkeys/')
        google = self.section(response, 'google-signin')
        self.assertEqual(google['state'], OFF)
        self.assertEqual(google['copy'][0][1], '%s/account/google/done/' % settings.APP_URL)
        self.assertContains(response, 'id="setting-GOOGLE_CLIENT_ID"')
        # Sign-in comes first; every setting is in a section, none left over.
        self.assertEqual(response.context['sections'][0]['key'], 'google-signin')
        self.assertFalse(response.context['other_rows'])

        self.set(settings.GOOGLE_CLIENT_ID, '1-abc.apps.googleusercontent.com')
        with mock.patch.object(settings, 'APP_URL', 'https://forum.example.org'):
            self.assertEqual(self.section(self.client.get('/admin/settings/extkeys/'), 'google-signin')['state'],
                             PARTIAL)
            self.set(settings.GOOGLE_CLIENT_SECRET, 'secret')
            self.assertEqual(self.section(self.client.get('/admin/settings/extkeys/'), 'google-signin')['state'], ON)
        # Plain http addresses are refused by the providers.
        with mock.patch.object(settings, 'APP_URL', 'http://forum.example.org'):
            section = self.section(self.client.get('/admin/settings/extkeys/'), 'google-signin')
            self.assertEqual(section['state'], WARNING)
            self.assertIn('https://', section['message'])

    def test_analytics_ids(self):
        for value, state in (('', OFF), ('G-ABC123XYZ9', ON), ('UA-1234-5', WARNING), ('12345', WARNING)):
            self.set(settings.GOOGLE_ANALYTICS_KEY, value)
            section = self.section(self.client.get('/admin/settings/extkeys/'), 'analytics')
            self.assertEqual(section['state'], state, value)

    def test_secrets_are_password_fields_that_keep_their_value(self):
        self.set(settings.GOOGLE_CLIENT_SECRET, 'kept-secret')
        response = self.client.get('/admin/settings/extkeys/')
        self.assertContains(response, 'type="password" name="GOOGLE_CLIENT_SECRET" value="kept-secret"')

    def test_guidance_keys_are_not_field_arguments(self):
        form = SettingsSetForm(Setting.sets['extkeys'])
        self.assertIn('Example:', str(form.as_table()))
        self.assertIn('<code>G-ABC123XYZ9</code>', str(form.as_table(['GOOGLE_ANALYTICS_KEY'])))

    def test_api_guide_examples_use_the_site_address(self):
        response = self.client.get('/admin/settings/api/')
        self.assertContains(response, "curl &#x27;%s/api/v1/questions?sort=newest&amp;limit=5&#x27;" % settings.APP_URL)
        self.assertContains(response, 'data-copy-target="#api-example-ask"')

    def test_analytics_snippet_is_gtag(self):
        self.set(settings.GOOGLE_ANALYTICS_KEY, 'G-ABC123XYZ9')
        response = self.client.get('/')
        self.assertContains(response, 'https://www.googletagmanager.com/gtag/js?id=G-ABC123XYZ9')
        self.assertIn('https://www.googletagmanager.com', response['Content-Security-Policy'])


class AdminSearchTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)

    def labels(self, query):
        return [r['label'] for r in admin_search.search(query, [])]

    def test_finds_settings_by_label_help_keywords_and_synonyms(self):
        self.assertEqual(self.labels('logo')[0], 'Application logo')
        self.assertEqual(self.labels('APP_LOGO')[0], 'Application logo')
        self.assertIn('Brand colour', self.labels('color'))
        self.assertIn('Google client ID', self.labels('oauth'))
        self.assertIn('Google client ID', self.labels('login google'))
        self.assertEqual(self.labels('zzzzqx'), [])
        # Accents and case don't matter.
        self.assertEqual(self.labels('LÓGO')[0], 'Application logo')

    def test_every_word_must_match(self):
        self.assertNotIn('Application logo', self.labels('logo secret'))

    def test_marks_words_escaped(self):
        self.assertEqual(str(admin_search.mark('<b> logo', 'logo')), '&lt;b&gt; <mark>logo</mark>')

    def test_page(self):
        self.login(self.admin)
        response = self.client.get('/admin/search/', {'q': 'favicon'})
        self.assertContains(response, 'href="/admin/settings/basic/#setting-APP_FAVICON"')
        self.assertContains(response, '<mark>Favicon</mark>')
        self.assertContains(self.client.get('/admin/'), 'id="admin-search-q"')

    def test_superusers_only(self):
        self.login(self.create_user('moderator', is_staff=True))
        self.assertNotEqual(self.client.get('/admin/search/', {'q': 'logo'}).status_code, 200)
        self.assertNotContains(self.client.get('/admin/moderation/'), 'id="admin-search-q"')


class AppearanceTest(SettingMixin, OSQATestCase):
    def values(self, **changes):
        return dict({'brand': appearance.DEFAULT_BRAND, 'accent': appearance.DEFAULT_ACCENT,
                     'background': 'default', 'font': 'system', 'width': 'standard'}, **changes)

    def test_defaults_write_nothing(self):
        self.assertEqual(appearance.css(self.values()), '')
        self.assertNotContains(self.client.get('/'), 'appearance-style')

    def test_presets_are_readable_as_they_are(self):
        for key, label, brand, accent in appearance.PRESETS:
            self.assertEqual(appearance.adjustments(self.values(brand=brand, accent=accent)), [], key)

    def test_light_colours_are_darkened_and_dark_mode_gets_its_own(self):
        values = self.values(brand='#ffd166', accent='#ffe066')
        colours = appearance.palette(values)
        for name in ('--brand',):
            self.assertGreaterEqual(appearance.contrast(colours['light'][name], '#ffffff'), 4.5)
            self.assertGreaterEqual(appearance.contrast(colours['light'][name], appearance.LIGHT_BACKGROUND), 4.5)
        self.assertGreaterEqual(appearance.contrast(colours['light']['--accent'], '#ffffff'), 4.5)
        self.assertGreaterEqual(appearance.contrast(colours['dark']['--brand'], appearance.DARK_SURFACE), 4.5)
        self.assertGreaterEqual(appearance.contrast(colours['dark']['--button-bg'], '#ffffff'), 4.5)
        self.assertEqual([what for what, _picked, _used in appearance.adjustments(values)], ['brand', 'accent'])
        # A dark colour stays readable on the dark theme too.
        dark = appearance.palette(self.values(brand='#1a1a40'))['dark']
        self.assertGreaterEqual(appearance.contrast(dark['--brand'], appearance.DARK_BACKGROUND), 4.5)

    def test_public_pages_get_the_style(self):
        self.set(settings.THEME_BRAND_COLOR, '#2d6a3e')
        self.set(settings.THEME_FONT, 'serif')
        self.set(settings.THEME_PAGE_WIDTH, 'narrow')
        self.set(settings.THEME_BACKGROUND, 'white')
        response = self.client.get('/')
        self.assertContains(response, '<style id="appearance-style">:root{--brand:#2d6a3e;')
        content = response.content.decode()
        self.assertIn("--font:Charter, 'Bitstream Charter'", content)  # quotes not escaped inside <style>
        self.assertIn('--content-width:960px', content)
        self.assertIn('--background:#ffffff', content)
        self.assertIn(':root[data-theme="dark"]{--brand:', content)
        self.assertContains(response, '<meta name="theme-color" content="#2d6a3e"')

    def test_invalid_colours_are_refused(self):
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(admin)
        response = self.client.post('/admin/settings/appearance/', {
            'THEME_BRAND_COLOR': 'red;}</style><script>', 'THEME_ACCENT_COLOR': '#c2410c', 'THEME_BACKGROUND': 'default',
            'THEME_FONT': 'system', 'THEME_PAGE_WIDTH': 'standard', 'DEFAULT_THEME': 'auto', 'submit': 'Save'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(settings.THEME_BRAND_COLOR), '#2c5aa0')
        # And a stored value that isn't a colour is ignored.
        self.set(settings.THEME_BRAND_COLOR, 'red;}</style>')
        self.assertNotContains(self.client.get('/'), 'appearance-style')

    def test_preview_is_for_the_administrator_only(self):
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(admin)
        self.client.post('/admin/settings/appearance/', {
            'THEME_BRAND_COLOR': '#6b3fa0', 'THEME_ACCENT_COLOR': '#be185d', 'THEME_BACKGROUND': 'default',
            'THEME_FONT': 'system', 'THEME_PAGE_WIDTH': 'standard', 'DEFAULT_THEME': 'auto', 'preview': 'Preview'})
        self.assertContains(self.client.get('/'), '--brand:#6b3fa0')
        self.assertEqual(str(settings.THEME_BRAND_COLOR), '#2c5aa0')
        self.client.logout()
        self.assertNotContains(self.client.get('/'), 'appearance-style')

    def test_theme_for_new_visitors(self):
        self.set(settings.DEFAULT_THEME, 'dark')
        self.assertContains(self.client.get('/'), 'data-theme="dark"')
        # Their own choice still wins.
        self.client.cookies['osqa_theme'] = 'light'
        self.assertContains(self.client.get('/'), 'data-theme="light"')
