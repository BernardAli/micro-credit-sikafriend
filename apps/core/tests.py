from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings


class DatabaseEngineChecksTests(SimpleTestCase):
    def test_check_passes_for_mysql_engine(self):
        with override_settings(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.mysql",
                    "NAME": "mirco_credit_db",
                }
            }
        ):
            errors = run_checks()

        self.assertFalse([error for error in errors if error.id == "core.E001"])

    def test_check_fails_for_sqlite_engine(self):
        with override_settings(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": "db.sqlite3",
                }
            }
        ):
            errors = run_checks()

        self.assertTrue(any(error.id == "core.E001" for error in errors))
