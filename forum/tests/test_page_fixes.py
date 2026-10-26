import base64
import datetime
import json
import re
import zlib

from django.core.cache import cache
from django.db import connection
from django.test import override_settings

from forum.actions import VoteUpAction
from forum.models import Action, ActionRepute, Answer, Node, Question, User
from forum.views.users import reputation_graph_points

from .base import OSQATestCase


class FocusedAnswerTest(OSQATestCase):
    def test_bad_focused_answer_id_is_ignored(self):
        alice = self.create_user('alice')
        question = Question(author=alice, title='A question title', body='Body text', tagnames='one')
        question.save()
        for value in ('abc', '', '12x', '7'):
            with self.subTest(value=value):
                self.assertCleanPage(self.client.get(question.get_absolute_url(), {'focusedAnswerId': value}))


class UnansweredSortTest(OSQATestCase):
    def test_unanswered_sort_lists_questions_with_fewer_answers_first(self):
        alice = self.create_user('alice')
        answered = Question(author=alice, title='An answered question', body='Body text', tagnames='one')
        answered.save()
        Answer(author=self.create_user('bob'), parent=answered, body='An answer long enough').save()
        open_question = Question(author=alice, title='An open question', body='Body text', tagnames='one')
        open_question.save()
        for url in ('/questions/unanswered/?sort=unanswered', '/questions/?sort=unanswered', '/tags/one/?sort=unanswered'):
            with self.subTest(url=url):
                self.assertCleanPage(self.client.get(url))
        html = self.client.get('/questions/?sort=unanswered').content.decode()
        self.assertLess(html.index('An open question'), html.index('An answered question'))


class BadRequestTest(OSQATestCase):
    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_unknown_host_is_a_plain_400(self):
        # SecurityMiddleware refuses the host before SessionMiddleware runs: the
        # 400 page must not need the session (CSRF_USE_SESSIONS).
        with self.assertNoLogs('forum.errors', level='ERROR'):
            response = self.client.get('/', HTTP_HOST='scanner.example')
        self.assertEqual(response.status_code, 400)

    def test_autocomplete_without_query_is_a_400(self):
        for url in ('/matching_users/', '/matching_tags/', '/matching_tags/?q=%20'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 400)


class ImportedLeftoversTest(OSQATestCase):
    """Rows an imported forum left behind must not break profile pages."""

    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice')
        self.bob = self.create_user('bob', reputation=1000)
        self.question = Question(author=self.alice, title='A question title', body='Body text', tagnames='one')
        self.question.save()
        answer = Answer(author=self.bob, parent=self.question, body='An answer whose question goes away')
        answer.save()
        self.imported_action(self.bob, 'answer', node=answer)
        accepted = self.imported_action(self.alice, 'acceptanswer', node=answer)
        ActionRepute(action=accepted, user=self.bob, value=15).save()
        VoteUpAction(user=self.alice, node=answer, ip='127.0.0.1').save()
        Node.objects.filter(id=answer.id).update(parent=None, abs_parent=None)
        # A badge award whose Award row is gone.
        self.imported_action(self.bob, 'award')
        cache.clear()

    def imported_action(self, user, action_type, node=None, extra=None):
        """An action row as an import writes it (Action.save() would set its type and extra)."""
        action = Action(user=user, node=node, ip='127.0.0.1')
        action.save()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE forum_action SET action_type = %s, extra = %s WHERE id = %s',
                           [action_type, extra, action.id])
        return action

    def assertProfilePagesClean(self, user):
        with self.assertNoLogs(level='ERROR'):
            for tab in ('', '/recent/', '/reputation/'):
                with self.subTest(tab=tab):
                    self.assertCleanPage(self.client.get(user.get_profile_url() + tab))

    def test_answer_without_question_and_award_without_badge(self):
        self.assertProfilePagesClean(self.bob)
        self.login(self.alice)
        with self.assertNoLogs(level='ERROR'):
            self.assertCleanPage(self.client.get(self.alice.get_profile_url() + '/votes/'))

    def test_other_activity_is_still_listed(self):
        self.imported_action(self.alice, 'ask', node=self.question)
        response = self.client.get(self.alice.get_profile_url() + '/recent/')
        self.assertContains(response, 'A question title')

    def test_report_from_the_original_osqa(self):
        # A pickle naming a function Django no longer has (Django 1.6 model pickles).
        legacy = base64.b64encode(zlib.compress(b'cdjango.db.models.base\nsimple_class_factory\n.')).decode()
        self.imported_action(self.alice, 'report', extra=legacy)
        cache.clear()
        self.assertProfilePagesClean(self.alice)
        self.assertContains(self.client.get(self.alice.get_profile_url() + '/recent/'), 'reported a user')


class ReputationGraphDataTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice')
        self.bob = self.create_user('bob', reputation=1000)
        self.question = Question(author=self.alice, title='A question title', body='Body text', tagnames='one')
        self.question.save()

    def test_running_total_ends_at_current_reputation(self):
        # Reputation no change accounts for (set by an administrator or
        # imported) is the starting value.
        User.objects.filter(pk=self.alice.pk).update(reputation=20)
        VoteUpAction(user=self.bob, node=self.question, ip='127.0.0.1').save()
        alice = User.objects.get(pk=self.alice.pk)
        changes = list(alice.reputes.order_by('date').values_list('value', flat=True))
        self.assertTrue(changes)

        later = datetime.datetime.now() + datetime.timedelta(hours=1)
        points = reputation_graph_points(alice, now=later)
        values = [y for _x, y in points]
        self.assertEqual(values[-1], alice.reputation)
        self.assertEqual(values[-1] - values[-2], 0)  # the point for "now" repeats the total
        # Every step is one change (the first point is the starting value
        # when the account is older than its first change).
        steps = [b - a for a, b in zip(values, values[1:-1])]
        self.assertEqual(steps[-len(changes):], changes)
        xs = [x for x, _y in points]
        self.assertEqual(xs, sorted(xs))

    def test_page_passes_the_points(self):
        VoteUpAction(user=self.bob, node=self.question, ip='127.0.0.1').save()
        alice = User.objects.get(pk=self.alice.pk)
        response = self.client.get(alice.get_profile_url() + '/reputation/')
        self.assertCleanPage(response)
        data = re.search(r'data-points="([^"]*)"', response.content.decode()).group(1)
        points = json.loads(data.replace('&quot;', '"'))
        self.assertEqual(points[-1][1], alice.reputation)

    def test_no_points_without_changes(self):
        carol = self.create_user('carol', reputation=5)
        self.assertEqual(reputation_graph_points(carol), [])


class DefaultStaticTextTest(OSQATestCase):
    def test_faq_headings_are_rendered(self):
        response = self.client.get('/faq/')
        self.assertCleanPage(response)
        html = response.content.decode()
        self.assertIn('<h2>Why are email notifications so important?</h2>', html)
        self.assertNotIn('**', html)
        self.assertNotRegex(html, r'\|REP_[A-Z_]+\|')

    def test_about_and_privacy(self):
        about = self.client.get('/about/')
        self.assertCleanPage(about)
        self.assertNotIn('**', about.content.decode())
        self.assertContains(about, 'href="/faq/"')
        privacy = self.client.get('/privacy/')
        self.assertCleanPage(privacy)
        self.assertNotContains(privacy, 'general message about privacy')
        self.assertNotContains(privacy, 'cookie policy details')
