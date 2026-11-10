"""The question page: post typography, code blocks with a Copy button, the
vote widget, the accepted answer, answer sorting, author cards with exact
times, the post menu from the keyboard, comments and the answer form, on a
desktop and on a phone, in light and dark mode (screenshots in
tmp/e2e/question-page-*.png)."""
import os

from forum.actions import AcceptAnswerAction, CloseAction, VoteUpAction
from forum.models import Question

from .base import ARTIFACTS, E2ETestCase

QUESTION_BODY = '''I export my **Collect** survey to CSV and load it in R, but the dates come out as text.

## What I tried

1. Exporting with the default settings
2. Changing the `date_format` option in the designer
3. Reading the file with `read.csv()`

> The exported file uses the format chosen in the survey settings.

<table>
<thead><tr><th>Column</th><th>Type in Collect</th><th>Type in R</th></tr></thead>
<tbody>
<tr><td>plot_id</td><td>integer</td><td>integer</td></tr>
<tr><td>survey_date</td><td>date</td><td>character (should be Date)</td></tr>
<tr><td>surveyor_name_and_organisation_with_a_long_name</td><td>text</td><td>character</td></tr>
</tbody>
</table>

```r
data <- read.csv("export.csv")
str(data$survey_date)   # chr "2024-05-01" "2024-05-02" ... and a long line that has to scroll sideways on a phone
```

How do I get proper dates?'''

ANSWER_BODY = '''Convert the column after reading it, or tell `read.csv()` the class up front:

```r
data <- read.csv("export.csv", colClasses = c(survey_date = "Date"))
```

If the format isn't ISO 8601, use `as.Date(x, format = "%d/%m/%Y")`.'''


class QuestionPageTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)    # asks
        self.bob = self.create_user('bob', reputation=1200)       # answers (accepted)
        self.carol = self.create_user('carol', reputation=300)    # answers, comments
        self.question = self.create_question(self.alice, 'How do I read Collect CSV dates as dates in R?',
                                             tags='collect export r', body=QUESTION_BODY)
        self.accepted = self.create_answer(self.bob, self.question, ANSWER_BODY)
        self.other = self.create_answer(self.carol, self.question,
                                        'The `lubridate` package also works: `ymd(data$survey_date)`.')
        self.create_comment(self.carol, self.question, 'Which version of Collect do you use, @alice?')
        self.create_comment(self.alice, self.question, 'Collect 4.1 with R 4.3 on Windows.')
        self.create_comment(self.alice, self.accepted, 'Thanks @bob, colClasses did it.')
        self._as_request(self.carol)
        VoteUpAction(user=self.carol, node=self.accepted, ip='127.0.0.1').save()
        self._as_request(self.alice)
        AcceptAnswerAction(user=self.alice, node=self.accepted, ip='127.0.0.1').save()

    def screenshot(self, page, name):
        os.makedirs(ARTIFACTS, exist_ok=True)
        page.screenshot(path=os.path.join(ARTIFACTS, 'question-page-%s.png' % name), full_page=True)

    def test_screenshots(self):
        for device, dark in (('desktop', False), ('desktop', True), ('mobile', False), ('mobile', True)):
            page = self.open(self.alice, device=device, dark=dark)
            self.visit(page, self.question.get_absolute_url())
            self.screenshot(page, '%s-%s' % (device, 'dark' if dark else 'light'))

    def test_copy_button(self):
        page = self.open(self.carol)
        page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=self.live_server_url)
        self.visit(page, self.question.get_absolute_url())
        answer = page.locator('#answer-container-%d' % self.accepted.id)
        button = answer.get_by_role('button', name='Copy code to the clipboard')
        self.assertEqual(button.inner_text(), 'Copy')
        button.click()
        page.wait_for_function('() => document.getElementById("copy-status").textContent === "Copied"')
        self.assertEqual(button.inner_text(), 'Copied')
        self.assertEqual(page.evaluate('navigator.clipboard.readText()'),
                         'data <- read.csv("export.csv", colClasses = c(survey_date = "Date"))')

        # From the keyboard: the question's code block, with Enter.
        question_button = page.locator('.question-body .code-copy')
        question_button.focus()
        page.keyboard.press('Enter')
        page.wait_for_function('() => document.querySelector(".question-body .code-copy").textContent === "Copied"')
        self.assertTrue(page.evaluate('navigator.clipboard.readText()').startswith('data <- read.csv("export.csv")\nstr('))
        self.check_page(page)

    def test_accepted_answer_and_jump_link(self):
        page = self.open(self.carol, device='mobile')
        self.visit(page, self.question.get_absolute_url())
        selector = '#answer-container-%d' % self.accepted.id
        accepted = page.locator(selector)
        self.assertTrue(accepted.locator('.accepted-badge').is_visible())
        self.assertEqual(accepted.locator('.accepted-badge').inner_text(), 'Accepted answer')
        self.assertFalse(page.locator('#answer-container-%d .accepted-badge' % self.other.id).is_visible())
        page.click('.jump-to-accepted')
        page.wait_for_function('h => location.hash === h', arg=selector)
        self.assertTrue(page.evaluate('s => { const box = document.querySelector(s).getBoundingClientRect(); '
                                      'return box.top >= -1 && box.top < window.innerHeight; }', selector))
        self.check_page(page)

        # The asker's accept control is a labelled toggle; without an accepted answer, no jump link.
        alice_page = self.open(self.alice)
        self.visit(alice_page, self.question.get_absolute_url())
        accept = alice_page.locator('#accept-answer-%d' % self.accepted.id)
        self.assertEqual(accept.get_attribute('aria-pressed'), 'true')
        self.click_command(alice_page, '#accept-answer-%d' % self.accepted.id)
        self.assertEqual(accept.get_attribute('aria-pressed'), 'false')
        self.assertFalse(alice_page.locator(selector + ' .accepted-badge').is_visible())
        self.visit(alice_page, self.question.get_absolute_url())
        self.assertEqual(alice_page.locator('.jump-to-accepted').count(), 0)
        self.assertEqual(alice_page.get_by_role('button', name='Accept').count(), 2)
        # Until one is accepted, the asker is told what Accept does; the note
        # goes as soon as they accept (others never see it).
        hint = alice_page.locator('#accept-hint')
        self.assertTrue(hint.is_visible())
        self.assertIn('Did an answer solve your problem?', hint.inner_text())
        self.assertEqual(page.locator('#accept-hint').count(), 0)
        self.click_command(alice_page, '#accept-answer-%d' % self.accepted.id)
        self.assertEqual(hint.count(), 0)
        self.check_page(alice_page)

    def test_sort_tabs(self):
        dave = self.create_user('dave', reputation=100)
        newest = self.create_answer(dave, self.question, 'Or set the column type in the Collect export dialog.')
        page = self.open(self.carol)
        self.visit(page, self.question.get_absolute_url())
        tabs = page.locator('nav.answer-sort a')
        self.assertEqual(tabs.all_inner_texts(), ['Highest score', 'Newest', 'Oldest', 'Recent activity'])
        self.assertEqual(page.locator('nav.answer-sort a[aria-current]').inner_text(), 'Highest score')

        def order():
            return [int(i.split('-')[-1]) for i in page.locator('article.answer').evaluate_all('els => els.map(e => e.id)')]

        with page.expect_navigation():
            page.click('nav.answer-sort a[data-sort=newest]')
        self.check_page(page)
        self.assertIn('sort=newest', page.url)
        self.assertEqual(page.locator('nav.answer-sort a[aria-current]').inner_text(), 'Newest')
        # The accepted answer stays first.
        self.assertEqual(order(), [self.accepted.id, newest.id, self.other.id])
        with page.expect_navigation():
            page.click('nav.answer-sort a[data-sort=oldest]')
        self.check_page(page)
        self.assertEqual(order(), [self.accepted.id, self.other.id, newest.id])

    def test_times_and_author_cards(self):
        page = self.open()
        self.visit(page, self.question.get_absolute_url())
        self.assertEqual(page.locator('.question-meta time').count(), 2)
        self.assertIn('Viewed', page.locator('.question-meta').inner_text())
        card = page.locator('#answer-container-%d .post-update-info-user' % self.accepted.id)
        time = card.locator('time')
        self.assertEqual(time.get_attribute('datetime'), self.accepted.added_at.isoformat(timespec='seconds'))
        self.assertTrue(time.get_attribute('title'))
        self.assertIn('ago', time.inner_text())
        self.assertIn('bob', card.inner_text())
        self.assertEqual(card.locator('.score').inner_text(), '1.2k')
        self.assertTrue(page.locator('.comment time').first.get_attribute('datetime'))

    def test_edited_post_links_to_revisions(self):
        from forum.actions import ReviseAction
        self._as_request(self.carol)
        ReviseAction(user=self.carol, node=self.other, ip='127.0.0.1').save(data=dict(
            text='The `lubridate` package also works: `ymd(data$survey_date)` (edited).', summary='fix'))
        page = self.open()
        self.visit(page, self.question.get_absolute_url())
        edited = page.locator('#answer-container-%d .post-update-info-edited a' % self.other.id)
        self.assertEqual(edited.get_attribute('href'), self.other.get_revisions_url())
        self.assertTrue(edited.locator('time').get_attribute('datetime'))

    def test_post_menu_from_the_keyboard(self):
        moderator = self.create_user('moderator', reputation=2000, is_staff=True)
        page = self.open(moderator)
        self.visit(page, self.question.get_absolute_url())
        trigger = page.locator('#node-%d-menu-trigger' % self.accepted.id)
        dropdown = page.locator('#node-%d-menu-dropdown' % self.accepted.id)
        focused = lambda: page.evaluate('document.activeElement.textContent.trim()')
        self.assertEqual(trigger.evaluate('el => el.tagName'), 'BUTTON')
        self.assertEqual(trigger.get_attribute('aria-expanded'), 'false')
        trigger.focus()
        page.keyboard.press('Enter')
        dropdown.wait_for(state='visible')
        self.assertEqual(trigger.get_attribute('aria-expanded'), 'true')
        page.wait_for_function('id => document.activeElement === document.querySelector("#" + id + " a")',
                               arg='node-%d-menu-dropdown' % self.accepted.id)
        page.keyboard.press('ArrowDown')
        self.assertEqual(focused(), dropdown.locator('a').nth(1).inner_text().strip())
        page.keyboard.press('ArrowUp')
        page.keyboard.press('ArrowUp')   # wraps round to the last link
        self.assertEqual(focused(), dropdown.locator('a').last.inner_text().strip())
        page.keyboard.press('Escape')
        dropdown.wait_for(state='hidden')
        self.assertEqual(trigger.get_attribute('aria-expanded'), 'false')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'node-%d-menu-trigger' % self.accepted.id)
        # Space opens it too.
        page.keyboard.press(' ')
        dropdown.wait_for(state='visible')
        self.check_page(page)

    def test_menu_on_a_phone(self):
        page = self.open(self.carol, device='mobile', dark=True)
        self.visit(page, self.question.get_absolute_url())
        page.tap('#node-%d-menu-trigger' % self.other.id)
        dropdown = page.locator('#node-%d-menu-dropdown' % self.other.id)
        dropdown.wait_for(state='visible')
        page.wait_for_function('() => !jQuery(":animated").length')
        box = dropdown.bounding_box()
        self.assertGreaterEqual(box['x'], 0)
        self.assertLessEqual(box['x'] + box['width'], 390)
        self.assertGreaterEqual(dropdown.locator('a').first.bounding_box()['height'], 40)
        self.check_page(page)
        page.screenshot(path=os.path.join(ARTIFACTS, 'question-page-mobile-dark-menu.png'))

    def test_votes_and_comment_form(self):
        page = self.open(self.carol, device='mobile', dark=True)
        self.visit(page, self.question.get_absolute_url())
        upvote = page.locator('#post-%d-upvote' % self.question.id)
        self.assertEqual(upvote.get_attribute('aria-label'), 'Vote up')
        self.assertEqual(upvote.get_attribute('aria-pressed'), 'false')
        self.assertEqual(page.locator('#post-%d-upvote' % self.accepted.id).get_attribute('aria-pressed'), 'true')
        self.click_command(page, '#post-%d-upvote' % self.question.id)
        self.assertEqual(upvote.get_attribute('aria-pressed'), 'true')
        self.assertEqual(page.locator('#post-%d-score' % self.question.id).inner_text().strip(), '1')

        page.click('#comment-tools-%d .add-comment-link' % self.other.id)
        form = page.locator('#comment-%d-form' % self.other.id)
        textarea = form.get_by_label('Your comment')
        textarea.wait_for()
        counter = page.locator('#comment-%d-chars-left' % self.other.id)
        self.assertTrue(counter.is_visible())
        self.assertIn('characters needed', counter.inner_text())
        textarea.fill('lubridate is great for this.')
        page.wait_for_function('el => /characters left/.test(el.innerText)', arg=counter.element_handle())
        page.wait_for_function('() => !jQuery(":animated").length')
        self.screenshot(page, 'mobile-dark-comment-form')
        form.locator('input.comment-submit').click()
        self.wait_for_ajax(page)
        page.wait_for_selector('.comment:has-text("lubridate is great")')
        self.check_page(page)

    def test_closed_duplicate(self):
        original = self.create_question(self.bob, 'Reading dates from a Collect export in R', tags='collect r')
        moderator = self.create_user('moderator', reputation=2000, is_staff=True)
        self._as_request(moderator)
        CloseAction(user=moderator, node=self.question, extra='duplicate', ip='127.0.0.1').save(
            data=dict(duplicate_of=original))
        for device, dark in (('desktop', False), ('mobile', True)):
            page = self.open(self.carol, device=device, dark=dark)
            self.visit(page, Question.objects.get(id=self.question.id).get_absolute_url())
            self.assertIn('This question already has an answer here', page.locator('.question-duplicate').inner_text())
            self.assertIn('Reading dates from a Collect export in R', page.locator('.question-duplicate a').inner_text())
            self.assertIn('closed for the following reason', page.locator('.question-status').inner_text())
            self.assertEqual(page.locator('#fmanswer #editor').count(), 0)
            self.screenshot(page, 'closed-%s-%s' % (device, 'dark' if dark else 'light'))
