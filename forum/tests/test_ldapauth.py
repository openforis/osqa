import importlib
import sys
import types
from unittest import mock

from forum.authentication import AUTH_PROVIDERS, ConsumerAndContext
from forum.models import User

from .base import OSQATestCase

USER_DN = 'uid=carol,ou=people,dc=example,dc=org'


def fake_ldap_module():
    """Just enough of python-ldap for the module, which is not installed here."""
    ldap = types.ModuleType('ldap')
    ldap.LDAPError = type('LDAPError', (Exception,), {})
    ldap.SCOPE_SUBTREE = 2
    ldap.OPT_PROTOCOL_VERSION = 17
    ldap.initialize = mock.Mock()

    ldap_filter = types.ModuleType('ldap.filter')

    def escape_filter_chars(value):
        # RFC 4515 escaping, as python-ldap does it.
        for char, escaped in (('\\', r'\5c'), ('*', r'\2a'), ('(', r'\28'), (')', r'\29'), ('\x00', r'\00')):
            value = value.replace(char, escaped)
        return value

    ldap_filter.escape_filter_chars = escape_filter_chars
    ldap.filter = ldap_filter
    return ldap


class LDAPAuthTest(OSQATestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ldap = fake_ldap_module()
        with mock.patch.dict(sys.modules, {'ldap': cls.ldap, 'ldap.filter': cls.ldap.filter}):
            sys.modules.pop('forum_modules.ldapauth.authentication', None)
            cls.auth = importlib.import_module('forum_modules.ldapauth.authentication')

    def setUp(self):
        super().setUp()
        self.connection = mock.Mock()
        self.connection.search_s.return_value = [(USER_DN, {
            'uid': [b'carol'], 'mail': [b'carol@example.org'], 'cn': [b'Carol Example'],
        })]

        def bind(dn, password):
            if dn == USER_DN and password != 'right-pass':
                raise self.ldap.LDAPError('Invalid credentials')

        self.connection.simple_bind_s.side_effect = bind
        self.ldap.initialize.reset_mock()
        self.ldap.initialize.return_value = self.connection

        # python-ldap is missing, so the module isn't loaded; register it as the loader would.
        provider = ConsumerAndContext('ldap', self.auth.LDAPAuthConsumer, self.auth.LDAPAuthContext)
        patcher = mock.patch.dict(AUTH_PROVIDERS, {'ldap': provider})
        patcher.start()
        self.addCleanup(patcher.stop)

    def signin(self, username, password):
        return self.client.post('/account/ldap/signin/', {'username': username, 'password': password})

    def logged_in_user_id(self):
        return self.client.session.get('_auth_user_id')

    def test_successful_bind_creates_and_logs_in_user(self):
        self.signin('carol', 'right-pass')

        user = User.objects.get(username='carol')
        self.assertEqual(user.email, 'carol@example.org')
        self.assertEqual(user.real_name, 'Carol Example')
        self.assertFalse(user.has_usable_password())
        self.assertEqual(self.logged_in_user_id(), str(user.id))
        self.connection.simple_bind_s.assert_called_with(USER_DN, 'right-pass')

        # The second login finds the existing user.
        self.client.logout()
        self.signin('carol', 'right-pass')
        self.assertEqual(self.logged_in_user_id(), str(user.id))
        self.assertEqual(User.objects.filter(username='carol').count(), 1)

    def test_a_local_account_with_the_same_username_is_not_taken_over(self):
        """Someone who signed up locally as a colleague's directory uid used to
        receive that colleague's LDAP sign-ins."""
        squatter = self.create_user('carol')  # their own address and password
        self.signin('carol', 'right-pass')
        self.assertIsNone(self.logged_in_user_id())
        self.assertContains(self.client.get('/account/signin/'), 'already exists on the forum')
        self.assertFalse(squatter.auth_keys.exists())

    def test_an_account_ldap_made_before_the_link_is_claimed(self):
        old = self.create_user('carol')
        old.set_unusable_password()
        old.save()
        self.signin('carol', 'right-pass')
        self.assertEqual(self.logged_in_user_id(), str(old.id))
        self.assertEqual(old.auth_keys.get().key, 'ldap:' + USER_DN)

    def test_wrong_password_is_refused(self):
        self.signin('carol', 'wrong-pass')
        self.assertIsNone(self.logged_in_user_id())
        self.assertFalse(User.objects.filter(username='carol').exists())
        self.assertContains(self.client.get('/account/signin/'), 'Login failed')

    def test_empty_password_never_binds(self):
        self.signin('carol', '')
        self.assertIsNone(self.logged_in_user_id())
        self.ldap.initialize.assert_not_called()

    def test_unknown_user_is_refused(self):
        self.connection.search_s.return_value = []
        self.signin('nobody', 'right-pass')
        self.assertIsNone(self.logged_in_user_id())

    def test_server_error_is_refused(self):
        self.connection.search_s.side_effect = self.ldap.LDAPError("Can't contact LDAP server")
        self.signin('carol', 'right-pass')
        self.assertIsNone(self.logged_in_user_id())
        self.assertContains(self.client.get('/account/signin/'), 'LDAP bind error')

    def test_username_is_escaped_in_search_filter(self):
        self.connection.search_s.return_value = []
        self.signin('*)(uid=*', 'right-pass')

        base_dn, scope, search_filter = self.connection.search_s.call_args[0]
        self.assertEqual(search_filter, r'UID=\2a\29\28uid=\2a')
        self.assertIsNone(self.logged_in_user_id())


class LDAPAuthAvailabilityTest(OSQATestCase):
    def test_disabled_without_python_ldap(self):
        import forum_modules.ldapauth as ldapauth
        from django.conf import settings

        try:
            with mock.patch.dict(sys.modules, {'ldap': None, 'ldap.filter': None}):
                self.assertFalse(importlib.reload(ldapauth).CAN_USE)

            ldap = fake_ldap_module()
            with mock.patch.dict(sys.modules, {'ldap': ldap, 'ldap.filter': ldap.filter}):
                self.assertTrue(importlib.reload(ldapauth).CAN_USE)
        finally:
            importlib.reload(ldapauth)

        if not ldapauth.CAN_USE:
            self.assertNotIn(ldapauth, settings.MODULE_LIST)
