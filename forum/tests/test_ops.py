"""Operations: /metrics, /readyz, request ids, JSON logs, cron last runs, backups."""
import io
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, override_settings

from forum import settings
from forum.models import Answer, KeyValue, Question, User
from forum.utils import backup, cron, logs, metrics

from .base import OSQATestCase

TOKEN = 'test-metrics-token-0123456789'
SAMPLE = re.compile(r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{([a-zA-Z_][a-zA-Z0-9_]*="([^"\\]|\\.)*",?)*\})? '
                    r'(-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?|\+Inf|-Inf|NaN)$')


class MetricsTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        # Requests of earlier tests may still be buffered in this process.
        metrics.flush()
        from django.core.cache import cache
        cache.clear()

    def scrape(self, token=TOKEN, **extra):
        headers = {'HTTP_AUTHORIZATION': 'Bearer %s' % token} if token else {}
        headers.update(extra)
        return self.client.get('/metrics', **headers)

    def samples(self, text):
        values = {}
        for line in text.splitlines():
            if line and not line.startswith('#'):
                name, _, value = line.rpartition(' ')
                values[name] = value
        return values

    def test_not_found_without_token_setting(self):
        with override_settings(METRICS_TOKEN=''):
            response = self.scrape()
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b'osqa_', response.content)

    @override_settings(METRICS_TOKEN=TOKEN)
    def test_token_required(self):
        response = self.scrape(token=None)
        self.assertEqual(response.status_code, 401)
        self.assertIn('Bearer', response['WWW-Authenticate'])
        self.assertEqual(self.client.get('/metrics', HTTP_AUTHORIZATION='Basic %s' % TOKEN).status_code, 401)
        with self.assertLogs('forum.security', 'WARNING') as logged:
            response = self.scrape(token='wrong-token')
        self.assertEqual(response.status_code, 403)
        self.assertIn('event=metrics_token_refused', logged.output[0])
        self.assertNotIn('wrong-token', logged.output[0])
        self.assertNotIn(b'osqa_', response.content)

    @override_settings(METRICS_TOKEN=TOKEN)
    def test_exposition(self):
        user = self.create_user('alice')
        question = Question(author=user, title='How do I export data?', tagnames='export', body='Long enough body.')
        question.save()
        Question(author=user, title='A question nobody answered', tagnames='export', body='Long enough body.').save()
        Answer(author=user, parent=question, body='An answer long enough.').save()
        self.client.get('/')
        self.client.get('/questions/')
        self.client.get('/no-such-page-at-all/')

        # Answered on any host name (Prometheus scrapes pod addresses), not cached.
        response = self.scrape(HTTP_HOST='10.1.2.3:8000')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain; version=0.0.4; charset=utf-8')
        self.assertEqual(response['Cache-Control'], 'no-store')
        text = response.content.decode()
        for line in text.splitlines():
            if line.startswith('#'):
                self.assertRegex(line, r'^# (HELP|TYPE) [a-zA-Z_:][a-zA-Z0-9_:]* ')
            else:
                self.assertRegex(line, SAMPLE)
        self.assertIn('# TYPE osqa_http_requests_total counter', text)
        self.assertIn('# TYPE osqa_http_request_duration_seconds histogram', text)

        values = self.samples(text)
        self.assertEqual(values['osqa_posts{type="question"}'], '2')
        self.assertEqual(values['osqa_posts{type="answer"}'], '1')
        self.assertEqual(values['osqa_questions_unanswered'], '1')
        self.assertEqual(values['osqa_users'], '1')
        self.assertEqual(values['osqa_moderation_pending{kind="flag"}'], '0')
        self.assertEqual(values['osqa_database_up'], '1')
        self.assertEqual(values['osqa_emails_failed_total'], '0')
        self.assertEqual(values['osqa_http_requests_total{method="GET",status="2xx",view="index"}'], '1')
        self.assertEqual(values['osqa_http_requests_total{method="GET",status="4xx",view="unmatched"}'], '1')
        # Histogram: cumulative buckets, +Inf equals the count.
        self.assertEqual(values['osqa_http_request_duration_seconds_bucket{le="+Inf",view="index"}'],
                         values['osqa_http_request_duration_seconds_count{view="index"}'])
        self.assertIn('osqa_http_request_duration_seconds_sum{view="index"}', values)
        # Probes and the scrape itself are not counted.
        self.assertNotIn('view="metrics"', text)

    @override_settings(METRICS_TOKEN=TOKEN)
    def test_email_and_security_counters(self):
        from forum.utils import mail, security_log
        alice = self.create_user('alice')
        settings.EMAIL_HOST.set_value('smtp.example.org')
        self.addCleanup(setattr, settings.EMAIL_HOST, '_temp', None)
        connection = mock.Mock()
        connection.sendmail.side_effect = [None, Exception('mailbox full')]
        with mock.patch.object(mail, 'create_connection', return_value=connection), self.assertLogs(level='ERROR'):
            errors = mail.create_and_send_mail_messages([(alice, 'Hi', '<p>Hi</p>', 'Hi', {})] * 2)
        self.assertEqual(len(errors), 1)
        with self.assertLogs('forum.security'):
            security_log.event('login_failed', username='alice')
            security_log.event('login_failed', username='alice')
            security_log.event('login_paused', username='alice')
        values = self.samples(self.scrape().content.decode())
        self.assertEqual(values['osqa_emails_sent_total'], '1')
        self.assertEqual(values['osqa_emails_failed_total'], '1')
        self.assertEqual(values['osqa_security_events_total{event="login_failed"}'], '2')
        self.assertEqual(values['osqa_security_events_total{event="login_paused"}'], '1')

    def test_counters_survive_a_missing_cache(self):
        with mock.patch.object(metrics, 'cache') as broken:
            broken.incr.side_effect = Exception('memcached down')
            metrics.count('osqa_emails_sent_total')  # must not raise


class ReadyTest(OSQATestCase):
    def test_ready(self):
        response = self.client.get('/readyz', HTTP_HOST='osqa-web-5d8f7:8000')
        self.assertEqual((response.status_code, response.content), (200, b'ok\n'))

    def test_probes_answer_with_a_trailing_slash(self):
        for path in ('/healthz/', '/readyz/'):
            response = self.client.get(path, HTTP_HOST='172.31.41.153')  # load balancer: instance IP as host
            self.assertEqual((response.status_code, response.content), (200, b'ok\n'), path)

    def test_database_down(self):
        with mock.patch('forum.views.ops.connection') as connection, self.assertLogs('forum.views.ops', 'WARNING'):
            connection.cursor.side_effect = Exception('Access denied for user osqa@10.0.0.3')
            response = self.client.get('/readyz')
        self.assertEqual((response.status_code, response.content), (503, b'unavailable\n'))

    def test_cache_down(self):
        with mock.patch('forum.views.ops.cache') as cache, self.assertLogs('forum.views.ops', 'WARNING'):
            cache.set.side_effect = Exception('connection refused')
            response = self.client.get('/readyz')
        self.assertEqual((response.status_code, response.content), (503, b'unavailable\n'))
        with mock.patch('forum.views.ops.cache') as cache:
            cache.get.return_value = None  # writes are lost
            self.assertEqual(self.client.get('/readyz').status_code, 503)


class RequestIdTest(OSQATestCase):
    def test_generated(self):
        first, second = self.client.get('/'), self.client.get('/')
        self.assertRegex(first['X-Request-ID'], r'^[0-9a-f]{32}$')
        self.assertNotEqual(first['X-Request-ID'], second['X-Request-ID'])
        self.assertRegex(self.client.get('/healthz')['X-Request-ID'], r'^[0-9a-f]{32}$')

    def test_proxy_id_honoured_when_well_formed(self):
        self.assertEqual(self.client.get('/', HTTP_X_REQUEST_ID='edge-4f2a.91')['X-Request-ID'], 'edge-4f2a.91')
        for bad in ('has spaces', 'x' * 200, '<script>', 'a\nb'):
            self.assertRegex(self.client.get('/', HTTP_X_REQUEST_ID=bad)['X-Request-ID'], r'^[0-9a-f]{32}$')

    @override_settings(METRICS_TOKEN=TOKEN)
    def test_logs_carry_request_and_user_id(self):
        records = []
        handler = logging.Handler()
        handler.addFilter(logs.RequestContextFilter())
        handler.emit = records.append
        logger = logging.getLogger('forum.security')
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.INFO)
        alice = self.create_user('alice')
        self.login(alice)
        self.client.get('/metrics', HTTP_AUTHORIZATION='Bearer nope', HTTP_X_REQUEST_ID='req-123')
        self.assertEqual(records[-1].request_id, 'req-123')
        # The scrape is answered before the session is read: no user.
        self.assertIsNone(records[-1].user_id)
        self.client.get('/no-such-page-at-all/')  # outside the request: no ids left behind
        self.assertIsNone(logs.current_request_id())

    def test_sentry_events_get_the_request_id(self):
        from forum.utils.sentry import before_send
        request = RequestFactory().get('/')
        tokens = logs.bind_request(request, 'abc123')
        try:
            event = before_send({'tags': {'x': '1'}}, None)
        finally:
            logs.unbind_request(tokens)
        self.assertEqual(event['tags'], {'x': '1', 'request_id': 'abc123'})
        self.assertNotIn('tags', before_send({}, None))


class JSONLogTest(OSQATestCase):
    def format(self, message, *args, logger='forum.views', exc=None):
        record = logging.LogRecord(logger, logging.ERROR, __file__, 1, message, args, exc)
        logs.RequestContextFilter().filter(record)
        return json.loads(logs.JSONFormatter().format(record))

    def test_fields(self):
        request = RequestFactory().get('/')
        request.user = self.create_user('alice')
        tokens = logs.bind_request(request, 'rid-1')
        try:
            entry = self.format('Something %s', 'happened')
        finally:
            logs.unbind_request(tokens)
        self.assertEqual(set(entry), {'time', 'level', 'logger', 'message', 'request_id', 'user_id'})
        self.assertEqual((entry['level'], entry['logger'], entry['message']), ('ERROR', 'forum.views', 'Something happened'))
        self.assertEqual((entry['request_id'], entry['user_id']), ('rid-1', request.user.id))
        self.assertRegex(entry['time'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')

    def test_secrets_masked(self):
        message = ('Login for bob@example.org from 203.0.113.9 / 2001:db8::1 failed: password=hunter2 '
                   'token: abcdef Authorization: Bearer s3cr3t-value sessionid=xyz at 12:30:45 v1.2.3')
        try:
            raise ValueError('api_key=SECRETKEY for carol@example.com')
        except ValueError:
            import sys
            entry = self.format(message, exc=sys.exc_info())
        text = json.dumps(entry)
        for secret in ('bob@example.org', '203.0.113.9', '2001:db8::1', 'hunter2', 'abcdef', 's3cr3t-value',
                       'xyz', 'SECRETKEY', 'carol@example.com'):
            self.assertNotIn(secret, text)
        self.assertIn('12:30:45 v1.2.3', entry['message'])  # times and versions are not addresses
        self.assertIn('ValueError', entry['exception'])

    def test_security_log_keeps_its_fields(self):
        entry = self.format('event=login_failed ip=203.0.113.9 user=anonymous', logger='forum.security')
        self.assertIn('ip=203.0.113.9', entry['message'])

    def test_json_logging_config(self):
        import logging.config
        config = logs.json_logging('WARNING')
        logging.config.dictConfig(dict(config, disable_existing_loggers=False, loggers={}, root={'handlers': []}))
        self.assertEqual(config['root']['level'], 'WARNING')
        self.assertEqual(config['handlers']['stdout']['formatter'], 'json')
        self.assertEqual(config['loggers']['forum.security']['level'], 'INFO')


class CronLastRunTest(OSQATestCase):
    def run_command(self, *args, **options):
        call_command(*args, stdout=io.StringIO(), **options)

    def test_success_recorded(self):
        self.run_command('remind_unaccepted')
        run = KeyValue.objects.get(key='ops.cron.remind_unaccepted').value
        self.assertIn('success', run)
        self.assertNotIn('failure', run)
        self.assertGreaterEqual(run['duration'], 0)
        self.assertIn('remind_unaccepted', cron.last_runs())

    def test_clearsessions_recorded(self):
        self.run_command('clearsessions')
        self.assertIn('success', KeyValue.objects.get(key='ops.cron.clearsessions').value)

    def test_dry_run_and_untracked_not_recorded(self):
        self.run_command('remind_unaccepted', dry_run=True)
        self.assertFalse(KeyValue.objects.filter(key='ops.cron.remind_unaccepted').exists())
        with override_settings(CRON_COMMANDS=['send_email_alerts']):
            self.run_command('remind_unaccepted')
        self.assertFalse(KeyValue.objects.filter(key='ops.cron.remind_unaccepted').exists())

    def test_failure_recorded(self):
        from forum.management.commands.cleanup_inactive_users import Command
        with mock.patch.object(Command, 'handle', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.run_command('cleanup_inactive_users')
        run = KeyValue.objects.get(key='ops.cron.cleanup_inactive_users').value
        self.assertIn('failure', run)
        self.assertNotIn('success', run)

    @override_settings(METRICS_TOKEN=TOKEN)
    def test_exposed(self):
        self.run_command('remind_unaccepted')
        text = self.client.get('/metrics', HTTP_AUTHORIZATION='Bearer ' + TOKEN).content.decode()
        self.assertRegex(text, r'osqa_cron_last_success_timestamp_seconds\{command="remind_unaccepted"\} \d{10}')


class BackupTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.backups = os.path.join(self.dir, 'backups')
        self.uploads = os.path.join(self.dir, 'upfiles')
        os.makedirs(os.path.join(self.uploads, 'sub'))
        with open(os.path.join(self.uploads, 'sub', 'picture.png'), 'wb') as f:
            f.write(b'\x89PNG fake image')
        # flush recreates content types with new ids; don't leave them cached.
        self.addCleanup(ContentType.objects.clear_cache)

    def run_command(self, *args, **options):
        out = io.StringIO()
        call_command(*args, stdout=out, **options)
        return out.getvalue()

    def test_round_trip(self):
        alice = self.create_user('alice')
        question = Question(author=alice, title='Backed up question', tagnames='backup', body='A body long enough.')
        question.save()
        Answer(author=alice, parent=question, body='A backed up answer.').save()
        settings.APP_SHORT_NAME.set_value('Backed Up Forum')
        self.addCleanup(setattr, settings.APP_SHORT_NAME, '_temp', None)

        out = self.run_command('backup_site', output_dir=self.backups, uploads_dir=self.uploads)
        [name] = os.listdir(self.backups)
        archive = os.path.join(self.backups, name)
        self.assertRegex(name, r'^osqa-backup-\d{8}-\d{6}\.tar\.gz$')
        self.assertIn(archive, out)
        if os.name == 'posix':  # Windows has no owner-only permission bits
            self.assertEqual(os.stat(archive).st_mode & 0o777, 0o600)
        self.assertIn('backup_site', cron.last_runs())

        # Wipe: content, a setting and the uploaded file.
        Question.objects.all().delete()
        User.objects.all().delete()
        settings.APP_SHORT_NAME.set_value('Something else')
        shutil.rmtree(self.uploads)

        with self.assertRaises(CommandError):
            self.run_command('restore_site', archive, uploads_dir=self.uploads)
        out = self.run_command('restore_site', archive, dry_run=True, uploads_dir=self.uploads)
        self.assertIn('1 users', out)
        self.assertIn('Dry run', out)
        self.assertFalse(User.objects.exists())

        out = self.run_command('restore_site', archive, confirm=True, uploads_dir=self.uploads,
                               backup_dir=self.backups)
        self.assertIn('Restored', out)
        settings.APP_SHORT_NAME._temp = None
        self.assertEqual(User.objects.get().username, 'alice')
        restored = Question.objects.get()
        self.assertEqual(restored.title, 'Backed up question')
        self.assertEqual(restored.answers.count(), 1)
        self.assertEqual(str(settings.APP_SHORT_NAME), 'Backed Up Forum')
        with open(os.path.join(self.uploads, 'sub', 'picture.png'), 'rb') as f:
            self.assertEqual(f.read(), b'\x89PNG fake image')
        # The state before the restore was saved first.
        self.assertEqual(len([n for n in os.listdir(self.backups) if n.startswith('osqa-pre-restore-')]), 1)
        # The restored site works.
        self.assertEqual(self.client.get('/questions/%d/' % restored.id, follow=True).status_code, 200)

    def test_retention(self):
        for _ in range(4):
            self.run_command('backup_site', output_dir=self.backups, uploads_dir=self.uploads, keep=2,
                             no_uploads=True)
        names = sorted(os.listdir(self.backups))
        self.assertEqual(len(names), 2)
        self.assertTrue(all(backup.NAME_RE.match(n) for n in names))
        with tarfile.open(os.path.join(self.backups, names[0])) as tar:
            self.assertFalse(any(n.startswith('upfiles') for n in tar.getnames()))

    def test_rejects_unsafe_archives(self):
        evil = os.path.join(self.dir, 'evil.tar.gz')
        with tarfile.open(evil, 'w:gz') as tar:
            for name, data in (('manifest.json', b'{"format": 1}'), ('data.json', b'[]'), ('../escape.txt', b'x')):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(CommandError):
            self.run_command('restore_site', evil, dry_run=True)
        with self.assertRaises(CommandError):
            self.run_command('restore_site', os.path.join(self.dir, 'missing.tar.gz'), dry_run=True)
