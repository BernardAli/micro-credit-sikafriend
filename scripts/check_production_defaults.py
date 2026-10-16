"""Exercise secure production defaults with synthetic CI configuration, not a live host."""
import os
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet

os.environ.update(
    DJANGO_SETTINGS_MODULE='config.settings', PYTHON_DOTENV_DISABLED='1',
    DJANGO_DEBUG='False', DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
    DJANGO_ALLOWED_HOSTS='deployment-check.invalid',
    DJANGO_CSRF_TRUSTED_ORIGINS='https://deployment-check.invalid',
    DB_ENGINE='mysql', DB_NAME='synthetic_security_check', DB_USER='synthetic_user',
    DB_PASSWORD='synthetic-check-only', DB_HOST='127.0.0.1', LEGACY_DB_NAME='',
    STAFF_MFA_REQUIRED='True', MFA_ENCRYPTION_KEYS=Fernet.generate_key().decode(),
    ALLOW_INSECURE_PAYMENT_WEBHOOKS='False', ALLOW_INSECURE_USSD_CALLBACKS='False',
)
for key in ('DJANGO_SECURE_SSL_REDIRECT','DJANGO_SESSION_COOKIE_SECURE','DJANGO_CSRF_COOKIE_SECURE',
            'DJANGO_SECURE_HSTS_SECONDS','DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS','DJANGO_SECURE_HSTS_PRELOAD'):
    os.environ.pop(key, None)
import django
django.setup()
from django.core.management import call_command
call_command('check', deploy=True, fail_level='WARNING')
