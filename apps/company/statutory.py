from __future__ import annotations

from copy import deepcopy
from decimal import Decimal


QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.01")

DEFAULT_PAYROLL_TAX_BRACKETS = [
    {"up_to": "490.00", "rate": "0.00", "label": "First 490"},
    {"up_to": "600.00", "rate": "5.00", "label": "Next 110"},
    {"up_to": "730.00", "rate": "10.00", "label": "Next 130"},
    {"up_to": "3896.67", "rate": "17.50", "label": "Next 3,166.67"},
    {"up_to": "19896.67", "rate": "25.00", "label": "Next 16,000"},
    {"up_to": "50416.67", "rate": "30.00", "label": "Next 30,520"},
    {"up_to": None, "rate": "35.00", "label": "Exceeding 50,416.67"},
]


def money(value) -> Decimal:
    return Decimal(str(value or "0.00")).quantize(QUANT)


def rate(value) -> Decimal:
    return Decimal(str(value or "0.00")).quantize(RATE_QUANT)


def default_payroll_tax_brackets():
    return deepcopy(DEFAULT_PAYROLL_TAX_BRACKETS)


def normalize_tax_brackets(brackets) -> list[dict]:
    normalized = []
    previous_upper = Decimal("0.00")

    for index, item in enumerate(brackets or [], start=1):
        upper = item.get("up_to")
        band_rate = rate(item.get("rate"))
        label = (item.get("label") or "").strip()

        if upper in {"", None}:
            upper_value = None
        else:
            upper_value = money(upper)
            if upper_value <= previous_upper:
                raise ValueError(f"Tax bracket {index} must have an upper limit above the previous band.")
            previous_upper = upper_value

        normalized.append(
            {
                "up_to": f"{upper_value:.2f}" if upper_value is not None else None,
                "rate": f"{band_rate:.2f}",
                "label": label or f"Band {index}",
            }
        )
    return normalized


def calculate_progressive_tax(chargeable_income, brackets) -> Decimal:
    taxable = money(chargeable_income)
    if taxable <= 0:
        return Decimal("0.00")

    total_tax = Decimal("0.00")
    previous_upper = Decimal("0.00")

    for band in normalize_tax_brackets(brackets):
        upper = band.get("up_to")
        band_rate = rate(band.get("rate")) / Decimal("100.00")

        if upper is None:
            taxable_band = max(taxable - previous_upper, Decimal("0.00"))
        else:
            upper_value = money(upper)
            taxable_band = min(taxable, upper_value) - previous_upper
            previous_upper = upper_value

        if taxable_band > 0:
            total_tax += taxable_band * band_rate

        if upper is None or taxable <= previous_upper:
            break

    return money(total_tax)
