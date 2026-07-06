"""Cross-company debt check — disabled in standalone (single-company) mode."""
from __future__ import annotations

from decimal import Decimal


def empty_cross_company_debt_check() -> dict:
    return {
        "requires_review": False,
        "has_default": False,
        "company_count": 0,
        "open_loan_count": 0,
        "total_outstanding": Decimal("0.00"),
        "total_expected": Decimal("0.00"),
        "companies": [],
        "headline": "Cross-company check not available in standalone mode.",
    }


def get_cross_company_debt_check(**kwargs) -> dict:
    return empty_cross_company_debt_check()


def serialize_cross_company_debt_check(summary: dict) -> dict:
    return {
        "requires_review": False,
        "has_default": False,
        "company_count": 0,
        "open_loan_count": 0,
        "total_outstanding": "0.00",
        "total_expected": "0.00",
        "headline": "",
        "companies": [],
    }


def format_cross_company_debt_summary(summary: dict) -> str:
    return ""
