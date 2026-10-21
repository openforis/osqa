"""Administrators' tools: static pages, statistics, recalculating counts,
bootstrap mode, resetting a setting to its default, testing the email
settings, resolving automated moderation reports, XML backups, the Stack
Exchange importer, and signing in with an OAuth 2.0 provider (GitHub,
Google) and managing the providers linked to an account."""
import os
import re
import shutil
import tempfile
import urllib.parse
import zipfile
from unittest import mock

from django.urls import reverse

from forum import settings
from forum.models import AuthKeyUserAssociation, ModerationReport, Page, Question, User
from forum.settings.base import Setting

from .base import E2ETestCase


class AdminTestCase(E2ETestCase):
    def submit(self, page, selector):
        """Clicks a button that submits a form, and checks the next page."""
        with page.expect_navigation():
            page.click(selector)
        self.check_page(page)

    def menu(self, page, name):
        """Follows a link of the administration menu on the dashboard (folded
        into an "Admin menu" disclosure on a phone, so it is opened first, and
        its group too when folded)."""
        self.visit(page, '/admin/')
        menu = page.locator('#admin-menu')
        if not menu.evaluate('details => details.open'):
            page.click('#admin-menu > summary')
        link = menu.locator('a').filter(has_text=re.compile(r'^\s*%s\s*$' % re.escape(name)))
        if not link.is_visible():  # in a folded group: open it
            link.locator('xpath=ancestor::details[1]/summary').click()
        with page.expect_navigation():
            link.click()
        self.check_page(page)


class AdminToolsTest(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', reputation=1000, is_superuser=True, is_staff=True)
        self.alice = self.create_user('alice', reputation=100)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?')

    def test_static_pages(self):
        page = self.open(self.admin)
        self.menu(page, 'Custom pages')
        with page.expect_navigation():
            page.get_by_role('link', name='New page').click()
        self.check_page(page)
        page.fill('#id_title', 'Field guide')
        page.fill('#id_path', 'pages/field-guide/')
        page.fill('#id_content', 'How to collect data **in the field**.')
        self.submit(page, '#publish')
        created = Page.objects.get(title='Field guide')
        self.assertTrue(created.published)
        self.assertEqual(page.url, self.url(reverse('admin_edit_page', kwargs={'id': created.id})))

        visitor = self.open()
        self.visit(visitor, '/pages/field-guide/')
        self.assertIn('in the field', visitor.locator('strong').all_inner_texts())

        page.fill('#id_title', 'Field guide for enumerators')
        self.submit(page, '#submit')
        self.assertEqual(Page.objects.get(id=created.id).title, 'Field guide for enumerators')
        self.visit(visitor, '/pages/field-guide/')
        self.assertIn('Field guide for enumerators', visitor.content())

        self.menu(page, 'Custom pages')
        self.assertIn('Field guide for enumerators', page.content())
        self.submit(page, 'form[action="%s"] button' % reverse('admin_delete_page', kwargs={'id': created.id}))
        self.assertFalse(Page.objects.filter(id=created.id).exists())
        self.assertNotIn('Field guide', page.content())
        self.assertEqual(visitor.goto(self.url('/pages/field-guide/')).status, 404)
        visitor.problems.clear()

    def test_statistics_on_a_phone(self):
        page = self.open(self.admin, device='mobile', dark=True)
        self.visit(page, '/admin/')
        # The menu starts folded on a phone, links hidden but kept.
        self.assertFalse(page.locator('#admin-menu').evaluate('details => details.open'))
        self.assertFalse(page.get_by_role('link', name='Statistics', exact=True).is_visible())
        self.menu(page, 'Statistics')
        self.assertEqual(page.url, self.url(reverse('admin_statistics')))
        # Flot draws each graph on a canvas.
        for graph in ('#questions_graph', '#userss_graph'):
            page.wait_for_selector(graph + ' canvas')

    def test_email_previews(self):
        page = self.open(self.admin)
        self.menu(page, 'Email previews')
        self.assertEqual(page.url, self.url(reverse('admin_email_previews')))
        listed = page.locator('.email-previews').inner_text()
        for name in ('New answer', 'Mention', 'Daily digest', 'Welcome', 'Password reset'):
            self.assertIn(name, listed)
        self.assertIn('New answer to: How do I export survey data to CSV?', listed)
        with page.expect_navigation():
            page.get_by_role('link', name='New answer', exact=True).click()
        self.check_page(page)
        self.assertEqual(page.url, self.url(reverse('admin_email_preview', kwargs={'kind': 'new-answer'})))
        frame = page.frame_locator('iframe.email-preview-frame')
        self.assertEqual(frame.get_by_role('link', name='View the answer').count(), 1)
        self.assertIn('Hi admin,', frame.locator('body').inner_text())
        self.assertIn('Unsubscribe from all emails', page.locator('.email-preview-text').inner_text())
        self.check_page(page)
        self.assertEqual(self.sent_mail, [])

        # On a phone, in dark mode: the list, a preview and the email itself fit the screen.
        phone = self.open(self.admin, device='mobile', dark=True)
        self.visit(phone, reverse('admin_email_previews'))
        with phone.expect_navigation():
            phone.get_by_role('link', name='Mention', exact=True).click()
        self.check_page(phone)
        frame = phone.frame_locator('iframe.email-preview-frame')
        self.assertIn('@admin', frame.locator('.em-quote').inner_text())
        self.visit(phone, reverse('admin_email_preview', kwargs={'kind': 'digest'}) + '?format=html')
        self.assertEqual(phone.get_by_role('link', name='See all new questions').count(), 1)
        # The dark-mode styles of the email apply.
        self.assertEqual(phone.locator('.em-card').evaluate('el => getComputedStyle(el).backgroundColor'),
                         'rgb(22, 27, 34)')
        self.visit(phone, reverse('admin_email_preview', kwargs={'kind': 'welcome'}) + '?format=text')
        self.assertIn('Confirm your email:', phone.locator('body').inner_text())

        # Not for members.
        member = self.open(self.alice)
        self.assertEqual(member.goto(self.url(reverse('admin_email_previews'))).status, 403)
        member.problems.clear()

    def test_recalculate_counts(self):
        # Counts gone wrong: a score with no votes, reputation with no history.
        Question.objects.filter(id=self.question.id).update(score=7)
        User.objects.filter(id=self.alice.id).update(reputation=12345)
        page = self.open(self.admin)
        self.visit(page, '/admin/')
        self.submit(page, 'form[action="%s"] button' % reverse('admin_denormalize'))
        self.assertIn('All values recalculated', page.content())
        self.assertEqual(Question.objects.filter(id=self.question.id).values_list('score', flat=True)[0], 0)
        self.assertEqual(User.objects.filter(id=self.alice.id).values_list('reputation', flat=True)[0],
                         sum(self.alice.reputes.values_list('value', flat=True)))

    def test_bootstrap_mode_and_back_to_defaults(self):
        for name in ('badges', 'minrep', 'repgain'):  # in-process copies of the values
            for setting in Setting.sets[name]:
                self.addCleanup(setattr, setting, '_temp', None)
        self.addCleanup(setattr, settings.SETTINGS_PACK, '_temp', None)

        page = self.open(self.admin)
        self.visit(page, '/admin/')
        self.assertIn('running in standard mode', page.content())
        self.submit(page, 'form[action="%s"] button' % reverse('admin_go_bootstrap'))
        self.assertIn('Bootstrap mode enabled', page.content())
        self.assertEqual(settings.SETTINGS_PACK.value, 'bootstrap')
        self.assertEqual(settings.REP_TO_VOTE_UP.value, 0)
        self.assertEqual(settings.REP_TO_COMMENT.value, 0)

        self.submit(page, 'form[action="%s"] button' % reverse('admin_go_defaults'))
        self.assertIn('All values reverted to defaults', page.content())
        self.assertEqual(settings.SETTINGS_PACK.value, 'default')
        self.assertEqual(settings.REP_TO_VOTE_UP.value, settings.REP_TO_VOTE_UP.default)
        self.assertEqual(settings.REP_TO_COMMENT.value, settings.REP_TO_COMMENT.default)
        self.assertIn('running in standard mode', page.content())

    def test_reset_a_setting_to_its_default(self):
        self.set_setting(settings.APP_TITLE, 'Open Foris Q&A')
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/basic/')
        row = page.locator('#setting-APP_TITLE')
        self.assertEqual(page.input_value('#id_APP_TITLE'), 'Open Foris Q&A')
        self.assertEqual(row.locator('.setting-changed').inner_text(), 'Changed')
        self.assertIn(settings.APP_TITLE.default, row.locator('.setting-default').inner_text())
        # Settings at their default offer no reset.
        self.assertFalse(page.locator('#setting-APP_SHORT_NAME .setting-default').is_visible())

        # "Use default" fills the field in; nothing is saved before Save.
        row.locator('.setting-reset').click()
        self.assertEqual(page.input_value('#id_APP_TITLE'), settings.APP_TITLE.default)
        self.assertIn('is-dirty', row.get_attribute('class'))
        self.assertEqual(page.locator('.admin-unsaved-status').inner_text(), '1 unsaved change')
        self.assertFalse(row.locator('.setting-default').is_visible())
        settings.APP_TITLE._temp = None
        self.assertEqual(settings.APP_TITLE.value, 'Open Foris Q&A')
        self.submit(page, '#submit')
        self.assertIn('Basic settings saved: Application title changed.', page.content())
        settings.APP_TITLE._temp = None
        self.assertEqual(settings.APP_TITLE.value, settings.APP_TITLE.default)
        self.assertEqual(page.locator('#setting-APP_TITLE .setting-changed').count(), 0)

        # A check box too.
        self.set_setting(settings.EMAIL_USE_TLS, True)
        self.visit(page, '/admin/settings/email/')
        self.assertTrue(page.is_checked('#id_EMAIL_USE_TLS'))
        page.locator('#setting-EMAIL_USE_TLS .setting-reset').click()
        self.assertFalse(page.is_checked('#id_EMAIL_USE_TLS'))
        self.submit(page, '#submit')
        settings.EMAIL_USE_TLS._temp = None
        self.assertFalse(settings.EMAIL_USE_TLS.value)

    def test_test_email_settings(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/email/')
        page.click('#test_email_settings a.test_button')
        page.wait_for_selector('#test_email_settings .test_status:has-text("admin@example.com")')
        self.check_page(page)
        self.assertEqual(len(self.mail_to(self.admin)), 1)

        # Visiting the URL explains the test and sends nothing until the button is pressed.
        phone = self.open(self.admin, device='mobile', dark=True)
        self.visit(phone, reverse('test_email_settings'))
        self.assertEqual(len(self.mail_to(self.admin)), 1)
        self.submit(phone, '#send-test-email')
        self.assertIn('The email server accepted the test message', phone.content())
        self.assertEqual(len(self.mail_to(self.admin)), 2)


class ModerationReportTest(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.moderator = self.create_user('moderator', reputation=10, is_staff=True)
        self.alice = self.create_user('alice', reputation=100)
        self.question = self.create_question(self.alice, 'Cheap watches at a great discount, buy now')

    def test_delete_a_reported_post(self):
        report = ModerationReport.objects.create(node=self.question, source='ai', verdict='spam', confidence=0.93,
                                                 reason='Advertises watches.')
        page = self.open(self.moderator)
        self.visit(page, reverse('admin_flagged_posts'))
        self.assertIn('Advertises watches.', page.locator('.moderation-reports').inner_text())
        form = 'form[action="%s"]' % reverse('admin_resolve_moderation_report', kwargs={'id': report.id})
        with page.expect_navigation():
            page.click(form + ' button[value=delete]')
        self.check_page(page)
        self.assertIn('The post has been deleted.', page.content())
        report.refresh_from_db()
        self.assertEqual(report.resolution, 'deleted')
        self.assertEqual(report.resolved_by, self.moderator)
        self.assertTrue(Question.objects.get(id=self.question.id).nis.deleted)
        self.assertEqual(page.locator('.moderation-reports').count(), 0)

    def test_suspend_a_reported_account_on_a_phone(self):
        spammer = self.create_user('spammer', website='http://watches.example.com')
        report = ModerationReport.objects.create(user=spammer, source='ai', verdict='spam', confidence=0.8,
                                                 reason='Spam links in the profile.')
        page = self.open(self.moderator, device='mobile', dark=True)
        self.visit(page, reverse('admin_flagged_posts'))
        form = 'form[action="%s"]' % reverse('admin_resolve_moderation_report', kwargs={'id': report.id})
        with page.expect_navigation():
            page.click(form + ' button[value=suspend]')
        self.check_page(page)
        self.assertIn('The account spammer has been suspended.', page.content())
        report.refresh_from_db()
        self.assertEqual(report.resolution, 'suspended')
        self.assertTrue(User.objects.get(id=spammer.id).is_suspended())


class BackupTest(AdminTestCase):
    def setUp(self):
        super().setUp()
        from forum_modules.exporter import settings as exporter_settings
        self.admin = self.create_user('admin', reputation=1000, is_superuser=True, is_staff=True)
        self.alice = self.create_user('alice', reputation=100)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?')
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.set_setting(exporter_settings.EXPORTER_BACKUP_STORAGE, os.path.join(self.folder, 'backups'))
        os.makedirs(os.path.join(self.folder, 'backups'))

    def download(self, page, selector):
        with page.expect_download() as info:
            page.click(selector)
        path = os.path.join(self.folder, 'download-%d.zip' % len(os.listdir(self.folder)))
        info.value.save_as(path)
        self.assertGreater(os.path.getsize(path), 0)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            self.assertIn('backup.inf', names)
            questions = [n for n in names if n.endswith('.xml') and 'node' in n.lower()]
            self.assertTrue(questions, names)
            self.assertIn(self.question.title, archive.read(questions[0]).decode('utf-8'))

    def test_export_and_download_a_backup(self):
        page = self.open(self.admin)
        self.menu(page, 'XML data export')
        page.select_option('#id_file_format', 'zip')
        page.uncheck('#id_uplodaded_files')
        with page.expect_navigation():
            page.click('input[name=start]')
        self.check_page(page)
        self.assertEqual(page.url, self.url(reverse('exporter_running', kwargs={'mode': 'exporter'})))
        # The running page polls the export's state until the file is ready.
        page.wait_for_selector('#download_link_a', state='visible', timeout=60000)
        self.assertIn('ready to be downloaded', page.locator('#wait_message').inner_text())
        self.check_page(page)
        self.download(page, '#download_link_a')

        # The backup is listed on the export page from then on.
        self.visit(page, reverse('admin_tools', kwargs={'name': 'exporter'}))
        self.download(page, 'a[href^="%s"]' % reverse('exporter_download'))
        self.check_page(page)

    def test_stack_exchange_importer(self):
        page = self.open(self.admin)
        self.menu(page, 'Stack Exchange import')
        self.assertEqual(page.url, self.url(reverse('sximporter')))
        self.assertIn('Stack Exchange dump importer', page.content())
        page.set_input_files('input[name=dump]', files=[
            {'name': 'dump.zip', 'mimeType': 'application/zip', 'buffer': b'not a zip file'}])
        self.submit(page, 'input[type=submit]')
        self.assertIn('The dump is not a zip file.', page.content())


class ExternalSignInTest(AdminTestCase):
    """OAuth 2.0 sign-in. The provider's pages are answered by the browser
    (redirecting straight back with a code) and its API calls are mocked:
    the live server runs in this process."""
    PROFILES = {
        'github': ({'access_token': 'gh-token'}, {'id': 4242, 'login': 'octofield', 'name': 'Octo Field',
                                                   'email': None},
                   [{'email': 'octo@example.com', 'primary': True, 'verified': True}]),
        'google': ({'access_token': 'g-token'}, {'sub': '1077', 'given_name': 'Octo', 'name': 'Octo Field',
                                                  'email': 'octo@example.com', 'email_verified': True}),
    }

    def setUp(self):
        super().setUp()
        from forum_modules.oauth2auth import settings as oauth_settings
        self.create_user('admin', is_superuser=True, is_staff=True)  # the first account becomes the owner
        for name in ('GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'):
            self.set_setting(getattr(oauth_settings, name), 'fake-%s' % name.lower())
        self.api_calls = []
        self._patch(mock.patch('forum_modules.oauth2auth.authentication.http_json', self.fake_api))

    def fake_api(self, url, data=None, headers=None):
        self.api_calls.append(url)
        provider = 'github' if 'github' in url else 'google'
        token, user = self.PROFILES[provider][:2]
        if data is not None:  # the code for a token
            self.assertEqual(data['code'], 'code-for-%s' % provider)
            return token
        if url.endswith('/user/emails'):
            return self.PROFILES['github'][2]
        return user

    def provider_answers(self, page):
        """The provider's authorization page sends the browser straight back
        with a code. (Playwright routes the forum's redirect, not the
        request to the provider it leads to.)"""
        def answer(route):
            response = route.fetch(max_redirects=0)
            location = response.headers.get('location', '')
            if not location.startswith(('https://github.com/', 'https://accounts.google.com/')):
                return route.fulfill(response=response)
            provider = 'github' if location.startswith('https://github.com/') else 'google'
            state = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)['state'][0]
            back = '%s%s?%s' % (self.live_server_url, reverse('auth_provider_done', kwargs={'provider': provider}),
                                urllib.parse.urlencode({'code': 'code-for-%s' % provider, 'state': state}))
            route.fulfill(response=response, headers=dict(response.headers, location=back))
        page.route('**/account/*/signin/**', answer)

    def test_sign_up_with_github_then_link_and_unlink_google(self):
        page = self.open()
        self.provider_answers(page)
        self.visit(page, '/account/signin/')
        with page.expect_navigation(url='**/account/register/'):
            page.click('a.oauth2_button[href^="/account/github/signin/"]')
        self.check_page(page)
        # The registration form is filled in from the GitHub profile.
        self.assertEqual(page.input_value('#id_username'), 'octofield')
        self.assertEqual(page.input_value('#id_email'), 'octo@example.com')
        self.assertEqual(page.locator('#id_username_validation_sum').count(), 0)  # no puzzle (WCAG 2.2 3.3.8)
        self.submit(page, '#bnewaccount')
        user = User.objects.get(username='octofield')
        self.assertTrue(user.email_isvalid)  # GitHub verified the address
        self.assertEqual(list(user.auth_keys.values_list('key', flat=True)), ['github:4242'])
        self.assertIn('https://github.com/login/oauth/access_token', self.api_calls)
        self.assertIn('octofield', page.locator('#top').inner_text())

        # Link Google to the same account from the authentication settings.
        self.visit(page, reverse('user_authsettings', kwargs={'id': user.id}))
        self.assertIn('GitHub', page.locator('#main-body, body').first.inner_text())
        with page.expect_navigation():
            page.click('a[href="%s"]' % reverse('user_add_external_provider'))
        self.check_page(page)
        self.assertEqual(page.url, self.url(reverse('user_add_external_provider')))
        with page.expect_navigation(url='**%s' % reverse('user_authsettings', kwargs={'id': user.id})):
            page.click('a.oauth2_button[href^="/account/google/signin/"]')
        self.check_page(page)
        self.assertIn('now associated with your account', page.content())
        self.assertEqual(sorted(user.auth_keys.values_list('key', flat=True)), ['github:4242', 'google:1077'])

        # Remove the GitHub link.
        github = AuthKeyUserAssociation.objects.get(user=user, provider='github')
        self.submit(page, 'form[action="%s"] button' % reverse('user_remove_external_provider',
                                                               kwargs={'id': github.id}))
        self.assertIn('You removed the association with github', page.content())
        self.assertEqual(list(user.auth_keys.values_list('key', flat=True)), ['google:1077'])

        # Signed out, Google signs the same person back in.
        page.context.clear_cookies()
        self.visit(page, '/account/signin/')
        with page.expect_navigation(url=self.url('/') + '**'):
            page.click('a.oauth2_button[href^="/account/google/signin/"]')
        self.check_page(page)
        self.assertIn('octofield', page.locator('#top').inner_text())
