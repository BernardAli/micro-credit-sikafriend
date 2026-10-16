import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


DEBUG = _env_bool("DJANGO_DEBUG", True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-secret-key-change-in-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "0.0.0.0"])
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

# Production transport security. These remain disabled for local HTTP development
# and default to enabled whenever DJANGO_DEBUG is false.
SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = _env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = _env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD", not DEBUG)
if _env_bool("DJANGO_TRUST_PROXY_HTTPS", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    "apps.accounts",
    "apps.loans",
    "apps.notifications",
    "apps.core",
    "apps.communication",
    "apps.company",
    "apps.borrower_portal",
    "apps.accounting",
    "apps.assets",
]

if DEBUG:
    INSTALLED_APPS.append("debug_toolbar")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.company.request_cache.CompanyRequestCacheMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.security_middleware.AccountSecurityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    MIDDLEWARE.insert(2, "debug_toolbar.middleware.DebugToolbarMiddleware")

INTERNAL_IPS = _env_list("DJANGO_INTERNAL_IPS", ["127.0.0.1"])

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.company.context_processors.company_profile",
                "apps.core.roles.user_role_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").strip().lower()
if DB_ENGINE == "mysql":
    required_mysql_settings = {
        "DB_NAME": os.getenv("DB_NAME", "").strip(),
        "DB_USER": os.getenv("DB_USER", "").strip(),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "DB_HOST": os.getenv("DB_HOST", "").strip(),
    }
    missing = [name for name, value in required_mysql_settings.items() if not value]
    if missing:
        raise ImproperlyConfigured(f"MySQL configuration is incomplete: {', '.join(missing)}")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": required_mysql_settings["DB_NAME"],
            "USER": required_mysql_settings["DB_USER"],
            "PASSWORD": required_mysql_settings["DB_PASSWORD"],
            "HOST": required_mysql_settings["DB_HOST"],
            "PORT": os.getenv("DB_PORT", "3306"),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
    mysql_test_name = os.getenv("DB_TEST_NAME", "").strip()
    if mysql_test_name:
        DATABASES["default"]["TEST"] = {"NAME": mysql_test_name}
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / os.getenv("SQLITE_NAME", "db.sqlite3"),
        }
    }
else:
    raise ImproperlyConfigured("DB_ENGINE must be either 'sqlite' or 'mysql'.")

LEGACY_DB_NAME = os.getenv("LEGACY_DB_NAME", "").strip()
if LEGACY_DB_NAME:
    DATABASES["legacy"] = {
        "ENGINE": "django.db.backends.mysql",
        "NAME": LEGACY_DB_NAME,
        "USER": os.getenv("LEGACY_DB_USER", os.getenv("DB_USER", "")),
        "PASSWORD": os.getenv("LEGACY_DB_PASSWORD", os.getenv("DB_PASSWORD", "")),
        "HOST": os.getenv("LEGACY_DB_HOST", os.getenv("DB_HOST", "")),
        "PORT": os.getenv("LEGACY_DB_PORT", os.getenv("DB_PORT", "3306")),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"charset": "utf8mb4"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Staff MFA is enforced on management views, Django admin and private media.
MFA_ENABLED = True
STAFF_MFA_REQUIRED = _env_bool("STAFF_MFA_REQUIRED", True)
MFA_ENCRYPTION_KEYS = _env_list("MFA_ENCRYPTION_KEYS", [])
MFA_ENROLLMENT_MAX_AGE = 600
MFA_SESSION_MAX_AGE = 28800
AUTH_THROTTLE_WINDOW = 900
AUTH_PASSWORD_ATTEMPT_LIMIT = 10
AUTH_MFA_ATTEMPT_LIMIT = 5
AUTH_RESET_ATTEMPT_LIMIT = 5
AUTH_IP_ATTEMPT_LIMIT = 120
TRUSTED_PROXY_CIDRS = _env_list("TRUSTED_PROXY_CIDRS", [])
# Browsers share cookies across ports, including other Django apps on localhost.
SESSION_COOKIE_NAME = os.getenv("DJANGO_SESSION_COOKIE_NAME", "microcredit_sessionid")
CSRF_COOKIE_NAME = os.getenv("DJANGO_CSRF_COOKIE_NAME", "microcredit_csrftoken")
SESSION_COOKIE_AGE = 28800
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_REFERRER_POLICY = "same-origin"
PASSWORD_RESET_TIMEOUT = 3600
HEALTHCHECK_TOKEN = os.getenv("HEALTHCHECK_TOKEN", "")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
IMPORT_MAX_BYTES = 10 * 1024 * 1024
IMPORT_MAX_EXPANDED_BYTES = 32 * 1024 * 1024
IMPORT_MAX_ROWS = 10000
IMPORT_MAX_COLUMNS = 100
EXPORTS_PER_MINUTE = 6
FILE_UPLOAD_HANDLERS = [
    "apps.core.upload_limits.LimitedUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Africa/Accra")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_MEDIA_ROOT = BASE_DIR / "private-media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "private": {"BACKEND": "apps.core.private_media.PrivateMediaStorage"},
}

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/redirect/"
LOGOUT_REDIRECT_URL = "login"

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@microcredit.local")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "false").lower() == "true"

ARKESEL_API_KEY = os.getenv("ARKESEL_API_KEY", "")
ARKESEL_SENDER_ID = os.getenv("ARKESEL_SENDER_ID", "MicroCredit")
ARKESEL_BASE_URL = os.getenv("ARKESEL_BASE_URL", "https://sms.arkesel.com/api/v2")

PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "")
ALLOW_INSECURE_PAYMENT_WEBHOOKS = _env_bool("ALLOW_INSECURE_PAYMENT_WEBHOOKS", DEBUG)
ALLOW_INSECURE_USSD_CALLBACKS = _env_bool("ALLOW_INSECURE_USSD_CALLBACKS", DEBUG)
