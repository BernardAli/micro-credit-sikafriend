from datetime import datetime, timezone
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import sqlite3

from django.contrib.auth.models import User
from django.db import close_old_connections, connections
from django.test import SimpleTestCase, TransactionTestCase, skipUnlessDBFeature
from apps.core.db_backups import _sql_literal, export_database_backup


class BackupLiteralTests(SimpleTestCase):
    def test_sqlite_roundtrip_preserves_quotes_backslashes_and_timestamp_precision(self):
        database = sqlite3.connect(':memory:')
        try:
            values = ["Customer's \\ document", datetime(2026, 10, 12, 14, 15, 16, 123456, tzinfo=timezone.utc)]
            for value in values:
                result = database.execute('SELECT ' + _sql_literal(value, vendor='sqlite')).fetchone()[0]
                expected = value if isinstance(value, str) else '2026-10-12 14:15:16.123456'
                self.assertEqual(result, expected)
        finally:
            database.close()


@skipUnlessDBFeature('has_select_for_update')
class BackupSnapshotTests(TransactionTestCase):
    def test_concurrent_updates_do_not_change_the_backup_read_snapshot(self):
        user = User.objects.create_user('backup-snapshot-user', first_name='Before')
        observed = []
        def exporter(*args):
            observed.append(User.objects.get(pk=user.pk).first_name)
            def update():
                close_old_connections()
                try:
                    User.objects.filter(pk=user.pk).update(first_name='After')
                finally:
                    connections['default'].close()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(update).result(timeout=10)
            observed.append(User.objects.get(pk=user.pk).first_name)
            return {}, b'snapshot'
        with patch('apps.core.db_backups._export_database_backup', side_effect=exporter):
            export_database_backup('default', 'json')
        self.assertEqual(observed, ['Before', 'Before'])
        self.assertEqual(User.objects.get(pk=user.pk).first_name, 'After')
