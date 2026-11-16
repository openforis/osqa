"""Search: the header search box, ranked results with marked snippets,
operators, sort tabs, the empty state and the search tips."""
from .base import E2ETestCase


class SearchTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=100)
        self.bob = self.create_user('bob', reputation=100)
        self.body_only = self.create_question(self.alice, 'Exporting survey results to a spreadsheet', tags='collect',
                                              body='The raster layer goes missing after the export. <b>Why</b>?',
                                              days_ago=2)
        self.title_match = self.create_question(self.bob, 'Raster layers in Earth Map', tags='earthmap',
                                                body='How can I show my own layers on the map in Earth Map?')
        self.create_answer(self.alice, self.title_match, 'Upload the raster as a GeoTIFF asset first.')

    def search_from_header(self, page, text):
        self.search_field(page).fill(text)
        page.locator('#searchBar button[type=submit]').click()
        page.wait_for_load_state()
        self.check_page(page)

    def result_titles(self, page):
        return page.locator('#search-results h2 a').all_inner_texts()

    def test_search_rank_filter_and_sort(self):
        page = self.open()
        self.visit(page, '/')
        self.search_from_header(page, 'raster')
        self.assertIn('/search/?', page.url)
        # The title match first; the snippet marks the word.
        self.assertEqual(self.result_titles(page), ['Raster layers in Earth Map',
                                                    'Exporting survey results to a spreadsheet'])
        marks = page.locator('#search-results .search-snippet mark')
        self.assertTrue(marks.first.is_visible())
        self.assertEqual({m.lower() for m in marks.all_inner_texts()}, {'raster'})
        self.assertIn('About 2 results', page.locator('.search-count').inner_text())

        # Newest first, then back to relevance, with the sort tabs.
        page.get_by_role('link', name='newest', exact=True).click()
        page.wait_for_load_state()
        self.check_page(page)
        self.assertEqual(self.result_titles(page)[0], 'Raster layers in Earth Map')
        page.get_by_role('link', name='votes', exact=True).click()
        page.wait_for_load_state()
        self.check_page(page)
        self.assertIn('sort=votes', page.url)
        page.get_by_role('link', name='relevance', exact=True).click()
        page.wait_for_load_state()
        self.assertEqual(self.result_titles(page)[0], 'Raster layers in Earth Map')

        # A tag operator from the page's own search form.
        page.fill('#search-page-q', 'raster [collect]')
        page.locator('.search-page-form button[type=submit]').click()
        page.wait_for_load_state()
        self.check_page(page)
        self.assertEqual(self.result_titles(page), ['Exporting survey results to a spreadsheet'])

        # Search tips open and explain the operators.
        page.locator('.search-tips summary').click()
        self.assertTrue(page.locator('.search-tips dl').is_visible())
        self.assertIn('is:unanswered', page.locator('.search-tips').inner_text())

    def test_empty_state_on_phone_in_dark_mode(self):
        page = self.open(device='mobile', dark=True)
        self.visit(page, '/search/?q=raster+is:accepted+%5Bcollect%5D')
        self.assertEqual(page.locator('#search-results').count(), 0)
        self.assertIn('No questions match your search.', page.locator('.search-empty').inner_text())
        page.locator('.search-empty a', has_text='without the filters').click()
        page.wait_for_load_state()
        self.check_page(page)
        self.assertEqual(len(self.result_titles(page)), 2)
        mark = page.locator('#search-results mark').first
        self.assertNotEqual(mark.evaluate('m => getComputedStyle(m).backgroundColor'), 'rgb(255, 255, 0)')

        self.visit(page, '/search/?q=nothing+like+this')
        page.locator('.search-empty a', has_text='Ask a question').click()
        page.wait_for_load_state()
        self.check_page(page)
        self.assertIn('/questions/ask/', page.url)
        self.assertEqual(page.locator('#id_title').input_value(), 'nothing like this')
