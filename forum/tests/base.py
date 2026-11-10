import datetime
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from forum.models import User
from forum.models.action import Action


class OSQATestCase(TestCase):
    """Base class: clean cache, synchronous action hooks and captured email."""

    AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def setUp(self):
        super().setUp()
        # Model instances and query results are cached outside the database,
        # so they would otherwise leak between tests.
        cache.clear()
        self.addCleanup(cache.clear)
        from forum.settings.base import Setting
        Setting.forget_values()
        # ...and keep the values a test reads for the whole test (set_value()
        # still replaces them): a copy expiring in the middle of a test made
        # the setting read the database again, inside query budgets, at a
        # moment that depended on how fast the machine was.
        values_patcher = mock.patch('forum.settings.base.TMP_MINICACHE_SECONDS', 3600)
        values_patcher.start()
        self.addCleanup(values_patcher.stop)

        # Action hooks run in a background thread, which can't see the test
        # transaction; run them inline instead.
        trigger_hooks = Action.trigger_hooks
        patcher = mock.patch.object(
            Action, 'trigger_hooks', lambda action, threaded, new=True: trigger_hooks(action, False, new))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.sent_mail = []
        patcher = mock.patch('forum.templatetags.email_tags.create_and_send_mail_messages',
                             lambda messages, **kwargs: self.sent_mail.extend(messages))
        patcher.start()
        self.addCleanup(patcher.stop)

    def create_user(self, username, password='secret-pass', **fields):
        user = User(username=username, email='%s@example.com' % username, **fields)
        user.set_password(password)
        user.save()
        return user

    def signup_token(self, age=60):
        """The hidden time stamp of a sign-up form shown `age` seconds ago."""
        import time
        from django.core import signing
        from forum.utils.antispam import SIGNUP_SALT
        return signing.dumps(time.time() - age, salt=SIGNUP_SALT)

    def login(self, user, recent=True):
        """Signs `user` in; like a real sign-in, it counts as recent for
        "Confirm it's you" (forum/utils/sudo.py) unless `recent` is False."""
        self.client.force_login(user)
        from forum.utils import accounts
        session = self.client.session
        session[accounts.EPOCH_SESSION_KEY] = int(user.session_epoch or 0)  # as accounts.signed_in() does
        if recent:
            session[accounts.AUTH_TIME_SESSION_KEY] = datetime.datetime.now().isoformat()
        session.save()

    def command(self, url, data=None):
        """POST to an AJAX command view and return the decoded JSON response."""
        response = self.client.post(url, data or {}, **self.AJAX)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def assertCleanPage(self, response, status=200):
        """The page rendered and shows no leftovers of broken URL or counter code."""
        self.assertEqual(response.status_code, status)
        body = response.content.decode('utf-8')
        for marker in ("', (), {", 'DenormalizedField object', '/((),'):
            self.assertNotIn(marker, body)
