"""Standalone creation limits.

The standalone edition has no subscription caps, so borrower and workforce
creation are always allowed. The return object keeps the existing calling
pattern in views and importers simple.
"""

from __future__ import annotations

from types import SimpleNamespace


def _allowed() -> SimpleNamespace:
    return SimpleNamespace(allowed=True, reason="")


def can_create_borrower(**kwargs) -> SimpleNamespace:
    return _allowed()


def can_create_agent(**kwargs) -> SimpleNamespace:
    return _allowed()
