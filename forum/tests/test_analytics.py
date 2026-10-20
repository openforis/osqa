"""Google Analytics 4 behind the consent banner (forum/utils/analytics.py):
nothing on the page or in the policy without a GA4 measurement ID, and with
one the banner, the footer button and Google's origins, but never a request
to Google from the server-rendered page itself."""
from forum import settings
from forum.utils import analytics

from .base import OSQATestCase
from .test_csp import directives
from .test_hardening import SettingMixin


class AnalyticsTest(SettingMixin, OSQATestCase):
    def page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        return response, response.content.decode('utf-8')

    def test_nothing_without_an_id(self):
        response, html = self.page()
        self.assertNotIn('analytics-consent', html)
        self.assertNotIn('data-analytics-settings', html)
        policy = response['Content-Security-Policy']
        self.assertNotIn('googletagmanager', policy)
        self.assertNotIn('google-analytics', policy)

    def test_old_and_malformed_keys_are_ignored(self):
        for value in ('UA-1234-5', 'G-', 'G-12"><script>alert(1)</script>', 'GTM-ABCD123', 'G-ABC 123'):
            self.set(settings.GOOGLE_ANALYTICS_KEY, value)
            self.assertEqual(analytics.measurement_id(), '', value)
            response, html = self.page()
            self.assertNotIn('analytics-consent', html, value)
            self.assertNotIn('googletagmanager', response['Content-Security-Policy'], value)

    def test_measurement_id_is_normalised(self):
        self.set(settings.GOOGLE_ANALYTICS_KEY, '  g-abc123xyz ')
        self.assertEqual(analytics.measurement_id(), 'G-ABC123XYZ')

    def test_banner_footer_button_and_policy(self):
        self.set(settings.GOOGLE_ANALYTICS_KEY, 'G-TEST1234')
        response, html = self.page()
        self.assertIn('id="analytics-consent"', html)
        self.assertIn('data-measurement-id="G-TEST1234"', html)
        self.assertIn('data-cookie="%s"' % analytics.COOKIE, html)
        self.assertIn('data-analytics-choice="yes"', html)
        self.assertIn('data-analytics-choice="no"', html)
        self.assertIn('data-analytics-settings', html)
        self.assertIn('osqa.analytics.js', html)
        # gtag.js is only fetched by osqa.analytics.js after "Accept".
        self.assertNotIn('googletagmanager.com/gtag/js', html)
        self.assertNotIn('ga.js', html)
        # Rendered hidden; the inline script shows it before the first paint.
        self.assertRegex(html, r'<section id="analytics-consent"[^>]*\bhidden>')

        policy = directives(response['Content-Security-Policy'])
        self.assertIn('https://www.googletagmanager.com', policy['script-src'])
        for source in analytics.CONNECT_SOURCES.split():
            self.assertIn(source, policy['connect-src'])
        self.assertNotIn('https://www.googletagmanager.com', policy['frame-src'])

    def test_extra_sources_still_come_last(self):
        self.set(settings.GOOGLE_ANALYTICS_KEY, 'G-TEST1234')
        self.set(settings.CSP_EXTRA_SOURCES, 'https://plausible.io')
        policy = directives(self.page()[0]['Content-Security-Policy'])
        self.assertEqual(policy['script-src'][-1], 'https://plausible.io')
        self.assertEqual(policy['connect-src'][-1], 'https://plausible.io')

    def test_signed_in_pages_ask_too(self):
        self.set(settings.GOOGLE_ANALYTICS_KEY, 'G-TEST1234')
        self.login(self.create_user('dora'))
        self.assertIn('id="analytics-consent"', self.page()[1])
