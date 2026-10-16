"""Isolated test configuration, including uploads that never touch customer media."""
import base64
import hashlib
from .settings import *  # noqa: F403

DEBUG = False
MFA_ENABLED = False
STAFF_MFA_REQUIRED = False
MFA_ENCRYPTION_KEYS = [base64.urlsafe_b64encode(hashlib.sha256(b"unit-test-mfa-only").digest()).decode()]
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "debug_toolbar"]
MIDDLEWARE = [middleware for middleware in MIDDLEWARE if "debug_toolbar" not in middleware]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "private": {"BACKEND": "django.core.files.storage.InMemoryStorage", "OPTIONS": {"base_url": "/private-media/"}},
}
