"""Stream loan summaries and fetch only twelve recent dashboard receipts."""
from decimal import Decimal
from django.db.models import BooleanField, Case, F, Max, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, Greatest
from .financial_queries import with_deposit_totals, with_repayment_totals
from .models import Loan, Payment, SecurityDeposit


def dashboard_loan_queryset():
    deposits = with_deposit_totals(SecurityDeposit.objects.filter(
        loan_id=OuterRef("pk"), enforce_before_disbursement=True,
    )).annotate(held=Greatest(Value(Decimal("0.00")), F("collected") + F("incoming") - F("refunded") - F("applied") - F("outgoing")))
    deposits = deposits.annotate(ready=Case(When(held__gte=F("required_amount"), then=Value(True)), default=Value(False), output_field=BooleanField()))
    loans = Loan.objects.select_related("borrower", "agent_name").only(
        "pk", "borrower_id", "agent_name_id", "amount", "duration_weeks", "duration_months",
        "repayment_frequency", "weekly_payment", "start_date", "status", "created_at", "loan_category",
        "disbursed_at", "security_deposit_applied_total", "borrower__id", "borrower__full_name",
        "borrower__national_id", "borrower__location", "borrower__group_name", "borrower__status",
        "agent_name__id", "agent_name__name",
    )
    return with_repayment_totals(loans).annotate(
        _latest_payment=Max("payments__created_at", filter=Q(payments__is_void=False, payments__is_pending=False)),
        _disbursement_ready=Case(When(disbursed_at__isnull=False, then=Value(True)),
            default=Coalesce(Subquery(deposits.values("ready")[:1]), Value(True)), output_field=BooleanField()),
    )


def recent_dashboard_payments():
    payments = list(Payment.objects.filter(is_void=False, is_pending=False).only(
        "pk", "loan_id", "amount", "principal_paid", "roic_paid", "customer_credit", "payment_date", "created_at",
    ).order_by("-created_at", "-pk")[:12])
    by_id = {loan.pk: loan for loan in dashboard_loan_queryset().filter(pk__in={row.loan_id for row in payments})}
    for payment in payments:
        payment.loan = by_id[payment.loan_id]
    return payments


def iter_dashboard_loans(batch_size=500):
    """Keyset pages also bound memory on MySQL, whose driver buffers a result set."""
    last = None
    while True:
        keys = Loan.objects.order_by("borrower_id", "pk")
        if last:
            keys = keys.filter(Q(borrower_id__gt=last[0]) | Q(borrower_id=last[0], pk__gt=last[1]))
        page = list(keys.values_list("borrower_id", "pk")[:batch_size])
        if not page:
            return
        yield from dashboard_loan_queryset().filter(pk__in=[key[1] for key in page]).order_by("borrower_id", "pk")
        if len(page) < batch_size:
            return
        last = page[-1]
