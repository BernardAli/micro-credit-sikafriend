"""Allocate recorded cash without turning customer funds into loan income."""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def allocate_receipt(amount, *, principal, expected, principal_remaining, roic_remaining):
    applied = min(amount, principal_remaining + roic_remaining)
    if applied <= ZERO:
        return ZERO, ZERO, amount
    principal_part = (applied * principal / expected).quantize(CENT, rounding=ROUND_HALF_UP)
    roic_part = applied - principal_part
    if principal_part > principal_remaining:
        roic_part += principal_part - principal_remaining
        principal_part = principal_remaining
    if roic_part > roic_remaining:
        principal_part += roic_part - roic_remaining
        roic_part = roic_remaining
    return principal_part, roic_part, amount - applied
