"""Emails and subscriptions through the real interface: comment, mention,
accepted-answer, new-member, new-question and digest emails, the email
settings that turn them on and off, a weekly or daily summary instead of
separate emails, following questions automatically and
the "Questions you follow" tab, unsubscribe links from each kind of email
(with undo), the welcome email's validation link and changing the email
address."""
import datetime
import re
from urllib.parse import urlsplit

from django.core.management import call_command
from django.urls import reverse

from forum import settings
from forum.models import Award, QuestionSubscription, User, ValidationHash
from forum.settings.email import EMAIL_DIGEST_FLAG

from .base import E2ETestCase


class EmailTestCase(E2ETestCase):
    def prefs(self, user, **changes):
        prefs = User.objects.get(id=user.id).subscription_settings
        for name, value in changes.items():
            setattr(prefs, name, value)
        if changes:
            prefs.save()
        return prefs

    def mails(self, user, subject):
        return [m for m in self.mail_to(user) if subject in m[1]]

    def link(self, text, label):
        """The path (and query) of the link after `label:` in a plain-text email."""
        url = re.search(re.escape(label) + r': (\S+)', text).group(1)
        parts = urlsplit(url)
        return parts.path + ('?' + parts.query if parts.query else '')

    def assert_notification(self, mail, recipient, subject, *content, specific=None):
        """A notification email: recipient, subject, content, the stop link and List-Unsubscribe."""
        to, mail_subject, html, text, media, headers = mail
        self.assertEqual(to, recipient)
        self.assertIn(subject, mail_subject)
        for part in content:
            self.assertIn(part, text)
        if specific:
            self.assertRegex(text, re.escape(specific) + r': http://testserver/unsubscribe/\S+/')
        self.assertIn('Unsubscribe from all emails: http://testserver/unsubscribe/', text)
        self.assertRegex(headers['List-Unsubscribe'], r'^<http://testserver/unsubscribe/[^>]+/>$')

    def unsubscribe_and_undo(self, path, is_on):
        """Opens an unsubscribe link signed out, unsubscribes, then undoes it."""
        page = self.open()
        self.visit(page, path)
        self.assertTrue(is_on(), 'opening the link must not unsubscribe')
        with page.expect_navigation():
            page.click('button.submit')
        self.check_page(page)
        self.assertIn("You're unsubscribed", page.content())
        self.assertFalse(is_on())
        with page.expect_navigation():
            page.get_by_role('button', name=re.compile('Undo')).click()
        self.check_page(page)
        self.assertIn("You're subscribed again", page.content())
        self.assertTrue(is_on())

    def save_email_settings(self, page, user, check=(), uncheck=(), radios=None):
        self.visit(page, user.get_user_subscriptions_url())
        for name in check:
            page.check('#id_%s' % name)
        for name in uncheck:
            page.uncheck('#id_%s' % name)
        for name, value in (radios or {}).items():
            page.check('input[name=%s][value=%s]' % (name, value))
        with page.expect_navigation():
            page.click('.email-settings-form [type=submit]')
        self.check_page(page)
        self.assertIn('Your email settings are saved', page.content())

    def comment(self, page, post, text):
        page.click('#comment-tools-%d .add-comment-link' % post.id)
        form = page.locator('#comment-%d-form' % post.id)
        form.locator('textarea').fill(text)
        page.keyboard.press('Escape')  # close the mention suggestions
        form.locator('input[type=submit]').first.click()
        self.wait_for_ajax(page)
        page.wait_for_selector('.comment:has-text("%s")' % text[:20])
        self.check_page(page)


class CommentAndMentionEmailTest(EmailTestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)   # asks
        self.bob = self.create_user('bob', reputation=500)       # answers
        self.carol = self.create_user('carol', reputation=500)   # comments
        self.dave = self.create_user('dave', reputation=500)     # is mentioned
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?')
        self.answer = self.create_answer(self.bob, self.question)
        self.sent_mail.clear()

    def test_comment_emails_follow_the_preferences(self):
        title = 'How do I export Collect survey data to CSV?'
        carol_page = self.open(self.carol)
        self.visit(carol_page, self.question.get_absolute_url())
        self.comment(carol_page, self.answer, 'Does this also work for @dave with older surveys?')

        # bob: a comment on his own answer
        comment_mails = self.mails(self.bob, 'New comment on')
        self.assertEqual(len(comment_mails), 1)
        self.assert_notification(comment_mails[0], self.bob, 'New comment on: %s' % title,
                                 'carol commented on your answer to "%s"' % title,
                                 'Does this also work for', specific='Stop emails about this question')
        # alice follows the question but not all its comments (the default); carol wrote it
        self.assertEqual(self.mail_to(self.alice), [])
        self.assertEqual(self.mail_to(self.carol), [])
        # dave gets only the mention email, with its own stop link
        self.assertEqual(len(self.mail_to(self.dave)), 1)
        self.assert_notification(self.mail_to(self.dave)[0], self.dave, 'carol mentioned you in: %s' % title,
                                 'You receive this email because someone mentioned you.',
                                 specific='Stop emails when someone mentions you')

        # alice asks for all comments in her email settings
        alice_page = self.open(self.alice)
        self.save_email_settings(alice_page, self.alice, check=['notify_comments'])
        self.assertTrue(self.prefs(self.alice).notify_comments)
        self.comment(carol_page, self.answer, 'Never mind, I found the export button myself.')
        self.assertEqual(len(self.mails(self.alice, 'New comment on')), 1)
        self.assertIn('Never mind, I found the export button', self.mails(self.alice, 'New comment on')[0][3])

        # the links in the emails stop them, and undo brings them back
        self.unsubscribe_and_undo(
            self.link(comment_mails[0][3], 'Stop emails about this question'),
            lambda: QuestionSubscription.objects.filter(user=self.bob, question=self.question).exists())
        self.unsubscribe_and_undo(
            self.link(self.mail_to(self.dave)[0][3], 'Stop emails when someone mentions you'),
            lambda: self.prefs(self.dave).notify_reply_to_comments)
        self.unsubscribe_and_undo(
            self.link(comment_mails[0][3], 'Unsubscribe from all emails'),
            lambda: self.prefs(self.bob).enable_notifications)


class AcceptedAnswerEmailTest(EmailTestCase):
    def test_accepting_emails_the_answerer_and_followers_who_asked(self):
        alice = self.create_user('alice', reputation=500)
        bob = self.create_user('bob', reputation=500)
        carol = self.create_user('carol', reputation=500)
        dave = self.create_user('dave', reputation=500)
        question = self.create_question(alice, 'Why does my Collect Earth plot not load?')
        answer = self.create_answer(bob, question)

        # carol and dave follow the question; carol also wants to hear about accepted answers
        for user in (carol, dave):
            page = self.open(user)
            self.visit(page, question.get_absolute_url())
            self.click_command(page, '.subscription_switch')
            self.assertTrue(QuestionSubscription.objects.filter(user=user, question=question).exists())
        carol_page = self.open(carol)
        self.save_email_settings(carol_page, carol, check=['notify_accepted'])
        self.sent_mail.clear()

        alice_page = self.open(alice)
        self.visit(alice_page, question.get_absolute_url())
        self.click_command(alice_page, 'a.accept-answer[href$="/%d/"]' % answer.id)
        self.assertEqual(sorted(m[0].username for m in self.sent_mail), ['bob', 'carol'])
        subject = 'Answer accepted: Why does my Collect Earth plot not load?'
        for user, sentence in ((bob, 'alice accepted your answer to'), (carol, "alice accepted bob's answer to")):
            self.assert_notification(self.mail_to(user)[0], user, subject, sentence,
                                     specific='Stop emails about this question')

        # carol switches it off again: no email the next time
        self.save_email_settings(carol_page, carol, uncheck=['notify_accepted'])
        self.click_command(alice_page, 'a.accept-answer[href$="/%d/"]' % answer.id)  # un-accept
        self.sent_mail.clear()
        self.click_command(alice_page, 'a.accept-answer[href$="/%d/"]' % answer.id)
        self.assertEqual([m[0].username for m in self.sent_mail], ['bob'])


class NewMemberEmailTest(EmailTestCase):
    def test_admin_hears_about_new_members(self):
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        page = self.open(admin)
        self.save_email_settings(page, admin, radios={'member_joins': 'i'})
        self.assertEqual(self.prefs(admin).member_joins, 'i')

        signup = self.open()
        self.visit(signup, '/account/local/register/')
        signup.fill('#id_username', 'newcomer')
        signup.fill('#id_email', 'newcomer@example.com')
        signup.fill('#id_password1', 'green-tree-river-7')
        signup.fill('#id_password2', 'green-tree-river-7')
        with signup.expect_navigation():
            signup.click('#bnewaccount')
        self.check_page(signup)
        newcomer = User.objects.get(username='newcomer')

        mails = self.mail_to(admin)
        self.assertEqual(len(mails), 1)
        self.assert_notification(mails[0], admin, 'newcomer joined', 'newcomer just joined',
                                 newcomer.get_profile_url(), specific='Stop emails about new members')
        self.assertEqual(self.mails(newcomer, 'newcomer joined'), [])
        self.unsubscribe_and_undo(self.link(mails[0][3], 'Stop emails about new members'),
                                  lambda: self.prefs(admin).member_joins == 'i')


class NewQuestionAndDigestEmailTest(EmailTestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)
        self.bob = self.create_user('bob', reputation=500)

    def test_any_new_question_when_chosen(self):
        page = self.open(self.bob)
        self.save_email_settings(page, self.bob, radios={'new_question': 'i'})
        self.create_question(self.alice, 'Can SEPAL mosaic Landsat 9 scenes?', tags='sepal')  # bob follows no tags
        mails = self.mail_to(self.bob)
        self.assertEqual(len(mails), 1)
        self.assert_notification(mails[0], self.bob, 'Can SEPAL mosaic Landsat 9 scenes?',
                                 specific='Stop emails about new questions')
        # undo puts back "any new question" as well as "tags I follow"
        self.unsubscribe_and_undo(self.link(mails[0][3], 'Stop emails about new questions'),
                                  lambda: self.prefs(self.bob).new_question == 'i'
                                  and self.prefs(self.bob).new_question_watched_tags == 'i')

    def test_answers_stop_when_switched_off(self):
        question = self.create_question(self.alice, 'Exporting plots from Collect Earth')
        page = self.open(self.alice)
        self.save_email_settings(page, self.alice, uncheck=['notify_answers'])
        self.create_answer(self.bob, question)
        self.assertEqual(self.mail_to(self.alice), [])

        self.save_email_settings(page, self.alice, check=['notify_answers'], radios={'subscribed_questions': 'n'})
        self.create_answer(self.create_user('carol'), question)
        self.assertEqual(self.mail_to(self.alice), [])

    def test_daily_digest(self):
        self.prefs(self.alice, send_digest=True)
        carol = self.create_user('carol', email_isvalid=False)
        self.prefs(carol, send_digest=True)
        self.set_setting(EMAIL_DIGEST_FLAG, {'LAST_DAILY': datetime.datetime.now() - datetime.timedelta(hours=1)})
        question = self.create_question(self.bob, 'What resolution do Sentinel-2 mosaics have?')
        self.sent_mail.clear()

        call_command('send_email_alerts')
        self.assertEqual([m[0] for m in self.sent_mail], [self.alice])
        mail = self.sent_mail[0]
        self.assert_notification(mail, self.alice, 'Daily digest', 'What resolution do Sentinel-2 mosaics have?',
                                 specific='Stop the daily digest')
        self.assertEqual(self.mail_to(carol), [])
        call_command('send_email_alerts')
        self.assertEqual(len(self.sent_mail), 1)

        # the question link in the HTML part opens the question
        path = re.search(r'href="http://testserver(%s[^"]*)"' % re.escape(question.get_absolute_url()), mail[2]).group(1)
        page = self.open(self.alice)
        self.visit(page, path)
        self.assertIn('What resolution do Sentinel-2 mosaics have?', page.locator('h1').first.inner_text())

        self.unsubscribe_and_undo(self.link(mail[3], 'Stop the daily digest'),
                                  lambda: self.prefs(self.alice).send_digest)


class EmailFrequencyTest(EmailTestCase):
    """A daily or weekly summary instead of separate emails."""

    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)
        self.bob = self.create_user('bob', reputation=500)
        self.prefs(self.alice, send_digest=False)  # the digest of new questions is another email
        self.question = self.create_question(self.alice, 'How do I merge repeat groups in Collect?')
        self.sent_mail.clear()

    def test_switch_to_weekly_on_the_settings_page(self):
        page = self.open(self.alice, device='mobile', dark=True)
        self.visit(page, self.alice.get_user_subscriptions_url())
        cards = page.locator('.email-frequency .frequency-option')
        self.assertEqual(cards.count(), 4)
        self.assertTrue(page.get_by_role('radio', name=re.compile('^As it happens')).is_checked())
        self.assertIn('One email every', cards.nth(2).inner_text())
        page.get_by_role('radio', name=re.compile('^Weekly summary')).check()
        with page.expect_navigation():
            page.locator('.email-frequency').get_by_role('button', name='Save').click()
        self.check_page(page)
        self.assertIn('Your email settings are saved', page.content())
        self.assertEqual(self.prefs(self.alice).email_frequency, 'w')
        self.assertTrue(page.get_by_role('radio', name=re.compile('^Weekly summary')).is_checked())

        # A new answer: no email now...
        answer = self.create_answer(self.bob, self.question, 'Use the merge option on the export page.')
        self.assertEqual(self.mail_to(self.alice), [])

        # ...but in the weekly summary, sent once.
        self.set_setting(settings.WEEKLY_SUMMARY_DAY, str(datetime.datetime.now().weekday()))
        call_command('send_email_alerts')
        call_command('send_email_alerts')
        mails = self.mail_to(self.alice)
        self.assertEqual(len(mails), 1)
        self.assert_notification(mails[0], self.alice, 'Your weekly summary: 1 update', 'Answers to your questions (1)',
                                 'How do I merge repeat groups in Collect?',
                                 'bob answered: Use the merge option on the export page.',
                                 specific='Stop these summaries')
        self.assertNotIn('Get a daily summary instead', mails[0][3])

        # its link opens the answer
        path = re.search(r'href="http://testserver(%s[^"]*)"' % re.escape(answer.get_absolute_url()), mails[0][2]).group(1)
        self.visit(page, path)
        self.assertIn('How do I merge repeat groups in Collect?', page.locator('h1').first.inner_text())

    def test_daily_summary_link_in_an_email(self):
        self.create_answer(self.bob, self.question)
        text = self.mail_to(self.alice)[0][3]
        path = self.link(text, 'Get a daily summary instead')

        page = self.open()
        self.visit(page, path)
        self.assertEqual(self.prefs(self.alice).email_frequency, 'i', 'opening the link must change nothing')
        with page.expect_navigation():
            page.click('button.submit')
        self.check_page(page)
        self.assertIn("You'll get a daily summary", page.content())
        self.assertEqual(self.prefs(self.alice).email_frequency, 'd')
        with page.expect_navigation():
            page.get_by_role('button', name=re.compile('Undo')).click()
        self.check_page(page)
        self.assertIn('Back to separate emails', page.content())
        self.assertEqual(self.prefs(self.alice).email_frequency, 'i')

    def test_weekly_summary_instead_of_unsubscribing(self):
        self.create_answer(self.bob, self.question)
        path = self.link(self.mail_to(self.alice)[0][3], 'Stop emails about this question')
        page = self.open(device='mobile')
        self.visit(page, path)
        with page.expect_navigation():
            page.get_by_role('button', name='Switch to a weekly summary instead').click()
        self.check_page(page)
        self.assertIn("You'll get a weekly summary", page.content())
        self.assertEqual(self.prefs(self.alice).email_frequency, 'w')
        self.assertTrue(QuestionSubscription.objects.filter(user=self.alice, question=self.question).exists())
        with page.expect_navigation():
            page.get_by_role('button', name=re.compile('Undo')).click()
        self.check_page(page)
        self.assertEqual(self.prefs(self.alice).email_frequency, 'i')


class FollowingQuestionsTest(EmailTestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)
        self.bob = self.create_user('bob', reputation=500)
        self.question = self.create_question(self.bob, 'How do I add a new user to Collect?')

    def test_follow_questions_viewed_and_manage_them(self):
        own = self.create_question(self.alice, 'A question alice asked herself')
        page = self.open(self.alice)
        self.save_email_settings(page, self.alice, check=['questions_viewed'])
        self.visit(page, self.question.get_absolute_url())
        subscription = QuestionSubscription.objects.get(user=self.alice, question=self.question)
        self.assertTrue(subscription.auto_subscription)

        # The "Questions you follow" tab lists both; the filter hides automatic ones
        self.visit(page, self.alice.get_user_subscriptions_url())
        with page.expect_navigation():
            page.click('#subscriptions_management_button')
        self.check_page(page)
        listed = page.locator('#subscription_list').inner_text()
        self.assertIn('How do I add a new user to Collect?', listed)
        self.assertIn('A question alice asked herself', listed)
        with page.expect_navigation():
            page.get_by_role('link', name="don't show auto-subscribe").click()
        self.check_page(page)
        self.assertNotIn('How do I add a new user to Collect?', page.locator('#subscription_list').inner_text())
        with page.expect_navigation():
            page.get_by_role('link', name='show auto-subscribe').click()
        self.check_page(page)

        # Unfollow from the list
        item = page.locator('.subscription_summary', has_text='How do I add a new user to Collect?')
        with page.expect_navigation():
            item.locator('button.subscription_unsubscribe_button').click()
        self.check_page(page)
        self.assertFalse(QuestionSubscription.objects.filter(user=self.alice, question=self.question).exists())
        self.assertIn('tab=manage', page.url)
        listed = page.locator('#subscription_list').inner_text()
        self.assertNotIn('How do I add a new user to Collect?', listed)
        self.assertIn('A question alice asked herself', listed)
        self.assertTrue(QuestionSubscription.objects.filter(user=self.alice, question=own).exists())

    def test_follow_all_new_questions(self):
        page = self.open(self.alice)
        self.save_email_settings(page, self.alice, check=['all_questions'])
        question = self.create_question(self.bob, 'Is there an API for Collect?', tags='api')
        self.assertTrue(QuestionSubscription.objects.filter(user=self.alice, question=question).exists())
        self.sent_mail.clear()
        self.create_answer(self.create_user('carol'), question)
        self.assertEqual(len(self.mails(self.alice, 'New answer')), 1)

    def test_admin_unfollows_for_someone_else(self):
        QuestionSubscription(user=self.alice, question=self.question, auto_subscription=False).save()
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        page = self.open(admin)
        self.visit(page, self.alice.get_user_subscriptions_url() + '?tab=manage')
        item = page.locator('.subscription_summary', has_text='How do I add a new user to Collect?')
        with page.expect_navigation():
            item.locator('button.subscription_unsubscribe_button').click()
        self.check_page(page)
        self.assertFalse(QuestionSubscription.objects.filter(user=self.alice, question=self.question).exists())
        self.assertFalse(QuestionSubscription.objects.filter(user=admin, question=self.question).exists())
        self.assertNotIn('How do I add a new user to Collect?', page.locator('#subscription_list').inner_text())


class EmailValidationTest(EmailTestCase):
    def test_welcome_email_validation_link(self):
        self.create_user('owner')  # the first account would become the site owner
        page = self.open()
        self.visit(page, '/account/local/register/')
        page.fill('#id_username', 'newcomer')
        page.fill('#id_email', 'newcomer@example.com')
        page.fill('#id_password1', 'green-tree-river-7')
        page.fill('#id_password2', 'green-tree-river-7')
        with page.expect_navigation():
            page.click('#bnewaccount')
        self.check_page(page)
        newcomer = User.objects.get(username='newcomer')
        self.assertFalse(newcomer.email_isvalid)
        reputation = newcomer.reputation

        welcome = [m for m in self.mail_to(newcomer) if 'Welcome' in m[1]]
        self.assertEqual(len(welcome), 1)
        to, subject, html, text, media, headers = welcome[0]
        self.assertEqual(headers, {})  # an account email: no unsubscribe
        link = re.search(r'http://testserver(/account/validate/%d/[^/\s]+/)' % newcomer.id, text).group(1)
        self.visit(page, link)
        self.assertIn('your email is now validated', page.locator('body').inner_text())
        newcomer = User.objects.get(id=newcomer.id)
        self.assertTrue(newcomer.email_isvalid)
        self.assertEqual(newcomer.reputation, reputation + int(settings.REP_GAIN_BY_EMAIL_VALIDATION))
        self.assertTrue(Award.objects.filter(user=newcomer, badge__cls='ValidatedEmail').exists())

        self.visit(page, link)
        self.assertIn('already confirmed', page.locator('body').inner_text())
        self.assertEqual(User.objects.get(id=newcomer.id).reputation, reputation + int(settings.REP_GAIN_BY_EMAIL_VALIDATION))

    def edit_email(self, page, user, email):
        self.visit(page, reverse('edit_user', kwargs={'id': user.id, 'slug': user.username}))
        page.fill('#id_email', email)
        with page.expect_navigation():
            page.locator('form:has(#id_email) input[type=submit]').click()
        self.check_page(page)

    def test_changing_the_email_address(self):
        alice = self.create_user('alice', reputation=100)
        page = self.open(alice)
        self.edit_email(page, alice, 'alice.forest@example.com')
        # The address changes once the new one is confirmed; the old one is told.
        alice = User.objects.get(id=alice.id)
        self.assertEqual(alice.email, 'alice@example.com')
        self.assertTrue(alice.email_isvalid)
        self.assertIn('alice.forest@example.com', page.locator('.email-pending').inner_text())
        notice = [m for m in self.mail_to(alice) if m[0].email == 'alice@example.com' and 'being changed' in m[1]]
        self.assertEqual(len(notice), 1)
        self.assertEqual(notice[0][5], {})  # a security notice: no unsubscribe

        to, subject, html, text, media, headers = [m for m in self.mail_to(alice)
                                                   if m[0].email == 'alice.forest@example.com'][-1]
        link = re.search(r'http://testserver(/account/email/confirm/\d+/[^/\s]+/)', text).group(1)
        self.visit(page, link)
        alice = User.objects.get(id=alice.id)
        self.assertEqual(alice.email, 'alice.forest@example.com')
        self.assertTrue(alice.email_isvalid)
        self.visit(page, alice.get_profile_url())
        self.assertNotIn('not validated', page.locator('.user-details').inner_text())

    def test_admin_changing_someones_email_keeps_their_own_link(self):
        alice = self.create_user('alice', reputation=100)
        admin = self.create_user('admin', is_superuser=True, is_staff=True, email_isvalid=False)
        admins_link = ValidationHash.objects.create_new(admin, 'email', [admin.email])
        page = self.open(admin)
        self.edit_email(page, alice, 'alice.new@example.com')
        self.assertEqual(User.objects.get(id=alice.id).email, 'alice.new@example.com')
        self.assertFalse(User.objects.get(id=alice.id).email_isvalid)
        self.assertTrue(ValidationHash.objects.filter(id=admins_link.id).exists())
