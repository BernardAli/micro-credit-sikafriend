"""Load a management dashboard without a query for each loan or deposit."""
from decimal import Decimal

from .financial_queries import with_deposit_totals, with_repayment_totals
from .models import Loan, Payment, SecurityDeposit


def dashboard_loans_and_payments():
    zero = Decimal("0.00")
    loans = list(with_repayment_totals(Loan.objects.select_related("borrower", "agent_name")))
    deposits = with_deposit_totals(SecurityDeposit.objects.filter(
        enforce_before_disbursement=True, loan__disbursed_at__isnull=True,
    )).values("loan_id", "required_amount", "collected", "refunded", "applied", "incoming", "outgoing")
    ready = {row["loan_id"]: max(zero, row["collected"] + row["incoming"] - row["refunded"] - row["applied"] - row["outgoing"]) >= row["required_amount"] for row in deposits}
    by_id = {loan.pk: loan for loan in loans}
    for loan in loans:
        loan._disbursement_ready = ready.get(loan.pk, True)

    payments = list(Payment.objects.filter(loan_id__in=by_id, is_void=False, is_pending=False).only(
        "pk", "loan_id", "amount", "principal_paid", "roic_paid", "customer_credit", "payment_date", "created_at",
    ).order_by("-created_at", "-pk"))
    for payment in payments:
        payment.loan = by_id[payment.loan_id]
    return loans, payments
