"""The header search box: "/" to focus, live suggestions (questions, tags,
people) from /search/suggest/ as an accessible combobox, the keyboard and the
mouse, the "Search for" row, the clear button, and the box on a phone in dark
mode. Screenshots of the open suggestions: tmp/e2e/searchbox-*.png."""
import os

from .base import ARTIFACTS, E2ETestCase

OPTIONS = '#searchbox-listbox [role=option]'


class SearchBoxTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=250)
        self.rasta = self.create_user('rastaman', reputation=40)
        self.layers = self.create_question(self.alice, 'Raster layers in Earth Map', tags='earthmap raster')
        self.create_answer(self.rasta, self.layers, 'Upload the raster as a GeoTIFF asset first.')
        self.export = self.create_question(self.rasta, 'Exporting a raster from SEPAL', tags='sepal raster',
                                           body='The <b>raster</b> export never finishes. What can I do?',
                                           days_ago=3)
        self.create_question(self.alice, 'Collect survey with a GPS field', tags='collect')

    def type_query(self, page, text):
        page.locator('#keywords').fill(text)
        page.wait_for_selector(OPTIONS)
        self.check_page(page)

    def option_texts(self, page):
        return [t.strip() for t in page.locator(OPTIONS).all_inner_texts()]

    def screenshot(self, page, name):
        os.makedirs(ARTIFACTS, exist_ok=True)
        path = os.path.join(ARTIFACTS, 'searchbox-%s.png' % name)
        bottom = page.evaluate("document.querySelector('.searchbox-panel').getBoundingClientRect().bottom")
        width = page.viewport_size['width']
        page.screenshot(path=path, clip={'x': 0, 'y': 0, 'width': width, 'height': min(bottom + 24, 900)})
        return path

    def test_keyboard(self):
        page = self.open()
        self.visit(page, '/')
        search = page.locator('#keywords')
        self.assertEqual(search.get_attribute('placeholder'), 'Search questions, tags and people')
        self.assertEqual(search.get_attribute('role'), 'combobox')
        self.assertEqual(search.get_attribute('aria-expanded'), 'false')
        self.assertTrue(page.locator('.searchbox-kbd').is_visible())

        # "/" focuses the box.
        page.locator('body').press('/')
        self.assertTrue(search.evaluate('el => el === document.activeElement'))
        self.assertEqual(search.input_value(), '')
        self.assertFalse(page.locator('.searchbox-kbd').is_visible())

        # Suggestions after two characters: questions, tags and people, the typed word marked.
        search.press_sequentially('r')
        page.wait_for_timeout(400)
        self.assertFalse(page.locator('.searchbox-panel').is_visible())
        search.press_sequentially('ast')
        page.wait_for_selector(OPTIONS)
        self.check_page(page)
        self.assertEqual(search.get_attribute('aria-expanded'), 'true')
        self.assertEqual(page.locator('.searchbox-group-label').all_inner_texts(), ['QUESTIONS', 'TAGS', 'PEOPLE'])
        texts = self.option_texts(page)
        self.assertIn('Raster layers in Earth Map', texts[0])
        self.assertIn('1 answer', texts[0])
        self.assertTrue(any(t.startswith('raster') and '2 questions' in t for t in texts))
        self.assertTrue(any('rastaman' in t and '40 reputation points' in t for t in texts))
        self.assertEqual(texts[-1], 'Search for “rast”')
        self.assertEqual(set(m.lower() for m in page.locator('#searchbox-listbox mark').all_inner_texts()),
                         {'rast'})
        self.assertIn('suggestions', page.locator('#searchbox [role=status]').inner_text())

        # Arrow keys move through the options (and wrap); Escape closes, then leaves the field.
        search.press('ArrowDown')
        first = page.locator(OPTIONS).first
        self.assertEqual(search.get_attribute('aria-activedescendant'), first.get_attribute('id'))
        self.assertEqual(first.get_attribute('aria-selected'), 'true')
        search.press('ArrowUp')
        self.assertEqual(search.get_attribute('aria-activedescendant'), page.locator(OPTIONS).last.get_attribute('id'))
        search.press('ArrowDown')
        self.assertEqual(search.get_attribute('aria-activedescendant'), first.get_attribute('id'))
        search.press('Escape')
        self.assertFalse(page.locator('.searchbox-panel').is_visible())
        self.assertEqual(search.get_attribute('aria-expanded'), 'false')
        self.assertIsNone(search.get_attribute('aria-activedescendant'))
        self.assertTrue(search.evaluate('el => el === document.activeElement'))
        search.press('Escape')
        self.assertFalse(search.evaluate('el => el === document.activeElement'))

        # Back in the field, the suggestions come back; Enter on a question opens it.
        search.focus()
        page.wait_for_selector(OPTIONS)
        search.press('ArrowDown')
        with page.expect_navigation():
            search.press('Enter')
        self.check_page(page)
        self.assertEqual(page.url, self.url(self.layers.get_absolute_url()))

        # The last row runs the full search.
        search = page.locator('#keywords')
        search.focus()
        search.press_sequentially('raster')
        page.wait_for_selector(OPTIONS + ' >> text=Search for “raster”')
        search.press('ArrowUp')
        with page.expect_navigation():
            search.press('Enter')
        self.check_page(page)
        self.assertIn('/search/?q=raster', page.url)
        self.assertEqual(page.locator('#search-results h2 a').count(), 2)
        self.assertEqual(page.locator('#keywords').input_value(), 'raster')

    def test_slash_ignored_in_other_fields_and_clear_button(self):
        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        title = page.locator('#id_title')
        title.click()
        title.press_sequentially('and/or')
        self.assertEqual(title.input_value(), 'and/or')
        self.assertTrue(title.evaluate('el => el === document.activeElement'))

        search = page.locator('#keywords')
        clear = page.locator('.searchbox-clear')
        self.assertFalse(clear.is_visible())
        self.type_query(page, 'collect')
        self.assertTrue(clear.is_visible())
        clear.click()
        self.assertEqual(search.input_value(), '')
        self.assertFalse(clear.is_visible())
        self.assertFalse(page.locator('.searchbox-panel').is_visible())
        self.assertTrue(search.evaluate('el => el === document.activeElement'))
        self.check_page(page)

    def test_mouse_and_screenshots(self):
        shots = []
        for dark in (False, True):
            page = self.open(dark=dark)
            self.visit(page, '/')
            idle = os.path.join(ARTIFACTS, 'searchbox-desktop-%s-idle.png' % ('dark' if dark else 'light'))
            page.screenshot(path=idle, clip={'x': 0, 'y': 0, 'width': 1280, 'height': 120})
            shots.append(idle)
            self.type_query(page, 'rast')
            page.locator(OPTIONS).nth(1).hover()
            shots.append(self.screenshot(page, 'desktop-%s' % ('dark' if dark else 'light')))
        # A click on a tag opens its page; on a person, their profile.
        page.locator(OPTIONS, has_text='2 questions').click()
        page.wait_for_url('**/tags/raster/')
        self.check_page(page)
        self.type_query(page, 'rasta')
        page.locator(OPTIONS, has_text='rastaman').click()
        page.wait_for_url('**' + self.rasta.get_profile_url())
        self.check_page(page)
        # Clicking elsewhere closes the panel.
        self.type_query(page, 'rast')
        page.mouse.click(5, 600)
        self.assertFalse(page.locator('.searchbox-panel').is_visible())
        self.assertTrue(all(os.path.exists(path) for path in shots))

    def test_phone_in_dark_mode(self):
        for dark in (True, False):
            page = self.open(device='mobile', dark=dark)
            self.visit(page, '/')
            # The tab bar's Search opens the box full screen.
            page.locator('#app-search').tap()
            self.assertFalse(page.locator('.searchbox-kbd').is_visible())
            field = page.locator('.searchbox-field').bounding_box()
            self.assertGreaterEqual(field['width'], 390 - 64 - 1)  # beside the back arrow
            self.assertGreaterEqual(field['height'], 44)
            self.type_query(page, 'rast')
            panel = page.locator('.searchbox-panel').bounding_box()
            self.assertEqual((round(panel['x']), round(panel['width'])), (0, 390))
            heights = [box['height'] for box in (o.bounding_box() for o in page.locator(OPTIONS).all())]
            self.assertTrue(all(h >= 44 for h in heights), heights)
            if dark:
                background = page.locator('.searchbox-panel').evaluate('el => getComputedStyle(el).backgroundColor')
                self.assertEqual(background, 'rgb(22, 27, 34)')  # --surface in dark mode
            self.screenshot(page, 'phone-%s' % ('dark' if dark else 'light'))
            self.check_page(page)
            if dark:
                page.locator(OPTIONS).first.tap()
                page.wait_for_url('**' + self.layers.get_absolute_url())
                self.check_page(page)
