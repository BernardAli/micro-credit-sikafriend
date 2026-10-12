"""Isolated test configuration, including uploads that never touch customer media."""
from .settings import *  # noqa: F403

DEBUG = False
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "debug_toolbar"]
MIDDLEWARE = [middleware for middleware in MIDDLEWARE if "debug_toolbar" not in middleware]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "private": {"BACKEND": "django.core.files.storage.InMemoryStorage", "OPTIONS": {"base_url": "/private-media/"}},
}
