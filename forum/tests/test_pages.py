from forum.actions import CloseAction, VoteUpAction
from forum.models import Question

from .base import OSQATestCase


class AnonymousPagesTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user('alice')
        self.question = Question(author=self.user, title='A question title', body='Body text', tagnames='one')
        self.question.save()

    def test_pages_render(self):
        for url in ['/', '/questions/', '/questions/unanswered/', '/tags/', '/users/', '/badges/',
                    '/account/signin/', '/cstyle.css', self.question.get_absolute_url(),
                    self.user.get_profile_url()]:
            with self.subTest(url=url):
                self.assertCleanPage(self.client.get(url))

    def test_question_list_links_to_question(self):
        response = self.client.get('/questions/')
        self.assertContains(response, 'href="%s"' % self.question.get_absolute_url())

    def test_phone_tab_bar_answer_and_share(self):
        # Open questions: Answer in the middle of the phone's tab bar, Share in the controls.
        page = self.client.get(self.question.get_absolute_url())
        self.assertContains(page, 'id="app-bar-answer" href="#fmanswer"')
        self.assertNotContains(page, 'id="app-bar-ask"')
        self.assertContains(page, 'post-share" href="%s"' % self.question.get_absolute_url())
        self.assertContains(page, 'id="app-back"')
        # Closed ones take no answers: Ask stays. Other pages have Ask, and the home page no Back.
        staff = self.create_user('staff', is_staff=True, is_superuser=True)
        CloseAction(user=staff, node=self.question, extra='off topic', ip='127.0.0.1').save()
        page = self.client.get(self.question.get_absolute_url())
        self.assertContains(page, 'id="app-bar-ask"')
        self.assertNotContains(page, 'id="app-bar-answer"')
        home = self.client.get('/')
        self.assertContains(home, 'id="app-bar-ask"')
        self.assertNotContains(home, 'id="app-back"')

    def test_custom_header_can_stay_off_phones(self):
        from forum import settings
        saved = [(s, s.value) for s in (settings.USE_CUSTOM_HEADER, settings.CUSTOM_HEADER,
                                          settings.CUSTOM_HEADER_RENDER_MODE, settings.CUSTOM_HEADER_ON_PHONES)]
        try:
            settings.USE_CUSTOM_HEADER.set_value(True)
            settings.CUSTOM_HEADER.set_value('<a href="https://www.openforis.org">Back to Open Foris</a>')
            settings.CUSTOM_HEADER_RENDER_MODE.set_value('html')
            self.assertContains(self.client.get('/'), '<div id="custom_header">')
            settings.CUSTOM_HEADER_ON_PHONES.set_value(False)
            page = self.client.get('/')
            self.assertContains(page, '<div id="custom_header" class="custom-header-wide-only">')
            self.assertContains(page, 'Back to Open Foris')  # still there for wider screens (osqa.css hides it on phones)
        finally:
            for setting, value in saved:
                setting.set_value(value)

    def test_feed_and_sitemap(self):
        self.assertContains(self.client.get('/feeds/rss/'), 'A question title')
        self.assertContains(self.client.get('/sitemap.xml'), 'http://testserver/sitemap-questions.xml')


class PaginationTest(OSQATestCase):
    def test_later_pages(self):
        user = self.create_user('alice')
        # 8 pages of 15: the page links around page 4 are computed from
        # visible_page_range / 2, which must stay an integer.
        for i in range(106):
            Question(author=user, title='Question number %d title' % i, body='Body text', tagnames='one').save()

        for page in (1, 4, 8):
            with self.subTest(page=page):
                self.assertCleanPage(self.client.get('/questions/?page=%d&pagesize=15' % page))

    def test_reputation_tab_with_history(self):
        alice = self.create_user('alice')
        bob = self.create_user('bob', reputation=1000)
        question = Question(author=alice, title='A question title', body='Body text', tagnames='one')
        question.save()
        VoteUpAction(user=bob, node=question, ip='127.0.0.1').save()

        self.assertTrue(alice.reputes.exists())
        self.assertCleanPage(self.client.get(alice.get_profile_url() + '/reputation/'))


class RobotsTxtTest(OSQATestCase):
    def test_robots_txt(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')


class LayoutTest(OSQATestCase):
    def test_mobile_viewport_and_stylesheet(self):
        response = self.client.get('/')
        self.assertContains(response, '<!DOCTYPE html>')
        # viewport-fit=cover: the phone tab bar keeps clear of rounded corners and the home indicator.
        self.assertContains(response, '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />')
        self.assertContains(response, '/media/style/osqa.css')
        self.assertNotContains(response, 'http://www.google.com/jsapi')
        # jQuery is served by the site itself, and every page carries the
        # CSRF token for the AJAX commands.
        self.assertContains(response, '/media/vendor/jquery-3.7.1.min.js')
        self.assertNotContains(response, 'ajax.googleapis.com')
        self.assertRegex(response.content.decode(), r'<meta name="csrf-token" content="\w{32,}" />')
        for path in ('/m/default/media/vendor/jquery-3.7.1.min.js',
                     '/m/default/media/js/osqa.csrf.js', '/m/default/media/vendor/jquery-ui-1.14.1/jquery-ui.min.js'):
            with self.subTest(path=path):
                asset = self.client.get(path)
                self.assertEqual(asset.status_code, 200)
                asset.close()

    def test_dark_mode_setting(self):
        from forum import settings
        self.addCleanup(setattr, settings.DARK_MODE, '_temp', None)

        self.assertContains(self.client.get('/'), 'data-color-scheme="auto"')

        settings.DARK_MODE.set_value(False)
        response = self.client.get('/')
        self.assertNotContains(response, 'data-color-scheme')
        self.assertNotContains(response, 'name="color-scheme"')

    def test_logo_url_has_no_double_slash(self):
        from forum import settings
        self.addCleanup(setattr, settings.APP_LOGO, '_temp', None)
        for value, src in [('/upfiles/logo.png', 'src="/upfiles/logo.png"'),
                           ('upfiles/logo.png', 'src="/upfiles/logo.png"'),
                           ('https://cdn.example.org/logo.png', 'src="https://cdn.example.org/logo.png"')]:
            with self.subTest(value=value):
                settings.APP_LOGO.set_value(value)
                self.assertContains(self.client.get('/'), src)

    def test_search_box(self):
        from forum import settings
        self.addCleanup(setattr, settings.GOOGLE_CSE_ID, '_temp', None)

        response = self.client.get('/')
        self.assertContains(response, 'name="q" id="keywords"')
        self.assertContains(response, 'role="combobox"')
        self.assertContains(response, 'aria-controls="searchbox-listbox"')
        self.assertContains(response, 'data-suggest-url="/search/suggest/"')
        self.assertContains(response, 'placeholder="Search questions, tags and people"')
        self.assertNotContains(response, '<select name="t"')
        # The tags page's filter isn't a question search.
        self.assertNotContains(self.client.get('/tags/', {'q': 'gis'}), 'id="keywords" value="gis"')
        self.assertContains(self.client.get('/search/', {'q': 'gis'}), 'id="keywords" value="gis"')
        # Old links with t=tag still work.
        self.assertRedirects(self.client.get('/search/', {'q': 'gis', 't': 'tag'}), '/tags/?q=gis',
                             fetch_redirect_response=False)

        # A Google custom search engine ID left in the database is ignored.
        settings.GOOGLE_CSE_ID.set_value('123:abc')
        response = self.client.get('/')
        self.assertContains(response, 'id="keywords"')
        self.assertNotContains(response, 'cse.google.com')
        self.assertNotContains(response, '123:abc')
        self.assertNotIn('google.com/cse', response['Content-Security-Policy'])
        self.assertNotIn('*.google.com', response['Content-Security-Policy'])

    def test_google_cse_setting_not_in_admin(self):
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(admin)
        response = self.client.get('/admin/settings/extkeys/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'GOOGLE_ANALYTICS_KEY')
        self.assertNotContains(response, 'GOOGLE_CSE_ID')


class AdminInterfaceTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        admin = self.create_user('admin')
        admin.is_superuser = True
        admin.save()
        self.login(admin)

    def test_django_style_admin_assets_are_served(self):
        page = self.client.get('/admin/settings/basic/')
        self.assertCleanPage(page)
        self.assertContains(page, 'href="/m/django_admin/css/base.css"')

        for path in ('css/base.css', 'css/responsive.css', 'js/core.js', 'img/icon-alert.svg'):
            with self.subTest(path=path):
                response = self.client.get('/m/django_admin/' + path)
                self.assertEqual(response.status_code, 200)
                response.close()
        with self.assertLogs('django.security', level='ERROR'):
            self.assertEqual(self.client.get('/m/django_admin/../../__init__.py').status_code, 400)

    def test_old_layout_switch_redirects_to_the_dashboard(self):
        for query in ('?to=default', '?to=djstyle', ''):
            with self.subTest(query=query):
                response = self.client.get('/admin/switch_interface/' + query)
                self.assertRedirects(response, '/admin/')
        page = self.client.get('/admin/')
        self.assertNotContains(page, 'switch_interface')
        self.assertNotContains(page, 'standard interface')

    def test_node_manager(self):
        page = self.client.get('/admin/tools/nodeman/')
        self.assertCleanPage(page)
        self.assertContains(page, 'class="changelist-form-container"')
        self.assertNotContains(page, "{% static")


class ErrorPageTest(OSQATestCase):
    def test_not_found_page_renders_with_request(self):
        # The footer's feedback link needs the request; without it the
        # registry logged a KeyError on every 404.
        with self.assertNoLogs(level='ERROR'):
            response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, '/contact/?next=%2Fno-such-page%2F', status_code=404)
        self.assertNotContains(response, 'linkhelp.clients.google.com', status_code=404)


class SidebarDefaultsMigrationTest(OSQATestCase):
    def run_migration(self):
        import importlib
        from django.apps import apps
        migration = importlib.import_module('forum.migrations.0007_remove_dead_sidebar_defaults')
        migration.hide_old_default_blocks(apps, None)
        return migration

    def test_old_default_blocks_are_hidden_and_edited_ones_kept(self):
        from forum.models import KeyValue
        import importlib
        old = importlib.import_module('forum.migrations.0007_remove_dead_sidebar_defaults').OLD_DEFAULTS

        # Saved through the admin form: same text, different line endings.
        KeyValue(key='SIDEBAR_UPPER_TEXT', value=old['SIDEBAR_UPPER'].replace('\n', '\r\n')).save()
        KeyValue(key='SIDEBAR_UPPER_SHOW', value=True).save()
        KeyValue(key='SIDEBAR_LOWER_TEXT', value='## Our community rules').save()
        KeyValue(key='SIDEBAR_LOWER_SHOW', value=True).save()

        self.run_migration()

        values = {kv.key: kv.value for kv in KeyValue.objects.filter(key__startswith='SIDEBAR_')}
        self.assertEqual(values['SIDEBAR_UPPER_TEXT'], '')
        self.assertIs(values['SIDEBAR_UPPER_SHOW'], False)
        self.assertEqual(values['SIDEBAR_LOWER_TEXT'], '## Our community rules')
        self.assertIs(values['SIDEBAR_LOWER_SHOW'], True)

    def test_new_site_shows_no_dead_blocks(self):
        response = self.client.get('/')
        self.assertNotContains(response, 'webfaction')
        self.assertNotContains(response, 'osqa.net')


class GravatarTagTest(OSQATestCase):
    def test_alt_text_is_the_escaped_username(self):
        from forum.templatetags.extra_tags import gravatar
        html = gravatar({'gravatar': 'abc', 'username': 'José <b>'}, 32)
        self.assertIn('alt="José &lt;b&gt;"', html)
        self.assertIn('loading="lazy"', html)
