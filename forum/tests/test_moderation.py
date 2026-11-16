"""Moderation and accounts: suspensions, closing and reopening, deleting,
bulk moderation, moderator rights, converting posts, mention notifications,
the contact form and avatars."""
import datetime
from hashlib import md5

from django.urls import reverse

from forum import settings
from forum.actions import SuspendAction
from forum.models import Action, Answer, Comment, Notification, Question, User

from .base import OSQATestCase


class SettingsMixin:
    def set_setting(self, setting, value):
        setting.set_value(value)
        self.addCleanup(setattr, setting, '_temp', None)


def fresh(user):
    return User.objects.get(id=user.id)


class SuspensionTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True, reputation=1000)
        self.spammer = self.create_user('spammer', password='spammer-pass', email_isvalid=True, reputation=10)

    def suspend(self, **data):
        self.login(self.admin)
        return self.command(reverse('user_suspend', kwargs={'id': self.spammer.id}), data)

    def sign_in(self, password='spammer-pass'):
        self.client.logout()
        return self.client.post('/account/local/signin/', {'username': 'spammer', 'password': password}, follow=True)

    def test_suspend_for_days_with_messages(self):
        self.assertTrue(self.suspend(bantype='forxdays', forxdays='1', publicmsg='Advertising',
                                     privatemsg='Please stop posting links.')['success'])
        spammer = fresh(self.spammer)
        self.assertTrue(spammer.is_suspended())
        self.assertEqual(spammer.suspension.extra, {'bantype': 'forxdays', 'forxdays': 1, 'publicmsg': 'Advertising',
                                                    'privatemsg': 'Please stop posting links.'})

    def test_bad_number_of_days_is_refused(self):
        response = self.suspend(bantype='forxdays', forxdays='soon', publicmsg='Advertising')
        self.assertFalse(response['success'])
        self.assertFalse(fresh(self.spammer).is_suspended())

    def test_only_superusers_suspend(self):
        self.login(self.create_user('moderator', is_staff=True, reputation=1000))
        response = self.command(reverse('user_suspend', kwargs={'id': self.spammer.id}),
                                {'bantype': 'indefinitely', 'publicmsg': 'x'})
        self.assertFalse(response['success'])
        self.assertFalse(fresh(self.spammer).is_suspended())

    def test_suspended_user_signing_in_sees_the_private_message_escaped(self):
        self.suspend(bantype='forxdays', forxdays='1', publicmsg='Public <b>x</b>', privatemsg='Private <b>x</b>')
        response = self.sign_in()
        self.assertNotIn('_auth_user_id', self.client.session)
        page = response.content.decode()
        self.assertIn('this account is suspended', page)
        self.assertIn('Private &lt;b&gt;x&lt;/b&gt;', page)
        self.assertNotIn('<b>x</b>', page)
        self.assertNotIn('or email and password', page)

    def test_wrong_password_of_a_suspended_account_says_nothing_about_it(self):
        self.suspend(bantype='indefinitely', publicmsg='Advertising', privatemsg='Secret note')
        page = self.sign_in('wrong-pass').content.decode()
        self.assertIn('or email and password', page)
        self.assertNotIn('Secret note', page)
        self.assertNotIn('suspended', page)

    def test_public_message_is_escaped_in_the_activity_log(self):
        self.suspend(bantype='indefinitely', publicmsg='Spam <b>x</b>', privatemsg='')
        action = Action.objects.get(action_type='suspend').leaf
        description = action.describe(self.admin)
        self.assertIn('Spam &lt;b&gt;x&lt;/b&gt;', description)
        self.assertNotIn('<b>x</b>', description)
        page = self.client.get(reverse('user_recent', kwargs={'id': self.spammer.id, 'slug': 'spammer'})).content.decode()
        self.assertIn('Spam &lt;b&gt;x&lt;/b&gt;', page)
        self.assertNotIn('Spam <b>x</b>', page)

    def test_withdrawn_suspension_lets_the_user_in_and_post(self):
        self.suspend(bantype='indefinitely', publicmsg='Advertising')
        self.assertTrue(self.suspend()['success'])  # no ban type: withdraw
        self.assertFalse(fresh(self.spammer).is_suspended())
        self.sign_in()
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.spammer.id))
        self.client.post(reverse('ask'), {'title': 'How do I export Collect survey data?',
                                          'text': 'A question body that is long enough to post.', 'tags': 'collect'})
        self.assertTrue(Question.objects.filter(author=self.spammer).exists())

    def backdate(self, days):
        Action.objects.filter(action_type='suspend').update(
            action_date=datetime.datetime.now() - datetime.timedelta(days=days))

    def test_suspension_past_its_end_lifts_on_sign_in(self):
        self.suspend(bantype='forxdays', forxdays='1', publicmsg='Advertising')
        self.backdate(2)
        response = self.sign_in()
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.spammer.id))
        self.assertNotIn('suspended', response.content.decode())
        spammer = fresh(self.spammer)
        self.assertTrue(spammer.is_active)
        self.assertTrue(Action.objects.get(action_type='suspend').canceled)

    def test_suspension_still_running_keeps_the_user_out(self):
        self.suspend(bantype='forxdays', forxdays='3', publicmsg='Advertising')
        self.backdate(2)
        self.sign_in()
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertTrue(fresh(self.spammer).is_suspended())

    def test_indefinite_suspension_stays(self):
        self.suspend(bantype='indefinitely', publicmsg='Advertising')
        self.backdate(1000)
        self.assertTrue(fresh(self.spammer).is_suspended())
        self.sign_in()
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_suspended_user_with_open_session_is_signed_out(self):
        self.client.force_login(self.spammer)
        SuspendAction(user=self.admin, ip='127.0.0.1').save(data={
            'bantype': 'indefinitely', 'publicmsg': 'x', 'privatemsg': 'bye', 'suspended': self.spammer})
        page = self.client.get('/', follow=True).content.decode()
        self.assertIn('/account/signin/', page)
        self.assertNotIn('>spammer<', page)

    def test_suspension_message_shown_by_the_middleware_is_escaped(self):
        from django.contrib.messages import get_messages
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        from forum.views.auth import forward_suspended_user
        SuspendAction(user=self.admin, ip='127.0.0.1').save(data={
            'bantype': 'indefinitely', 'publicmsg': '<i>public</i>', 'privatemsg': '<i>bye</i>',
            'suspended': self.spammer})
        request = RequestFactory().get('/')
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        forward_suspended_user(request, fresh(self.spammer), show_private_msg=False)
        self.assertEqual([str(m) for m in get_messages(request)],
                         ['Sorry, but this account is suspended:<br />&lt;i&gt;public&lt;/i&gt;'])

    def test_penalty_message_is_escaped_in_the_activity_log(self):
        self.login(self.admin)
        self.command(reverse('user_award_points', kwargs={'id': self.spammer.id}),
                     {'points': '-5', 'message': 'Spam <b>x</b>'})
        description = Action.objects.get(action_type='bonusrep').leaf.describe(self.admin)
        self.assertIn('Spam &lt;b&gt;x&lt;/b&gt;', description)
        self.assertNotIn('<b>x</b>', description)


class CloseReopenDeleteTest(SettingsMixin, OSQATestCase):
    def setUp(self):
        super().setUp()
        self.moderator = self.create_user('moderator', is_staff=True, reputation=10)
        self.alice = self.create_user('alice', reputation=300)
        self.bob = self.create_user('bob', reputation=100)
        self.question = Question(author=self.alice, title='How do I export data?', body='Body text', tagnames='csv')
        self.question.save()

    def close(self, user, **data):
        self.login(user)
        return self.command(reverse('close', kwargs={'id': self.question.id}), data)

    def reopen(self, user):
        self.login(user)
        return self.command(reverse('reopen', kwargs={'id': self.question.id}))

    def closed(self):
        return Question.objects.get(id=self.question.id).nis.closed

    def test_close_with_a_plain_reason(self):
        self.assertTrue(self.close(self.moderator, prompt='Off topic for this forum')['success'])
        question = Question.objects.get(id=self.question.id)
        self.assertTrue(question.nis.closed)
        self.assertEqual(question.nstate.closed.extra, 'Off topic for this forum')
        self.assertIsNone(question.duplicate_of)
        self.assertContains(self.client.get(question.get_absolute_url()), 'Off topic for this forum')

    def test_empty_reason_is_refused(self):
        response = self.close(self.moderator, prompt='   ')
        self.assertFalse(response['success'])
        self.assertIn('Reason is empty', response['error_message'])
        self.assertFalse(self.closed())

    def test_owner_closes_own_question_with_enough_reputation(self):
        self.set_setting(settings.REP_TO_CLOSE_OWN, 250)
        self.assertTrue(self.close(self.alice, prompt='Solved elsewhere')['success'])
        self.assertTrue(self.closed())

    def test_owner_without_enough_reputation_cannot_close(self):
        self.set_setting(settings.REP_TO_CLOSE_OWN, 500)
        self.assertFalse(self.close(self.alice, prompt='Solved elsewhere')['success'])
        self.assertFalse(self.closed())

    def test_others_cannot_close_without_reputation(self):
        self.assertFalse(self.close(self.bob, prompt='Not a question')['success'])
        self.assertFalse(self.closed())

    def test_owner_reopens_when_allowed(self):
        self.set_setting(settings.UNIFY_PERMISSIONS_TO_CLOSE_AND_REOPEN, False)
        self.set_setting(settings.REP_TO_REOPEN_OWN, 250)
        self.close(self.moderator, prompt='Off topic')
        self.assertTrue(self.reopen(self.alice)['success'])
        self.assertFalse(self.closed())

    def test_owner_cannot_reopen_without_reputation(self):
        self.set_setting(settings.UNIFY_PERMISSIONS_TO_CLOSE_AND_REOPEN, False)
        self.set_setting(settings.REP_TO_REOPEN_OWN, 500)
        self.close(self.moderator, prompt='Off topic')
        self.assertFalse(self.reopen(self.alice)['success'])
        self.assertTrue(self.closed())
        self.assertFalse(self.reopen(self.bob)['success'])

    def test_owner_cannot_delete_a_question_others_answered(self):
        answer = Answer(author=self.bob, parent=self.question, body='An answer from bob')
        answer.save()
        self.login(self.alice)
        response = self.command(reverse('delete_post', kwargs={'id': self.question.id}))
        self.assertFalse(response['success'])
        self.assertFalse(Question.objects.get(id=self.question.id).nis.deleted)

    def test_owner_deletes_a_question_answered_only_by_themselves(self):
        Answer(author=self.alice, parent=self.question, body='My own answer').save()
        self.login(self.alice)
        self.assertTrue(self.command(reverse('delete_post', kwargs={'id': self.question.id}))['success'])
        self.assertTrue(Question.objects.get(id=self.question.id).nis.deleted)

    def test_moderator_undeletes(self):
        self.login(self.moderator)
        self.command(reverse('delete_post', kwargs={'id': self.question.id}))
        self.assertTrue(Question.objects.get(id=self.question.id).nis.deleted)
        response = self.command(reverse('delete_post', kwargs={'id': self.question.id}))
        self.assertEqual(response['commands'], {'unmark_deleted': ['question', str(self.question.id)]})
        self.assertFalse(Question.objects.get(id=self.question.id).nis.deleted)


class BulkModerationTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)
        alice = self.create_user('alice')
        self.questions = []
        for title in ('First question here', 'Second question here', 'Third question here'):
            question = Question(author=alice, title=title, body='Body text', tagnames='csv')
            question.save()
            self.questions.append(question)
        self.login(self.admin)

    def bulk(self, action, questions):
        response = self.client.post('/admin/tools/nodeman/', {
            'execute': '0', 'action': action, '_selected_node': [q.id for q in questions]}, follow=True)
        self.assertEqual(response.status_code, 200)
        return response

    def states(self, state):
        return [getattr(Question.objects.get(id=q.id).nis, state) for q in self.questions]

    def test_bulk_close_delete_and_undelete(self):
        response = self.bulk('close_selected', self.questions[:2])
        self.assertContains(response, 'Selected questions were closed')
        self.assertEqual(self.states('closed'), [True, True, False])
        self.assertEqual(Question.objects.get(id=self.questions[0].id).nstate.closed.extra, 'bulk close')

        self.assertContains(self.bulk('delete_selected', self.questions[1:]), 'All selected nodes marked as deleted')
        self.assertEqual(self.states('deleted'), [False, True, True])

        self.assertContains(self.bulk('undelete_selected', self.questions[1:]), 'All selected nodes undeleted')
        self.assertEqual(self.states('deleted'), [False, False, False])

    def test_list_links_each_post(self):
        answer = Answer(author=self.admin, parent=self.questions[0], body='An answer')
        answer.save()
        page = self.client.get('/admin/tools/nodeman/').content.decode()
        for question in self.questions:
            self.assertIn('<strong><a href="%s" >%s</a></strong>' % (question.get_absolute_url(), question.title), page)
        self.assertIn('(<strong><a href="%s" >%s</a></strong>)' % (answer.get_absolute_url(), self.questions[0].title), page)

    def test_no_selection_does_nothing(self):
        self.client.post('/admin/tools/nodeman/', {'execute': '0', 'action': 'delete_selected'})
        self.assertEqual(self.states('deleted'), [False, False, False])

    def test_moderators_cannot_use_it(self):
        self.login(self.create_user('moderator', is_staff=True))
        self.client.post('/admin/tools/nodeman/', {'execute': '0', 'action': 'delete_selected',
                                                   '_selected_node': [self.questions[0].id]})
        self.assertEqual(self.states('deleted'), [False, False, False])


class ModeratorRightsTest(OSQATestCase):
    def test_grant_and_revoke(self):
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        alice = self.create_user('alice')
        url = lambda action: reverse('user_powers', kwargs={'id': alice.id, 'action': action, 'status': 'staff'})

        self.login(admin)
        self.assertTrue(self.command(url('grant'))['success'])
        self.assertTrue(fresh(alice).is_staff)
        # (a fresh copy: signing in saves the user object, and with it the cache)
        self.login(fresh(alice))
        self.assertEqual(self.client.get('/admin/support/').status_code, 200)
        self.assertEqual(self.client.get(reverse('admin_flagged_posts')).status_code, 200)

        self.login(admin)
        self.assertTrue(self.command(url('remove'))['success'])
        self.assertFalse(fresh(alice).is_staff)
        self.login(fresh(alice))
        for path in ('/admin/support/', reverse('admin_flagged_posts'), '/admin/'):
            with self.subTest(path=path):
                self.assertIn(self.client.get(path).status_code, (401, 403))

    def test_moderators_cannot_grant(self):
        moderator = self.create_user('moderator', is_staff=True)
        alice = self.create_user('alice')
        self.login(moderator)
        response = self.command(reverse('user_powers', kwargs={'id': alice.id, 'action': 'grant', 'status': 'staff'}))
        self.assertFalse(response['success'])
        self.assertFalse(fresh(alice).is_staff)


class ConvertToQuestionTest(SettingsMixin, OSQATestCase):
    def setUp(self):
        super().setUp()
        self.moderator = self.create_user('moderator', is_staff=True, reputation=10)
        self.alice = self.create_user('alice', reputation=10)
        self.bob = self.create_user('bob', reputation=10)
        self.question = Question(author=self.alice, title='How do I export data?', body='Body text', tagnames='csv')
        self.question.save()

    def convert(self, node, node_type='answer', title='A separate question about plots'):
        url = reverse('convert_to_question', kwargs={'id': node.id}) + '?node_type=%s' % node_type
        form = self.client.get(url)
        if form.status_code != 200:
            return form
        return self.client.post(url, {'title': title, 'text': 'The body of the converted question, long enough.',
                                      'tags': 'plots', 'summary': '', 'revision': '1'})

    def test_moderator_converts_a_comment(self):
        from forum.actions import CommentAction
        comment = CommentAction(user=self.bob, ip='127.0.0.1').save(
            data=dict(text='Another question in a comment, long enough.', parent=self.question)).node
        self.login(self.moderator)
        response = self.convert(comment, 'comment')
        self.assertEqual(response.status_code, 302)
        converted = Question.objects.get(id=comment.id)
        self.assertEqual(converted.title, 'A separate question about plots')
        self.assertIsNone(converted.parent)
        self.assertEqual(converted.author, self.bob)
        self.assertFalse(Comment.objects.filter(id=comment.id).exists())
        self.assertRedirects(response, converted.get_absolute_url(), fetch_redirect_response=False)
        self.assertCleanPage(self.client.get(converted.get_absolute_url()))
        self.assertConversionDescribed('comment')

    def assertConversionDescribed(self, kind):
        # The activity entry names the question the post came from.
        from forum.models import Action
        action = Action.objects.filter(action_type='%stoquestion' % kind).latest('id')
        self.assertIn(self.question.title, action.describe(self.moderator))

    def test_owner_converts_own_answer(self):
        self.set_setting(settings.REP_TO_CONVERT_TO_QUESTION, 2000)
        answer = Answer(author=self.bob, parent=self.question, body='A follow-up question really')
        answer.save()
        self.login(self.bob)
        self.assertEqual(self.convert(answer).status_code, 302)
        self.assertEqual(Question.objects.get(id=answer.id).title, 'A separate question about plots')
        self.assertConversionDescribed('answer')

    def test_answerers_profile_after_their_answer_became_a_question(self):
        # Sentry OSQA-B: the "answered" entry pointed at a post with no question.
        self.login(self.bob)
        self.client.post(reverse('answer', args=[self.question.id]), {'text': 'A follow-up question really, long enough.'})
        answer = Answer.objects.get(author=self.bob)
        self.login(self.moderator)
        self.assertEqual(self.convert(answer).status_code, 302)
        with self.assertNoLogs(level='ERROR'):
            for tab in ('', '/recent/'):
                with self.subTest(tab=tab):
                    self.assertCleanPage(self.client.get(self.bob.get_profile_url() + tab))

    def test_others_without_reputation_cannot_convert(self):
        self.set_setting(settings.REP_TO_CONVERT_TO_QUESTION, 2000)
        answer = Answer(author=self.bob, parent=self.question, body='A follow-up question really')
        answer.save()
        self.login(self.alice)
        self.assertEqual(self.convert(answer).status_code, 403)
        self.assertTrue(Answer.objects.filter(id=answer.id).exists())


class MentionNotificationTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=100, email_isvalid=True)
        self.bob = self.create_user('bob', reputation=100, email_isvalid=True)
        self.carol = self.create_user('carol', reputation=100, email_isvalid=True)

    def mentions(self, user):
        return list(Notification.objects.filter(user=user, kind=Notification.MENTION).values_list('node_id', flat=True))

    def bell(self, user):
        self.login(user)
        return self.client.get('/').content.decode()

    def test_mention_in_a_question_and_in_an_edit(self):
        self.login(self.alice)
        self.client.post(reverse('ask'), {'title': 'How do I export Collect survey data?',
                                          'text': 'Hello @bob, how do I export the survey data?', 'tags': 'collect'})
        question = Question.objects.get()
        self.assertEqual(self.mentions(self.bob), [question.id])
        self.assertEqual(self.mentions(self.carol), [])
        self.assertIn('class="notification-count">1<', self.bell(self.bob))

        self.login(self.alice)
        response = self.client.post(reverse('edit_question', kwargs={'id': question.id}), {
            'title': question.title, 'tags': 'collect', 'summary': 'ask carol too', 'revision': '1',
            'text': 'Hello @bob and @carol, how do I export the survey data?'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.mentions(self.carol), [question.id])
        self.assertEqual(self.mentions(self.bob), [question.id])  # not again
        self.assertIn('class="notification-count">1<', self.bell(self.carol))
        notifications = self.client.get(reverse('notifications')).content.decode()
        self.assertIn('alice', notifications)
        self.assertIn(question.title, notifications)


class FeedbackTest(OSQATestCase):
    def test_signed_in_user_name_and_email_come_from_the_account(self):
        admins = [self.create_user('admin%d' % n, is_superuser=True, is_staff=True) for n in (1, 2)]
        self.create_user('moderator', is_staff=True)
        alice = self.create_user('alice', email_isvalid=True)
        self.login(alice)
        form = self.client.get(reverse('feedback')).content.decode()
        self.assertNotIn('id="id_email"', form)
        self.assertNotIn('id="id_name"', form)

        response = self.client.post(reverse('feedback'), {
            'message': 'The export button is missing.', 'next': '/faq/',
            'name': 'Someone Else', 'email': 'forged@example.com'})
        self.assertRedirects(response, '/faq/', fetch_redirect_response=False)
        self.assertEqual(sorted(m[0].username for m in self.sent_mail), ['admin1', 'admin2'])
        text = self.sent_mail[0][3]
        self.assertIn('From: alice', text)
        self.assertIn('Email: alice@example.com', text)
        self.assertIn('The export button is missing.', text)
        self.assertNotIn('forged@example.com', text)
        self.assertNotIn('Someone Else', text)
        del admins


class AvatarTest(SettingsMixin, OSQATestCase):
    def test_profile_shows_the_gravatar(self):
        alice = self.create_user('alice')
        alice.email = 'Alice.Smith@Example.com'
        alice.save()
        digest = md5(b'alice.smith@example.com').hexdigest()
        page = self.client.get(alice.get_profile_url()).content.decode()
        self.assertIn('src="https://secure.gravatar.com/avatar/%s?s=128&amp;d=identicon&amp;r=g"' % digest, page)
        self.assertIn('width="128" height="128"', page)
        self.assertIn('alt="alice"', page)

        self.set_setting(settings.GRAVATAR_DEFAULT_IMAGE, 'mm')
        self.set_setting(settings.GRAVATAR_ALLOWED_RATING, 'pg')
        page = self.client.get(alice.get_profile_url()).content.decode()
        self.assertIn('/avatar/%s?s=128&amp;d=mm&amp;r=pg"' % digest, page)
