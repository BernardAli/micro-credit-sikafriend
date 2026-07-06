from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils.crypto import constant_time_compare


def _company_profile(profile=None):
    if profile is not None:
        return profile

    try:
        from .models import CompanyProfile

        return CompanyProfile.get_solo()
    except Exception:
        return None


def get_company_email_config(profile=None) -> dict:
    profile = _company_profile(profile)

    has_transport_override = bool(
        profile
        and (
            profile.tenant_email_host
            or profile.tenant_email_port
            or profile.tenant_email_host_user
            or profile.tenant_email_host_password
            or profile.tenant_email_use_tls is not None
            or profile.tenant_email_use_ssl is not None
        )
    )

    return {
        "from_email": (
            (getattr(profile, "tenant_email_from_address", "") or getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@microcredit.local")).strip()
        ),
        "host": ((getattr(profile, "tenant_email_host", "") or getattr(settings, "EMAIL_HOST", "")).strip()),
        "port": getattr(profile, "tenant_email_port", None) or int(getattr(settings, "EMAIL_PORT", 587) or 587),
        "username": ((getattr(profile, "tenant_email_host_user", "") or getattr(settings, "EMAIL_HOST_USER", "")).strip()),
        "password": ((getattr(profile, "tenant_email_host_password", "") or getattr(settings, "EMAIL_HOST_PASSWORD", "")).strip()),
        "use_tls": (
            getattr(profile, "tenant_email_use_tls", None)
            if profile and getattr(profile, "tenant_email_use_tls", None) is not None
            else bool(getattr(settings, "EMAIL_USE_TLS", True))
        ),
        "use_ssl": (
            getattr(profile, "tenant_email_use_ssl", None)
            if profile and getattr(profile, "tenant_email_use_ssl", None) is not None
            else bool(getattr(settings, "EMAIL_USE_SSL", False))
        ),
        "has_transport_override": has_transport_override,
    }


def send_company_email(
    subject: str,
    message: str,
    recipient_list: list[str],
    from_email: str | None = None,
    fail_silently: bool = True,
    profile=None,
) -> int:
    config = get_company_email_config(profile)

    if config["has_transport_override"]:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            fail_silently=fail_silently,
            host=config["host"],
            port=config["port"],
            username=config["username"],
            password=config["password"],
            use_tls=config["use_tls"],
            use_ssl=config["use_ssl"],
        )
    else:
        connection = get_connection(fail_silently=fail_silently)

    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=(from_email or config["from_email"]),
        to=recipient_list,
        connection=connection,
    )
    return email.send()


def get_company_sms_config(profile=None) -> dict:
    profile = _company_profile(profile)
    return {
        "provider": ((getattr(profile, "tenant_sms_provider", "") or "ARKESEL").strip().upper()),
        "api_key": ((getattr(profile, "tenant_sms_api_key", "") or getattr(settings, "ARKESEL_API_KEY", "")).strip()),
        "sender_id": ((getattr(profile, "tenant_sms_sender_id", "") or getattr(settings, "ARKESEL_SENDER_ID", "")).strip()),
        "base_url": (
            (getattr(profile, "tenant_sms_base_url", "") or getattr(settings, "ARKESEL_BASE_URL", "https://sms.arkesel.com/api/v2")).rstrip("/")
        ),
    }


def get_company_ussd_config(profile=None) -> dict:
    profile = _company_profile(profile)
    return {
        "provider": ((getattr(profile, "tenant_ussd_provider", "") or "").strip().upper()),
        "api_key": ((getattr(profile, "tenant_ussd_api_key", "") or "").strip()),
        "shortcode": ((getattr(profile, "tenant_ussd_shortcode", "") or "").strip()),
        "username": ((getattr(profile, "tenant_ussd_username", "") or "").strip()),
        "callback_token": ((getattr(profile, "tenant_ussd_callback_token", "") or "").strip()),
    }


def validate_company_ussd_request(request, profile=None) -> bool:
    config = get_company_ussd_config(profile)
    expected = config["callback_token"] or config["api_key"]
    if not expected:
        return bool(
            getattr(settings, "DEBUG", False)
            and getattr(settings, "ALLOW_INSECURE_USSD_CALLBACKS", False)
        )

    auth_header = (request.headers.get("Authorization", "") or "").strip()
    if auth_header.lower().startswith("bearer "):
        auth_header = auth_header[7:].strip()

    candidates = [
        request.headers.get("X-API-Key", ""),
        request.headers.get("X-Ussd-Token", ""),
        request.POST.get("api_key", ""),
        request.POST.get("token", ""),
        request.GET.get("api_key", ""),
        request.GET.get("token", ""),
        auth_header,
    ]
    return any(
        candidate and constant_time_compare(candidate.strip(), expected)
        for candidate in candidates
    )
