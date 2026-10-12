"""Grouped financial totals for read-only management pages."""
from decimal import Decimal

from django.db.models import Count, DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from .models import SecurityDepositTransfer


def money_total(expression, *, filter=None):
    return Coalesce(Sum(expression, filter=filter), Value(Decimal("0.00")),
                    output_field=DecimalField(max_digits=20, decimal_places=2))


def with_repayment_totals(loans, *, include_pending=False):
    settled = Q(payments__is_void=False, payments__is_pending=False)
    totals = {f"_settled_total_{field}": money_total(f"payments__{field}", filter=settled)
              for field in ("amount", "principal_paid", "roic_paid", "customer_credit")}
    totals["_settled_payment_count"] = Count("payments", filter=settled)
    if include_pending:
        pending = Q(payments__is_void=False, payments__is_pending=True)
        totals["_pending_payment_count"] = Count("payments", filter=pending)
        totals["_pending_payment_amount"] = money_total("payments__amount", filter=pending)
    return loans.annotate(**totals)


def with_deposit_totals(deposits):
    def transfer_total(field):
        rows = SecurityDepositTransfer.objects.filter(reversal__isnull=True, **{field: OuterRef("pk")}).order_by().values(field).annotate(total=Sum("amount"))
        return Coalesce(Subquery(rows.values("total")), Value(Decimal("0.00")),
                        output_field=DecimalField(max_digits=20, decimal_places=2))

    return deposits.annotate(
        collected=money_total("transactions__amount", filter=Q(transactions__action="COLLECTION", transactions__reversal__isnull=True)),
        refunded=money_total("transactions__amount", filter=Q(transactions__action="REFUND", transactions__reversal__isnull=True)),
        applied=money_total("transactions__amount", filter=Q(transactions__action="DEFAULT_APPLICATION", transactions__reversal__isnull=True)),
        incoming=transfer_total("target_id"), outgoing=transfer_total("source_id"),
    )
