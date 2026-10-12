"""Synchronize repayment evidence while retaining closed-period postings."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import JournalEntry, create_journal_entry, get_ledger_account, reverse_journal_entry


@transaction.atomic
def sync_repayment_entry(payment, *, user=None, historical_adjustment=False):
    source_key = f"payment:{payment.pk}:repayment"
    postings = JournalEntry.objects.select_for_update().filter(source_key=source_key, source_type="LOAN_REPAYMENT", status="POSTED")
    existing = postings.filter(reversed_by__isnull=True).first()
    if payment.is_void or payment.is_pending:
        return int(reverse_journal_entry(existing, user=user, reason="Repayment voided or returned to pending")[1]) if existing else 0
    method_codes = {"CASH": "1000", "MOBILE_MONEY": "1005", "BANK": "1010", "CHEQUE": "1010", "CARD": "1010", "OTHER": "1090"}
    cash = get_ledger_account(method_codes.get(payment.payment_method, "1090"))
    principal = get_ledger_account("1300")
    interest = get_ledger_account("4000")
    credit = get_ledger_account("2066")
    if not cash or not principal or not interest:
        return 0
    if payment.customer_credit and (not credit or credit.account_type != "LIABILITY"):
        raise ValueError("Customer credit requires liability account 2066 before posting.")
    zero = Decimal("0.00")
    lines = [{"account": cash, "debit": payment.amount, "credit": zero, "description": f"Loan #{payment.loan_id} receipt"}]
    for account, amount, description in ((principal, payment.principal_paid, "Principal collected"), (interest, payment.roic_paid, "ROIC collected"), (credit, payment.customer_credit, "Customer credit held")):
        if amount > zero:
            lines.append({"account": account, "debit": zero, "credit": amount, "description": description})
    created = 0
    correction = postings.exists()
    if existing:
        recorded = sorted((line.account_id, line.debit, line.credit) for line in existing.lines.all())
        expected = sorted((line["account"].pk, line["debit"], line["credit"]) for line in lines)
        if recorded == expected and (existing.source_date or existing.entry_date) == payment.payment_date:
            return 0
        created += int(reverse_journal_entry(existing, user=user, reason="Repayment corrected")[1])
    create_journal_entry(
        entry_date=timezone.localdate() if correction or historical_adjustment else payment.payment_date,
        source_date=payment.payment_date, memo=f"Loan repayment from {payment.loan.borrower.full_name}",
        lines=lines, created_by=user, reference=payment.reference or f"Payment {payment.pk}",
        source_type="LOAN_REPAYMENT", source_key=source_key, source_label=f"Payment #{payment.pk}")
    return created + 1
