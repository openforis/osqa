"""Accounts: signing up, in and out, forgotten passwords, email settings,
profiles, data export and deleting an account."""
import re

from django.urls import reverse

from forum.models import MarkedTag, User

from .base import E2ETestCase, PASSWORD


class SignUpAndSignInTest(E2ETestCase):
    def sign_in(self, page, username, password):
        self.visit(page, '/account/signin/')
        page.fill('#id_username', username)
        page.fill('#id_password', password)
        with page.expect_navigation():
            page.click('#blogin')

    def test_sign_up_sign_out_and_in(self):
        self.create_user('owner')  # the first account would become the site owner
        page = self.open()
        self.visit(page, '/account/local/register/')
        page.fill('#id_username', 'newcomer')
        page.fill('#id_email', 'newcomer@example.com')
        page.fill('#id_password1', 'short')
        page.fill('#id_password2', 'short')
        with page.expect_navigation():
            page.click('#bnewaccount')
        self.assertIn('too short', page.content())  # password rules
        self.check_page(page)

        page.fill('#id_password1', 'green-tree-river-7')
        page.fill('#id_password2', 'green-tree-river-7')
        with page.expect_navigation():
            page.click('#bnewaccount')
        self.check_page(page)
        newcomer = User.objects.get(username='newcomer')
        # Not signed in until the address is confirmed with the link in the welcome email.
        self.assertIn('Check your inbox', page.locator('.auth-card h1').inner_text())
        self.assertNotIn('newcomer', page.locator('#top').inner_text())
        welcome = [m for m in self.mail_to(newcomer) if 'Welcome' in m[1]]
        self.assertEqual(len(welcome), 1)
        link = re.search(r'http://testserver(/account/validate/\d+/[^/\s]+/)', welcome[0][3]).group(1)
        self.visit(page, link)
        self.assertIn('Email address confirmed', page.locator('.auth-card h1').inner_text())
        self.sign_in(page, 'newcomer', 'green-tree-river-7')
        self.check_page(page)
        self.assertIn('newcomer', page.locator('#top').inner_text())

        page.get_by_role('link', name='logout').click()
        page.wait_for_load_state()
        with page.expect_navigation():
            page.click('#btLogout')  # "Logout now" on the confirmation page
        self.check_page(page)
        self.assertIn('login', page.locator('#top').inner_text())

        self.sign_in(page, 'newcomer', 'green-tree-river-7')
        self.check_page(page)
        self.assertIn('newcomer', page.locator('#top').inner_text())

    def test_wrong_passwords_pause_sign_in(self):
        self.create_user('carol')
        page = self.open()
        for _ in range(5):
            self.sign_in(page, 'carol', 'wrong-password')
            self.assertIn('or email and password', page.content())
        self.sign_in(page, 'carol', PASSWORD)
        self.assertIn('Too many failed sign-in attempts', page.content())
        self.assertNotIn('carol', page.locator('#top').inner_text())
        self.check_page(page)

    def test_forgotten_password(self):
        carol = self.create_user('carol')
        page = self.open()
        self.visit(page, '/account/tempsignin/')
        page.fill('#id_email', 'carol@example.com')
        with page.expect_navigation():
            page.locator('form:has(#id_email) [type=submit]').click()
        self.assertIn('If this address belongs to an account', page.content())
        self.check_page(page)

        text = self.mail_to(carol)[-1][3]
        link = re.search(r'https?://\S+/account/tempsignin/\d+/[^/\s]+/', text).group(0)
        self.visit(page, link[link.index('/account/'):])
        self.assertIn('Choose a new password', page.locator('h1').inner_text())

        page.fill('#id_password1', 'a-new-long-password-9')
        page.fill('#id_password2', 'a-new-long-password-9')
        with page.expect_navigation():
            page.locator('form:has(#id_password1) [type=submit]').click()
        self.check_page(page)
        self.assertTrue(User.objects.get(id=carol.id).check_password('a-new-long-password-9'))
        self.assertIn(reverse('auth_signin'), page.url)  # signs in again with the new password


class EmailSettingsTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=100)
        self.bob = self.create_user('bob', reputation=100)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?')

    def test_follow_a_tag_and_manage_emails(self):
        page = self.open(self.bob)
        self.visit(page, '/tags/collect/')
        with page.expect_navigation():
            page.click('.tag-follow button[value=follow]')
        self.check_page(page)
        self.assertIn('You follow this tag', page.locator('.tag-follow').inner_text())
        self.assertTrue(MarkedTag.objects.filter(user=self.bob, tag__name='collect', reason='good').exists())

        self.visit(page, self.bob.get_user_subscriptions_url())
        self.assertIn('collect', page.locator('.followed-tags').inner_text())
        with page.expect_navigation():
            page.click('.email-master button')
        self.check_page(page)
        self.assertFalse(User.objects.get(id=self.bob.id).subscription_settings.enable_notifications)
        self.assertIn('Email notifications are off', page.content())
        with page.expect_navigation():
            page.click('.email-master button')
        self.assertTrue(User.objects.get(id=self.bob.id).subscription_settings.enable_notifications)

        page.check('#id_send_digest')
        with page.expect_navigation():
            page.click('.email-settings-form [type=submit]')
        self.check_page(page)
        self.assertTrue(User.objects.get(id=self.bob.id).subscription_settings.send_digest)

    def test_unsubscribe_link_from_an_email(self):
        self.create_answer(self.bob, self.question)  # emails alice, who follows her question
        text = self.mail_to(self.alice)[-1][3]
        link = re.search(r'Stop emails about this question: (\S+)', text).group(1)

        page = self.open()  # links work without signing in
        self.visit(page, link[link.index('/unsubscribe/'):])
        self.assertIn('How do I export Collect survey data to CSV?', page.content())
        with page.expect_navigation():
            page.click('button.submit')
        self.check_page(page)
        self.assertIn("You're unsubscribed", page.content())
        self.assertFalse(self.question.subscribers.filter(id=self.alice.id).exists())
        with page.expect_navigation():
            page.get_by_role('button', name=re.compile('Undo')).click()
        self.assertTrue(self.question.subscribers.filter(id=self.alice.id).exists())
        self.check_page(page)


class ProfileTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=100)

    def test_edit_profile(self):
        # Only the email can be edited: the other profile fields are hidden on
        # this site (users/edit.html).
        page = self.open(self.alice)
        self.visit(page, reverse('edit_user', kwargs={'id': self.alice.id, 'slug': 'alice'}))
        page.fill('#id_email', 'alice.forest@example.com')
        with page.expect_navigation():
            page.locator('form:has(#id_email) input[type=submit]').click()
        self.check_page(page)
        # The new address is used once confirmed from the email sent to it.
        self.assertEqual(User.objects.get(id=self.alice.id).email, 'alice@example.com')
        self.assertIn('alice.forest@example.com', page.locator('.email-pending').inner_text())
        text = [m for m in self.sent_mail if m[0].email == 'alice.forest@example.com'][-1][3]
        self.visit(page, re.search(r'http://testserver(/account/email/confirm/\d+/[^/\s]+/)', text).group(1))
        self.assertEqual(User.objects.get(id=self.alice.id).email, 'alice.forest@example.com')

    def test_profile_pages_on_a_phone(self):
        question = self.create_question(self.alice, 'A question by alice for her profile page')
        self.create_answer(self.create_user('bob'), question)
        page = self.open(self.alice, device='mobile', dark=True)
        for path in (self.alice.get_profile_url(), self.alice.get_user_subscriptions_url(),
                     reverse('user_authsettings', kwargs={'id': self.alice.id}),
                     reverse('user_account_data', kwargs={'id': self.alice.id}), '/notifications/'):
            with self.subTest(path=path):
                self.visit(page, path)

    def test_download_data_and_delete_account(self):
        page = self.open(self.alice)
        self.visit(page, reverse('user_account_data', kwargs={'id': self.alice.id}))
        with page.expect_download() as download:
            page.get_by_role('link', name='Download my data').click()
        self.assertIn('alice', open(download.value.path()).read())

        page.fill('input[name=confirm_username]', 'alice')
        page.fill('input[name=password]', PASSWORD)
        with page.expect_navigation():
            page.locator('form:has(input[name=confirm_username]) [type=submit]').click()
        self.check_page(page)
        self.assertIn('Your account has been deleted', page.content())
        self.assertFalse(User.objects.filter(username='alice').exists())
