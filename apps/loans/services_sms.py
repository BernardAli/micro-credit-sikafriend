import logging
import re

import requests

from apps.company.messaging import get_company_sms_config

logger = logging.getLogger(__name__)


def _response_detail(response) -> str:
    if response is None:
        return "no response body"

    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("detail") or str(payload)
        elif payload:
            detail = str(payload)
    except ValueError:
        detail = (getattr(response, "text", "") or "").strip()

    detail = detail or "no response body"
    return detail[:200]


def normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""

    cleaned = re.sub(r"[^\d+]", "", str(phone).strip())
    if not cleaned:
        return ""

    if cleaned.startswith("+233"):
        return cleaned[1:]
    if cleaned.startswith("233"):
        return cleaned
    if cleaned.startswith("0") and len(cleaned) == 10:
        return f"233{cleaned[1:]}"
    if cleaned.isdigit() and len(cleaned) == 9:
        return f"233{cleaned}"
    return cleaned


def send_sms(phone: str, message: str) -> None:
    """
    Send a loan-related SMS through Arkesel.
    """
    recipient = normalize_phone(phone)
    text = (message or "").strip()

    if not recipient or not text:
        return

    config = get_company_sms_config()
    provider = config["provider"]
    api_key = config["api_key"]
    sender_id = config["sender_id"]
    base_url = config["base_url"]

    if provider and provider != "ARKESEL":
        logger.warning("SMS skipped because tenant provider '%s' is not yet supported by this flow.", provider)
        return

    if not api_key or not sender_id:
        logger.warning("Arkesel SMS skipped because configuration is incomplete.")
        return

    response = requests.post(
        f"{base_url}/sms/send",
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "sender": sender_id,
            "message": text,
            "recipients": [recipient],
        },
        timeout=20,
    )
    response.raise_for_status()


def safe_send_sms(phone: str | None, message: str) -> None:
    try:
        if phone:
            send_sms(phone, message)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        logger.warning(
            "Loan SMS delivery skipped: Arkesel returned %s for %s (%s).",
            status_code,
            normalize_phone(phone),
            _response_detail(exc.response),
        )
    except requests.RequestException as exc:
        logger.warning("Loan SMS delivery skipped because Arkesel request failed: %s", exc)
    except Exception:
        # Never fail a loan or payment workflow because SMS delivery failed.
        logger.exception("Loan SMS delivery failed unexpectedly.")
