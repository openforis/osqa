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
                     'background': 'default', 'font': 'system', 'width': 'standard', 'style': 'none'}, **changes)

    def test_defaults_write_nothing(self):
        self.assertEqual(appearance.css(self.values()), '')
        self.assertNotContains(self.client.get('/'), 'appearance-style')

    def test_ten_styles_that_are_readable_as_they_are(self):
        from forum.utils import display
        self.assertEqual(len(appearance.STYLES), 10)
        self.assertEqual(len(appearance.STYLES_BY_KEY), 10)
        for style in appearance.STYLES:
            values = self.values(brand=style.brand, accent=style.accent, background=style.background,
                                 font=style.font, width=style.width, style=style.key)
            self.assertEqual(appearance.adjustments(values), [], style.key)
            self.assertIn(style.font, appearance.FONTS)
            self.assertIn(style.width, appearance.WIDTHS)
            self.assertIn(style.background, appearance.BACKGROUNDS)
            self.assertIn(style.theme, (None,) + display.THEMES)
            self.assertNotIn('<', appearance.css(values))

    def test_open_foris_style(self):
        style = appearance.STYLES_BY_KEY['openforis']
        self.assertEqual((style.brand, style.accent), ('#8f5a5a', '#17798f'))
        css = appearance.css(self.values(brand=style.brand, accent=style.accent, style='openforis'))
        self.assertIn('--brand:#8f5a5a', css)
        self.assertIn('#roof{box-shadow:inset 0 4px 0 var(--brand)}', css)

    def test_a_style_adds_its_rules_only_while_chosen(self):
        self.set(settings.THEME_STYLE, 'minimal')
        self.assertContains(self.client.get('/'), '--shadow:none')
        self.set(settings.THEME_STYLE, 'none')
        self.assertNotContains(self.client.get('/'), '--shadow:none')
        # The classic style is the skin itself: nothing to write.
        self.set(settings.THEME_STYLE, 'classic')
        self.assertNotContains(self.client.get('/'), 'appearance-style')

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


class SettingRowsTest(SettingMixin, OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(self.admin)

    def test_rows_show_the_name_default_and_changed_marker(self):
        self.set(settings.REP_TO_VOTE_UP, 20)
        content = self.client.get('/admin/settings/minrep/').content.decode()
        row = content[content.index('id="setting-REP_TO_VOTE_UP"'):]
        row = row[:row.index('</tr>')]
        self.assertIn('is-customized', row)
        self.assertIn('data-default="15"', row)
        self.assertIn('<span class="setting-changed">Changed</span>', row)
        self.assertIn('<span class="setting-name"', row)
        self.assertIn('<div class="setting-default">Default: <span class="setting-default-value">15</span>', row)
        # At the default: no marker, the default line hidden until the field changes.
        other = content[content.index('id="setting-REP_TO_COMMENT"'):]
        other = other[:other.index('</tr>')]
        self.assertNotIn('setting-changed', other)
        self.assertIn('<div class="setting-default" hidden>', other)
        # The help text is what the field's aria-describedby names.
        self.assertIn('id="id_REP_TO_VOTE_UP_helptext"', row)

    def test_default_texts(self):
        content = self.client.get('/admin/settings/email/').content.decode()
        self.assertIn('data-default="false"', content)  # EMAIL_USE_TLS
        content = self.client.get('/admin/settings/appearance/').content.decode()
        self.assertIn('<span class="setting-default-value">Light grey</span>', content)  # a choice's label

    def test_save_message_names_the_page_and_the_settings(self):
        data = dict((s.name, s.value) for s in Setting.sets['basic'] if not isinstance(s.value, bool))
        data.update({'APP_TITLE': 'Open Foris Support', 'APP_LOGO_old': settings.APP_LOGO.value,
                     'APP_FAVICON_old': settings.APP_FAVICON.value, 'submit': 'Save'})
        response = self.client.post('/admin/settings/basic/', data, follow=True)
        self.assertContains(response, 'Basic settings saved: Application title changed.')
        response = self.client.post('/admin/settings/basic/', data, follow=True)
        self.assertContains(response, 'Basic settings: nothing to save, no setting was changed.')

    def test_the_old_reset_link_is_gone(self):
        # It saved the default on a GET; "Use default" now only fills the field in.
        self.set(settings.APP_TITLE, 'Kept')
        self.assertEqual(self.client.get('/admin/settings/basic/APP_TITLE/').status_code, 404)
        self.assertEqual(str(settings.APP_TITLE), 'Kept')


class SetupChecklistTest(SettingMixin, OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(self.admin)

    def test_items_follow_the_settings(self):
        from forum.utils import setup_checklist
        done = lambda: dict((i['key'], i['done']) for i in setup_checklist.items())
        self.assertFalse(any(done().values()))
        self.set(settings.APP_TITLE, 'Open Foris Support')
        self.set(settings.EMAIL_HOST, 'smtp.example.org')
        self.set(settings.FIRST_POSTS_MODERATION, 'before')
        self.set(settings.THEME_BRAND_COLOR, '#2d6a3e')
        self.assertEqual([k for k, v in done().items() if v], ['name', 'email', 'look', 'spam'])
        self.assertEqual(setup_checklist.checklist()['done'], 4)

    def test_dashboard_shows_hides_and_finishes(self):
        self.assertContains(self.client.get('/admin/'), 'Getting started')
        self.client.post('/admin/', {'checklist': 'hide'})
        response = self.client.get('/admin/')
        self.assertNotContains(response, 'class="admin-guide admin-checklist"')
        self.assertContains(response, 'Show the Getting started list')
        self.client.post('/admin/', {'checklist': 'show'})
        self.assertContains(self.client.get('/admin/'), 'class="admin-guide admin-checklist"')
        # Gone once every required item is done (signing in with providers is optional).
        for setting, value in ((settings.APP_TITLE, 'Site'), (settings.EMAIL_HOST, 'smtp.example.org'),
                               (settings.APP_LOGO, '/upfiles/mine.png'), (settings.THEME_FONT, 'serif'),
                               (settings.ABOUT_PAGE_TEXT, 'About us'), (settings.FIRST_POSTS_MODERATION, 'after')):
            self.set(setting, value)
        self.assertNotContains(self.client.get('/admin/'), 'class="admin-guide admin-checklist"')

    def test_moderators_neither_see_nor_change_it(self):
        moderator = self.create_user('moderator', is_staff=True)
        self.login(moderator)
        self.assertNotContains(self.client.get('/admin/'), 'Getting started')
        self.client.post('/admin/', {'checklist': 'hide'})
        self.assertFalse(settings.SETUP_CHECKLIST_HIDDEN.value)


class AdminMenuTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(self.admin)

    def groups(self, path='/admin/'):
        return self.client.get(path).context['admin_menu']

    def test_every_settings_page_is_in_a_task_group(self):
        from forum.settings.base import Setting
        groups = self.groups()
        titles = [str(g['title']) for g in groups]
        self.assertEqual(titles, ['Moderation', 'Site', 'Members and permissions', 'Questions and answers',
                                  'Look and feel', 'Pages', 'Integrations', 'Tools'])
        urls = [i['url'] for g in groups for i in g['items']]
        for name in Setting.sets:
            self.assertIn('/admin/settings/%s/' % name, urls)
        self.assertEqual(len(urls), len(set(urls)))

    def test_open_group_and_folded_count(self):
        from forum.actions import FlagAction
        from forum.models import Question
        question = Question(author=self.admin, title='Flag me please', body='<p>Body text</p>', tagnames='one')
        question.save()
        FlagAction(user=self.create_user('flagger', reputation=500), node=question, extra='spam',
                   ip='127.0.0.1').save()
        groups = dict((g['id'], g) for g in self.groups('/admin/settings/minrep/'))
        self.assertTrue(groups['members-menu']['open'])
        self.assertFalse(groups['moderation-menu']['open'])
        self.assertEqual(groups['moderation-menu']['count'], 1)
        # On the dashboard, where no group holds the page, the moderation one is open.
        self.assertTrue(dict((g['id'], g) for g in self.groups())['moderation-menu']['open'])

    def test_clearer_page_names(self):
        labels = [str(i['label']) for g in self.groups() for i in g['items']]
        for name in ('Members', 'Privileges', 'Reputation points', 'Badges', 'Asking and answering', 'Display',
                     'File uploads', 'Custom pages'):
            self.assertIn(name, labels)
        for old in ('Users settings', 'Minimum reputation config', 'Reputation gains and losses config'):
            self.assertNotIn(old, labels)
