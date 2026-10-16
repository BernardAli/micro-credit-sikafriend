from django.conf import settings
from django.core.checks import Error, Tags, register
from cryptography.fernet import Fernet
from ipaddress import ip_network

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


@register(Tags.security)
def proxy_configuration_check(app_configs, **kwargs):
    try:
        for value in settings.TRUSTED_PROXY_CIDRS:
            network = ip_network(value)
            if network.prefixlen == 0:
                raise ValueError("Do not trust every address as a proxy.")
    except ValueError:
        return [Error("Invalid or unrestricted TRUSTED_PROXY_CIDRS.", id="core.E002")]
    return []


@register(Tags.security, deploy=True)
def authentication_deployment_check(app_configs, **kwargs):
    errors = []
    if not settings.MFA_ENABLED or not settings.STAFF_MFA_REQUIRED:
        errors.append(Error("Production staff MFA must be enabled and required.", id="core.E003"))
    try:
        if not settings.MFA_ENCRYPTION_KEYS:
            raise ValueError()
        for value in settings.MFA_ENCRYPTION_KEYS:
            Fernet(value.encode())
    except (ValueError, TypeError):
        errors.append(Error("Configure valid MFA_ENCRYPTION_KEYS separately from the Django secret.", id="core.E004"))
    if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
        errors.append(Error("Production financial workflows require a database with row locking, such as MySQL.", id="core.E005"))
    if settings.ALLOW_INSECURE_PAYMENT_WEBHOOKS or settings.ALLOW_INSECURE_USSD_CALLBACKS:
        errors.append(Error("Insecure callback options must be disabled in production.", id="core.E006"))
    return errors
