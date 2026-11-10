"""Regression tests for the findings of the security review (one class each):
the ways around two-step verification, "Confirm it's you" and moderation
that it found, and the places that showed removed or held content."""
import datetime

from django.urls import reverse

from forum.utils import two_factor

from .base import OSQATestCase


class DjangoAdminSignInTest(OSQATestCase):
    """/nimda/ (Django's model admin) had its own login page: a staff password
    alone opened it, and the OSQA admin, without the second factor or the
    sign-in lockout."""

    def setUp(self):
        super().setUp()
        self.boss = self.create_user('boss', is_staff=True, is_superuser=True)
        device = two_factor.setup_device(self.boss)
        device.confirmed_at = datetime.datetime.now()
        device.save()

    def test_its_login_page_sends_to_the_osqa_sign_in(self):
        response = self.client.get('/nimda/login/?next=/nimda/auth/user/')
        self.assertRedirects(response, reverse('auth_signin') + '?next=/nimda/auth/user/', fetch_redirect_response=False)
        # The password posted to it signs nobody in.
        response = self.client.post('/nimda/login/', {'username': 'boss', 'password': 'secret-pass', 'next': '/nimda/'})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get('/admin/').status_code, 401)
        self.assertRedirects(self.client.get('/nimda/'), '/nimda/login/?next=/nimda/', fetch_redirect_response=False)

    def test_a_session_osqa_did_not_sign_in_is_turned_away(self):
        self.client.force_login(self.boss)  # no session epoch: not OSQA's sign-in
        response = self.client.get('/nimda/auth/user/')
        self.assertRedirects(response, '/nimda/login/?next=/nimda/auth/user/', fetch_redirect_response=False)
        response = self.client.get(response['Location'])
        self.assertRedirects(response, reverse('auth_signin') + '?next=/nimda/auth/user/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)  # signed out, to start over

    def test_staff_signed_in_by_osqa_get_in(self):
        self.login(self.boss)
        self.assertEqual(self.client.get('/nimda/auth/user/').status_code, 200)

    def test_members_signed_in_are_refused_without_a_loop(self):
        member = self.create_user('member')
        self.login(member)
        self.assertRedirects(self.client.get('/nimda/'), '/nimda/login/?next=/nimda/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/nimda/login/?next=/nimda/').status_code, 403)

    def test_staff_without_required_two_step_are_sent_to_set_it_up(self):
        from forum import settings
        two_factor.disable(self.boss)
        self.login(self.boss)
        old = settings.TWO_FACTOR_REQUIRED_FOR_STAFF.value
        settings.TWO_FACTOR_REQUIRED_FOR_STAFF.set_value(True)
        try:
            response = self.client.get('/nimda/login/?next=/nimda/')
            self.assertRedirects(response, reverse('user_security', kwargs={'id': self.boss.id}),
                                 fetch_redirect_response=False)
            self.assertNotEqual(self.client.get('/nimda/auth/user/').status_code, 200)
        finally:
            settings.TWO_FACTOR_REQUIRED_FOR_STAFF.set_value(old)


class SettingAPasswordTest(OSQATestCase):
    """Members who sign in only with Google/GitHub (and administrators) set a
    password without typing an old one: that now needs "Confirm it's you"."""

    def test_without_the_old_password_it_needs_a_recent_sign_in(self):
        erin = self.create_user('erin')
        erin.set_unusable_password()
        erin.save()
        url = reverse('user_authsettings', kwargs={'id': erin.id})
        data = {'password1': 'A-new-Passw0rd-123', 'password2': 'A-new-Passw0rd-123'}
        self.login(erin, recent=False)
        response = self.client.post(url, data)
        self.assertTrue(response['Location'].startswith(reverse('auth_confirm_identity')), response['Location'])
        erin.refresh_from_db()
        self.assertFalse(erin.has_usable_password())

        self.login(erin)
        self.client.post(url, data)
        erin.refresh_from_db()
        self.assertTrue(erin.check_password('A-new-Passw0rd-123'))


class UndeleteTest(OSQATestCase):
    """The delete command undid any deletion for whoever may delete the post:
    an author brought back the spam a moderator, or the flags, removed."""

    def setUp(self):
        super().setUp()
        from forum.models import Answer, Question
        self.author = self.create_user('spammer', reputation=100)
        self.mod = self.create_user('mod', is_staff=True)
        asker = self.create_user('asker')
        question = Question(author=asker, title='A question about exports', body='Body', tagnames='collect')
        question.save()
        self.answer = Answer(author=self.author, parent=question, body='Buy cheap things')
        self.answer.save()

    def delete(self, user):
        self.login(user)
        return self.client.post('/delete/%d/' % self.answer.id, **self.AJAX)

    def deleted(self):
        from forum.models import Answer
        return Answer.objects.get(id=self.answer.id).nis.deleted

    def test_the_author_cannot_undo_a_moderators_deletion(self):
        self.delete(self.mod)
        self.assertTrue(self.deleted())
        response = self.delete(self.author)
        self.assertIn('Only a moderator can bring this post back.', response.content.decode())
        self.assertTrue(self.deleted())
        # No undelete link for them either; the moderator still can.
        from forum.models import Answer, User
        from forum.templatetags.node_tags import post_controls
        answer = Answer.objects.get(id=self.answer.id)

        def labels(user):
            return [str(c['text']) for c in post_controls(answer, User.objects.get(id=user.id))['controls']]
        self.assertNotIn('undelete', labels(self.author))
        self.assertIn('undelete', labels(self.mod))
        self.delete(self.mod)
        self.assertFalse(self.deleted())

    def test_nor_a_deletion_by_the_flags(self):
        from forum.actions import DeleteAction
        DeleteAction(node=self.answer, user=self.author, extra='BYFLAGGED').save()
        self.assertTrue(self.deleted())
        self.delete(self.author)
        self.assertTrue(self.deleted())

    def test_authors_can_undo_their_own_deletion(self):
        self.delete(self.author)
        self.assertTrue(self.deleted())
        self.delete(self.author)
        self.assertFalse(self.deleted())


class HiddenQuestionsTest(OSQATestCase):
    """Favorites and follows took any question id, deleted or held ones too,
    and the lists then showed their titles; answers, the Markdown source and
    the comments feed reached past a deleted question or answer."""

    def setUp(self):
        super().setUp()
        from forum.actions import CloseAction, DeleteAction
        from forum.models import Answer, Comment, Question
        self.owner = self.create_user('owner')
        self.mod = self.create_user('mod', is_staff=True)
        self.member = self.create_user('member', reputation=500)
        self.secret = Question(author=self.owner, title='A removed question with a secret', body='Secret body',
                               tagnames='collect')
        self.secret.save()
        self.answer = Answer(author=self.owner, parent=self.secret, body='An answer under it')
        self.answer.save()
        self.comment = Comment(author=self.owner, parent=self.answer, body='A comment under the answer')
        self.comment.save()
        DeleteAction(user=self.mod, node=self.secret, ip='127.0.0.1').save()
        self.closed = Question(author=self.owner, title='A closed question', body='Closed body', tagnames='collect')
        self.closed.save()
        CloseAction(user=self.mod, node=self.closed, extra='duplicate', ip='127.0.0.1').save()

    def test_favorites_and_follows_refuse_hidden_questions(self):
        self.login(self.member)
        response = self.client.post('/mark_favorite/%d/' % self.secret.id, **self.AJAX)
        self.assertNotEqual(response.status_code, 200)
        response = self.client.post('/subscribe/%d/' % self.secret.id, **self.AJAX)
        self.assertNotEqual(response.status_code, 200)
        from forum.actions import FavoriteAction
        from forum.models import QuestionSubscription
        self.assertFalse(FavoriteAction.objects.filter(user=self.member).exists())
        self.assertFalse(QuestionSubscription.objects.filter(user=self.member, question=self.secret).exists())

    def test_lists_leave_out_questions_deleted_since(self):
        from forum.actions import FavoriteAction
        from forum.models import QuestionSubscription
        FavoriteAction(user=self.member, node=self.secret, ip='127.0.0.1').save()
        QuestionSubscription(user=self.member, question=self.secret, auto_subscription=False).save()
        from django.urls import reverse
        favorites = reverse('user_favorites', kwargs={'id': self.member.id, 'slug': 'member'})
        self.assertNotContains(self.client.get(favorites), 'removed question')
        self.login(self.member)
        page = self.client.get(self.member.get_user_subscriptions_url() + '?tab=manage')
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'removed question')

    def test_no_answers_on_closed_or_deleted_questions(self):
        from forum.models import Answer
        self.login(self.member)
        before = Answer.objects.count()
        response = self.client.post('/questions/%d/answer/' % self.closed.id, {'text': 'An answer long enough to post.'})
        self.assertRedirects(response, self.closed.get_absolute_url(), fetch_redirect_response=False)
        response = self.client.post('/questions/%d/answer/' % self.secret.id, {'text': 'An answer long enough to post.'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Answer.objects.count(), before)

    def test_markdown_source_and_feed_stop_at_a_deleted_parent(self):
        self.login(self.member)
        for node in (self.answer, self.comment):
            response = self.client.post('/node_markdown/%d/' % node.id, **self.AJAX)
            self.assertNotIn(node.body, response.content.decode())
        # The comments feed of a visible question: not the comments on its deleted answer.
        from forum.actions import DeleteAction
        from forum.models import Answer, Comment, Question
        question = Question(author=self.owner, title='A visible question', body='Visible body', tagnames='collect')
        question.save()
        gone = Answer(author=self.owner, parent=question, body='A deleted answer')
        gone.save()
        Comment(author=self.owner, parent=gone, body='Comment on the deleted answer').save()
        DeleteAction(user=self.mod, node=gone, ip='127.0.0.1').save()
        feed = self.client.get(question.get_absolute_url() + '?type=rss&comments=yes')
        self.assertNotIn('Comment on the deleted answer', feed.content.decode())


class SignOutEverywhereTest(OSQATestCase):
    """Signing out everywhere left browser push on, and a password reset left
    the API tokens someone may have made with the account."""

    def test_push_stops_on_every_device(self):
        from forum.models import PushSubscription
        from forum.utils import accounts, push
        member = self.create_user('member')
        endpoint = 'https://fcm.googleapis.com/fcm/send/device'
        PushSubscription.objects.create(user=member, endpoint=endpoint, endpoint_hash=push.endpoint_hash(endpoint),
                                        p256dh='key', auth='auth')
        accounts.sign_out_everywhere(member)
        self.assertFalse(PushSubscription.objects.filter(user=member).exists())

    def test_a_password_reset_revokes_api_tokens(self):
        from forum.models import ApiToken
        from forum.utils import accounts
        member = self.create_user('member')
        from django.test import RequestFactory
        request = RequestFactory().post('/')
        request.user = member
        request.session = self.client.session
        ApiToken.objects.create_token(member, 'made by whoever had the account')
        accounts.password_changed(request, member, 'changed')
        self.assertTrue(ApiToken.objects.filter(user=member).exists())  # a change by the member keeps them
        accounts.password_changed(request, member, 'reset')
        self.assertFalse(ApiToken.objects.filter(user=member).exists())


class SignInLockoutTest(OSQATestCase):
    """The per-account lockout counted the name as typed: on MySQL, whose
    collation takes "Alice", "alice" and "àlice" for the same name, every
    spelling had its own counter."""

    def test_spellings_of_one_account_share_its_counter(self):
        from unittest import mock
        from forum import settings
        from forum.utils import accounts
        alice = self.create_user('alice')
        # The database matches names as MySQL's case- and accent-insensitive collation does.
        with mock.patch.object(accounts, '_account_pk', lambda name: alice.pk if name.lower() in
                               ('alice', 'àlice', 'alicé') else None):
            for name in ('alice', 'Alice', 'àlice', 'alicé') * 3:
                self.client.post('/account/local/signin/', {'username': name, 'password': 'wrong-pass'})
            self.assertEqual(accounts.login_counter('ÀLICE'.lower()), accounts.login_counter(user=alice))
            response = self.client.post('/account/local/signin/', {'username': 'alicé', 'password': 'secret-pass'})
        self.assertGreaterEqual(int(settings.LOGIN_FAILURES_LIMIT), 1)
        self.assertNotEqual(self.client.session.get('_auth_user_id'), str(alice.id))  # paused, even with the password
        self.assertEqual(response.status_code, 302)


class TemplateCodeTest(OSQATestCase):
    def test_declare_blocks_refuse_template_variables(self):
        from django.template import Template, TemplateSyntaxError
        with self.assertRaises(TemplateSyntaxError):
            Template('{% load extra_tags %}{% declare %}x = "{{ user_text }}"{% enddeclare %}')

    def test_mentions_dont_reopen_sanitized_attributes(self):
        """link_mentions() splits the sanitized HTML on tags: it relies on the
        sanitizer escaping < and > inside attribute values."""
        from forum.models.node import render_markdown
        self.create_user('bob')
        html = render_markdown('<span title="> @bob <img src=x onerror=alert(1)>">hi</span>')
        self.assertNotIn('<img', html)
        self.assertNotIn('onerror=alert', html.replace('&gt;', '>').split('title=')[0])
