from __future__ import annotations

from django.contrib.auth import get_user_model


UserModel = get_user_model()
TENANT_USERNAME_SEPARATOR = "__"


def current_schema_name(request=None) -> str:
    return ""


def normalize_portal_username(username: str | None) -> str:
    return (username or "").strip()


def build_tenant_scoped_username(username: str | None, *, schema_name: str = "") -> str:
    raw_username = normalize_portal_username(username)
    schema_name = (schema_name or "").strip()
    if not raw_username or not schema_name:
        return raw_username
    return f"{schema_name}{TENANT_USERNAME_SEPARATOR}{raw_username}"


def visible_portal_username(username: str | None, *, schema_name: str = "") -> str:
    username = normalize_portal_username(username)
    schema_name = (schema_name or "").strip()
    scoped_prefix = f"{schema_name}{TENANT_USERNAME_SEPARATOR}"
    if schema_name and username.startswith(scoped_prefix):
        return username[len(scoped_prefix):]
    return username


def validate_tenant_scoped_username(username: str | None, *, schema_name: str = "") -> str:
    raw_username = normalize_portal_username(username)
    scoped_username = build_tenant_scoped_username(raw_username, schema_name=schema_name)
    max_length = UserModel._meta.get_field("username").max_length
    if len(scoped_username) > max_length:
        raise ValueError(
            f"Username is too long for this workspace. Use at most {max_length - len(scoped_username) + len(raw_username)} characters."
        )
    return raw_username


def tenant_username_exists(username: str | None, *, schema_name: str = "", exclude_user_id=None) -> bool:
    scoped_username = build_tenant_scoped_username(username, schema_name=schema_name)
    if not scoped_username:
        return False

    users = UserModel._default_manager.filter(username__iexact=scoped_username)
    if exclude_user_id:
        users = users.exclude(pk=exclude_user_id)
    return users.exists()


def login_username_candidates(username: str | None, *, schema_name: str = "") -> list[str]:
    raw_username = normalize_portal_username(username)
    if not raw_username:
        return []

    candidates = []
    scoped_username = build_tenant_scoped_username(raw_username, schema_name=schema_name)
    if scoped_username and scoped_username not in candidates:
        candidates.append(scoped_username)
    if raw_username not in candidates:
        candidates.append(raw_username)
    return candidates
