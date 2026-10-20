"""Admin > AI assistance: the connection settings, the "In use now" panel
and "Test connection" (forum_modules/ai/diagnostics.py). The test tries the
values typed in the form without saving them, shows what works and, for a
failure, what to do; the page passes axe with a result shown, in both
themes and on a phone."""
from unittest import mock

from google.genai import errors

from forum.tests.test_ai_admin import FakeApi, api_error

from .base import E2ETestCase
from . import test_accessibility

KEY = 'AIzaTestKey0123456789abcdef'


class AISettingsTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        from forum_modules.ai import settings as ai
        self.ai = ai
        self._patch(mock.patch.dict('os.environ', {name: '' for name in (
            'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION')}))
        self.set_setting(ai.GEMINI_API_KEY, '')
        self.admin = self.create_user('admin', reputation=10, is_superuser=True, is_staff=True)
        self.fakes = []

    def answer_with(self, **kwargs):
        fake = FakeApi(**kwargs)
        self._patch(mock.patch('forum_modules.ai.client.build_client', lambda target, timeout=None: fake))
        return fake

    def test_test_connection_before_saving(self):
        page = self.open(self.admin)
        self.visit(page, '/admin/settings/ai/')
        self.assertIn('Not set up', page.inner_text('#section-connection .admin-status'))

        # A wrong key: explained, with what to do and Google's own message.
        self.answer_with(text_error=api_error(errors.ClientError, 400, 'API key not valid.', 'INVALID_ARGUMENT',
                                              'API_KEY_INVALID'))
        page.fill('#id_GEMINI_API_KEY', 'AIzaWrongKey0000000000000')
        page.click('#ai-test-button')
        page.wait_for_selector('#ai-test-result .ai-test-fail')
        result = page.inner_text('#ai-test-result')
        self.assertIn("Google doesn't accept this API key.", result)
        self.assertIn('Not tested: fix the problem above first.', result)
        page.click('#ai-test-result summary')
        self.assertIn('API_KEY_INVALID', page.inner_text('#ai-test-result pre'))
        self.assertTrue(page.is_enabled('#ai-test-button'))

        # The right key: everything works; still nothing saved until Save.
        self.answer_with()
        page.fill('#id_GEMINI_API_KEY', KEY)
        page.click('#ai-test-button')
        page.wait_for_selector('#ai-test-result .ai-test-ok')
        self.assertEqual(page.locator('#ai-test-result .ai-check-ok').count(), 3)
        self.assertEqual(str(self.ai.GEMINI_API_KEY), '')

        page.click('#submit')
        page.wait_for_load_state('load')
        self.check_page(page)
        self.assertEqual(str(self.ai.GEMINI_API_KEY), KEY)
        self.assertIn('Gemini API with the key AIza…cdef (from this page).',
                      page.inner_text('#section-connection .admin-guide-message'))

    def test_accessible_with_a_result(self):
        self.answer_with(text_error=api_error(errors.ClientError, 404, 'models/gemini-9 is not found', 'NOT_FOUND'),
                         models=('gemini-3.8-flash',))
        for device, dark in (('desktop', False), ('mobile', True)):
            page = self.open(self.admin, device=device, dark=dark)
            self.visit(page, '/admin/settings/ai/')
            page.fill('#id_GEMINI_API_KEY', KEY)
            page.fill('#id_AI_MODEL', 'gemini-9')
            page.click('#ai-test-button')
            page.wait_for_selector('#ai-test-result .ai-check-fail')
            self.assertIn('Models this connection offers include: gemini-3.8-flash.', page.inner_text('#ai-test-result'))
            violations = test_accessibility.AccessibilityTest.axe(
                self, page, tags=test_accessibility.WCAG_TAGS + ['wcag22a', 'wcag22aa'])
            self.assertEqual(violations, [], '%s:\n%s' % (device, '\n'.join(violations)))
