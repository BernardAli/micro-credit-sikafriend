"""Repair derived allocations; retain every original cash receipt."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounting.models import JournalEntry, ensure_default_ledger_accounts
from apps.accounting.repayments import sync_repayment_entry
from apps.loans.models import Borrower, Loan, Payment
from apps.loans.payment_allocations import allocate_receipt, ZERO


class Command(BaseCommand):
    help = "Preview historical allocation repairs and hold excess receipts as customer credit. Use --apply after backing up."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report", metavar="FILE")
        parser.add_argument("--exclude-loan", type=int, action="append", default=[], metavar="ID",
                            help="Defer a specific reviewed loan while its agreed terms are confirmed.")

    @transaction.atomic
    def handle(self, *args, **options):
        changes, skipped, borrower_ids = [], [], set()
        excluded = sorted(set(options["exclude_loan"]))
        if Loan.objects.filter(pk__in=excluded).count() != len(excluded):
            raise CommandError("An excluded loan ID does not exist.")
        changed_credit = ZERO
        ledger_entries = 0
        for loan in Loan.objects.select_for_update().exclude(pk__in=excluded).select_related("borrower").order_by("pk"):
            payments = list(Payment.objects.select_for_update().filter(loan=loan).order_by("payment_date", "pk"))
            settled = [p for p in payments if not p.is_void and not p.is_pending]
            principal = loan.principal_amount
            expected = loan.total_expected_amount
            deposit = loan.security_deposit_applied_amount
            if principal <= ZERO or expected < principal or deposit < ZERO or deposit > principal or any(not p.amount.is_finite() or p.amount <= ZERO for p in payments):
                skipped.append({"loan": loan.pk, "reason": "Invalid repayment schedule, deposit, or receipt amount; source evidence required."})
                continue
            if not payments:
                continue
            principal_remaining = principal - deposit
            roic_remaining = expected - principal
            needs_repair = (
                any(p.amount != p.principal_paid + p.roic_paid + p.customer_credit or min(p.principal_paid, p.roic_paid, p.customer_credit) < ZERO for p in settled)
                or sum((p.principal_paid for p in settled), ZERO) > principal_remaining
                or sum((p.roic_paid for p in settled), ZERO) > roic_remaining
                or any(p.principal_paid or p.roic_paid or p.customer_credit for p in payments if (p.is_void or p.is_pending) and not p.reversal_id)
            )
            if not needs_repair:
                continue
            for payment in payments:
                if payment.reversal_id:
                    continue  # Original approved reversal evidence must remain intact.
                old = (payment.principal_paid, payment.roic_paid, payment.customer_credit)
                if payment.is_void or payment.is_pending:
                    new = (ZERO, ZERO, ZERO)
                else:
                    new = allocate_receipt(payment.amount, principal=principal, expected=expected,
                                           principal_remaining=principal_remaining, roic_remaining=roic_remaining)
                    principal_remaining -= new[0]
                    roic_remaining -= new[1]
                if old == new:
                    continue
                changes.append({"loan": loan.pk, "payment": payment.pk, "cash_received": str(payment.amount),
                                "before": dict(zip(("principal", "interest", "customer_credit"), map(str, old))),
                                "after": dict(zip(("principal", "interest", "customer_credit"), map(str, new)))})
                changed_credit += new[2] - old[2]
                if options["apply"]:
                    payment.principal_paid, payment.roic_paid, payment.customer_credit = new
                    Payment.objects.filter(pk=payment.pk).update(principal_paid=new[0], roic_paid=new[1], customer_credit=new[2])
                    if new[2] or old[2] or JournalEntry.objects.filter(source_type="LOAN_REPAYMENT", source_key=f"payment:{payment.pk}:repayment").exists():
                        ensure_default_ledger_accounts()
                        ledger_entries += sync_repayment_entry(payment, historical_adjustment=True)
                    borrower_ids.add(loan.borrower_id)
            if options["apply"]:
                loan.refresh_status(save=True)
        for borrower in Borrower.objects.filter(pk__in=borrower_ids):
            borrower.refresh_status(save=True)
        report = {"applied": options["apply"] and not skipped, "changed_receipts": len(changes), "customer_credit_change": str(changed_credit),
                  "ledger_entries_created": ledger_entries, "changes": changes, "skipped": skipped, "excluded_loans": excluded}
        if options["report"]:
            path = Path(options["report"])
            with path.open("w", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2)
            path.chmod(0o600)
        action = ("Rolled back" if skipped else "Applied") if options["apply"] else "Preview only"
        self.stdout.write(f"{action}: {len(changes)} receipt allocation(s); customer credit change {changed_credit:,.2f}; {ledger_entries} ledger entry/entries; {len(skipped)} loan(s) require source review. Receipt amounts are preserved.")
        if skipped:
            raise CommandError("Some records require source evidence. See the private report for loan IDs.")
