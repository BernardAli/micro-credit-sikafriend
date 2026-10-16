from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from .models import ActivityLog
from .security import client_ip


def _json_safe(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def log_activity(
    *,
    category,
    action,
    message,
    actor=None,
    object_type="",
    object_id="",
    object_label="",
    metadata=None,
    request=None,
):
    ip_address = None
    if request is not None:
        ip_address = client_ip(request)

    return ActivityLog.objects.create(
        category=category,
        action=action,
        actor=actor,
        object_type=object_type,
        object_id=str(object_id or ""),
        object_label=object_label,
        message=message,
        metadata=_json_safe(metadata or {}),
        ip_address=ip_address,
    )
