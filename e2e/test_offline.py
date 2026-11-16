"""Installable app and offline reading: the manifest and the service worker,
saved questions readable offline with the offline banner, the offline page
listing what was saved, and saved pages forgotten on sign-out."""
import json

from . import test_accessibility
from .base import E2ETestCase

PAGES = 'osqa-pages-v1'

CONTROLLED = "() => !!(navigator.serviceWorker && navigator.serviceWorker.controller)"
SAVED = "async ([name, url]) => !!(await (await caches.open(name)).match(url, {ignoreVary: true}))"
NOT_SAVED = "async ([name, url]) => !(await (await caches.open(name)).match(url, {ignoreVary: true}))"
FETCH = '''async (url) => {
    const response = await fetch(url);
    return {status: response.status, type: response.headers.get('Content-Type'),
            cache: response.headers.get('Cache-Control'), allowed: response.headers.get('Service-Worker-Allowed'),
            text: await response.text()};
}'''


class OfflineReadingTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=100)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?')
        self.create_answer(self.alice, self.question, 'Use the CSV export in the Collect designer, it works.')
        self.other = self.create_question(self.alice, 'Can SEPAL process Sentinel-2 time series?', tags='sepal')

    def save_for_offline(self, page, path):
        """Visits a page, waits for the service worker to control it, and
        visits it again, now through the worker, which saves it."""
        self.visit(page, path)
        page.wait_for_function(CONTROLLED)
        self.visit(page, path)
        page.wait_for_function(SAVED, arg=[PAGES, self.url(path)])

    def go_offline(self, page):
        """Cuts the network of the page and of the service worker. Playwright
        stops emulating the network conditions in the worker after each
        navigation, so this is called again before every navigation."""
        page.context.set_offline(False)
        page.context.set_offline(True)

    def test_sharing_a_screenshot_opens_the_ask_page_with_it(self):
        """"Share" from another app (manifest share_target): the service worker
        keeps what was shared and opens the ask page, which uploads the image
        and fills in the title and text."""
        import base64
        import io
        from PIL import Image
        png = io.BytesIO()
        Image.new('RGB', (40, 30), (200, 30, 30)).save(png, 'PNG')
        page = self.open(self.alice, device='mobile')
        self.visit(page, '/')
        page.wait_for_function(CONTROLLED)
        # What Android's share sheet sends: a multipart POST navigation.
        with page.expect_navigation():
            page.evaluate("""([png]) => {
                const form = document.createElement('form');
                form.method = 'post'; form.enctype = 'multipart/form-data'; form.action = '/share-target/';
                const add = (name, value) => { const input = document.createElement('input');
                    input.type = 'hidden'; input.name = name; input.value = value; form.appendChild(input); };
                add('title', 'Collect crashes when exporting');
                add('text', 'Error 42 when exporting the survey');
                const bytes = Uint8Array.from(atob(png), c => c.charCodeAt(0));
                const files = new DataTransfer();
                files.items.add(new File([bytes], 'screenshot.png', {type: 'image/png'}));
                const input = document.createElement('input');
                input.type = 'file'; input.name = 'images'; input.files = files.files; form.appendChild(input);
                document.body.appendChild(form);
                form.submit();
            }""", [base64.b64encode(png.getvalue()).decode()])
        page.wait_for_url('**/questions/ask/')
        page.wait_for_function("() => /!\\[[^\\]]*\\]\\([^)]*upfiles[^)]*\\)/.test(document.querySelector('#editor').value)")
        self.assertEqual(page.input_value('#id_title'), 'Collect crashes when exporting')
        self.assertIn('Error 42 when exporting the survey', page.input_value('#editor'))
        self.assertNotIn('shared=1', page.url)
        page.wait_for_function("async () => !(await caches.has('osqa-shared'))")
        self.check_page(page)

    def test_manifest_and_service_worker(self):
        page = self.open()
        self.visit(page, '/')
        self.assertEqual(page.get_attribute('link[rel=manifest]', 'href'), '/manifest.webmanifest')
        self.assertEqual(page.locator('meta[name=theme-color]').count(), 2)  # light and dark

        manifest = page.evaluate(FETCH, '/manifest.webmanifest')
        self.assertEqual(manifest['status'], 200)
        self.assertEqual(manifest['type'], 'application/manifest+json')
        data = json.loads(manifest['text'])
        self.assertEqual((data['start_url'], data['display']), ('/', 'standalone'))
        self.assertEqual(data['short_name'], 'OSQA')
        icons = data['icons'] + [{'src': page.get_attribute('link[rel=apple-touch-icon]', 'href')}]
        for icon in icons:
            self.assertEqual(page.evaluate('async (url) => (await fetch(url)).status', icon['src']), 200, icon['src'])
        self.assertIn('maskable', [icon.get('purpose') for icon in data['icons']])

        worker = page.evaluate(FETCH, '/sw.js')
        self.assertEqual(worker['status'], 200)
        self.assertTrue(worker['type'].startswith('application/javascript'))
        self.assertEqual(worker['allowed'], '/')
        self.assertIn('no-cache', worker['cache'])
        self.assertIn("addEventListener('fetch'", worker['text'])

        # The offline page, online and with nothing saved yet.
        self.visit(page, '/offline/')
        page.wait_for_selector('#offline-pages[data-loaded="0"]', state='attached')
        self.assertTrue(page.is_visible('#offline-none'))
        self.assertFalse(page.is_visible('#offline-banner'))
        self.check_page(page)

    def check_offline_pages(self, page, device, dark):
        self.save_for_offline(page, self.question.get_absolute_url())
        try:
            # The saved question, with the banner.
            self.go_offline(page)
            page.reload()
            page.wait_for_selector('#offline-banner', state='visible')
            self.assertIn('You are offline', page.inner_text('#offline-banner'))
            self.assertIn(self.question.title, page.inner_text('#main-body'))
            self.check_page(page)
            violations = test_accessibility.AccessibilityTest.axe(self, page)
            self.assertEqual(violations, [], 'saved copy (%s%s)' % (device, ', dark' if dark else ''))

            # A page never visited: the offline page, listing the saved question.
            self.go_offline(page)
            page.goto(self.url(self.other.get_absolute_url()))
            page.wait_for_selector('#offline-pages[data-loaded]', state='attached')
            self.assertIn('You are offline', page.inner_text('h1'))
            link = page.locator('#offline-pages a', has_text=self.question.title)
            self.assertEqual(link.get_attribute('href'), self.url(self.question.get_absolute_url()))
            self.assertFalse(page.is_visible('#offline-banner'))
            self.check_page(page)
            violations = test_accessibility.AccessibilityTest.axe(self, page)
            self.assertEqual(violations, [], 'offline page (%s%s)' % (device, ', dark' if dark else ''))

            # Following the link opens the saved copy.
            self.go_offline(page)
            link.click()
            page.wait_for_selector('#offline-banner', state='visible')
            self.check_page(page)
        finally:
            page.context.set_offline(False)

    def test_saved_question_readable_offline(self):
        self.check_offline_pages(self.open(), 'desktop', False)

    def test_saved_question_readable_offline_on_a_phone(self):
        self.check_offline_pages(self.open(device='mobile', dark=True), 'mobile', True)

    def test_sign_out_forgets_saved_pages(self):
        page = self.open(self.alice, device='mobile', dark=True)
        path = self.question.get_absolute_url()
        self.save_for_offline(page, path)
        self.assertIn('alice', page.content())  # a saved page shows who was signed in

        self.visit(page, '/logout/')
        with page.expect_navigation():
            page.click('#btLogout')
        page.wait_for_load_state('load')
        self.check_page(page)
        page.wait_for_function(NOT_SAVED, arg=[PAGES, self.url(path)])

        try:
            self.go_offline(page)
            page.goto(self.url(path))
            page.wait_for_selector('#offline-pages[data-loaded]', state='attached')
            self.assertEqual(page.locator('#offline-pages a', has_text=self.question.title).count(), 0)
            self.assertNotIn('alice', page.inner_text('#roof'))
            self.check_page(page)
        finally:
            page.context.set_offline(False)
