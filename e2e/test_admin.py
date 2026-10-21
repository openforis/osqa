"""Moderators (staff) and administrators (superusers): moderation tools,
the support dashboard, every settings page, maintenance mode, user
management, and what ordinary users are kept out of."""

from django.test import override_settings
from django.urls import reverse

from forum import settings
from forum.models import Answer, Question, User

from .base import E2ETestCase


class ModerationTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.moderator = self.create_user('moderator', reputation=10, is_staff=True)
        self.alice = self.create_user('alice', reputation=100)
        self.bob = self.create_user('bob', reputation=100)
        self.question = self.create_question(self.alice, 'Cheap watches at a great discount, buy now')
        self.original = self.create_question(self.bob, 'How do I export Collect survey data to CSV?')
        self.answer = self.create_answer(self.bob, self.question, 'Buy now at example dot com, best prices.')

    def test_close_as_duplicate_reopen_and_delete(self):
        page = self.open(self.moderator)
        self.visit(page, self.question.get_absolute_url())
        page.click('#node-%d-menu-trigger' % self.question.id)
        page.click('a[href="%s"]' % reverse('close', kwargs={'id': self.question.id}))
        self.confirm_dialog(page, {'#close-duplicate-of': str(self.original.id)})
        question = Question.objects.get(id=self.question.id)
        self.assertTrue(question.nis.closed)
        self.assertEqual(question.duplicate_of.id, self.original.id)
        self.visit(page, self.question.get_absolute_url())
        self.assertIn(self.original.title, page.content())

        page.click('#node-%d-menu-trigger' % self.question.id)
        self.click_command(page, 'a[href="%s"]' % reverse('reopen', kwargs={'id': self.question.id}))
        self.assertFalse(Question.objects.get(id=self.question.id).nis.closed)

        self.visit(page, self.question.get_absolute_url())
        page.click('#node-%d-menu-trigger' % self.answer.id)
        page.click('a[href="%s"]' % reverse('delete_post', kwargs={'id': self.answer.id}))
        self.confirm_dialog(page)
        self.assertTrue(Answer.objects.get(id=self.answer.id).nis.deleted)

    def test_flagged_posts_and_support_dashboard(self):
        flagger = self.create_user('flagger', reputation=500)
        page = self.open(flagger)
        self.visit(page, self.question.get_absolute_url())
        page.click('#node-%d-menu-trigger' % self.question.id)
        page.click('a[href^="/flag/%d/"]' % self.question.id)
        self.confirm_dialog(page, {'textarea[name=prompt]': 'spam'})

        page = self.open(self.moderator)
        self.visit(page, reverse('admin_flagged_posts'))
        self.assertIn(self.question.title, page.content())
        self.visit(page, '/')
        page.get_by_role('link', name='support queue').click()
        page.wait_for_load_state()
        self.check_page(page)
        self.assertIn('Support dashboard', page.content())
        self.assertIn(self.original.title, page.locator('.support-module').nth(1).inner_text())
        for days in (30, 90, 365, 0):
            self.visit(page, '/admin/support/?days=%d&tag=collect' % days)

    def test_ordinary_users_are_kept_out(self):
        page = self.open(self.alice)
        for path in ('/admin/', '/admin/support/', reverse('admin_flagged_posts'), '/admin/settings/basic/',
                     '/admin/maintenance/', '/nimda/'):
            with self.subTest(path=path):
                response = page.goto(self.url(path))
                page.problems.clear()
                if path == '/nimda/':  # Django's admin asks staff to sign in
                    self.assertIn('/nimda/login/', page.url)
                    continue
                self.assertIn(response.status, (401, 403), path)
        # Staff can moderate but not administer the site.
        page = self.open(self.moderator)
        self.assertEqual(page.goto(self.url('/admin/settings/basic/')).status, 403)
        page.problems.clear()


class AdministrationTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', reputation=1000, is_superuser=True, is_staff=True)
        self.alice = self.create_user('alice', reputation=100)
        self.create_question(self.alice, 'How do I export Collect survey data to CSV?')

    def settings_pages(self, page):
        self.visit(page, '/admin/')
        links = page.eval_on_selector_all('a[href^="/admin/settings/"]', 'els => els.map(e => e.getAttribute("href"))')
        # The "Getting started" list links to settings on these pages (#setting-...).
        return sorted(set(link.split('#')[0] for link in links))

    def test_every_settings_page_loads_and_saves(self):
        page = self.open(self.admin)
        paths = self.settings_pages(page)
        self.assertGreater(len(paths), 20)
        for path in paths:
            with self.subTest(path=path):
                self.visit(page, path)
                with page.expect_navigation():
                    page.click('#submit')
                self.check_page(page, 'saving ' + path)
                self.assertEqual(page.url, self.url(path), 'saving %s did not succeed' % path)
                self.assertEqual(page.locator('.errorlist').count(), 0, 'form errors when saving %s' % path)

    def test_change_a_setting(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/basic/')
        page.fill('#id_APP_TITLE', 'Open Foris Q&A')
        with page.expect_navigation():
            page.click('#submit')
        self.check_page(page)
        anonymous = self.open()
        self.visit(anonymous, '/')
        self.assertIn('Open Foris Q&A', anonymous.title())

    def test_admin_pages(self):
        page = self.open(self.admin)
        for path in ('/admin/', '/admin/support/', reverse('admin_flagged_posts'), '/admin/maintenance/',
                     '/admin/tools/createuser/', '/admin/tools/nodeman/', '/admin/settings/security/',
                     '/admin/statistics/', '/admin/static_pages/', '/admin/email-previews/',
                     '/admin/test_email_settings/', '/admin/sximporter/'):
            with self.subTest(path=path):
                self.visit(page, path)
                # One layout: the header links back to the site, to the inbox and to sign out.
                header = page.locator('#header')
                for name in ('View site', 'Moderation inbox', 'admin', 'Log out'):
                    self.assertTrue(header.get_by_role('link', name=name).first.is_visible(), name)
                if path != '/admin/tools/nodeman/':  # the node manager uses the whole width
                    self.assertTrue(page.locator('#admin-menu').evaluate('details => details.open'))
                    # The menu sits beside the page, not under it.
                    menu, main = page.locator('#admin-menu').bounding_box(), page.locator('#content-main').bounding_box()
                    self.assertLess(menu['x'] + menu['width'], main['x'])
        # The page being shown is marked in the menu.
        self.visit(page, '/admin/settings/security/')
        self.assertEqual(page.locator('#admin-menu a[aria-current="page"]').inner_text(), 'Security')
        self.assertEqual(page.locator('h1.admin-title').inner_text(), 'Security')
        phone = self.open(self.admin, device='mobile', dark=True)
        for path in ('/admin/', '/admin/support/', '/admin/settings/basic/', '/admin/moderation/'):
            with self.subTest(device='mobile', path=path):
                self.visit(phone, path)
                # The folded menu comes before the page.
                menu, main = phone.locator('#admin-menu').bounding_box(), phone.locator('#content-main').bounding_box()
                self.assertLess(menu['y'] + menu['height'], main['y'] + 1)
                # The header's links fit on the screen, big enough to tap.
                for link in phone.locator('#user-tools a').all():
                    box = link.bounding_box()
                    self.assertGreaterEqual(box['height'], 32)
                    self.assertLessEqual(box['x'] + box['width'], 390)

    def test_old_layout_switch_link_goes_to_the_dashboard(self):
        page = self.open(self.admin)
        for query in ('?to=default', '?to=djstyle'):
            response = page.goto(self.url('/admin/switch_interface/' + query))
            self.assertEqual(response.status, 200)
            self.assertEqual(page.url, self.url('/admin/'))
            self.check_page(page)
        self.assertEqual(page.get_by_role('link', name='To standard interface').count(), 0)

    def test_moderators_menu(self):
        moderator = self.create_user('moderator', reputation=10, is_staff=True)
        page = self.open(moderator)
        self.visit(page, '/admin/moderation/')
        links = page.locator('#admin-menu a').all_inner_texts()
        # The dashboard (community health) and the moderation pages; no settings or tools.
        self.assertEqual([t.strip() for t in links],
                         ['Dashboard', 'Moderation inbox', 'Support dashboard', 'Email previews'])
        self.assertEqual(page.locator('#admin-menu a[href^="/admin/settings/"]').count(), 0)

    def test_admin_on_a_phone_in_dark_mode(self):
        phone = self.open(self.admin, device='mobile', dark=True)
        self.visit(phone, '/admin/tools/createuser/')
        # Dark background, from Django's dark_mode.css.
        background = phone.evaluate('getComputedStyle(document.body).backgroundColor')
        rgb = [int(n) for n in background[background.index('(') + 1:-1].split(',')[:3]]
        self.assertLess(sum(rgb) / 3, 60, 'admin background is not dark: %s' % background)
        # Labels sit above their fields instead of breaking letter by letter.
        for label in phone.locator('.admin-form-table th label').all():
            box = label.bounding_box()
            self.assertGreater(box['width'], 60, label.inner_text())
            self.assertLess(box['height'], 40, '%s wraps' % label.inner_text())
            self.assertGreater(label.evaluate('l => l.closest("th").getBoundingClientRect().width'), 250)
        self.assertFalse(phone.locator('#admin-menu').evaluate('details => details.open'))
        # Without the dark mode setting the admin stays light.
        self.set_setting(settings.DARK_MODE, False)
        light = self.open(self.admin, device='mobile', dark=True)
        self.visit(light, '/admin/tools/createuser/')
        background = light.evaluate('getComputedStyle(document.body).backgroundColor')
        rgb = [int(n) for n in background[background.index('(') + 1:-1].split(',')[:3]]
        self.assertGreater(sum(rgb) / 3, 200, 'admin background is not light: %s' % background)

        self.create_question(self.alice, 'How do I export Collect survey data to CSV?')
        phone = self.open(self.admin, device='mobile')
        self.visit(phone, '/admin/tools/nodeman/')
        # Node manager: one card per post, the column headers hidden.
        self.assertFalse(phone.locator('#result_list thead').is_visible())
        row = phone.locator('#result_list tbody tr').first
        self.assertEqual(row.evaluate('tr => getComputedStyle(tr).display'), 'grid')
        self.assertGreater(row.locator('td.node-summary').bounding_box()['width'], 250)

    def test_create_user(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/tools/createuser/')
        page.fill('#id_username', 'fieldworker')
        page.fill('#id_email', 'fieldworker@example.com')
        page.fill('#id_password1', 'a-long-new-password-3')
        page.fill('#id_password2', 'a-long-new-password-3')
        with page.expect_navigation():
            page.click('form input[type=submit]')
        self.check_page(page)
        self.assertTrue(User.objects.filter(username='fieldworker').exists())

    def test_grant_moderator_rights_and_suspend(self):
        page = self.open(self.admin)
        self.visit(page, self.alice.get_profile_url())
        page.click('#user-menu')
        page.click('#user-menu-dropdown a[href="%s"]' % reverse('user_powers', kwargs={
            'id': self.alice.id, 'action': 'grant', 'status': 'staff'}))
        self.confirm_dialog(page)
        self.assertTrue(User.objects.get(id=self.alice.id).is_staff)

        # Suspending is for administrators (moderators don't get the menu).
        spammer = self.create_user('spammer', reputation=1)
        self.visit(page, spammer.get_profile_url())
        page.click('#user-menu')
        page.click('#user-menu-dropdown a[href="%s"]' % reverse('user_suspend', kwargs={'id': spammer.id}))
        self.confirm_dialog(page)
        self.assertTrue(User.objects.get(id=spammer.id).is_suspended())

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_maintenance_mode(self):
        # Each browser gets its own address through X-Forwarded-For.
        admin = self.open(self.admin)
        admin.context.set_extra_http_headers({'X-Forwarded-For': '10.0.0.1'})
        visitor = self.open()
        visitor.context.set_extra_http_headers({'X-Forwarded-For': '10.0.0.2'})

        self.visit(admin, '/admin/maintenance/')
        admin.fill('#id_ips', '10.0.0.1')
        admin.fill('#id_message', 'Back in ten minutes')
        with admin.expect_navigation():
            admin.click('input[name=close]')
        self.check_page(admin)

        response = visitor.goto(self.url('/'))
        self.assertEqual(response.status, 503)
        self.assertIn('Back in ten minutes', visitor.content())
        visitor.wait_for_timeout(500)  # the favicon request gets a 503 too
        visitor.problems.clear()
        self.visit(admin, '/')  # the allowed address still gets in

        self.visit(admin, '/admin/maintenance/')
        with admin.expect_navigation():
            admin.click('input[name=open]')
        self.check_page(admin)
        self.visit(visitor, '/')

    def test_django_admin(self):
        page = self.open(self.admin)
        self.visit(page, '/nimda/')
        # Django's admin CSS is served by OSQA (no collectstatic needed).
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('#header')).display"), 'flex')
        self.visit(page, '/nimda/auth/user/')
        self.assertIn('alice', page.content())
