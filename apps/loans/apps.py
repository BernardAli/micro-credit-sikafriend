from django.apps import AppConfig

class LoansConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.loans"

    def ready(self):
        from . import signals  # noqa