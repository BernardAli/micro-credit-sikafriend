"""Password attempt budgets and replay-resistant encrypted TOTP authentication."""
import base64
import hashlib
import secrets
import time

import pyotp
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from apps.core.security import client_ip
from .models import AuthenticationThrottle, Authenticator


def cipher():
    keys = settings.MFA_ENCRYPTION_KEYS
    if not keys:
        if not settings.DEBUG:
            raise ImproperlyConfigured("Set MFA_ENCRYPTION_KEYS before enabling production authentication.")
        keys = [base64.urlsafe_b64encode(hashlib.sha256(("local-mfa:" + settings.SECRET_KEY).encode()).digest()).decode()]
    return MultiFernet([Fernet(key.encode()) for key in keys])


def throttle_key(scope, identifier):
    return salted_hmac("authentication-throttle", f"{scope}:{identifier}", algorithm="sha256").hexdigest()


def reserve_attempt(scope, identifier, limit, window=None):
    """Reserve before doing password/hash work. Works across application workers."""
    now = timezone.now()
    window = window or settings.AUTH_THROTTLE_WINDOW
    key = throttle_key(scope, identifier)
    with transaction.atomic():
        bucket, _ = AuthenticationThrottle.objects.get_or_create(
            key=key, defaults={"expires_at": now + timezone.timedelta(seconds=window)},
        )
        bucket = AuthenticationThrottle.objects.select_for_update().get(pk=key)
        if bucket.expires_at <= now:
            bucket.attempts = 0
            bucket.expires_at = now + timezone.timedelta(seconds=window)
        if bucket.attempts >= limit:
            return max(1, int((bucket.expires_at - now).total_seconds()))
        bucket.attempts += 1
        bucket.save(update_fields=["attempts", "expires_at"])
    return 0


def account_identifier(value):
    # Old schema-prefixed usernames and their short aliases share a budget.
    return (value or "").strip().casefold().rsplit("__", 1)[-1][:254]


def reserve_request(request, scope, identifier, limit):
    wait = reserve_attempt(f"{scope}-ip", client_ip(request) or "unknown", settings.AUTH_IP_ATTEMPT_LIMIT)
    if wait:
        return wait
    return reserve_attempt(scope, identifier, limit)


def clear_attempts(scope, identifier):
    AuthenticationThrottle.objects.filter(pk=throttle_key(scope, identifier)).delete()


def new_recovery_codes():
    codes = ["-".join(secrets.token_hex(4).upper() for _ in range(4)) for _ in range(10)]
    return codes, [recovery_hash(code) for code in codes]


def recovery_hash(code):
    return hashlib.sha256(code.replace("-", "").replace(" ", "").upper().encode()).hexdigest()


def verify_code(user, code, *, allow_recovery=True, at=None):
    """Consume a code under a row lock; later timestamps cannot replay older codes."""
    code = (code or "").strip()
    with transaction.atomic():
        device = Authenticator.objects.select_for_update().filter(user=user, confirmed_at__isnull=False).first()
        if device is None:
            return None
        if len(code) == 6 and code.isascii() and code.isdigit():
            step = int((at if at is not None else time.time()) // 30)
            secret = cipher().decrypt(device.secret_ciphertext.encode()).decode()
            otp = pyotp.TOTP(secret)
            for candidate in (step, step - 1, step + 1):
                if candidate > device.last_step and constant_time_compare(otp.at(candidate * 30), code):
                    device.last_step = candidate
                    device.save(update_fields=["last_step"])
                    return device
        elif allow_recovery and len(code.replace("-", "").replace(" ", "")) == 32:
            digest = recovery_hash(code)
            for item in device.recovery_hashes:
                if constant_time_compare(item, digest):
                    device.recovery_hashes = [value for value in device.recovery_hashes if value != item]
                    device.save(update_fields=["recovery_hashes"])
                    return device
    return None


def session_verified(request, device):
    verified = request.session.get("mfa_verified", {})
    return bool(device and device.confirmed_at and
                verified.get("user") == request.user.pk and
                verified.get("revision") == str(device.revision) and
                0 <= time.time() - verified.get("at", 0) < settings.MFA_SESSION_MAX_AGE)


def mark_verified(request, device):
    request.session.cycle_key()
    request.session["mfa_verified"] = {"user": request.user.pk, "revision": str(device.revision), "at": time.time()}
    clear_attempts("mfa", str(request.user.pk))
