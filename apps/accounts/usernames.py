"""Standalone username helpers."""

from __future__ import annotations

from django.contrib.auth import get_user_model


UserModel = get_user_model()


def normalize_portal_username(username: str | None) -> str:
    return (username or "").strip()


def build_portal_username(username: str | None) -> str:
    return normalize_portal_username(username)


def visible_portal_username(username: str | None) -> str:
    return normalize_portal_username(username)


def validate_portal_username(username: str | None) -> str:
    raw_username = normalize_portal_username(username)
    max_length = UserModel._meta.get_field("username").max_length
    if len(raw_username) > max_length:
        raise ValueError(f"Username is too long. Use at most {max_length} characters.")
    return raw_username


def portal_username_exists(username: str | None, *, exclude_user_id=None) -> bool:
    username = build_portal_username(username)
    if not username:
        return False

    users = UserModel._default_manager.filter(username__iexact=username)
    if exclude_user_id:
        users = users.exclude(pk=exclude_user_id)
    return users.exists()


def login_username_candidates(username: str | None) -> list[str]:
    username = normalize_portal_username(username)
    if not username:
        return []
    candidates = [username]
    # Tenant-edition accounts were stored as ``schema__username``.
    legacy_suffix = f"__{username}"
    legacy_names = UserModel._default_manager.filter(
        username__iendswith=legacy_suffix,
    ).order_by("id").values_list("username", flat=True)
    candidates.extend(name for name in legacy_names if name not in candidates)
    return candidates
