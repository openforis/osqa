from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from forum.management.commands.import_original_osqa import copy_plan, model_fields_by_column


class CopyPlanTest(SimpleTestCase):
    """The column mapping of `manage.py import_original_osqa` (the copy itself needs MySQL)."""

    def test_copies_common_columns_in_new_order_and_fills_new_ones_with_model_defaults(self):
        old = ['id', 'name', 'used_count', 'created_at', 'created_by_id']
        new = {'id': False, 'name': False, 'created_at': False, 'used_count': False,
               'created_by_id': False, 'description': False}
        common, defaults = copy_plan('forum_tag', old, new, model_fields_by_column())
        self.assertEqual(common, ['id', 'name', 'created_at', 'used_count', 'created_by_id'])
        self.assertEqual(defaults, [('description', '')])

    def test_new_nullable_columns_are_left_null(self):
        old = ['id', 'user_id']
        new = {'id': False, 'user_id': False, 'last_summary_at': True}
        self.assertEqual(copy_plan('forum_subscriptionsettings', old, new, model_fields_by_column()),
                         (['id', 'user_id'], []))

    def test_refuses_a_new_not_null_column_without_default(self):
        with self.assertRaises(CommandError):
            copy_plan('forum_tag', ['id'], {'id': False, 'name': False}, model_fields_by_column())

    def test_refuses_databases_other_than_mysql(self):
        with self.assertRaisesMessage(CommandError, 'MySQL/MariaDB'):
            call_command('import_original_osqa', '--from', 'osqa_old')
