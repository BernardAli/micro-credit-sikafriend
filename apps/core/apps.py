from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'apps.core'

    def ready(self):
        # Register project-level system checks.
        from . import checks  # noqa: F401
