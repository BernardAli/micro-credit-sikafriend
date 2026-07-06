from django.conf import settings
from django.core.checks import Error, register

SUPPORTED_ENGINES = {
    "django.db.backends.sqlite3",
    "django.db.backends.postgresql",
    "django.db.backends.mysql",
}


@register()
def database_engine_check(app_configs, **kwargs):
    default_db = settings.DATABASES.get("default", {})
    engine = default_db.get("ENGINE", "")

    if engine not in SUPPORTED_ENGINES:
        return [
            Error(
                f"Unsupported database engine: '{engine}'.",
                hint=f"Use one of: {', '.join(sorted(SUPPORTED_ENGINES))}",
                id="core.E001",
            )
        ]

    return []
