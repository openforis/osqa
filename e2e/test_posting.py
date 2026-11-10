"""The core Q&A loop through the real interface: asking, previewing,
answering, commenting with mentions, voting, accepting, following,
favourites, editing, reporting, and the notifications that result."""
import re

from django.urls import reverse

from forum.models import Answer, Comment, Flag, Notification, Question, QuestionSubscription

from .base import E2ETestCase


class PostingTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)   # asks
        self.bob = self.create_user('bob', reputation=500)       # answers
        self.carol = self.create_user('carol', reputation=500)   # comments, votes, reports

    def ask(self, page, title, text, tags):
        self.visit(page, '/questions/ask/')
        page.fill('#id_title', title)
        page.fill('#editor', text)
        page.fill('#id_tags', tags)
        page.keyboard.press('Escape')  # close the tag suggestions
        with page.expect_navigation():
            page.click('#fmask input[name=ask]')
        self.check_page(page)
        return Question.objects.get(title=title)

    def answer(self, page, question, text):
        self.visit(page, question.get_absolute_url())
        page.fill('#fmanswer #editor', text)
        with page.expect_navigation():
            page.click('#fmanswer input[type=button]')
        self.check_page(page)
        return Answer.objects.filter(parent=question).latest('id')

    def comment(self, page, post, text):
        page.click('#comment-tools-%d .add-comment-link' % post.id)
        form = page.locator('#comment-%d-form' % post.id)
        form.locator('textarea').fill(text)
        form.locator('input[type=submit]').first.click()
        self.wait_for_ajax(page)
        page.wait_for_selector('.comment:has-text("%s")' % text[:20])
        self.check_page(page)
        return Comment.objects.filter(parent=post).latest('id')

    def test_question_lifecycle(self):
        # alice asks, with a live preview of the Markdown
        alice_page = self.open(self.alice)
        self.visit(alice_page, '/questions/ask/')
        alice_page.fill('#editor', 'Testing the **preview** first.')
        alice_page.wait_for_selector('#previewer strong:has-text("preview")')
        question = self.ask(alice_page, 'How do I export Collect survey data to CSV?',
                            'I have a survey with **200 plots** and need the data as CSV for R.', 'collect export')
        self.assertIn('How do I export Collect survey data to CSV?', alice_page.locator('h1').first.inner_text())
        self.assertEqual(alice_page.locator('.question-body strong, .post-text strong').first.inner_text(), '200 plots')
        self.assertEqual(sorted(question.tagname_list()), ['collect', 'export'])

        # bob answers
        bob_page = self.open(self.bob)
        answer = self.answer(bob_page, question, 'Open the survey in the designer and use **Export > CSV**.')
        self.assertEqual(bob_page.locator('.answer').count(), 1)

        # carol comments on the answer, mentioning alice, and votes it up
        carol_page = self.open(self.carol)
        self.visit(carol_page, question.get_absolute_url())
        comment = self.comment(carol_page, answer, 'Thanks @alice for asking, this helped me too.')
        self.assertIn('href="%s"' % self.alice.get_profile_url(), comment.body)
        self.click_command(carol_page, '#post-%d-upvote' % answer.id)
        self.assertEqual(carol_page.locator('#post-%d-score' % answer.id).inner_text().strip(), '1')
        self.assertEqual(Answer.objects.get(id=answer.id).score, 1)

        # alice sees the bell, reads her notifications and accepts the answer
        self.visit(alice_page, '/')
        self.assertIn('unread', alice_page.get_attribute('#notification-bell', 'aria-label'))
        # On a phone the tab bar's More shows the count too, and so does its sheet.
        phone = self.open(self.alice, device='mobile')
        phone.add_init_script('navigator.setAppBadge = n => { window.__badge = n; return Promise.resolve(); };'
                              'navigator.clearAppBadge = () => { window.__badge = 0; return Promise.resolve(); };')
        self.visit(phone, '/')
        unread = phone.locator('#notification-bell .notification-count').inner_text()
        self.assertEqual(phone.locator('#app-more .app-unread').inner_text(), unread)
        # ...and the installed app's icon (Badging API).
        self.assertEqual(phone.evaluate('window.__badge'), int(unread))
        self.assertIn('Notifications: %s unread' % unread, phone.locator('#app-more').inner_text())
        phone.click('#app-more')
        self.assertIn(unread, phone.locator('#app-more-sheet .app-sheet-count').inner_text())
        phone.keyboard.press('Escape')
        self.visit(alice_page, '/notifications/')
        texts = alice_page.locator('.inbox-text').all_inner_texts()
        self.assertTrue(any('bob answered' in t for t in texts), texts)
        self.assertTrue(any('carol mentioned you' in t for t in texts), texts)
        with alice_page.expect_navigation():
            alice_page.locator('.inbox-item a').filter(has_text='answered').click()
        self.check_page(alice_page)
        self.click_command(alice_page, 'a.accept-answer[href$="/%d/"]' % answer.id)
        self.assertTrue(Answer.objects.get(id=answer.id).nis.accepted)
        self.assertTrue(Notification.objects.filter(user=self.bob, kind='accepted').exists())

        # favourite and follow/unfollow
        self.click_command(alice_page, '#favorite-mark')
        self.assertTrue(alice_page.locator('#favorite-mark.on').count() == 1)
        # carol follows the question since she commented; the switch toggles that
        following = lambda: QuestionSubscription.objects.filter(user=self.carol, question=question).exists()
        self.assertTrue(following())
        self.click_command(carol_page, '.subscription_switch')
        self.assertFalse(following())
        self.click_command(carol_page, '.subscription_switch')
        self.assertTrue(following())

        # bob was told about the acceptance; emails went out too
        self.visit(bob_page, '/notifications/')
        self.assertIn('alice accepted your answer', bob_page.locator('.inbox-list').inner_text())
        self.assertTrue(any('New answer' in m[1] for m in self.mail_to(self.alice)))

    def test_edit_question(self):
        question = self.create_question(self.alice, 'Exporting data from Collect')
        page = self.open(self.alice)
        self.visit(page, reverse('edit_question', kwargs={'id': question.id}))
        page.fill('#id_title', 'Exporting survey data from Collect to CSV')
        page.fill('#id_summary', 'clearer title')
        with page.expect_navigation():
            page.get_by_role('button', name='Save edit').click()
        self.check_page(page)
        self.assertEqual(Question.objects.get(id=question.id).title, 'Exporting survey data from Collect to CSV')
        self.assertIn('Exporting survey data from Collect to CSV', page.locator('h1').first.inner_text())

    def test_report_a_post(self):
        question = self.create_question(self.alice, 'Cheap watches, buy now at a great discount')
        page = self.open(self.carol)
        self.visit(page, question.get_absolute_url())
        page.click('#node-%d-menu-trigger' % question.id)
        page.click('a[href^="/flag/%d/"]' % question.id)
        page.wait_for_selector('.dialog.prompt textarea[name=prompt]')
        page.fill('.dialog.prompt textarea[name=prompt]', 'spam')
        self.confirm_dialog(page)
        self.assertTrue(Flag.objects.filter(user=self.carol, node=question).exists())

    def test_answer_on_a_phone(self):
        question = self.create_question(self.alice, 'Can SEPAL process Sentinel-2 time series?', tags='sepal')
        page = self.open(self.bob, device='mobile', dark=True)
        answer = self.answer(page, question, 'Yes, use the time series recipe in SEPAL with Sentinel-2 enabled.')
        self.assertIn('time series recipe', page.locator('#answer-container-%d, .answer' % answer.id).first.inner_text())
        self.click_command(page, '#post-%d-upvote' % question.id)
        self.assertEqual(Question.objects.get(id=question.id).score, 1)

    def test_comment_mentions_suggest_users(self):
        question = self.create_question(self.alice, 'How do I install Collect Earth on a Mac?', tags='collect-earth')
        page = self.open(self.carol)
        self.visit(page, question.get_absolute_url())
        page.click('#comment-tools-%d .add-comment-link' % question.id)
        textarea = page.locator('#comment-%d-form textarea' % question.id)
        textarea.press_sequentially('Ping @al', delay=50)
        suggestion = page.locator('.mention-suggestions li:has-text("alice")')
        suggestion.first.wait_for()
        suggestion.first.click()
        self.assertRegex(textarea.input_value(), re.compile(r'@alice\b'))
        self.check_page(page)
