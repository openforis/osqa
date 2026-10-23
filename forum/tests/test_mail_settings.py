from email import message_from_string
from email.header import decode_header, make_header
from email.utils import parseaddr
from smtplib import SMTPAuthenticationError, SMTPNotSupportedError
from unittest import mock

from forum import settings
from forum.models import User
from forum.templatetags import email_tags
from forum.utils import mail

from .base import OSQATestCase
from .test_antispam import SettingMixin


class EmailSettingsTestButtonTest(SettingMixin, OSQATestCase):
    """Admin > Email settings > Test reports what the SMTP server said."""

    def setUp(self):
        super().setUp()
        # Use the real sender instead of the base class's capture, with a fake SMTP class.
        patcher = mock.patch.object(email_tags, 'create_and_send_mail_messages', mail.create_and_send_mail_messages)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.smtp = mock.MagicMock()
        patcher = mock.patch.object(mail, 'SMTP', return_value=self.smtp)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.set(settings.EMAIL_HOST, 'smtp.example.com')
        self.set(settings.EMAIL_PORT, 587)
        self.set(settings.EMAIL_HOST_USER, 'forum')
        self.set(settings.EMAIL_HOST_PASSWORD, 'app-password')
        self.set(settings.DEFAULT_FROM_EMAIL, 'forum@example.com')
        self.login(self.create_user('admin', is_superuser=True, is_staff=True))

    def press_test(self):
        # The Test button on the email settings page posts with AJAX and shows the fragment.
        return self.client.post('/admin/test_email_settings/', **self.AJAX)

    def test_success(self):
        response = self.press_test()
        self.assertContains(response, 'The email server accepted the test message for admin@example.com')
        self.assertNotContains(response, 'could not be sent')
        self.assertNotContains(response, '<html')
        self.assertEqual(self.smtp.sendmail.call_args[0][1], ['admin@example.com'])

    def test_addresses_stay_readable(self):
        # Amazon SES refuses headers whose address is inside an encoded word.
        self.set(settings.APP_SHORT_NAME, 'Fórum (OF)')
        User.objects.filter(username='admin').update(username='José (OF)')
        self.press_test()
        envelope_sender, _, raw = self.smtp.sendmail.call_args[0]
        self.assertEqual(envelope_sender, 'forum@example.com')
        message = message_from_string(raw)
        for header, name, address in (('From', 'Fórum (OF)', 'forum@example.com'),
                                      ('To', 'José (OF)', 'admin@example.com')):
            self.assertTrue(message[header].endswith(' <%s>' % address), message[header])
            self.assertEqual(parseaddr(str(make_header(decode_header(message[header])))), (name, address))

    def test_visiting_the_url_sends_nothing(self):
        response = self.client.get('/admin/test_email_settings/')
        self.assertContains(response, 'Send a test email')
        mail.SMTP.assert_not_called()

    def test_sign_in_without_tls(self):
        self.set(settings.EMAIL_USE_TLS, False)
        self.smtp.login.side_effect = SMTPNotSupportedError('SMTP AUTH extension not supported by server.')
        response = self.press_test()
        self.assertContains(response, 'could not be sent')
        self.assertContains(response, 'SMTPNotSupportedError: SMTP AUTH extension not supported by server.')
        self.assertContains(response, 'Use TLS')
        self.smtp.sendmail.assert_not_called()

    def test_wrong_password(self):
        self.smtp.login.side_effect = SMTPAuthenticationError(535, b'5.7.8 Username and Password not accepted.')
        response = self.press_test()
        self.assertContains(response, 'SMTPAuthenticationError')
        self.assertContains(response, 'App Password')
        self.assertNotContains(response, 'app-password')

    def test_message_refused(self):
        self.smtp.sendmail.side_effect = Exception('555 5.5.2 Syntax error')
        self.assertContains(self.press_test(), "Couldn&#x27;t send mail using the sendmail method: 555 5.5.2 Syntax error")

    def test_no_server(self):
        self.set(settings.EMAIL_HOST, '')
        self.assertContains(self.press_test(), 'No email server is set')
        mail.SMTP.assert_not_called()
