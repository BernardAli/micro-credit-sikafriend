"""Complete account statements, built without per-loan financial queries."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Prefetch, Q
from django.utils import timezone

from .financial_queries import with_deposit_totals, with_repayment_totals
from .models import Payment, SecurityDeposit, SecurityDepositTransaction, SecurityDepositTransfer

ZERO = Decimal("0.00")


def account_statement(loans):
    loans = list(with_repayment_totals(loans.select_related("borrower", "portfolio", "agent_name"), include_pending=True).prefetch_related(
        Prefetch("payments", queryset=Payment.objects.select_related("collected_by", "reversal__approved_by").order_by("payment_date", "pk"), to_attr="statement_payments"),
    ).order_by("start_date", "pk"))
    by_id = {loan.pk: loan for loan in loans}
    deposits = list(with_deposit_totals(SecurityDeposit.objects.filter(loan_id__in=by_id)))
    deposit_by_id = {deposit.pk: deposit for deposit in deposits}
    deposit_by_loan = {deposit.loan_id: deposit for deposit in deposits}
    transactions = list(SecurityDepositTransaction.objects.filter(deposit_id__in=deposit_by_id).select_related("approved_by", "reversal__approved_by").order_by("transaction_date", "pk"))
    transfers = list(SecurityDepositTransfer.objects.filter(Q(source_id__in=deposit_by_id) | Q(target_id__in=deposit_by_id)).select_related("source", "target", "approved_by", "reversal__approved_by").order_by("created_at", "pk"))
    movements, applications = defaultdict(list), defaultdict(list)
    for transaction in transactions:
        deposit = deposit_by_id[transaction.deposit_id]
        change = transaction.amount if transaction.action == "COLLECTION" else -transaction.amount
        movements[deposit.pk].append({"date": transaction.transaction_date, "order": (0, transaction.pk), "loan_id": deposit.loan_id,
            "description": transaction.get_action_display(), "reference": transaction.reference, "change": change,
            "method": transaction.get_payment_method_display(), "notes": transaction.notes})
        if transaction.reversal_id:
            reversal = transaction.reversal
            movements[deposit.pk].append({"date": reversal.effective_date, "order": (2, reversal.pk), "loan_id": deposit.loan_id,
                "description": f"{reversal.reference} · Reversal of {transaction.get_action_display()} #{transaction.pk}",
                "reference": reversal.evidence_reference, "change": -change, "method": "Approved reversal",
                "notes": f"Approved by {reversal.approved_by}: {reversal.reason}"})
        if transaction.action == "DEFAULT_APPLICATION":
            applications[deposit.loan_id].append(transaction)
    for transfer in transfers:
        for deposit_id, change, other_loan, label in (
            (transfer.source_id, -transfer.amount, transfer.target.loan_id, "Transfer to"),
            (transfer.target_id, transfer.amount, transfer.source.loan_id, "Transfer from"),
        ):
            if deposit_id in deposit_by_id:
                movements[deposit_id].append({"date": timezone.localtime(transfer.created_at).date(), "order": (1, transfer.pk),
                    "loan_id": deposit_by_id[deposit_id].loan_id, "description": f"{label} Loan #{other_loan}",
                    "reference": transfer.reference, "change": change, "method": "Transfer", "notes": ""})
                if transfer.reversal_id:
                    reversal = transfer.reversal
                    movements[deposit_id].append({"date": reversal.effective_date, "order": (2, reversal.pk),
                        "loan_id": deposit_by_id[deposit_id].loan_id, "description": f"{reversal.reference} · Reversal of transfer #{transfer.pk}",
                        "reference": reversal.evidence_reference, "change": -change, "method": "Approved reversal",
                        "notes": f"Approved by {reversal.approved_by}: {reversal.reason}"})
    deposit_rows, deposit_movements, loan_rows, ledger, receipts = [], [], [], [], []
    totals = {key: ZERO for key in ("principal", "expected", "cash", "paid", "principal_paid", "interest_paid", "outstanding", "principal_outstanding", "interest_outstanding", "credit", "deposit_applied", "deposit_held", "pending")}
    review_loans = []
    for loan in loans:
        deposit = deposit_by_loan.get(loan.pk)
        held = max(ZERO, deposit.collected + deposit.incoming - deposit.refunded - deposit.applied - deposit.outgoing) if deposit else ZERO
        loan._disbursement_ready = bool(loan.disbursed_at or deposit is None or not deposit.enforce_before_disbursement or held >= deposit.required_amount)
        if deposit:
            deposit_rows.append({"loan_id": loan.pk, "required": deposit.required_amount, "collected": deposit.collected,
                "refunded": deposit.refunded, "applied": deposit.applied, "incoming": deposit.incoming, "outgoing": deposit.outgoing,
                "held": held, "due": max(ZERO, deposit.required_amount-held)})
            running_held = ZERO
            for movement in sorted(movements[deposit.pk], key=lambda row: (row["date"], row["order"])):
                running_held += movement["change"]
                deposit_movements.append({**movement, "held": running_held})
        settled = [p for p in loan.statement_payments if not p.is_void and not p.is_pending]
        review = loan.total_expected_amount < loan.principal_amount or loan.balance_amount != loan.principal_outstanding + loan.roic_outstanding or any(p.amount != p.principal_paid+p.roic_paid+p.customer_credit for p in settled)
        recorded_applications = applications[loan.pk]
        dated_applied = sum((item.amount for item in recorded_applications if not item.reversal_id), ZERO)
        if dated_applied > loan.security_deposit_applied_amount:
            review = True
            recorded_applications = []
            dated_applied = ZERO
        opening_application = loan.security_deposit_applied_amount - dated_applied
        events = []
        if opening_application:
            events.append({"date": None, "order": (-1, 0), "description": "Opening deposit application (undated)", "status": "Applied", "amount": opening_application,
                "applied": opening_application, "principal": opening_application, "interest": ZERO, "credit": ZERO, "reference": "", "method": "Deposit", "collector": "", "notes": ""})
        for item in recorded_applications:
            events.append({"date": item.transaction_date, "order": (0, item.pk), "description": "Security deposit application", "status": "Applied", "amount": item.amount,
                "applied": item.amount, "principal": item.amount, "interest": ZERO, "credit": ZERO, "reference": item.reference,
                "method": "Deposit", "collector": str(item.approved_by) if item.approved_by_id else "", "notes": item.notes})
            if item.reversal_id:
                reversal = item.reversal
                events.append({"date": reversal.effective_date, "order": (2, reversal.pk), "description": f"{reversal.reference} · Reversal of deposit application #{item.pk}",
                    "status": "Reversal", "amount": -item.amount, "applied": -item.amount, "principal": -item.amount,
                    "interest": ZERO, "credit": ZERO, "reference": reversal.evidence_reference, "method": "Approved reversal",
                    "collector": str(reversal.approved_by), "notes": reversal.reason})
        for payment in loan.statement_payments:
            status = "Reversed" if payment.reversal_id else "Void" if payment.is_void else "Pending" if payment.is_pending else "Settled"
            historical = status in {"Settled", "Reversed"}
            applied = payment.loan_applied_amount if historical else ZERO
            events.append({"date": payment.payment_date, "order": (1, payment.pk), "description": f"Receipt #{payment.pk}", "status": status, "amount": payment.amount,
                "applied": applied, "principal": payment.principal_paid if historical else ZERO,
                "interest": payment.roic_paid if historical else ZERO, "credit": payment.customer_credit if historical else ZERO,
                "reference": payment.reference, "method": payment.get_payment_method_display(),
                "collector": payment.collected_by.name if payment.collected_by_id else "", "collector_id": payment.collected_by_id, "notes": payment.note})
            if payment.reversal_id:
                reversal = payment.reversal
                events.append({"date": reversal.effective_date, "order": (2, reversal.pk), "description": f"{reversal.reference} · Reversal of receipt #{payment.pk}",
                    "status": "Reversal", "amount": -payment.amount, "applied": -applied, "principal": -payment.principal_paid,
                    "interest": -payment.roic_paid, "credit": -payment.customer_credit, "reference": reversal.evidence_reference,
                    "method": "Approved reversal", "collector": str(reversal.approved_by), "notes": reversal.reason})
            if status == "Settled":
                receipts.append({"payment": payment, "loan": loan, "amount": payment.amount, "applied": applied, "credit": payment.customer_credit})
        running_balance = loan.total_expected_amount
        for event in sorted(events, key=lambda row: (row["date"] or date.min, row["order"])):
            running_balance = max(ZERO, running_balance-event["applied"])
            ledger.append({**event, "loan_id": loan.pk, "customer": loan.borrower.full_name, "customer_id": loan.borrower.borrower_id, "balance": running_balance})
        if review:
            review_loans.append(loan.pk)
        row = {"loan": loan, "review": review, "principal": loan.principal_amount, "expected": loan.total_expected_amount,
               "cash": loan.total_cash_received, "paid": loan.total_paid_amount, "principal_paid": loan.total_principal_paid, "interest_paid": loan.total_roic_paid,
               "outstanding": loan.balance_amount, "principal_outstanding": loan.principal_outstanding, "interest_outstanding": loan.roic_outstanding,
               "credit": loan.total_customer_credit, "deposit_applied": loan.security_deposit_applied_amount, "deposit_held": held,
               "pending": loan._pending_payment_amount, "overdue": loan.overdue_weeks, "covered": loan.paid_installments_count}
        loan_rows.append(row)
        for key in totals:
            totals[key] += row[key]
    ledger.sort(key=lambda row: (row["date"] or date.min, row["loan_id"], row["order"]))
    deposit_movements.sort(key=lambda row: (row["date"], row["loan_id"], row["order"]))
    totals.update(loans=len(loans), receipts=len(receipts), pending_count=sum(loan._pending_payment_count for loan in loans),
                  active=sum(loan.status=="ACTIVE" for loan in loans), closed=sum(loan.status=="CLOSED" for loan in loans), default=sum(loan.status=="DEFAULT" for loan in loans))
    return {"loans": loan_rows, "totals": totals, "ledger": ledger, "deposits": deposit_rows, "deposit_movements": deposit_movements,
            "receipts": receipts, "review_loans": review_loans, "has_opening_applications": any(row["date"] is None for row in ledger)}
