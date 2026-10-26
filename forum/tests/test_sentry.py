import json
from unittest import mock

import sentry_sdk
from django.conf import settings as djsettings
from django.test import Client, RequestFactory, override_settings
from sentry_sdk.transport import Transport

from forum.middleware.sentry import SentryUserMiddleware
from forum.utils.sentry import dsn_origin, init_server

from .base import OSQATestCase

DSN = 'https://abc123@o77.ingest.de.sentry.io/42'


class CapturingTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == 'event':
                self.events.append(json.loads(item.payload.get_bytes()))


class BrowserReportingTest(OSQATestCase):
    def test_off_without_a_dsn(self):
        response = self.client.get('/')
        self.assertNotContains(response, 'sentry-config')
        self.assertNotIn('sentry.io', response['Content-Security-Policy'])

    @override_settings(SENTRY_FRONTEND_DSN=DSN, SENTRY_ENVIRONMENT='staging', SENTRY_RELEASE='osqa@abc')
    def test_pages_load_the_sdk_with_the_settings(self):
        alice = self.create_user('alice')
        self.login(alice)
        response = self.client.get('/')
        self.assertContains(response, '<script id="sentry-config" type="application/json">')
        config = json.loads(response.content.decode().split('<script id="sentry-config" type="application/json">')[1]
                            .split('</script>')[0])
        self.assertEqual(config, {'dsn': DSN, 'environment': 'staging', 'release': 'osqa@abc', 'user': str(alice.id),
                                  'maxEvents': 10})
        self.assertContains(response, '/m/default/media/vendor/sentry-10.75.3/sentry.bundle.min.js')
        self.assertContains(response, '/m/default/media/js/osqa.sentry.js')
        csp = response['Content-Security-Policy']
        self.assertIn('https://o77.ingest.de.sentry.io', csp.split('connect-src')[1].split(';')[0])

        # The bundle comes before jQuery, so errors in every other script are caught.
        body = response.content.decode()
        self.assertLess(body.index('sentry.bundle.min.js'), body.index('jquery-3.7.1.min.js'))
        self.assertEqual(self.client.get('/m/default/media/vendor/sentry-10.75.3/sentry.bundle.min.js').status_code, 200)

        alice.is_superuser = True
        alice.save()
        self.assertContains(self.client.get('/admin/'), 'sentry-config')

    def test_dsn_origin(self):
        self.assertEqual(dsn_origin(DSN), 'https://o77.ingest.de.sentry.io')
        self.assertEqual(dsn_origin('https://k@sentry.openforis.org:9000/3'), 'https://sentry.openforis.org:9000')
        self.assertEqual(dsn_origin('not a dsn'), '')


class ServerReportingTest(OSQATestCase):
    def init_sentry(self):
        transport = CapturingTransport()
        init_server(DSN, 'test', transport=transport)  # as settings.py does when SENTRY_DSN is set
        self.addCleanup(sentry_sdk.init)  # back to a disabled client
        return transport

    def test_errors_are_reported_without_personal_data(self):
        transport = self.init_sentry()
        alice = self.create_user('alice')
        client = Client(raise_request_exception=False)
        client.force_login(alice)
        client.cookies['sessionid'] = client.cookies['sessionid'].value
        # SentryUserMiddleware is in MIDDLEWARE whenever sentry-sdk is installed.
        with mock.patch('forum.views.meta.render', side_effect=RuntimeError('template exploded')):
            response = client.post('/about/', {'password': 'hunter2'}, HTTP_USER_AGENT='Test')
        self.assertEqual(response.status_code, 500)

        self.assertEqual(len(transport.events), 1)
        event = transport.events[0]
        self.assertEqual(event['exception']['values'][-1]['value'], 'template exploded')
        self.assertEqual(event['environment'], 'test')
        self.assertEqual(event['user'], {'id': str(alice.id)})
        serialized = json.dumps(event)
        for secret in ('hunter2', client.cookies['sessionid'].value, 'alice@example.com', '127.0.0.1'):
            self.assertNotIn(secret, serialized)

    def fail_pages(self, client, times):
        def explode(*args, **kwargs):
            raise RuntimeError('template exploded')  # a new exception each time, like real failures
        with mock.patch('forum.views.meta.render', side_effect=explode):
            for _ in range(times):
                self.assertEqual(client.get('/about/').status_code, 500)

    @override_settings(SENTRY_MAX_EVENTS_PER_VISITOR=3)
    def test_one_visitor_cannot_flood_sentry(self):
        transport = self.init_sentry()
        alice_client = Client(raise_request_exception=False)
        alice_client.force_login(self.create_user('alice'))
        self.fail_pages(alice_client, 10)
        self.assertEqual(len(transport.events), 3)

        # Other visitors are still reported: another user, and anonymous
        # visitors (counted by IP address).
        bob_client = Client(raise_request_exception=False)
        bob = self.create_user('bob')
        bob_client.force_login(bob)
        self.fail_pages(bob_client, 1)
        self.assertEqual(transport.events[-1]['user'], {'id': str(bob.id)})
        self.fail_pages(Client(raise_request_exception=False, REMOTE_ADDR='198.51.100.7'), 5)
        self.assertEqual(len(transport.events), 7)
        self.assertNotIn('198.51.100.7', json.dumps(transport.events))

    def test_user_id_only(self):
        request = RequestFactory().get('/')
        request.user = self.create_user('alice')
        with mock.patch('sentry_sdk.set_user') as set_user:
            SentryUserMiddleware(lambda r: None)(request)
        set_user.assert_called_once_with({'id': str(request.user.id)})

    @override_settings(SENTRY_DSN=DSN)
    def test_csp_violations_are_sent_as_warnings(self):
        report = {'csp-report': {'violated-directive': 'script-src-elem', 'blocked-uri': 'https://cdn.example/x.js',
                                 'document-uri': 'http://testserver/'}}
        transport = self.init_sentry()
        with self.assertLogs('forum.security', 'WARNING'):
            self.client.post('/csp-report/', json.dumps(report), content_type='application/csp-report')
        event = transport.events[0]
        self.assertEqual(event['level'], 'warning')
        self.assertEqual(event['message'], 'CSP blocked https://cdn.example/x.js (script-src-elem)')
        self.assertEqual(event['fingerprint'], ['csp', 'script-src-elem', 'https://cdn.example/x.js'])


class AdminDsnTest(OSQATestCase):
    """The DSN set under Admin > External Keys, used without SENTRY_DSN."""
    def setUp(self):
        super().setUp()
        from forum.utils import sentry
        self.sentry = sentry
        self.addCleanup(self.reset)

    def reset(self):
        self.sentry._admin_client['dsn'] = ''
        sentry_sdk.init()  # back to a disabled client
        from forum import settings
        for setting in (settings.ERROR_REPORTING_DSN, settings.ERROR_REPORTING_BROWSER):
            setting._temp = None

    def set_dsn(self, dsn, browser=True):
        from forum import settings
        settings.ERROR_REPORTING_DSN.set_value(dsn)
        settings.ERROR_REPORTING_BROWSER.set_value(browser)

    def start(self):
        """As the middleware does on a request, with a transport that keeps the events."""
        transport = CapturingTransport()
        self.sentry.ensure_admin_client(transport=transport)
        return transport

    def test_valid_dsn(self):
        self.assertTrue(self.sentry.valid_dsn(DSN))
        self.assertTrue(self.sentry.valid_dsn('https://k@sentry.openforis.org:9000/3'))
        for value in ('', 'not a dsn', 'https://o77.ingest.sentry.io/42', 'https://abc@o77.ingest.sentry.io/'):
            self.assertFalse(self.sentry.valid_dsn(value), value)

    def test_server_errors_are_reported_after_saving(self):
        transport = self.start()
        self.assertFalse(self.sentry.server_reporting())  # nothing set yet
        self.set_dsn(DSN)
        transport = self.start()
        self.assertTrue(self.sentry.server_reporting())
        self.assertIn('forum.middleware.sentry.SentryUserMiddleware', djsettings.MIDDLEWARE)
        client = Client(raise_request_exception=False)
        with mock.patch('forum.views.meta.render', side_effect=RuntimeError('template exploded')):
            self.assertEqual(client.get('/about/').status_code, 500)
        self.assertEqual(len(transport.events), 1)
        self.assertEqual(transport.events[0]['environment'], 'production')

        # Cleared: the client stops.
        self.set_dsn('')
        self.sentry.ensure_admin_client()
        self.assertFalse(self.sentry.server_reporting())
        self.assertIsNone(sentry_sdk.get_client().dsn)

    def test_browser_reporting_follows_the_admin(self):
        self.set_dsn(DSN)
        response = self.client.get('/')
        self.assertContains(response, 'sentry-config')
        self.assertIn('https://o77.ingest.de.sentry.io', response['Content-Security-Policy'].split('connect-src')[1]
                      .split(';')[0])
        self.set_dsn(DSN, browser=False)
        response = self.client.get('/')
        self.assertNotContains(response, 'sentry-config')
        self.assertNotIn('sentry.io', response['Content-Security-Policy'])

    @override_settings(SENTRY_DSN='https://server@o1.ingest.sentry.io/1', SENTRY_FRONTEND_DSN='https://server@o1.ingest.sentry.io/1')
    def test_the_server_dsn_wins(self):
        self.set_dsn(DSN)
        self.assertEqual(self.sentry.frontend_dsn(), 'https://server@o1.ingest.sentry.io/1')
        self.sentry.ensure_admin_client()
        self.assertEqual(self.sentry._admin_client['dsn'], '')  # the admin's is not started
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(admin)
        section = dict((s['key'], s) for s in self.client.get('/admin/settings/extkeys/').context['sections'])['sentry']
        self.assertEqual(section['state'], 'on')
        self.assertIn('set on the server', section['message'])

    def test_admin_page_status_and_validation(self):
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(admin)
        sections = lambda: dict((s['key'], s) for s in self.client.get('/admin/settings/extkeys/').context['sections'])
        self.assertEqual(sections()['sentry']['state'], 'off')
        self.assertContains(self.client.get('/admin/settings/extkeys/'), 'form="action-sentry-0"')
        self.set_dsn(DSN)
        self.assertEqual(sections()['sentry']['state'], 'on')
        # A value that isn't a DSN is refused.
        from forum.settings.base import Setting
        data = dict((s.name, s.value) for s in Setting.sets['extkeys'] if not isinstance(s.value, bool))
        data.update({'ERROR_REPORTING_DSN': 'my-project-key', 'submit': 'Save'})
        response = self.client.post('/admin/settings/extkeys/', data)
        self.assertContains(response, 'Enter the DSN as Sentry shows it')
        self.assertEqual(self.sentry.admin_config()['dsn'], DSN)

    def test_send_a_test_error(self):
        admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(admin)
        response = self.client.post('/admin/sentry-test/', follow=True)
        self.assertContains(response, 'set up yet: enter its DSN and save first')
        self.set_dsn(DSN)
        transport = self.start()
        response = self.client.post('/admin/sentry-test/', follow=True)
        self.assertContains(response, 'Test event sent')
        self.assertEqual(transport.events[-1]['message'], 'Test event from OSQA (Admin > External Keys)')
        self.assertEqual(self.client.get('/admin/sentry-test/').status_code, 405)
        # Superusers only.
        self.login(self.create_user('moderator', is_staff=True))
        count = len(transport.events)
        self.client.post('/admin/sentry-test/')
        self.assertEqual(len(transport.events), count)
