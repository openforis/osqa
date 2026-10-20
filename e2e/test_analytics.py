"""Google Analytics 4 behind the consent banner (osqa.analytics.js,
display/analytics_consent.html, forum/utils/analytics.py).

Nothing is requested from Google before "Accept"; the banner is there at the
first paint, passes axe in both themes and on a phone, and is reached early
with Tab. Accepting loads gtag.js (a stub here) with advertising signals
denied, hides the banner and survives a reload; the footer's "Analytics
cookies" shows it again with the current choice, and "Decline" turns
Analytics off, deletes its cookies, gives the focus back and is remembered."""
from forum import settings

from .base import E2ETestCase
from . import test_accessibility

ID = 'G-TEST1234'
GTAG = 'https://www.googletagmanager.com/**'
# Stands in for gtag.js: counts loads and sets a cookie as Analytics would.
STUB = "window.__gtagLoads = (window.__gtagLoads || 0) + 1; document.cookie = '_ga=GA1.1.1.1; path=/';"

BANNER = '#analytics-consent'
FIRST_PAINT = '''() => {
    document.addEventListener('DOMContentLoaded', () => {
        const banner = document.querySelector('#analytics-consent');
        window.__bannerAtFirstPaint = !!banner && !banner.hidden;
    });
}'''


class AnalyticsConsentTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.set_setting(settings.GOOGLE_ANALYTICS_KEY, ID)

    def open_page(self, **options):
        page = self.open(**options)
        page.google = []
        page.on('request', lambda request: page.google.append(request.url)
                if 'google' in request.url and not request.url.startswith(self.live_server_url) else None)
        page.context.route(GTAG, lambda route: route.fulfill(status=200, content_type='application/javascript', body=STUB))
        page.context.route('https://*.google-analytics.com/**', lambda route: route.abort())
        page.add_init_script(script='(%s)()' % FIRST_PAINT)
        return page

    def cookie(self, page, name='osqa_analytics'):
        return next((c['value'] for c in page.context.cookies() if c['name'] == name), None)

    def test_nothing_before_consent_and_the_banner_is_accessible(self):
        for device, dark in (('desktop', False), ('mobile', True)):
            page = self.open_page(device=device, dark=dark)
            self.visit(page, '/')
            self.assertTrue(page.evaluate('window.__bannerAtFirstPaint'), device)
            self.assertTrue(page.is_visible(BANNER))
            violations = test_accessibility.AccessibilityTest.axe(
                self, page, tags=test_accessibility.WCAG_TAGS + ['wcag22a', 'wcag22aa'])
            self.assertEqual(violations, [], '\n'.join(violations))
            page.wait_for_timeout(300)
            self.assertEqual(page.google, [], 'requests to Google before consent')
            self.assertIsNone(self.cookie(page))
            self.assertIsNone(page.evaluate('window.dataLayer'))

            # Tab: the skip link, then the banner's link and buttons.
            page.keyboard.press('Tab')
            page.keyboard.press('Tab')
            self.assertTrue(page.evaluate('''() => document.querySelector('#analytics-consent')
                                                     .contains(document.activeElement)'''))
            # Without a choice it asks on the next page too.
            self.visit(page, '/questions/')
            self.assertTrue(page.is_visible(BANNER))

    def test_accept_then_decline_from_the_footer(self):
        page = self.open_page()
        self.visit(page, '/')
        page.click('[data-analytics-choice="yes"]')
        page.wait_for_function('window.__gtagLoads === 1')
        self.assertTrue(page.is_hidden(BANNER))
        self.assertEqual(self.cookie(page), 'yes')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'wrapper')
        consent = page.evaluate('''() => window.dataLayer.map(args => Array.from(args))
                                       .filter(args => args[0] === 'consent')''')
        self.assertEqual(consent[0][1], 'default')
        self.assertEqual(consent[0][2]['ad_storage'], 'denied')
        self.assertEqual(consent[0][2]['analytics_storage'], 'granted')
        self.assertTrue(any(url.startswith('https://www.googletagmanager.com/gtag/js?id=' + ID) for url in page.google))

        # Remembered: no banner, Analytics loads again on the next page.
        self.visit(page, '/questions/')
        self.assertTrue(page.is_hidden(BANNER))
        page.wait_for_function('window.__gtagLoads === 1')
        self.assertFalse(page.evaluate('window.__bannerAtFirstPaint'))

        # The footer button shows the banner again with the current choice.
        page.click('[data-analytics-settings]')
        self.assertTrue(page.is_visible(BANNER))
        self.assertEqual(page.evaluate('document.activeElement.id'), 'analytics-consent')
        self.assertTrue(page.is_visible('[data-consent-current="yes"]'))
        self.assertTrue(page.is_hidden('[data-consent-current="no"]'))
        page.click('[data-analytics-choice="no"]')
        self.assertTrue(page.is_hidden(BANNER))
        self.assertTrue(page.evaluate("document.activeElement.hasAttribute('data-analytics-settings')"))
        self.assertEqual(self.cookie(page), 'no')
        self.assertIsNone(self.cookie(page, '_ga'))
        self.assertTrue(page.evaluate("window['ga-disable-%s']" % ID))
        self.assertEqual(page.evaluate('''() => window.dataLayer.map(args => Array.from(args))
                                              .filter(args => args[0] === 'consent').pop()'''),
                         ['consent', 'update', {'analytics_storage': 'denied'}])

        # Declined: nothing is loaded on later pages and the banner stays away.
        page.google.clear()
        self.visit(page, '/tags/')
        self.assertTrue(page.is_hidden(BANNER))
        page.wait_for_timeout(300)
        self.assertEqual(page.google, [])
        self.check_page(page)

    def test_no_banner_or_button_without_an_id(self):
        self.set_setting(settings.GOOGLE_ANALYTICS_KEY, '')
        page = self.open_page()
        self.visit(page, '/')
        self.assertEqual(page.locator(BANNER).count(), 0)
        self.assertEqual(page.locator('[data-analytics-settings]').count(), 0)
