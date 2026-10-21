"""Administration pages: statistics, the test email page, dark mode and
layout details of the admin templates."""
import json
import re
from datetime import datetime, timedelta

from django.test import Client

from forum import settings
from forum.models import Question, User
from forum.settings.forms import StringListWidget

from .base import OSQATestCase
from .test_antispam import SettingMixin


class AdminPagesTest(SettingMixin, OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(self.admin)

    def question(self, title, days_ago=0, body='<p>Body text</p>'):
        question = Question(author=self.admin, title=title, body=body, tagnames='one')
        question.save()
        if days_ago:
            Question.objects.filter(id=question.id).update(added_at=datetime.now() - timedelta(days=days_ago))
        return question

    def graph(self, response, graph_id):
        match = re.search(r"osqaTimeChart\('#%s', (\[.*?\])\);" % graph_id, response.content.decode())
        return json.loads(match.group(1))

    def test_statistics_count_every_item(self):
        self.question('An old question', days_ago=60)
        self.question('A recent question')
        self.question('Another recent question')
        response = self.client.get('/admin/statistics/')
        self.assertEqual([n for _, n in self.graph(response, 'questions_graph')], [2, 3])
        # The last point of the users graph is the number of users.
        self.assertEqual(self.graph(response, 'userss_graph')[-1][1], User.objects.count())

    def test_statistics_page_title(self):
        self.assertContains(self.client.get('/admin/statistics/'), '<title>OSQA administration area - Statistics</title>',
                            html=False)

    def test_test_email_page_does_not_send_on_get(self):
        response = self.client.get('/admin/test_email_settings/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sent_mail, [])
        self.assertContains(response, 'id="send-test-email"')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'id="admin-menu"')

    def test_test_email_needs_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post('/admin/test_email_settings/').status_code, 403)
        self.assertEqual(self.sent_mail, [])

    def test_test_email_form_post_shows_full_page(self):
        response = self.client.post('/admin/test_email_settings/')
        self.assertEqual(len(self.sent_mail), 1)
        self.assertContains(response, 'admin@example.com')
        self.assertContains(response, 'id="send-test-email"')

    def test_test_email_other_methods_refused(self):
        self.assertEqual(self.client.put('/admin/test_email_settings/').status_code, 405)
        self.assertEqual(self.sent_mail, [])

    def test_test_email_needs_superuser(self):
        self.login(self.create_user('moderator', is_staff=True))
        self.client.post('/admin/test_email_settings/', **self.AJAX)
        self.assertEqual(self.sent_mail, [])

    def test_dark_mode_follows_the_site_setting(self):
        self.set(settings.DARK_MODE, True)
        response = self.client.get('/admin/')
        self.assertContains(response, 'data-color-scheme="auto"')
        self.assertContains(response, 'css/dark_mode.css')
        self.set(settings.DARK_MODE, False)
        response = self.client.get('/admin/')
        self.assertNotContains(response, 'data-color-scheme')
        self.assertNotContains(response, 'css/dark_mode.css')

    def test_one_layout_with_header_and_menu(self):
        from forum.views.admin import TOOL_LINKS
        TOOL_LINKS.append(('admin_statistics', 'A module tool'))
        self.addCleanup(TOOL_LINKS.pop)
        body = self.client.get('/admin/settings/basic/').content.decode()
        self.assertIn('href="/m/django_admin/css/base.css"', body)
        self.assertIn('/media/style/admin.css', body)
        self.assertNotIn('djstyle', body)
        header = re.search(r'<header id="header">(.*?)</header>', body, re.S).group(1)
        for link in ('href="/"', 'href="/admin/moderation/"', 'href="/logout/"', '>admin<'):
            self.assertIn(link, header)
        menu = re.search(r'<nav id="content-related".*?</nav>', body, re.S).group(0)
        # Every settings page, the moderation pages, the core and module tools.
        from forum.settings.base import Setting
        for name in Setting.sets:
            self.assertIn('href="/admin/settings/%s/"' % name, menu)
        for path in ('/admin/moderation/', '/admin/support/', '/admin/email-previews/', '/admin/static_pages/',
                     '/admin/maintenance/', '/admin/tools/createuser/', '/admin/tools/nodeman/'):
            self.assertIn('href="%s"' % path, menu)
        self.assertIn('A module tool', menu)
        self.assertIn('href="/admin/settings/basic/" aria-current="page"', menu)
        # Groups by task; the one holding this page is open, the others folded.
        self.assertIn('<details id="site-menu" class="module admin-menu-group has-current" data-group="site-menu" open>', menu)
        self.assertIn('<details id="members-menu" class="module admin-menu-group" data-group="members-menu">', menu)
        self.assertNotIn('id="other-sets-menu"', menu)  # every core page has a group

    def test_header_shows_the_moderation_inbox_count(self):
        from forum.actions import FlagAction
        question = self.question('Flag me')
        FlagAction(user=self.create_user('flagger', reputation=500), node=question, extra='spam',
                   ip='127.0.0.1').save()
        header = re.search(r'<header id="header">(.*?)</header>', self.client.get('/admin/').content.decode(),
                           re.S).group(1)
        self.assertRegex(header, r'Moderation inbox <span class="admin-count"[^>]*>1</span>')

    def test_moderators_get_the_moderation_menu_only(self):
        self.login(self.create_user('moderator', is_staff=True))
        body = self.client.get('/admin/moderation/').content.decode()
        menu = re.search(r'<nav id="content-related".*?</nav>', body, re.S).group(0)
        self.assertIn('href="/admin/support/"', menu)
        self.assertNotIn('/admin/settings/', menu)
        self.assertNotIn('/admin/tools/', menu)

    def test_dark_mode_stylesheet_is_served(self):
        response = self.client.get('/m/django_admin/css/dark_mode.css')
        self.assertEqual(response.status_code, 200)

    def test_breadcrumbs_have_no_stray_dash(self):
        for path in ('/admin/', '/admin/tools/createuser/', '/admin/tools/nodeman/', '/admin/tools/exporter/',
                     '/admin/tools/importer/', '/admin/sximporter/'):
            with self.subTest(path=path):
                body = self.client.get(path).content.decode()
                crumbs = re.search(r'<nav class="breadcrumbs"[^>]*>(.*?)</nav>', body, re.S).group(1)
                self.assertNotIn(' - ', re.sub(r'\s+', ' ', crumbs))

    def test_node_manager_summary_escaped_once(self):
        self.question('Exporting', body='<p>Use Export &gt; CSV &amp; <b>more</b> &lt;script&gt;</p>')
        body = self.client.get('/admin/tools/nodeman/').content.decode()
        self.assertIn('Use Export &gt; CSV &amp; more &lt;script&gt;', body)
        self.assertNotIn('&amp;gt;', body)
        self.assertNotIn('<script>', body.split('<body', 1)[1].replace('<script>osqaAdminMenu', ''))

    def test_summary_is_plain_text(self):
        question = Question(title='T', body='<p>A &gt; B &amp; C &lt;i&gt;</p>')
        self.assertEqual(question.summary, 'A > B & C <i>')

    def test_empty_states(self):
        self.assertContains(self.client.get('/admin/static_pages/'), 'There are no custom pages yet.')

    def test_string_list_widget_escapes_values(self):
        html = StringListWidget().render('FLAG_REASONS', ['"><script>alert(1)</script>'])
        self.assertNotIn('<script>', html)
        self.assertIn('&quot;&gt;&lt;script&gt;', html)
        self.assertIn('type="button"', html)
