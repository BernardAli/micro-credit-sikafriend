from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class LegacyImportConfigurationTests(SimpleTestCase):
    def test_command_requires_separate_legacy_database(self):
        with self.assertRaisesMessage(CommandError, "Set LEGACY_DB_NAME"):
            call_command("import_legacy_data", dry_run=True)
