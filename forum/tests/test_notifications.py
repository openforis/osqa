import json

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from forum.models import Answer, Comment, Notification, Question, User

from .base import OSQATestCase


class NotificationFixture(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', email_isvalid=True, reputation=100)
        self.bob = self.create_user('bob', email_isvalid=True, reputation=100)
        self.carol = self.create_user('carol', email_isvalid=True, reputation=100)
        self.login(self.alice)
        self.client.post(reverse('ask'), {'title': 'How do I export survey data to CSV?',
                                          'text': 'Question body that is long enough.', 'tags': 'collect'})
        self.question = Question.objects.get()

    def answer_as(self, user, text='An answer that is long enough to post.'):
        self.login(user)
        self.client.post(reverse('answer', args=[self.question.id]), {'text': text})
        return Answer.objects.filter(author=user).latest('id')

    def comment_as(self, user, post, text):
        self.login(user)
        self.command(reverse('comment', kwargs={'id': post.id}), {'comment': text})
        return Comment.objects.filter(author=user).latest('id')

    def kinds(self, user):
        return sorted(Notification.objects.filter(user=user).values_list('kind', flat=True))


class CreatingNotificationsTest(NotificationFixture):
    def test_replies_mentions_and_accepted_answers(self):
        answer = self.answer_as(self.bob)
        self.assertEqual(self.kinds(self.alice), ['answer'])
        self.assertEqual(self.kinds(self.bob), [])

        # A comment on bob's answer: bob (its author) and alice (the asker);
        # carol, mentioned, gets a mention instead.
        dave = self.create_user('dave', reputation=100)
        self.comment_as(dave, answer, 'Thanks, @carol might know more about this.')
        self.assertEqual(self.kinds(self.bob), ['comment'])
        self.assertEqual(self.kinds(self.alice), ['answer', 'comment'])
        self.assertEqual(self.kinds(self.carol), ['mention'])
        self.assertEqual(Notification.objects.get(user=self.carol).actor, dave)

        self.login(self.alice)
        self.assertTrue(self.command('/accept_answer/%d/' % answer.id)['success'])
        self.assertIn('accepted', self.kinds(self.bob))

    def test_followers_hear_about_answers_even_with_emails_off(self):
        prefs = User.objects.get(id=self.alice.id).subscription_settings
        prefs.enable_notifications = False
        prefs.save()
        self.question.subscribers  # noqa: B018  carol follows the question
        from forum.models import QuestionSubscription
        QuestionSubscription(user=self.carol, question=self.question).save()

        self.answer_as(self.bob)
        self.assertEqual(self.kinds(self.alice), ['answer'])
        self.assertEqual(self.kinds(self.carol), ['answer'])

    def test_own_posts_notify_nobody_and_inactive_users_are_skipped(self):
        self.answer_as(self.alice, 'I found it myself, here is the answer.')
        self.assertEqual(Notification.objects.count(), 0)
        User.objects.filter(id=self.carol.id).update(is_active=False)
        self.comment_as(self.bob, self.question, 'Hello @carol, have a look at this one.')
        self.assertEqual(self.kinds(self.carol), [])

    def test_badges(self):
        answer = self.answer_as(self.bob)
        self.login(self.alice)
        self.command('/accept_answer/%d/' % answer.id)
        badges = Notification.objects.filter(kind='badge')
        self.assertTrue(badges.exists())
        self.assertTrue(all(n.text for n in badges))


class BellAndListTest(NotificationFixture):
    def test_bell_list_and_reading(self):
        self.answer_as(self.bob)
        self.comment_as(self.carol, self.question, 'A comment that is long enough.')

        self.login(self.alice)
        page = self.client.get('/')
        self.assertContains(page, 'id="notification-bell"')
        self.assertContains(page, 'aria-label="Notifications: 2 unread"')
        self.assertContains(page, '<span class="notification-count">2</span>', html=False)
        # The phone's tab bar shows it on More and in its sheet, from the same query.
        self.assertContains(page, '<span data-unread-number>2</span>', count=2)
        self.assertContains(page, '<span class="visually-hidden" data-unread-label>, Notifications: 2 unread</span>')
        with CaptureQueriesContext(connection) as queries:
            self.client.get('/')
        counts = [q['sql'] for q in queries.captured_queries
                  if 'forum_notification' in q['sql'] and 'COUNT(' in q['sql'].upper()]
        self.assertEqual(len(counts), 1, counts)
        self.assertEqual(json.loads(self.client.get(reverse('notifications_count')).content), {'unread': 2})

        page = self.client.get(reverse('notifications'))
        self.assertContains(page, '<strong>bob</strong> answered <em>How do I export survey data to CSV?</em>', html=True)
        self.assertContains(page, '<strong>carol</strong> commented on', html=False)
        self.assertContains(page, 'Mark all as read')

        first = Notification.objects.filter(user=self.alice, kind='answer').get()
        response = self.client.get(reverse('notification_open', kwargs={'id': first.id}))
        self.assertRedirects(response, Answer.objects.get().get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(json.loads(self.client.get(reverse('notifications_count')).content), {'unread': 1})

        self.client.post(reverse('notifications_read'))
        self.assertEqual(json.loads(self.client.get(reverse('notifications_count')).content), {'unread': 0})
        page = self.client.get('/')
        self.assertContains(page, '<span class="notification-count" hidden>0</span>', html=False)
        self.assertContains(page, '<span class="app-unread" data-unread-badge aria-hidden="true" hidden>')
        self.assertContains(page, '<span class="visually-hidden" data-unread-label></span>')

    def test_opening_the_question_marks_its_notifications_read(self):
        self.answer_as(self.bob)
        self.login(self.alice)
        self.client.get(self.question.get_absolute_url())
        self.assertFalse(Notification.objects.filter(user=self.alice, read_at=None).exists())

    def test_privacy(self):
        self.answer_as(self.bob)
        item = Notification.objects.get(user=self.alice)
        self.login(self.carol)
        self.assertEqual(self.client.get(reverse('notification_open', kwargs={'id': item.id})).status_code, 404)
        self.client.logout()
        self.assertEqual(json.loads(self.client.get(reverse('notifications_count')).content), {'unread': 0})
        self.assertEqual(self.client.get(reverse('notifications')).status_code, 302)
        self.assertNotContains(self.client.get('/'), 'notification-bell')
        self.assertEqual(self.client.get(reverse('notifications_read')).status_code, 405)

    def test_empty_list(self):
        self.login(self.carol)
        self.assertContains(self.client.get(reverse('notifications')), 'No notifications yet')
