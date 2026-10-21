"""When each scheduled management command last ran.

The commands run from cron are not edited for this: install() (called from
ForumConfig.ready()) wraps BaseCommand.execute once, and a command whose name
is in tracked_commands() gets its outcome recorded in a KeyValue row
('ops.cron.<name>': unix times of the last success and failure, and the last
duration). Both `python manage.py <name>` and call_command() pass through
execute(). Runs with --dry-run are not recorded.

Add a command to the list with CRON_COMMANDS in settings_local.py (it
replaces the default list), or set `record_last_run = True` on its class.
/metrics exposes the times as osqa_cron_last_success_timestamp_seconds etc.
"""
import logging
import time

from django.conf import settings as djsettings

log = logging.getLogger(__name__)

DEFAULT_COMMANDS = (
    'send_email_alerts', 'remind_unaccepted', 'cleanup_inactive_users', 'clearsessions',
    'build_knowledge_index', 'suggest_answers', 'backup_site', 'rebuild_search_index', 'refresh_tag_expertise',
)
KEY_PREFIX = 'ops.cron.'

_installed = False


def tracked_commands():
    return set(getattr(djsettings, 'CRON_COMMANDS', DEFAULT_COMMANDS))


def command_name(command):
    return type(command).__module__.rsplit('.', 1)[-1]


def record(name, success, started, finished=None):
    """Stores the outcome of one run. Never raises (the command's own result counts)."""
    finished = finished or time.time()
    try:
        from forum.models import KeyValue
        kv = KeyValue.objects.filter(key=KEY_PREFIX + name).first()
        value = dict(kv.value) if kv is not None and isinstance(kv.value, dict) else {}
        value['success' if success else 'failure'] = finished
        value['duration'] = round(finished - started, 3)
        if kv is None:
            kv = KeyValue(key=KEY_PREFIX + name)
        kv.value = value
        kv.save()
    except Exception:
        log.warning('Could not record the last run of %s', name, exc_info=True)


def last_runs():
    """{command: {'success': ts, 'failure': ts, 'duration': s}} for recorded commands."""
    from forum.models import KeyValue
    runs = {}
    for kv in KeyValue.objects.filter(key__startswith=KEY_PREFIX):
        if isinstance(kv.value, dict):
            runs[kv.key[len(KEY_PREFIX):]] = kv.value
    return runs


def install():
    global _installed
    if _installed:
        return
    from django.core.management.base import BaseCommand
    original = BaseCommand.execute

    def execute(self, *args, **options):
        name = command_name(self)
        if not (getattr(self, 'record_last_run', False) or name in tracked_commands()) or options.get('dry_run'):
            return original(self, *args, **options)
        started = time.time()
        try:
            result = original(self, *args, **options)
        except BaseException:
            record(name, False, started)
            raise
        record(name, True, started)
        return result

    execute.__wrapped__ = original
    BaseCommand.execute = execute
    _installed = True
