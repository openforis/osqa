"""Browser push notifications: the "Get notifications on this device" switch
(asks for permission only when pressed, subscribes, unsubscribes), the device
settings, the explanations when it can't be used (blocked, unsupported, iPhone
without the Home Screen app), and the service worker showing a pushed message
and opening it.

Headless Chromium has no push service to subscribe to, so PushManager is
replaced in the page by a fake that returns a subscription with real keys
(add_init_script); everything else is real: the permission prompt API (the
context grants it), the service worker, the server's endpoints and pages.
The server's push request is replaced too (forum.utils.push.webpush): the
test hands the payload it would have sent to the service worker as a push
event, then "clicks" the notification."""
import base64
import json
import os
import re
from unittest import mock

from django.conf import settings as djsettings
from django.contrib.sessions.backends.db import SessionStore
from django.test import override_settings
from django.urls import reverse

from forum.models import Notification, PushSubscription
from forum.utils import push

from . import test_accessibility
from .base import E2ETestCase

PUBLIC_KEY, PRIVATE_KEY = push.generate_keys()
ENDPOINT = 'https://fcm.googleapis.com/fcm/send/e2e-device'
IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) '
          'Version/18.0 Mobile/15E148 Safari/604.1')


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def fake_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {'p256dh': b64(public), 'auth': b64(os.urandom(16))}


# Counts permission requests; replaces PushManager with a fake whose
# subscription survives reloads (localStorage), like a real one.
FAKE_PUSH = '''(() => {
    const FAKE = %s;
    window.__permissionAsks = 0;
    // The permission is faked too: Chromium's headless shell (what CI's
    // "playwright install chromium" runs) reports "denied" even when the
    // context was granted notifications, and an ungranted full Chromium
    // reports "denied" rather than "default".
    if (window.Notification && Notification.requestPermission) {
        let permission = FAKE.permission || (FAKE.grant ? 'granted' : 'default');
        Notification.requestPermission = function () {
            window.__permissionAsks++;
            const answer = FAKE.answer || (FAKE.grant ? 'granted' : 'denied');
            if (answer !== 'default') permission = answer;
            return Promise.resolve(answer);
        };
        Object.defineProperty(Notification, 'permission', {get: () => permission});
    }
    if (FAKE.noPush) { delete window.PushManager; return; }
    if (!window.PushManager) return;
    const KEY = 'e2e-fake-push';
    const subscription = () => ({
        endpoint: FAKE.endpoint, expirationTime: null,
        toJSON: () => ({endpoint: FAKE.endpoint, expirationTime: null, keys: FAKE.keys}),
        unsubscribe: () => { localStorage.removeItem(KEY); return Promise.resolve(true); },
    });
    PushManager.prototype.subscribe = function (options) {
        const key = new Uint8Array(options.applicationServerKey);
        window.__subscribeOptions = {userVisibleOnly: options.userVisibleOnly, length: key.length, first: key[0]};
        localStorage.setItem(KEY, '1');
        return Promise.resolve(subscription());
    };
    PushManager.prototype.getSubscription = function () {
        return Promise.resolve(localStorage.getItem(KEY) ? subscription() : null);
    };
})();'''

# A push event as the push service would deliver it, and the notification it shows.
PUSH = '''async (payload) => {
    const shown = [];
    const original = self.registration.showNotification.bind(self.registration);
    self.registration.showNotification = (title, options) => {
        shown.push({title: title, body: options.body, tag: options.tag, icon: options.icon, badge: options.badge,
                    data: options.data});
        return original(title, options).catch(() => null);
    };
    const data = typeof payload === 'string' ? payload : JSON.stringify(payload);
    let event;
    try {
        event = new PushEvent('push', {data: data});
    } catch (error) {
        event = new ExtendableEvent('push');
        Object.defineProperty(event, 'data', {value: {json: () => JSON.parse(data)}});
    }
    const waits = [];
    Object.defineProperty(event, 'waitUntil', {value: promise => waits.push(promise)});
    self.dispatchEvent(event);
    await Promise.all(waits);
    delete self.registration.showNotification;
    return shown;
}'''

CLICK = '''async (data) => {
    const event = new ExtendableEvent('notificationclick');
    let closed = false;
    Object.defineProperty(event, 'notification', {value: {data: data, close: () => { closed = true; }}});
    const waits = [];
    Object.defineProperty(event, 'waitUntil', {value: promise => waits.push(promise)});
    self.dispatchEvent(event);
    await Promise.all(waits);
    return closed;
}'''

# Records what the Badging API is given (the app icon's unread count).
BADGES = """() => {
    self.__badges = [];
    self.navigator.setAppBadge = n => { self.__badges.push(n); return Promise.resolve(); };
    self.navigator.clearAppBadge = () => { self.__badges.push(0); return Promise.resolve(); };
}"""

CONTROLLED = "() => !!(navigator.serviceWorker && navigator.serviceWorker.controller)"


@override_settings(VAPID_PUBLIC_KEY=PUBLIC_KEY, VAPID_PRIVATE_KEY=PRIVATE_KEY, VAPID_SUBJECT='mailto:admin@example.org')
class PushNotificationsTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=100)
        self.bob = self.create_user('bob', reputation=100)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?')
        self.keys = fake_keys()
        self.pushed = []
        self._patch(mock.patch('forum.utils.push.webpush',
                               lambda subscription, data: self.pushed.append((subscription.endpoint, json.loads(data)))))

    def open_with_push(self, user, grant=True, **fake):
        options = fake.pop('options', {})
        if grant:
            options['permissions'] = ['notifications']
        page = self.open(user, **options)
        page.context.add_init_script(FAKE_PUSH % json.dumps(dict({'endpoint': ENDPOINT, 'keys': self.keys, 'grant': grant}, **fake)))
        return page

    def switch(self, page):
        return page.locator('[data-push-switch]:visible .push-toggle')

    def wait_checked(self, page, value):
        page.wait_for_function("(v) => document.querySelector('[data-push-switch] .push-toggle')"
                               ".getAttribute('aria-checked') === v && !document.querySelector('.push-toggle[aria-busy]')",
                               arg=value)

    def service_worker(self, page):
        page.wait_for_function(CONTROLLED)
        for _attempt in range(50):
            workers = page.context.service_workers
            if workers:
                return workers[0]
            page.wait_for_timeout(100)
        self.fail('no service worker')

    def sign_in(self, context, user):
        session = SessionStore()
        session['_auth_user_id'] = str(user.pk)
        session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        session['_auth_user_hash'] = user.get_session_auth_hash()
        session.create()
        context.add_cookies([{'name': djsettings.SESSION_COOKIE_NAME, 'value': session.session_key,
                              'url': self.live_server_url}])

    def test_turn_on_and_off_from_the_notifications_page(self):
        page = self.open_with_push(self.alice)
        self.visit(page, reverse('notifications'))
        toggle = self.switch(page)
        self.assertTrue(toggle.is_visible())
        self.assertEqual(toggle.get_attribute('role'), 'switch')
        self.assertEqual(toggle.get_attribute('aria-checked'), 'false')
        self.assertIn('Never the text of posts', page.inner_text('[data-push-switch]'))
        self.assertEqual(page.evaluate('window.__permissionAsks'), 0)  # never asked on page load

        toggle.click()
        self.wait_checked(page, 'true')
        self.check_page(page)
        self.assertEqual(page.evaluate('window.__permissionAsks'), 1)
        # The forum's key, as an uncompressed P-256 point.
        self.assertEqual(page.evaluate('window.__subscribeOptions'), {'userVisibleOnly': True, 'length': 65, 'first': 4})
        self.assertIn('on for this device', page.inner_text('.push-status'))
        device = PushSubscription.objects.get()
        self.assertEqual((device.user_id, device.endpoint, device.p256dh), (self.alice.id, ENDPOINT, self.keys['p256dh']))
        self.assertTrue(device.label.startswith('Chrome on '))

        # Still on after a reload (this browser's subscription is one of alice's devices).
        page.reload()
        self.wait_checked(page, 'true')

        toggle.click()
        self.wait_checked(page, 'false')
        self.check_page(page)
        self.assertIn('off for this device', page.inner_text('.push-status'))
        self.assertFalse(PushSubscription.objects.exists())

    def test_device_settings_on_a_phone_in_dark_mode(self):
        page = self.open_with_push(self.alice, options={'device': 'mobile', 'dark': True})
        settings_url = self.alice.get_user_subscriptions_url()
        self.visit(page, settings_url)
        self.assertEqual(page.locator('#push-settings .push-device').count(), 0)
        self.switch(page).click()
        self.wait_checked(page, 'true')
        violations = test_accessibility.AccessibilityTest.axe(self, page)
        self.assertEqual(violations, [], 'email settings with the push switch on')

        other = PushSubscription.objects.create(user=self.alice, endpoint=ENDPOINT + '-laptop', label='Firefox on Linux',
                                                endpoint_hash=push.endpoint_hash(ENDPOINT + '-laptop'),
                                                p256dh=self.keys['p256dh'], auth=self.keys['auth'])
        self.visit(page, settings_url)
        self.wait_checked(page, 'true')
        devices = page.locator('#push-settings .push-device')
        self.assertEqual(devices.count(), 2)
        this = page.locator('.push-device:has(.push-device-this:not([hidden]))')
        this.wait_for()
        self.assertEqual(this.count(), 1)
        self.assertNotIn('Firefox', this.inner_text())

        # Which notifications: badges on, comments off.
        page.check('#push-settings input[value=badge]')
        page.uncheck('#push-settings input[value=comment]')
        with page.expect_navigation():
            page.click('#push-settings .push-kinds button[type=submit]')
        self.check_page(page)
        self.assertEqual(push.kinds_for(self.alice.__class__.objects.get(id=self.alice.id)),
                         {'answer_mine', 'mention', 'accepted', 'badge', 'edit', 'answer_request'})
        self.assertTrue(page.is_checked('#push-settings input[value=badge]'))
        self.assertFalse(page.is_checked('#push-settings input[value=comment]'))

        # Remove the other device.
        with page.expect_navigation():
            page.locator('.push-device', has_text='Firefox on Linux').get_by_role('button', name='Remove').click()
        self.check_page(page)
        self.assertFalse(PushSubscription.objects.filter(id=other.id).exists())
        self.assertEqual(devices.count(), 1)
        violations = test_accessibility.AccessibilityTest.axe(self, page)
        self.assertEqual(violations, [], 'device settings (mobile, dark)')

    def test_explanations_when_it_cannot_be_used(self):
        # Blocked in the browser: how to allow it again.
        page = self.open_with_push(self.alice, grant=False, permission='denied')
        self.visit(page, reverse('notifications'))
        self.assertTrue(page.is_visible('.push-denied'))
        self.assertTrue(self.switch(page).is_disabled())
        violations = test_accessibility.AccessibilityTest.axe(self, page)
        self.assertEqual(violations, [], 'push blocked')

        # The prompt dismissed: nothing subscribed, can ask again.
        page = self.open_with_push(self.alice, grant=False, answer='default')
        self.visit(page, reverse('notifications'))
        self.switch(page).click()
        page.wait_for_function("() => document.querySelector('.push-status').textContent.includes('not allowed')")
        self.assertEqual(self.switch(page).get_attribute('aria-checked'), 'false')
        self.assertFalse(self.switch(page).is_disabled())
        self.assertFalse(PushSubscription.objects.exists())

        # No Push API.
        page = self.open_with_push(self.alice, noPush=True)
        self.visit(page, reverse('notifications'))
        self.assertTrue(page.is_visible('.push-unsupported'))
        self.assertTrue(self.switch(page).is_disabled())

        # iPhone, in Safari rather than the Home Screen app.
        page = self.open_with_push(self.alice, options={'device': 'mobile', 'user_agent': IPHONE})
        self.visit(page, self.alice.get_user_subscriptions_url())
        self.assertTrue(page.is_visible('.push-ios'))
        self.assertIn('Add to Home Screen', page.inner_text('.push-ios'))
        self.assertTrue(self.switch(page).is_disabled())
        self.assertEqual(page.evaluate('window.__permissionAsks'), 0)
        violations = test_accessibility.AccessibilityTest.axe(self, page)
        self.assertEqual(violations, [], 'iPhone hint (mobile)')

    def test_pushed_answer_shown_and_opened(self):
        page = self.open_with_push(self.alice)
        self.visit(page, reverse('notifications'))
        self.switch(page).click()
        self.wait_checked(page, 'true')

        # bob answers: the server pushes to alice's device.
        answer = self.create_answer(self.bob, self.question)
        [(endpoint, payload)] = self.pushed
        notification = Notification.objects.get(user=self.alice, kind='answer')
        self.assertEqual(endpoint, ENDPOINT)
        self.assertEqual(payload['title'], 'bob answered your question')
        self.assertEqual(payload['body'], self.question.title)
        self.assertEqual(payload['url'], '/notifications/%d/' % notification.id)

        # The service worker shows it, and puts the unread count on the app's icon.
        self.visit(page, '/')
        worker = self.service_worker(page)
        worker.evaluate(BADGES)
        [shown] = worker.evaluate(PUSH, payload)
        self.assertEqual(worker.evaluate('self.__badges'), [1])
        self.assertEqual(shown['title'], 'bob answered your question')
        self.assertEqual(shown['body'], self.question.title)
        self.assertEqual(shown['tag'], 'osqa-question-%d' % self.question.id)
        self.assertEqual(shown['data']['url'], self.url(payload['url']))
        self.assertTrue(shown['icon'].startswith(self.url('/m/default/media/images/icons/icon-192.png')))
        self.assertEqual(page.evaluate('async (url) => (await fetch(url)).status', shown['icon']), 200)

        # Opening it: the forum tab goes to the answer and the notification is read.
        self.assertIsNone(Notification.objects.get(id=notification.id).read_at)
        self.assertTrue(worker.evaluate(CLICK, shown['data']))
        page.wait_for_url(re.compile(r'.*/questions/%d/.*' % self.question.id))
        page.wait_for_load_state('load')
        self.check_page(page)
        self.assertIn(str(answer.id), page.url)
        self.assertIsNotNone(Notification.objects.get(id=notification.id).read_at)

        # Messages it can't read, or links to other sites: a plain notification about the notifications page.
        [shown] = worker.evaluate(PUSH, 'not json')
        self.assertEqual((shown['title'], shown['data']['url']), ('OSQA', self.url('/notifications/')))
        [shown] = worker.evaluate(PUSH, {'title': 'x', 'url': 'https://evil.example.org/phish'})
        self.assertEqual(shown['data']['url'], self.url('/notifications/'))

    def test_the_asker_is_offered_notifications_for_answers(self):
        page = self.open_with_push(self.alice, options={'device': 'mobile'})
        self.visit(page, self.question.get_absolute_url())
        prompt = page.locator('#push-prompt')
        self.assertTrue(prompt.is_visible())
        self.assertIn('Get a notification when someone answers', prompt.inner_text())
        self.assertEqual(page.evaluate('window.__permissionAsks'), 0)  # only when pressed
        violations = test_accessibility.AccessibilityTest.axe(self, page)
        self.assertEqual(violations, [], 'the offer under a new question')
        prompt.locator('.push-toggle').click()
        self.wait_checked(page, 'true')
        self.assertEqual(PushSubscription.objects.get().user_id, self.alice.id)
        # On for this browser: not offered again.
        page.reload()
        self.assertFalse(prompt.is_visible())
        self.check_page(page)

        # "Not now": gone, for 30 days, and the focus goes to the question.
        other = self.open_with_push(self.alice, options={'device': 'mobile'})
        self.visit(other, self.question.get_absolute_url())
        other.click('#push-prompt [data-push-prompt-later]')
        self.assertFalse(other.locator('#push-prompt').is_visible())
        self.assertEqual(other.evaluate('document.activeElement.tagName'), 'H1')
        other.reload()
        self.assertFalse(other.locator('#push-prompt').is_visible())

        # Not for others, nor once the question has an answer.
        bob = self.open_with_push(self.bob)
        self.visit(bob, self.question.get_absolute_url())
        self.assertEqual(bob.locator('#push-prompt').count(), 0)
        self.create_answer(self.bob, self.question)
        fresh = self.open_with_push(self.alice)
        self.visit(fresh, self.question.get_absolute_url())
        self.assertEqual(fresh.locator('#push-prompt').count(), 0)

    def test_another_member_signing_in_stops_push_on_this_browser(self):
        page = self.open_with_push(self.alice)
        self.visit(page, reverse('notifications'))
        self.switch(page).click()
        self.wait_checked(page, 'true')
        self.assertEqual(page.evaluate("localStorage.getItem('osqa-push-user')"), str(self.alice.id))

        self.sign_in(page.context, self.bob)
        self.visit(page, '/')
        page.wait_for_function("() => localStorage.getItem('e2e-fake-push') === null")
        self.assertIsNone(page.evaluate("localStorage.getItem('osqa-push-user')"))
        self.visit(page, reverse('notifications'))
        self.wait_checked(page, 'false')
