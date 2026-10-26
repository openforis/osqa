"""Notification emails and email preferences: the digest cron command, the
management commands, which preferences stop which emails, following
questions automatically, the "questions you follow" tab, unsubscribe links
with undo for every kind of email, and changing the email address."""
import contextlib
import datetime
import glob
import io
import os
import re
from importlib import import_module

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.urls import reverse

from forum import settings
from forum.models import Question, QuestionSubscription, Tag, MarkedTag, User, ValidationHash
from forum.settings.email import EMAIL_DIGEST_FLAG
from forum.utils import unsubscribe

from .base import OSQATestCase

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class EmailTestCase(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', email_isvalid=True)
        self.bob = self.create_user('bob', email_isvalid=True)

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

    def ask(self, user, title, tags='collect'):
        self.login(user)
        self.client.post(reverse('ask'), {'title': title, 'text': 'A question body that is long enough.', 'tags': tags})
        return Question.objects.get(title=title)

    def answer(self, user, question):
        self.login(user)
        self.client.post(reverse('answer', args=[question.id]), {'text': 'An answer that is long enough to post.'})
        return question.answers.latest('id')

    def follow(self, user, question):
        QuestionSubscription(user=user, question=question, auto_subscription=False).save()


class ManagementCommandsTest(OSQATestCase):
    """Every management command imports on Python 3 / Django 5 and has a --help."""

    def command_names(self):
        paths = glob.glob(os.path.join(ROOT, 'forum', 'management', 'commands', '*.py')) + \
            glob.glob(os.path.join(ROOT, 'forum_modules', '*', 'management', 'commands', '*.py'))
        for path in sorted(paths):
            name = os.path.basename(path)[:-3]
            if name.startswith('_'):
                continue
            package = os.path.relpath(os.path.dirname(path), ROOT).replace(os.sep, '.')
            yield name, '%s.%s' % (package, name)

    def test_every_command_imports_and_has_help(self):
        names = list(self.command_names())
        self.assertIn('send_email_alerts', [n for n, _ in names])
        for name, module in names:
            with self.subTest(command=name):
                command = import_module(module).Command
                self.assertTrue(issubclass(command, BaseCommand))
                out = io.StringIO()
                with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as exit:
                    call_command(name, '--help')
                self.assertEqual(exit.exception.code, 0)
                self.assertRegex(out.getvalue(), r'^usage: .*\b%s\b' % name)

    def test_create_subscriptions_follows_own_questions(self):
        alice = self.create_user('alice')
        self.login(alice)
        self.client.post(reverse('ask'), {'title': 'A question to follow again', 'text': 'Body long enough to post.',
                                          'tags': 'collect'})
        QuestionSubscription.objects.all().delete()
        call_command('create_subscriptions')
        call_command('create_subscriptions')  # twice: nothing duplicated
        self.assertEqual(QuestionSubscription.objects.filter(user=alice).count(), 1)


class DigestTest(EmailTestCase):
    def setUp(self):
        super().setUp()
        self.prefs(self.alice, send_digest=True)
        self.carol = self.create_user('carol', email_isvalid=False)
        self.prefs(self.carol, send_digest=True)  # digest on, but not validated
        self.addCleanup(setattr, EMAIL_DIGEST_FLAG, '_temp', None)
        self.set_setting(EMAIL_DIGEST_FLAG, {'LAST_DAILY': datetime.datetime.now() - datetime.timedelta(hours=1)})
        self.question = self.ask(self.bob, 'How do I import plots from a shapefile?')
        self.sent_mail.clear()

    def test_digest_goes_to_those_who_want_it_once(self):
        call_command('send_email_alerts')
        self.assertEqual([m[0] for m in self.sent_mail], [self.alice])
        recipient, subject, html, text, media, headers = self.sent_mail[0]
        self.assertIn('Daily digest', subject)
        self.assertNotIn('Weekly', subject)
        self.assertIn('How do I import plots from a shapefile?', text)
        self.assertIn('How do I import plots from a shapefile?', html)
        self.assertIn(self.question.get_absolute_url(), html)
        self.assertIn('1 new question was posted.', text)
        self.assertIn('Daily digest: 1 new question', subject)
        self.assertIn('Stop the daily digest: http://testserver/unsubscribe/', text)
        self.assertIn('You receive this email because you are subscribed to the daily digest.', text)
        self.assertRegex(headers['List-Unsubscribe'], r'^<http://testserver/unsubscribe/[^>]+/>$')
        self.assertGreater(EMAIL_DIGEST_FLAG.value['LAST_DAILY'], datetime.datetime.now() - datetime.timedelta(minutes=1))

        # The next run only covers what happened since this one.
        call_command('send_email_alerts')
        self.assertEqual(len(self.sent_mail), 1)

        # The link in the email stops the digest.
        link = re.search(r'Stop the daily digest: http://testserver(\S+)', text).group(1)
        self.client.logout()
        self.client.post(link, {'action': 'unsubscribe'})
        self.assertFalse(self.prefs(self.alice).send_digest)

    def test_first_run_ever_covers_the_last_day(self):
        self.set_setting(EMAIL_DIGEST_FLAG, None)
        call_command('send_email_alerts')
        self.assertEqual([m[0] for m in self.sent_mail], [self.alice])

    def test_questions_seen_since_the_last_activity_are_left_out(self):
        from forum.management.commands.send_email_alerts import DigestQuestionsIndex
        digest = DigestQuestionsIndex(datetime.datetime.now() - datetime.timedelta(hours=1))
        self.assertTrue(digest.unseen_question(self.alice, self.question))
        self.follow(self.alice, self.question)
        QuestionSubscription.objects.filter(user=self.alice).update(
            last_view=datetime.datetime.now() + datetime.timedelta(minutes=1))
        self.assertFalse(digest.unseen_question(self.alice, self.question))
        self.assertEqual(digest.get_for_user(self.alice)['interesting'], [])

    def test_nothing_new_sends_nothing(self):
        self.set_setting(EMAIL_DIGEST_FLAG, {'LAST_DAILY': datetime.datetime.now()})
        call_command('send_email_alerts')
        self.assertEqual(self.sent_mail, [])


class PreferencesStopEmailsTest(EmailTestCase):
    def setUp(self):
        super().setUp()
        self.question = self.ask(self.alice, 'How do I export survey data to CSV?')
        self.sent_mail.clear()

    def test_new_answer_respects_notify_answers_and_subscribed_questions(self):
        self.prefs(self.alice, notify_answers=False)
        self.answer(self.bob, self.question)
        self.assertEqual(self.mail_to(self.alice), [])

        self.prefs(self.alice, notify_answers=True, subscribed_questions='n')
        self.answer(self.create_user('carol', email_isvalid=True), self.question)
        self.assertEqual(self.mail_to(self.alice), [])

        self.prefs(self.alice, subscribed_questions='i')
        self.answer(self.create_user('dave', email_isvalid=True), self.question)
        self.assertEqual(len(self.mail_to(self.alice)), 1)

    def test_any_new_question_when_asked_for(self):
        carol = self.create_user('carol', email_isvalid=True)
        self.prefs(carol, new_question='i')
        self.ask(self.bob, 'A question in a tag carol does not follow', tags='sepal')
        mails = self.mail_to(carol)
        self.assertEqual(len(mails), 1)
        recipient, subject, html, text, media, headers = mails[0]
        self.assertIn('A question in a tag carol does not follow', subject)
        self.assertIn('Stop emails about new questions: http://testserver/unsubscribe/', text)
        self.assertIn('List-Unsubscribe', headers)
        self.assertEqual(self.mail_to(self.alice), [])  # default: only tags she follows

    def test_unvalidated_and_inactive_followers_get_nothing(self):
        carol = self.create_user('carol', email_isvalid=False)
        dave = self.create_user('dave', email_isvalid=True, is_active=False)
        self.follow(carol, self.question)
        self.follow(dave, self.question)
        self.set_setting(settings.DONT_NOTIFY_UNVALIDATED, True)
        self.answer(self.bob, self.question)
        self.assertEqual(self.mail_to(carol), [])
        self.assertEqual(self.mail_to(dave), [])
        self.assertEqual(len(self.mail_to(self.alice)), 1)

        self.set_setting(settings.DONT_NOTIFY_UNVALIDATED, False)
        self.answer(self.create_user('erin', email_isvalid=True), self.question)
        self.assertEqual(len(self.mail_to(carol)), 1)
        self.assertEqual(self.mail_to(dave), [])  # inactive: never

    def test_answer_accepted_respects_notify_accepted(self):
        carol = self.create_user('carol', email_isvalid=True)
        dave = self.create_user('dave', email_isvalid=True)
        self.follow(carol, self.question)
        self.follow(dave, self.question)
        self.prefs(carol, notify_accepted=True)  # dave keeps the default (off)
        answer = self.answer(self.bob, self.question)
        self.sent_mail.clear()

        self.login(self.alice)
        self.command(reverse('accept_answer', kwargs={'id': answer.id}))
        self.assertEqual(sorted(m[0].username for m in self.sent_mail), ['bob', 'carol'])
        recipient, subject, html, text, media, headers = self.mail_to(carol)[0]
        self.assertIn('Answer accepted: How do I export survey data to CSV?', subject)
        self.assertIn('Stop emails about this question: http://testserver/unsubscribe/', text)
        self.assertIn('List-Unsubscribe', headers)

    def test_answer_author_can_still_switch_it_off(self):
        answer = self.answer(self.bob, self.question)
        self.prefs(self.bob, subscribed_questions='n')
        self.sent_mail.clear()
        self.login(self.alice)
        self.command(reverse('accept_answer', kwargs={'id': answer.id}))
        self.assertEqual(self.sent_mail, [])


class AutoFollowTest(EmailTestCase):
    def test_questions_viewed(self):
        question = self.ask(self.alice, 'A question bob will look at')
        self.login(self.bob)
        self.client.get(question.get_absolute_url())
        self.assertFalse(QuestionSubscription.objects.filter(user=self.bob, question=question).exists())

        self.prefs(self.bob, questions_viewed=True)
        other = self.ask(self.alice, 'Another question bob will look at')
        self.login(self.bob)
        self.client.get(other.get_absolute_url())
        subscription = QuestionSubscription.objects.get(user=self.bob, question=other)
        self.assertTrue(subscription.auto_subscription)

    def test_all_questions_and_all_in_followed_tags(self):
        carol = self.create_user('carol', email_isvalid=True)
        dave = self.create_user('dave', email_isvalid=True)
        self.prefs(self.bob, all_questions=True)
        self.prefs(carol, all_questions_watched_tags=True)
        self.prefs(dave, all_questions_watched_tags=True)
        self.ask(self.alice, 'Creating the tags first')
        MarkedTag.objects.create(user=carol, tag=Tag.objects.get(name='collect'), reason='good')
        # dave ignores this tag and follows another one: not followed
        MarkedTag.objects.create(user=dave, tag=Tag.objects.get(name='collect'), reason='bad')
        MarkedTag.objects.create(user=dave, tag=Tag.objects.create(name='sepal', created_by=dave), reason='good')

        question = self.ask(self.alice, 'A brand new question about collect')
        followers = set(QuestionSubscription.objects.filter(question=question).values_list('user__username', flat=True))
        self.assertEqual(followers, {'alice', 'bob', 'carol'})

        self.sent_mail.clear()
        self.answer(self.create_user('erin', email_isvalid=True), question)
        self.assertEqual(len(self.mail_to(self.bob)), 1)


class ManageSubscriptionsTest(EmailTestCase):
    def setUp(self):
        super().setUp()
        self.own = self.ask(self.alice, 'A question alice asked herself')
        self.followed = self.ask(self.bob, 'A question alice follows on purpose')
        self.follow(self.alice, self.followed)
        self.url = self.alice.get_user_subscriptions_url() + '?tab=manage'

    def test_lists_followed_questions_and_filters_auto(self):
        self.login(self.alice)
        page = self.client.get(self.url)
        self.assertContains(page, 'A question alice asked herself')
        self.assertContains(page, 'A question alice follows on purpose')
        self.assertContains(page, 'action="%s"' % reverse('subscribe', kwargs={'id': self.own.id, 'user': self.alice.id}))
        page = self.client.get(self.url.replace('?', '?auto=False&'))
        self.assertNotContains(page, 'A question alice asked herself')
        self.assertContains(page, 'A question alice follows on purpose')

    def test_unfollow_from_the_list(self):
        self.login(self.alice)
        response = self.client.post(reverse('subscribe', kwargs={'id': self.own.id, 'user': self.alice.id}),
                                    HTTP_REFERER='http://testserver' + self.url)
        self.assertRedirects(response, 'http://testserver' + self.url, fetch_redirect_response=False)
        self.assertFalse(QuestionSubscription.objects.filter(user=self.alice, question=self.own).exists())
        self.assertNotContains(self.client.get(self.url), 'A question alice asked herself')

    def test_only_owner_or_admin(self):
        self.login(self.bob)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.command(reverse('subscribe', kwargs={'id': self.own.id, 'user': self.alice.id}))
        self.assertTrue(QuestionSubscription.objects.filter(user=self.alice, question=self.own).exists())

        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(admin)
        self.assertContains(self.client.get(self.url), 'A question alice asked herself')
        self.command(reverse('subscribe', kwargs={'id': self.own.id, 'user': self.alice.id}))
        self.assertFalse(QuestionSubscription.objects.filter(user=self.alice, question=self.own).exists())
        self.assertFalse(QuestionSubscription.objects.filter(user=admin, question=self.own).exists())
        self.command(reverse('subscribe', kwargs={'id': self.own.id, 'user': self.alice.id}))
        self.assertTrue(QuestionSubscription.objects.filter(user=self.alice, question=self.own).exists())


class UnsubscribeUndoTest(EmailTestCase):
    """Undo on the landing page puts back exactly what the link switched off."""

    def run_link(self, scope, question=None):
        self.client.logout()
        link = unsubscribe.url(self.alice, scope, question).replace('http://testserver', '')
        self.assertContains(self.client.post(link, {'action': 'unsubscribe'}), "You're unsubscribed")
        changed = self.prefs(self.alice)
        self.assertContains(self.client.post(link, {'action': 'undo'}), "You're subscribed again")
        return changed, self.prefs(self.alice)

    def test_every_scope(self):
        self.prefs(self.alice, member_joins='i', send_digest=True)
        checks = {
            'all': lambda p: p.enable_notifications,
            'mentions': lambda p: p.notify_reply_to_comments,
            'members': lambda p: p.member_joins == 'i',
            'digest': lambda p: p.send_digest,
            'new_questions': lambda p: p.new_question_watched_tags == 'i',
        }
        for scope, check in checks.items():
            with self.subTest(scope=scope):
                changed, restored = self.run_link(scope)
                self.assertFalse(check(changed))
                self.assertTrue(check(restored))

    def test_question_scope(self):
        question = self.ask(self.alice, 'A question alice follows')
        self.client.logout()
        link = unsubscribe.url(self.alice, 'question', question).replace('http://testserver', '')
        self.client.post(link, {'action': 'unsubscribe'})
        self.assertFalse(QuestionSubscription.objects.filter(user=self.alice, question=question).exists())
        self.client.post(link, {'action': 'undo'})
        self.assertTrue(QuestionSubscription.objects.filter(user=self.alice, question=question).exists())

    def test_new_questions_undo_restores_all_new_questions_too(self):
        self.prefs(self.alice, new_question='i', new_question_watched_tags='i')
        changed, restored = self.run_link('new_questions')
        self.assertEqual((changed.new_question, changed.new_question_watched_tags), ('n', 'n'))
        self.assertEqual((restored.new_question, restored.new_question_watched_tags), ('i', 'i'))

    def test_undo_keeps_settings_that_were_off(self):
        self.prefs(self.alice, new_question='n', new_question_watched_tags='i')
        changed, restored = self.run_link('new_questions')
        self.assertEqual((restored.new_question, restored.new_question_watched_tags), ('n', 'i'))


class EmailChangeTest(EmailTestCase):
    def edit(self, user, email):
        return self.client.post(reverse('edit_user', kwargs={'id': user.id, 'slug': user.username}),
                                {'email': email, 'realname': '', 'website': '', 'city': '', 'birthday': '',
                                 'about': '', 'username': user.username})

    def test_changing_the_email_needs_confirming_the_new_address(self):
        User.objects.filter(id=self.alice.id).update(email_isvalid=True)
        old = ValidationHash.objects.create_new(self.alice, 'email', [self.alice.email])
        self.login(self.alice)
        self.edit(self.alice, 'alice.new@example.com')
        alice = User.objects.get(id=self.alice.id)
        # The old address stays (and confirmed) until the new one is confirmed.
        self.assertEqual(alice.email, 'alice@example.com')
        self.assertTrue(alice.email_isvalid)
        self.assertTrue(ValidationHash.objects.filter(id=old.id).exists())

        to_new = [m for m in self.sent_mail if m[0].email == 'alice.new@example.com']
        to_old = [m for m in self.sent_mail if m[0].email == 'alice@example.com']
        self.assertEqual(len(to_new), 1)
        self.assertEqual(len(to_old), 1)
        self.assertIn('Cancel the change', to_old[0][3])
        link = re.search(r'http://testserver(/account/email/confirm/\d+/[^/\s]+/)', to_new[0][3]).group(1)
        self.client.get(link)
        alice = User.objects.get(id=self.alice.id)
        self.assertEqual(alice.email, 'alice.new@example.com')
        self.assertTrue(alice.email_isvalid)

    def test_admin_editing_someone_keeps_their_own_validation_link(self):
        admin = self.create_user('admin', is_superuser=True, is_staff=True, email_isvalid=False)
        admins = ValidationHash.objects.create_new(admin, 'email', [admin.email])
        alices = ValidationHash.objects.create_new(self.alice, 'email', [self.alice.email])
        self.login(admin)
        self.edit(self.alice, 'alice.other@example.com')
        self.assertEqual(User.objects.get(id=self.alice.id).email, 'alice.other@example.com')
        self.assertTrue(ValidationHash.objects.filter(id=admins.id).exists())
        self.assertFalse(ValidationHash.objects.filter(id=alices.id).exists())
