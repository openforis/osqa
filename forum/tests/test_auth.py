import re

from forum.forms.general import clean_next
from forum.models import User

from .base import OSQATestCase


class LocalAuthTest(OSQATestCase):
    def register(self, username='carol', password='s3cret-pass'):
        return self.client.post('/account/local/register/', {
            'username': username, 'email': '%s@example.com' % username,
            'password1': password, 'password2': password, 'next': '/',
            'form_token': self.signup_token(),
        })

    def logged_in_user_id(self):
        return self.client.session.get('_auth_user_id')

    def test_signin_page_shows_local_form(self):
        self.assertContains(self.client.get('/account/signin/'), 'id="id_password"')

    def test_register_creates_superuser_and_sends_welcome_mail(self):
        response = self.register()
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username='carol')
        self.assertTrue(user.is_superuser)  # the first account owns the site
        self.assertEqual(self.logged_in_user_id(), str(user.id))

        self.assertEqual(len(self.sent_mail), 1)
        recipient, subject, html, text, media, headers = self.sent_mail[0]
        self.assertEqual(recipient, user)
        self.assertIn('Welcome', subject)
        self.assertTrue(text.strip())

    def test_second_account_is_not_superuser(self):
        self.create_user('alice')
        self.register()
        self.assertFalse(User.objects.get(username='carol').is_superuser)

    def test_password_login(self):
        user = self.create_user('carol', password='right-pass')

        self.client.post('/account/local/signin/', {'username': 'carol', 'password': 'wrong'})
        self.assertIsNone(self.logged_in_user_id())
        page = self.client.get('/account/signin/')
        self.assertContains(page, 'or email and password')
        self.assertContains(page, 'value="carol"')  # what was typed is kept

        self.client.post('/account/local/signin/', {'username': 'carol', 'password': 'right-pass'})
        self.assertEqual(self.logged_in_user_id(), str(user.id))

        self.client.get('/account/signout/')  # only the confirmation page
        self.assertEqual(self.logged_in_user_id(), str(user.id))
        self.client.post('/account/signout/')
        self.assertIsNone(self.logged_in_user_id())

    def test_signin_without_fields_redirects(self):
        # Sentry OSQA-3: a GET (no username field) crashed with a 500
        response = self.client.get('/account/local/signin/')
        self.assertRedirects(response, '/account/signin/', fetch_redirect_response=False)
        self.assertIsNone(self.logged_in_user_id())

    def test_register_without_provider_redirects(self):
        # Sentry OSQA-T: a direct visit logged every request header as an error.
        with self.assertNoLogs(level='ERROR'):
            response = self.client.get('/account/register/')
        self.assertRedirects(response, '/account/signin/', fetch_redirect_response=False)

    def test_sign_in_with_email_address(self):
        user = self.create_user('carol', password='right-pass')
        self.client.post('/account/local/signin/', {'username': 'Carol@Example.com', 'password': 'right-pass'})
        self.assertEqual(self.logged_in_user_id(), str(user.id))

    def test_email_shared_by_two_accounts_does_not_sign_in(self):
        from forum import settings
        settings.EMAIL_UNIQUE.set_value(False)
        self.addCleanup(setattr, settings.EMAIL_UNIQUE, '_temp', None)
        self.create_user('carol', password='right-pass')
        other = self.create_user('carolyn', password='right-pass')
        User.objects.filter(id=other.id).update(email='carol@example.com')
        self.client.post('/account/local/signin/', {'username': 'carol@example.com', 'password': 'right-pass'})
        self.assertIsNone(self.logged_in_user_id())
        self.assertContains(self.client.get('/account/signin/'), 'or email and password')

    def test_wrong_passwords_by_email_count_against_the_account(self):
        from forum import settings
        self.create_user('carol', password='right-pass')
        for attempt in range(int(settings.LOGIN_FAILURES_LIMIT)):
            username = 'carol@example.com' if attempt % 2 else 'carol'
            self.client.post('/account/local/signin/', {'username': username, 'password': 'wrong'})
        self.client.post('/account/local/signin/', {'username': 'carol', 'password': 'right-pass'})
        self.assertIsNone(self.logged_in_user_id())
        self.assertContains(self.client.get('/account/signin/'), 'Too many failed sign-in attempts')

    def test_next_parameter_is_where_signing_in_leads(self):
        self.create_user('carol', password='right-pass')
        self.client.get('/account/signin/?next=/tags/collect/', HTTP_REFERER='http://testserver/questions/')
        response = self.client.post('/account/local/signin/', {'username': 'carol', 'password': 'right-pass'})
        self.assertTrue(response['Location'].startswith('/tags/collect/'))

        self.client.logout()
        self.client.get('/account/signin/?next=https://evil.example/')
        response = self.client.post('/account/local/signin/', {'username': 'carol', 'password': 'right-pass'})
        self.assertNotIn('evil.example', response['Location'])

    def test_coming_back_from_the_sign_up_page_keeps_the_destination(self):
        self.create_user('carol', password='right-pass')
        self.client.get('/account/signin/', HTTP_REFERER='http://testserver/tags/')
        self.client.get('/account/signin/', HTTP_REFERER='http://testserver/account/local/register/')
        response = self.client.post('/account/local/signin/', {'username': 'carol', 'password': 'right-pass'})
        self.assertTrue(response['Location'].startswith('http://testserver/tags/'))

    def test_sign_up_errors_are_listed_and_linked_to_the_fields(self):
        self.create_user('carol')
        page = self.client.post('/account/local/register/', {
            'username': 'carol', 'email': 'not-an-address', 'password1': 'short', 'password2': 'short',
            'next': '/', 'form_token': self.signup_token()}).content.decode()
        self.assertIn('role="alert"', page)
        self.assertIn('href="#id_username"', page)
        self.assertIn('id="id_username-error"', page)
        self.assertRegex(page, r'<input[^>]*aria-invalid="true"[^>]*id="id_email"|<input[^>]*id="id_email"[^>]*aria-invalid="true"')
        self.assertIn('value="not-an-address"', page)  # what was typed is kept
        self.assertIn('That username is taken', page)

    def test_password_reset_link(self):
        user = self.create_user('carol')
        self.client.post('/account/tempsignin/', {'email': 'carol@example.com'})
        self.assertEqual(len(self.sent_mail), 1)

        link = re.search(r'/account/tempsignin/\d+/[^/\s"<]+/', self.sent_mail[0][3]).group(0)
        self.assertContains(self.client.get(link), 'Choose a new password')
        self.client.post(link, {'password1': 'a-new-long-pass-1', 'password2': 'a-new-long-pass-1'})
        self.assertTrue(User.objects.get(id=user.id).check_password('a-new-long-pass-1'))
        self.client.post('/account/local/signin/', {'username': 'carol', 'password': 'a-new-long-pass-1'})
        self.assertEqual(self.logged_in_user_id(), str(user.id))


class NextUrlTest(OSQATestCase):
    def test_accepts_local_paths(self):
        self.assertEqual(clean_next('/questions/1/'), '/questions/1/')

    def test_rejects_offsite_urls(self):
        default = clean_next(None)
        for url in ['//evil.com', '/\\evil.com', '%2F%2Fevil.com', 'http://evil.com']:
            with self.subTest(url=url):
                self.assertEqual(clean_next(url), default)


class UserCopyTest(OSQATestCase):
    def test_users_with_loaded_properties_can_be_copied(self):
        # The ONLINE_USERS setting deep-copies user objects when it is saved.
        import copy
        user = self.create_user('carol')
        user.prop.some_property  # noqa: B018  (reads the property)
        self.assertEqual(copy.deepcopy({user: 1}).popitem()[1], 1)
