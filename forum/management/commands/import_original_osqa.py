"""Copy the data of an original OSQA forum (Django 1.6) into this site's freshly migrated database.

The old forum's mysqldump is loaded into its own database on the same MySQL/MariaDB server
(docs/upgrading-from-original-osqa.md); every table is then copied with INSERT ... SELECT on
named columns, so the server converts the character set (latin1 to utf8mb4) and column order
and new columns don't matter. Columns that only exist in the new schema get the model default.
Python 2 pickled values are copied as they are: PickledObjectField reads them.
"""
import importlib
import os
import re

from django.apps import apps
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import NOT_PROVIDED

# Recreated by migrate, not used by OSQA, or removed in this version.
SKIP_TABLES = {
    'django_content_type', 'auth_permission', 'auth_group_permissions', 'auth_user_user_permissions',
    'django_admin_log', 'django_session', 'django_site', 'south_migrationhistory',
    'forum_openidassociation', 'forum_openidnonce', 'forum_mysqlftsindex',
}
# Settings are saved with their default value the first time they are read (some while the
# app loads), so a freshly migrated site may already have a few: the old ones replace them.
SETTINGS_TABLE = 'forum_keyvalue'


# Settings holding a folder of the old server (module settings only when the module is installed).
FOLDER_SETTINGS = (('forum.settings', 'UPFILES_FOLDER'), ('forum_modules.exporter.settings', 'EXPORTER_BACKUP_STORAGE'))


def reset_old_server_settings():
    """Imported settings that only fit the old server: maintenance mode (the final dump is taken
    in it) and folders that don't exist here go back to their defaults. Returns the names reset."""
    from forum import settings

    reset = []
    if settings.MAINTAINANCE_MODE.value is not None:
        settings.MAINTAINANCE_MODE.set_value(None)
        reset.append('MAINTAINANCE_MODE')
    for module, name in FOLDER_SETTINGS:
        try:
            setting = getattr(importlib.import_module(module), name)
        except (ImportError, AttributeError):
            continue
        if not os.path.isdir(str(setting.value)):
            setting.set_value(setting.default)
            reset.append(name)
    return reset


def model_fields_by_column():
    """(db_table, column) -> model field, for every model including M2M tables."""
    fields = {}
    for model in apps.get_models(include_auto_created=True):
        for field in model._meta.local_fields:
            fields[(model._meta.db_table, field.column)] = field
    return fields


def copy_plan(table, old_columns, new_columns, fields):
    """Columns to copy and (column, default) pairs for the new NOT NULL columns the old table lacks.

    old_columns: names; new_columns: {name: nullable} in table order.
    """
    common = [column for column in new_columns if column in old_columns]
    defaults = []
    for column, nullable in new_columns.items():
        if column in old_columns or nullable:
            continue
        field = fields.get((table, column))
        if field is None or field.default is NOT_PROVIDED:
            raise CommandError("No default for the new column %s.%s: can't copy %s." % (table, column, table))
        defaults.append((column, field.get_default()))
    return common, defaults


class Command(BaseCommand):
    help = ("Copies an original OSQA forum (Python 2 / Django 1.6), loaded from its mysqldump into another "
            "database on the same MySQL/MariaDB server, into this site's freshly migrated, empty database. "
            "See docs/upgrading-from-original-osqa.md.")

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='source', required=True,
                            help="Name of the database holding the old forum (e.g. osqa_old).")

    def handle(self, source, **options):
        if connection.vendor != 'mysql':
            raise CommandError("This command copies between databases of one MySQL/MariaDB server; "
                               "this site uses %s." % connection.vendor)
        if not re.fullmatch(r'[A-Za-z0-9_$]+', source):
            raise CommandError("Invalid database name: %s" % source)
        target = connection.settings_dict['NAME']
        if source == target:
            raise CommandError("--from must name the old forum's database, not this site's.")

        with connection.cursor() as cursor:
            old_tables = self._tables(cursor, source)
            if 'forum_node' not in old_tables:
                raise CommandError("%s doesn't look like an OSQA database (no forum_node table)." % source)
            new_tables = self._tables(cursor, target)
            tables = sorted(t for t in old_tables if t in new_tables and t not in SKIP_TABLES)
            not_empty = [t for t in tables if t != SETTINGS_TABLE and self._count(cursor, target, t)]
            if not_empty:
                raise CommandError("This site's database already has data (%s). Drop and recreate it, run "
                                   "migrate, and import before anybody signs up or posts." % ', '.join(not_empty))

            fields = model_fields_by_column()
            with transaction.atomic():
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                try:
                    cursor.execute("DELETE FROM `%s`.`%s`" % (target, SETTINGS_TABLE))
                    for table in tables:
                        self._copy(cursor, source, target, table, fields)
                finally:
                    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        # Data migration 0007 ran on the empty database: apply it to the imported settings.
        importlib.import_module('forum.migrations.0007_remove_dead_sidebar_defaults').hide_old_default_blocks(
            apps, None)
        cache.clear()
        reset = reset_old_server_settings()
        if reset:
            self.stdout.write("Reset to this server's defaults: %s." % ', '.join(reset))
        self.stdout.write(self.style.SUCCESS("Imported %d tables from %s." % (len(tables), source)))
        self.stdout.write("Next: manage.py rebuild_search_index, and copy the old forum/upfiles/.")

    def _copy(self, cursor, source, target, table, fields):
        old_columns = self._columns(cursor, source, table)
        common, defaults = copy_plan(table, old_columns, self._columns(cursor, target, table), fields)
        target_columns = ', '.join('`%s`' % c for c in common + [c for c, _ in defaults])
        source_columns = ', '.join(['`%s`' % c for c in common] + ['%s'] * len(defaults))
        cursor.execute("INSERT INTO `%s`.`%s` (%s) SELECT %s FROM `%s`.`%s`" % (
            target, table, target_columns, source_columns, source, table), [value for _, value in defaults])

        before, after = self._count(cursor, source, table), self._count(cursor, target, table)
        if before != after:
            raise CommandError("%s: %d rows in %s but %d copied; nothing was imported." % (
                table, before, source, after))
        added = ' (new columns: %s)' % ', '.join('%s=%r' % d for d in defaults) if defaults else ''
        self.stdout.write("%-32s %7d rows%s" % (table, after, added))

    @staticmethod
    def _tables(cursor, schema):
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", [schema])
        return {row[0] for row in cursor.fetchall()}

    @staticmethod
    def _columns(cursor, schema, table):
        cursor.execute("SELECT column_name, is_nullable FROM information_schema.columns "
                       "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", [schema, table])
        return {name: nullable == 'YES' for name, nullable in cursor.fetchall()}

    @staticmethod
    def _count(cursor, schema, table):
        cursor.execute("SELECT COUNT(*) FROM `%s`.`%s`" % (schema, table))
        return cursor.fetchone()[0]
