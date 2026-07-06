"""Stub enforcement module — single-tenant standalone project."""
from __future__ import annotations
from types import SimpleNamespace


def _ok() -> SimpleNamespace:
    return SimpleNamespace(allowed=True, reason="")


def tenant_access_status(tenant=None, **kwargs) -> SimpleNamespace:
    return _ok()


def can_create_borrower(tenant=None, schema_name=None, **kwargs) -> SimpleNamespace:
    return _ok()


def can_create_agent(tenant=None, schema_name=None, **kwargs) -> SimpleNamespace:
    return _ok()
