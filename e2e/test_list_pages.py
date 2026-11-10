"""List pages: the home page and question lists (rows with compact stats,
accepted and unanswered states, excerpts, tag chips, author and <time>), sort
tabs, pagination, tag pages, the tags index with its filter box, the users
index with its search, the empty state, interesting and ignored tags, and the
keyboard order, on a desktop and a phone in light and dark mode (screenshots
in tmp/e2e/lists-*.png)."""
import os

from forum.actions import AcceptAnswerAction, VoteUpAction
from forum.models import MarkedTag, Question, Tag

from .base import ARTIFACTS, E2ETestCase

VIEWS = (('desktop', False), ('desktop', True), ('mobile', False), ('mobile', True))


class ListPagesTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=520)
        self.bob = self.create_user('bob', reputation=1250, real_name='Robert Builder')
        self.carol = self.create_user('carol', reputation=90)
        # Oldest first: accepted (3 days), answered (2 days), unanswered (today).
        self.accepted = self.create_question(
            self.alice, 'How do I read Collect CSV dates as dates in R?', tags='collect export r', days_ago=3,
            body='I export my **Collect** survey to CSV and load it in R, but the dates come out as text. '
                 'I tried changing the date format in the designer and reading the file again with read.csv().')
        answer = self.create_answer(self.bob, self.accepted, 'Use `colClasses` when reading the file.')
        self._as_request(self.alice)
        AcceptAnswerAction(user=self.alice, node=answer, ip='127.0.0.1').save()
        self.answered = self.create_question(self.carol, 'Can SEPAL process Sentinel-2 time series?',
                                             tags='sepal', days_ago=2)
        self.create_answer(self.alice, self.answered, 'Yes, with the time series module.')
        self.unanswered = self.create_question(self.bob, 'Exporting Earth Map layers as GeoTIFF',
                                               tags='earthmap export')
        # The unanswered one has the most votes.
        for voter in (self.alice, self.carol):
            self._as_request(voter)
            VoteUpAction(user=voter, node=self.unanswered, ip='127.0.0.1').save()

    def screenshot(self, page, name):
        os.makedirs(ARTIFACTS, exist_ok=True)
        page.screenshot(path=os.path.join(ARTIFACTS, 'lists-%s.png' % name), full_page=True)

    @staticmethod
    def text(locator):
        return ' '.join(locator.inner_text().split())

    def titles(self, page):
        return [t.strip() for t in page.locator('#listA .question-row h2 a').all_inner_texts()]

    def row(self, page, question):
        return page.locator('#listA .question-row:has(h2 a[href="%s"])' % question.get_absolute_url())

    def test_screenshots(self):
        member = self.create_user('dave', reputation=300)
        MarkedTag.objects.create(user=member, tag=Tag.objects.get(name='collect'), reason='good')
        MarkedTag.objects.create(user=member, tag=Tag.objects.get(name='earthmap'), reason='bad')
        for device, dark in VIEWS:
            suffix = '%s-%s' % (device, 'dark' if dark else 'light')
            page = self.open(device=device, dark=dark)
            for path, name in (('/', 'home'), ('/tags/', 'tags'), ('/users/', 'users'),
                               ('/tags/?q=zzz', 'tags-empty')):
                self.visit(page, path)
                self.screenshot(page, '%s-%s' % (name, suffix))
            member_page = self.open(member, device=device, dark=dark)
            self.visit(member_page, '/tags/export/')
            self.screenshot(member_page, 'tag-marked-%s' % suffix)

    def test_rows_show_stats_and_states(self):
        page = self.open()
        self.visit(page, '/questions/')
        self.assertEqual(page.locator('h1').inner_text().strip(), 'All Questions')
        self.assertEqual(page.locator('.list-count').inner_text(), '3 questions')
        accepted = self.row(page, self.accepted)
        self.assertIn('is-accepted', accepted.get_attribute('class'))
        status = accepted.locator('.status')
        self.assertIn('answered-accepted', status.get_attribute('class'))
        self.assertIn('1 answer', self.text(status))
        self.assertIn('this question has an accepted answer', self.text(status))   # for screen readers
        self.assertTrue(status.locator('.visually-hidden').count() == 1)
        self.assertIn('dates come out as text', accepted.locator('.summary.excerpt').inner_text())
        self.assertEqual(accepted.locator('.tags a').all_inner_texts(), ['collect', 'export', 'r'])
        # Last active: bob answered, then alice accepted; the row names who and when.
        time = accepted.locator('.userinfo time')
        self.assertTrue(time.get_attribute('datetime'))
        self.assertTrue(time.get_attribute('title'))
        self.assertIn('modified', self.text(accepted.locator('.userinfo')))

        unanswered = self.row(page, self.unanswered)
        self.assertIn('is-unanswered', unanswered.get_attribute('class'))
        self.assertIn('unanswered', unanswered.locator('.status').get_attribute('class'))
        self.assertEqual(unanswered.locator('.votes .item-count').inner_text(), '2')
        self.assertIn('asked', unanswered.locator('.userinfo').inner_text())
        self.assertIn('bob', unanswered.locator('.userinfo').inner_text())
        # Distinct colours for the three answer states.
        colours = [self.row(page, q).locator('.status').evaluate('el => getComputedStyle(el).backgroundColor')
                   for q in (self.accepted, self.answered, self.unanswered)]
        self.assertEqual(len(set(colours)), 3, colours)

        # On a phone the stats are one line above the title.
        phone = self.open(device='mobile', dark=True)
        self.visit(phone, '/questions/')
        row = self.row(phone, self.accepted)
        counts, title = row.locator('.counts').bounding_box(), row.locator('h2').bounding_box()
        self.assertLess(counts['y'] + counts['height'], title['y'] + 1)
        self.assertLess(counts['height'], 40)
        self.assertEqual(phone.locator('.list-ask').is_visible(), False)   # the tab bar's Ask is there
        self.assertTrue(phone.locator('.app-bar-ask').is_visible())

    def test_sort_tabs_change_order(self):
        page = self.open()
        self.visit(page, '/questions/')
        tabs = page.locator('nav.sort-tabs a')
        self.assertEqual(tabs.all_inner_texts(), ['active', 'newest', 'hottest', 'most voted', 'unanswered'])
        self.assertEqual(page.locator('nav.sort-tabs a[aria-current]').inner_text(), 'active')
        with page.expect_navigation():
            page.click('nav.sort-tabs a[data-sort=newest]')
        self.check_page(page)
        self.assertEqual(page.locator('nav.sort-tabs a[aria-current]').inner_text(), 'newest')
        self.assertEqual(page.locator('nav.sort-tabs a[aria-current=true]').count(), 1)
        self.assertEqual(self.titles(page), [self.unanswered.title, self.answered.title, self.accepted.title])
        with page.expect_navigation():
            page.click('nav.sort-tabs a[data-sort=mostvoted]')
        self.check_page(page)
        self.assertIn('sort=mostvoted', page.url)
        self.assertEqual(self.titles(page)[0], self.unanswered.title)
        # The sidebar says what the order is.
        self.assertIn('voted', page.locator('.list-stats-sort').inner_text())

    def test_pagination(self):
        for i in range(15):
            Question(author=self.carol, title='Filler question number %d about plots' % i,
                     body='Body of filler question %d, long enough.' % i, tagnames='plots').save()
        page = self.open(device='mobile')
        self.visit(page, '/questions/?sort=newest&pagesize=15')
        pager = page.locator('.list-footer nav.paginator')
        self.assertEqual(pager.get_attribute('aria-label'), 'Pages')
        self.assertEqual(pager.locator('[aria-current=page]').inner_text(), '1')
        self.assertEqual(pager.locator('.prev.disabled').count(), 1)
        self.assertEqual(page.locator('#listA .question-row').count(), 15)
        self.assertEqual(page.locator('.page-sizes [aria-current]').inner_text(), '15')
        with page.expect_navigation():
            pager.locator('a[rel=next]').click()
        self.check_page(page)
        self.assertEqual(page.locator('nav.paginator [aria-current=page]').inner_text(), '2')
        self.assertEqual(page.locator('#listA .question-row').count(), 3)
        self.assertEqual(page.locator('nav.paginator .next.disabled').count(), 1)
        self.assertIn(self.accepted.title, self.titles(page))
        with page.expect_navigation():
            page.locator('nav.paginator a[rel=prev]').click()
        self.check_page(page)
        self.assertEqual(page.locator('nav.paginator [aria-current=page]').inner_text(), '1')
        # A bigger page size: everything on one page, no pager.
        with page.expect_navigation():
            page.locator('.page-sizes a', has_text='30').click()
        self.check_page(page)
        self.assertEqual(page.locator('#listA .question-row').count(), 18)
        self.assertEqual(page.locator('nav.paginator').count(), 0)
        self.screenshot(page, 'pagination-mobile-light')

    def test_tag_page(self):
        page = self.open()
        self.visit(page, '/')
        self.row(page, self.unanswered).locator('.tags a', has_text='export').click()
        page.wait_for_load_state()
        self.check_page(page)
        self.assertTrue(page.url.endswith('/tags/export/'))
        self.assertIn('export', page.locator('h1').inner_text())
        self.assertEqual(sorted(self.titles(page)), sorted([self.accepted.title, self.unanswered.title]))
        self.assertIn('related tags', page.locator('#CARight').inner_text().lower())

    def test_tags_index_filter(self):
        page = self.open()
        self.visit(page, '/tags/')
        cards = page.locator('#searchtags li.tag-card')
        self.assertEqual(cards.count(), 5)
        self.assertIn('2 questions', self.text(page.locator('li.tag-card:has(a[href="/tags/export/"])')))
        self.assertEqual(page.locator('nav.sort-tabs a[aria-current]').inner_text(), 'by popularity')
        # Filters this page as you type.
        filter_box = page.get_by_label('Filter tags')
        filter_box.press_sequentially('ex')
        self.assertEqual([c.strip() for c in page.locator('li.tag-card:visible > a').all_inner_texts()], ['export'])
        filter_box.fill('zzz')
        filter_box.dispatch_event('input')
        self.assertEqual(page.locator('li.tag-card:visible').count(), 0)
        self.assertIn('Press Enter to search all tags', page.locator('#tag-filter-status').inner_text())
        filter_box.press('Escape')
        self.assertEqual(page.locator('li.tag-card:visible').count(), 5)
        # Enter searches on the server.
        filter_box.fill('sep')
        with page.expect_navigation():
            filter_box.press('Enter')
        self.check_page(page)
        self.assertIn('q=sep', page.url)
        self.assertEqual(cards.count(), 1)
        self.assertIn('1 tag matches', page.locator('#tag-filter-status').inner_text())
        # Sorting keeps the search.
        with page.expect_navigation():
            page.click('nav.sort-tabs a[data-sort=name]')
        self.check_page(page)
        self.assertIn('q=sep', page.url)
        self.assertEqual(page.locator('nav.sort-tabs a[aria-current]').inner_text(), 'by name')
        # The whole card opens the tag.
        with page.expect_navigation():
            cards.first.click(position={'x': 150, 'y': 40})
        self.check_page(page)
        self.assertTrue(page.url.endswith('/tags/sepal/'))

    def test_users_index_search(self):
        page = self.open(device='mobile', dark=True)
        self.visit(page, '/users/')
        cards = page.locator('.userList li.user-card')
        self.assertEqual(cards.count(), 3)
        self.assertEqual(page.locator('nav.sort-tabs a[aria-current]').inner_text(), 'reputation')
        self.assertIn('bob', cards.first.inner_text())
        self.assertRegex(cards.first.locator('.score').inner_text(), r'^1\.\dk$')
        search = page.get_by_label('Search users')
        search.press_sequentially('rob')    # the real name counts too
        self.assertEqual(page.locator('li.user-card:visible .user-card-name').all_inner_texts(), ['bob'])
        search.fill('car')
        with page.expect_navigation():
            search.press('Enter')
        self.check_page(page)
        self.assertEqual(cards.count(), 1)
        self.assertIn('1 person matches', page.locator('#user-filter-status').inner_text())
        # The whole card is the profile link (the profile page itself is tested elsewhere).
        link = cards.first.locator('a.user-card-name')
        self.assertIn('/users/%d/' % self.carol.id, link.get_attribute('href'))
        cards.first.evaluate('el => el.scrollIntoView({block: "center"})')   # not under the phone's tab bar
        box = cards.first.bounding_box()
        self.assertTrue(page.evaluate('([x, y]) => document.elementFromPoint(x, y).closest("li.user-card") !== null && '
                                      'getComputedStyle(document.querySelector("a.user-card-name"), "::after").position === "absolute"',
                                      [box['x'] + box['width'] - 10, box['y'] + box['height'] - 6]))
        # Nobody found.
        self.visit(page, '/users/?q=nobody-at-all')
        self.assertIn('Nobody matches', page.locator('.list-empty h2').inner_text())
        page.click('.list-empty a:has-text("Show everyone")')
        page.wait_for_load_state()
        self.check_page(page)
        self.assertEqual(cards.count(), 3)

    def test_interesting_and_ignored_tags(self):
        member = self.create_user('dave', reputation=300)
        MarkedTag.objects.create(user=member, tag=Tag.objects.get(name='collect'), reason='good')
        MarkedTag.objects.create(user=member, tag=Tag.objects.get(name='earthmap'), reason='bad')
        page = self.open(member)
        self.visit(page, '/questions/')
        # Ignored questions are left out of the lists; interesting ones are marked.
        self.assertNotIn(self.unanswered.title, self.titles(page))
        self.assertIn('is-interesting', self.row(page, self.accepted).get_attribute('class'))
        self.assertEqual(self.row(page, self.accepted).locator('a.tag-interesting').inner_text(), 'collect')
        # A tag page shows them, marked.
        self.visit(page, '/tags/export/')
        self.assertIn('is-ignored', self.row(page, self.unanswered).get_attribute('class'))
        # The remove icon works from the keyboard.
        icon = page.locator('#ignored-tag-earthmap .delete-icon')
        self.assertEqual(icon.get_attribute('role'), 'button')
        icon.focus()
        page.keyboard.press('Enter')
        page.wait_for_selector('#ignored-tag-earthmap', state='detached')
        self.wait_for_ajax(page)
        self.assertNotIn('is-ignored', self.row(page, self.unanswered).get_attribute('class'))
        self.assertFalse(MarkedTag.objects.filter(user=member, reason='bad').exists())
        self.check_page(page)

    def test_keyboard_focus_order(self):
        page = self.open()
        self.visit(page, '/questions/')
        page.locator('.list-ask').focus()
        order = []
        for _ in range(9):
            page.keyboard.press('Tab')
            order.append(page.evaluate('''() => { const el = document.activeElement;
                return (el.closest('nav.sort-tabs') ? 'sort:' : el.classList.contains('feed-icon') ? 'feed' :
                        el.closest('.question-row h2') ? 'title:' : el.closest('.question-row .tags') ? 'tag:' :
                        el.closest('.question-row .userinfo') ? 'user:' : el.tagName + ':') +
                       el.textContent.trim(); }'''))
        self.assertEqual(order[:5], ['sort:active', 'sort:newest', 'sort:hottest', 'sort:most voted', 'sort:unanswered'])
        self.assertEqual(order[5], 'feed')
        self.assertTrue(order[6].startswith('title:'), order)
        self.assertTrue(order[7].startswith('tag:'), order)
        # The focused link is visibly outlined.
        self.assertNotEqual(page.evaluate('getComputedStyle(document.activeElement).outlineStyle'), 'none')
        self.check_page(page)


class EmptyListTest(E2ETestCase):
    def test_empty_state(self):
        os.makedirs(ARTIFACTS, exist_ok=True)
        for device, dark in VIEWS:
            page = self.open(device=device, dark=dark)
            self.visit(page, '/')
            empty = page.locator('#listA .list-empty')
            self.assertEqual(empty.locator('h2').inner_text(), 'No questions here yet')
            self.assertEqual(page.locator('.list-count').inner_text(), '0 questions')
            self.assertTrue(empty.get_by_role('link', name='Ask a question').is_visible())
            self.assertEqual(page.locator('nav.paginator').count(), 0)
            page.screenshot(path=os.path.join(ARTIFACTS, 'lists-empty-%s-%s.png' % (
                device, 'dark' if dark else 'light')), full_page=True)
        self.assertEqual(empty.get_by_role('link', name='Ask a question').get_attribute('href'), '/questions/ask/')
        self.assertEqual(empty.get_by_role('link', name='Browse tags').get_attribute('href'), '/tags/')
