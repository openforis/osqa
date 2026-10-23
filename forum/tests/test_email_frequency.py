"""How often activity emails come (SubscriptionSettings.email_frequency): which
emails are sent right away and which wait for the daily or weekly summary, the
summary's contents, the weekly day, running the command twice or missing runs,
the email settings page, the "Switch to a weekly summary instead" alternative
on the unsubscribe page and the "Get a daily summary instead" footer link."""
import datetime
import re

from django.core.management import call_command
from django.urls import reverse

from forum import settings
from forum.models import MarkedTag, PendingEmail, Question, Tag, User
from forum.settings.email import EMAIL_DIGEST_FLAG
from forum.utils import email_frequency, unsubscribe

from .base import OSQATestCase


def days_ahead(n):
    return datetime.datetime.now() + datetime.timedelta(days=n)


def next_weekday(day, at_least=1):
    """A moment `at_least` days from now or later that falls on `day` (0 = Monday)."""
    moment = days_ahead(at_least)
    while moment.weekday() != day:
        moment += datetime.timedelta(days=1)
    return moment


class FrequencyTestCase(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', email_isvalid=True, reputation=500)
        self.bob = self.create_user('bob', email_isvalid=True, reputation=500)
        self.carol = self.create_user('carol', email_isvalid=True, reputation=500)
        self.set_setting(settings.WEEKLY_SUMMARY_DAY, '0')
        self.set_setting(EMAIL_DIGEST_FLAG, None)
        self.question = self.ask(self.alice, 'How do I export survey data to CSV?')
        self.sent_mail.clear()

    def set_setting(self, setting, value):
        setting.set_value(value)
        self.addCleanup(setattr, setting, '_temp', None)

    def prefs(self, user, **changes):
        prefs = User.objects.get(id=user.id).subscription_settings
        for name, value in changes.items():
            setattr(prefs, name, value)
        if changes:
            prefs.save()
        return prefs

    def mail_to(self, user):
        return [m for m in self.sent_mail if m[0] == user]

    def ask(self, user, title, tags='collect', text='A question body that is long enough.'):
        self.login(user)
        self.client.post(reverse('ask'), {'title': title, 'text': text, 'tags': tags})
        return Question.objects.get(title=title)

    def answer(self, user, question, text='An answer that is long enough to post.'):
        self.login(user)
        self.client.post(reverse('answer', args=[question.id]), {'text': text})
        return question.answers.latest('id')

    def comment(self, user, post, text='A comment that is long enough to post.'):
        self.login(user)
        self.command(reverse('comment', kwargs={'id': post.id}), {'comment': text})

    def pending(self, user):
        return list(PendingEmail.objects.filter(user=user).values_list('kind', flat=True))


class RoutingTest(FrequencyTestCase):
    """Immediate or queued, per frequency and per kind."""

    def test_new_answer_per_frequency(self):
        expected = {'i': (1, []), 'd': (0, ['answer']), 'w': (0, ['answer']), 'n': (0, [])}
        for n, (frequency, (emails, queued)) in enumerate(expected.items()):
            with self.subTest(frequency=frequency):
                self.prefs(self.alice, email_frequency=frequency)
                PendingEmail.objects.all().delete()
                self.sent_mail.clear()
                self.answer(self.create_user('helper%d' % n, email_isvalid=True), self.question)
                self.assertEqual(len(self.mail_to(self.alice)), emails)
                self.assertEqual(self.pending(self.alice), queued)

    def test_the_per_kind_switches_still_apply(self):
        self.prefs(self.alice, email_frequency='d', notify_answers=False)
        self.answer(self.bob, self.question)
        self.assertEqual(self.pending(self.alice), [])
        self.assertEqual(self.mail_to(self.alice), [])

    def test_comments_and_accepted_answers_are_queued(self):
        answer = self.answer(self.bob, self.question)
        self.prefs(self.bob, email_frequency='w')
        self.prefs(self.alice, email_frequency='d')
        self.sent_mail.clear()
        self.comment(self.alice, answer, 'Thanks, does it keep the GPS columns too?')
        self.assertEqual(self.pending(self.bob), ['comment'])
        self.login(self.alice)
        self.command(reverse('accept_answer', kwargs={'id': answer.id}))
        self.assertEqual(self.pending(self.bob), ['comment', 'accepted'])
        self.assertEqual(self.sent_mail, [])
        row = PendingEmail.objects.get(user=self.bob, kind='accepted')
        self.assertEqual((row.node_id, row.actor_id), (answer.id, self.alice.id))

    def test_mentions_stay_immediate_unless_switched_off(self):
        self.prefs(self.carol, email_frequency='w')
        self.answer(self.bob, self.question, 'Ask @carol, she exported hundreds of surveys.')
        self.assertEqual(len(self.mail_to(self.carol)), 1)
        self.assertIn('mentioned you', self.mail_to(self.carol)[0][1])
        self.assertEqual(self.pending(self.carol), [])

        self.prefs(self.carol, mentions_immediate=False)
        self.sent_mail.clear()
        self.answer(self.create_user('dave', email_isvalid=True), self.question, 'Ask @carol about the exports.')
        self.assertEqual(self.mail_to(self.carol), [])
        self.assertEqual(self.pending(self.carol), ['mention'])

        # "never" with mentions right away: only mentions arrive.
        self.prefs(self.carol, email_frequency='n', mentions_immediate=True)
        PendingEmail.objects.all().delete()
        self.answer(self.create_user('erin', email_isvalid=True), self.question, 'Ask @carol again.')
        self.assertEqual(len(self.mail_to(self.carol)), 1)
        self.assertEqual(self.pending(self.carol), [])

    def test_new_questions_in_followed_tags_and_new_members(self):
        MarkedTag.objects.create(user=self.carol, tag=Tag.objects.get(name='collect'), reason='good')
        self.prefs(self.carol, email_frequency='d')
        question = self.ask(self.bob, 'Can Collect read barcodes?')
        self.assertEqual(self.mail_to(self.carol), [])
        self.assertEqual(self.pending(self.carol), ['new_question'])
        self.assertEqual(PendingEmail.objects.get(user=self.carol).node_id, question.id)

        admin = self.create_user('admin', email_isvalid=True, is_superuser=True)
        self.prefs(admin, member_joins='i', email_frequency='w')
        self.client.logout()
        self.client.post('/account/local/register/', {
            'username': 'newcomer', 'email': 'newcomer@example.com', 'password1': 's3cret-pass-word',
            'password2': 's3cret-pass-word', 'next': '/', 'form_token': self.signup_token()})
        self.assertEqual(self.pending(admin), ['member'])
        self.assertEqual(PendingEmail.objects.get(user=admin).actor.username, 'newcomer')
        self.assertFalse([m for m in self.mail_to(admin) if 'joined' in m[1]])


class SummaryTest(FrequencyTestCase):
    def test_daily_summary_groups_the_news(self):
        self.prefs(self.alice, email_frequency='d', mentions_immediate=False)
        followed = self.ask(self.bob, 'Why does my map not load offline?', tags='maps')
        self.prefs(self.alice, notify_comments=True)
        from forum.models import QuestionSubscription
        QuestionSubscription(user=self.alice, question=followed, auto_subscription=False).save()
        self.sent_mail.clear()

        answer = self.answer(self.bob, self.question, 'Open the survey and choose Data, then Export.')
        self.answer(self.carol, followed, 'Download the map area first.')
        self.comment(self.carol, answer, 'Does this keep the GPS columns, @alice?')
        self.comment(self.carol, self.question, 'Which version of Collect do you use?')
        self.assertEqual(self.mail_to(self.alice), [])
        self.assertEqual(sorted(self.pending(self.alice)), ['answer', 'answer', 'comment', 'mention'])

        sent = email_frequency.send_summaries(days_ahead(1))
        self.assertEqual(sent, {'daily': 1, 'weekly': 0})
        to, subject, html, text, media, headers = self.mail_to(self.alice)[0]
        self.assertEqual(subject, 'Your daily summary: 4 updates')
        sections = ['Mentions (1)', 'Answers to your questions (1)', 'New answers on questions you follow (1)',
                    'New comments (1)']
        positions = [text.index(section) for section in sections]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('bob answered: Open the survey and choose Data, then Export.', text)
        self.assertIn('carol answered: Download the map area first.', text)
        self.assertIn('carol mentioned you: Does this keep the GPS columns, @alice?', text)
        self.assertIn('carol commented: Which version of Collect do you use?', text)
        self.assertIn('http://testserver%s' % answer.get_absolute_url(), text)
        self.assertIn('Why does my map not load offline?', html)
        self.assertIn('You receive this email because you chose a daily summary of the activity you follow.', text)
        self.assertIn('Stop these summaries: http://testserver/unsubscribe/', text)
        self.assertNotIn('Get a daily summary instead', text)
        self.assertRegex(headers['List-Unsubscribe'], r'^<http://testserver/unsubscribe/[^>]+/>$')
        self.assertEqual(PendingEmail.objects.count(), 0)
        self.assertIsNotNone(self.prefs(self.alice).last_summary_at)

        # "Stop these summaries" sets the frequency to never.
        link = re.search(r'Stop these summaries: http://testserver(\S+)', text).group(1)
        self.client.logout()
        self.client.post(link, {'action': 'unsubscribe'})
        self.assertEqual(self.prefs(self.alice).email_frequency, 'n')

    def test_long_sections_are_cut(self):
        self.prefs(self.alice, email_frequency='d')
        for n in range(email_frequency.SECTION_LIMIT + 2):
            self.answer(self.create_user('helper%d' % n, email_isvalid=True), self.question)
        email_frequency.send_summaries(days_ahead(1))
        text = self.mail_to(self.alice)[0][3]
        self.assertIn('Answers to your questions (12)', text)
        self.assertEqual(text.count('answered:'), email_frequency.SECTION_LIMIT)
        self.assertIn('And 2 more.', text)

    def test_deleted_posts_and_nothing_new_send_nothing(self):
        self.prefs(self.alice, email_frequency='d')
        self.assertEqual(email_frequency.send_summaries(days_ahead(1)), {'daily': 0, 'weekly': 0})
        answer = self.answer(self.bob, self.question)
        self.login(self.bob)
        self.command(reverse('delete_post', kwargs={'id': answer.id}))
        self.sent_mail.clear()
        email_frequency.send_summaries(days_ahead(1))
        self.assertEqual(self.sent_mail, [])
        self.assertEqual(PendingEmail.objects.count(), 0)
        self.assertIsNone(self.prefs(self.alice).last_summary_at)

    def test_back_to_as_it_happens_flushes_and_never_drops(self):
        self.prefs(self.alice, email_frequency='w')
        self.answer(self.bob, self.question)
        self.prefs(self.alice, email_frequency='i')
        email_frequency.send_summaries(next_weekday(2))  # not the weekly day: sent as a last daily summary
        self.assertEqual([m[1] for m in self.mail_to(self.alice)], ['Your daily summary: 1 update'])

        self.prefs(self.alice, email_frequency='w')
        self.answer(self.carol, self.question)
        self.prefs(self.alice, email_frequency='n')
        self.sent_mail.clear()
        email_frequency.send_summaries(next_weekday(0, at_least=2))
        self.assertEqual(self.sent_mail, [])
        self.assertEqual(PendingEmail.objects.count(), 0)

    def test_suspended_or_switched_off_members_get_nothing(self):
        self.prefs(self.alice, email_frequency='d')
        self.answer(self.bob, self.question)
        self.prefs(self.alice, enable_notifications=False)
        email_frequency.send_summaries(days_ahead(1))
        self.assertEqual(self.sent_mail, [])
        self.assertEqual(PendingEmail.objects.count(), 0)


class ScheduleTest(FrequencyTestCase):
    def setUp(self):
        super().setUp()
        self.prefs(self.alice, email_frequency='w')
        self.answer(self.bob, self.question)

    def test_weekly_day_logic(self):
        monday, tuesday = next_weekday(0), next_weekday(1)
        self.assertTrue(email_frequency.weekly_run_due(monday, None))
        self.assertFalse(email_frequency.weekly_run_due(tuesday, None))
        self.assertFalse(email_frequency.weekly_run_due(tuesday, tuesday - datetime.timedelta(days=1)))
        self.assertTrue(email_frequency.weekly_run_due(tuesday, tuesday - datetime.timedelta(days=8)))
        self.set_setting(settings.WEEKLY_SUMMARY_DAY, '1')
        self.assertTrue(email_frequency.weekly_run_due(tuesday, None))
        self.assertEqual(str(email_frequency.weekly_day_name()), 'Tuesday')

    def test_weekly_members_wait_for_the_weekly_day(self):
        tuesday = next_weekday(1)
        self.assertEqual(email_frequency.send_summaries(tuesday), {'daily': 0, 'weekly': 0})
        self.assertEqual(self.sent_mail, [])
        self.assertEqual(self.pending(self.alice), ['answer'])

        monday = next_weekday(0, at_least=(tuesday - datetime.datetime.now()).days + 1)
        self.assertEqual(email_frequency.send_summaries(monday), {'daily': 0, 'weekly': 1})
        self.assertEqual(self.mail_to(self.alice)[0][1], 'Your weekly summary: 1 update')
        self.assertIn('you chose a weekly summary', self.mail_to(self.alice)[0][3])
        self.assertEqual(EMAIL_DIGEST_FLAG.value['LAST_WEEKLY'], monday)

    def test_running_twice_sends_once(self):
        monday = next_weekday(0)
        email_frequency.send_summaries(monday)
        email_frequency.send_summaries(monday)
        self.assertEqual(len(self.mail_to(self.alice)), 1)
        # Something new later the same day waits for the next summary, not a second one today.
        self.answer(self.carol, self.question)
        email_frequency.send_summaries(monday + datetime.timedelta(minutes=5))
        self.assertEqual(len(self.mail_to(self.alice)), 1)
        self.assertEqual(self.pending(self.alice), ['answer'])
        email_frequency.send_summaries(monday + datetime.timedelta(days=7))
        self.assertEqual(len(self.mail_to(self.alice)), 2)

    def test_a_missed_weekly_run_is_caught_up(self):
        tuesday = next_weekday(1)
        self.set_setting(EMAIL_DIGEST_FLAG, {'LAST_WEEKLY': tuesday - datetime.timedelta(days=8)})
        self.assertEqual(email_frequency.send_summaries(tuesday), {'daily': 0, 'weekly': 1})

    def test_missed_daily_runs_cover_everything_since_the_last_summary(self):
        self.prefs(self.alice, email_frequency='d')
        PendingEmail.objects.filter(user=self.alice).update(created_at=datetime.datetime.now() - datetime.timedelta(days=3))
        self.answer(self.carol, self.question)
        email_frequency.send_summaries(days_ahead(1))
        mails = self.mail_to(self.alice)
        self.assertEqual(len(mails), 1)
        self.assertIn('Answers to your questions (2)', mails[0][3])

    def test_the_command_sends_summaries(self):
        self.set_setting(settings.WEEKLY_SUMMARY_DAY, str(datetime.datetime.now().weekday()))
        self.prefs(self.alice, send_digest=False)  # the digest of new questions is another email
        call_command('send_email_alerts')
        self.assertEqual([m[1] for m in self.mail_to(self.alice)], ['Your weekly summary: 1 update'])
        call_command('send_email_alerts')
        self.assertEqual(len(self.mail_to(self.alice)), 1)


class SettingsPageTest(FrequencyTestCase):
    def test_frequency_cards_and_saving(self):
        self.login(self.alice)
        url = self.alice.get_user_subscriptions_url()
        page = self.client.get(url)
        self.assertContains(page, 'How often should we email you?')
        for name in ('As it happens', 'Daily summary', 'Weekly summary', 'Never'):
            self.assertContains(page, name)
        self.assertContains(page, 'One email every Monday with everything new.')
        self.assertContains(page, 'form="email-settings-form"', count=5)  # four radios and the save button
        self.assertContains(page, 'id="email-settings-form"')
        self.assertRegex(page.content.decode(), r'<input type="radio" name="email_frequency" value="i"[^>]* checked')

        data = {'member_joins': 'n', 'new_question': 'n', 'new_question_watched_tags': 'i',
                'subscribed_questions': 'i', 'notify_answers': 'on', 'notify_reply_to_comments': 'on'}
        self.client.post(url, dict(data, email_frequency='w'))
        prefs = self.prefs(self.alice)
        self.assertEqual(prefs.email_frequency, 'w')
        self.assertFalse(prefs.mentions_immediate)
        self.client.post(url, dict(data, mentions_immediate='on'))  # an old page without the choice
        prefs = self.prefs(self.alice)
        self.assertEqual(prefs.email_frequency, 'w')
        self.assertTrue(prefs.mentions_immediate)
        self.client.post(url, dict(data, email_frequency='x'))
        self.assertEqual(self.prefs(self.alice).email_frequency, 'w')

    def test_new_members_defaults(self):
        prefs = self.prefs(self.create_user('newuser'))
        self.assertEqual((prefs.email_frequency, prefs.mentions_immediate, prefs.send_digest), ('i', True, False))


class SwitchLinksTest(FrequencyTestCase):
    def link(self, scope, question=None):
        return unsubscribe.url(self.alice, scope, question).replace('http://testserver', '')

    def test_footer_offers_a_daily_summary_with_undo(self):
        self.answer(self.bob, self.question)
        to, subject, html, text, media, headers = self.mail_to(self.alice)[0]
        self.assertIn('Too many emails? Get a daily summary instead: http://testserver/unsubscribe/', text)
        self.assertIn('Get a daily summary instead</a>', html)
        link = re.search(r'Get a daily summary instead: http://testserver(\S+)', text).group(1)

        self.client.logout()
        page = self.client.get(link)
        self.assertContains(page, 'one summary email a day instead of a separate email for each update?')
        self.assertEqual(self.prefs(self.alice).email_frequency, 'i')  # opening the link changes nothing

        page = self.client.post(link, {'action': 'switch'})
        self.assertContains(page, "You'll get a daily summary")
        self.assertContains(page, 'Mentions still arrive right away.')
        self.assertEqual(self.prefs(self.alice).email_frequency, 'd')
        self.sent_mail.clear()
        self.answer(self.carol, self.question)
        self.assertEqual(self.mail_to(self.alice), [])

        page = self.client.post(link, {'action': 'undo'})
        self.assertContains(page, 'Back to separate emails')
        self.assertEqual(self.prefs(self.alice).email_frequency, 'i')

    def test_no_daily_offer_when_not_sent_as_it_happens(self):
        self.prefs(self.carol, email_frequency='d')  # mentions still immediate
        self.answer(self.bob, self.question, 'Ask @carol about it.')
        self.assertNotIn('Get a daily summary instead', self.mail_to(self.carol)[0][3])

    def test_unsubscribe_page_offers_a_weekly_summary(self):
        self.client.logout()
        page = self.client.get(self.link('question', self.question))
        self.assertContains(page, 'Switch to a weekly summary instead')
        weekly = re.search(r'action="(/unsubscribe/[^"]+/)"[^>]*>\s*<input type="hidden" name="action" value="switch">',
                           page.content.decode()).group(1)
        page = self.client.post(weekly, {'action': 'switch'})
        self.assertContains(page, "You'll get a weekly summary")
        self.assertContains(page, 'one summary every Monday')
        self.assertEqual(self.prefs(self.alice).email_frequency, 'w')
        # still following the question: nothing was unsubscribed
        self.assertTrue(self.question.subscribers.filter(id=self.alice.id).exists())
        self.assertNotContains(self.client.get(self.link('question', self.question)), 'Switch to a weekly summary')

        self.client.post(weekly, {'action': 'undo'})
        self.assertEqual(self.prefs(self.alice).email_frequency, 'i')
        # The digest is not about activity: no weekly offer there.
        self.assertNotContains(self.client.get(self.link('digest')), 'Switch to a weekly summary')

    def test_undo_puts_back_exactly_what_was_there(self):
        self.prefs(self.alice, enable_notifications=False, email_frequency='d')
        self.client.logout()
        link = self.link('weekly')
        self.client.post(link, {'action': 'switch'})
        prefs = self.prefs(self.alice)
        self.assertEqual((prefs.enable_notifications, prefs.email_frequency), (True, 'w'))
        self.client.post(link, {'action': 'undo'})
        prefs = self.prefs(self.alice)
        self.assertEqual((prefs.enable_notifications, prefs.email_frequency), (False, 'd'))
