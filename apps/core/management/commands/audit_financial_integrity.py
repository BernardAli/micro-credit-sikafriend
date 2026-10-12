"""Read-only checks for historical data affected by the repaired workflows."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.accounting.models import JournalEntry
from apps.loans.models import Loan, Payment, RepaymentCollection


class Command(BaseCommand):
    help = "Audit historical balances and postings without changing records. Reports use record IDs, not customer identities."

    def add_arguments(self, parser):
        parser.add_argument("--report", metavar="FILE")
        parser.add_argument("--fail", action="store_true", help="Return an error when findings need management review.")

    def handle(self, *args, **options):
        findings = []
        for payment in Payment.objects.filter(is_void=False, is_pending=False).iterator():
            if payment.amount != payment.principal_paid + payment.roic_paid + payment.customer_credit or min(payment.principal_paid, payment.roic_paid, payment.customer_credit) < 0:
                findings.append({"record": "Payment", "id": payment.pk, "issue": "Received amount differs from principal, interest, and held customer credit."})
        for loan in Loan.objects.prefetch_related("payments").iterator(chunk_size=200):
            if loan.balance_amount != loan.principal_outstanding + loan.roic_outstanding:
                findings.append({"record": "Loan", "id": loan.pk, "issue": "Balance differs from principal plus interest outstanding."})
            if loan.total_paid_amount + loan.security_deposit_applied_amount > loan.total_expected_amount:
                findings.append({"record": "Loan", "id": loan.pk, "issue": "Recorded settlements exceed expected repayment."})
        for collection in RepaymentCollection.objects.iterator():
            if (collection.status == "RECONCILED") != bool(collection.payment_id):
                findings.append({"record": "RepaymentCollection", "id": collection.pk, "issue": "Collection status disagrees with its posted payment."})
        duplicates = RepaymentCollection.objects.filter(payment__isnull=False).exclude(provider_reference="").values("provider", "provider_reference").annotate(count=Count("pk")).filter(count__gt=1)
        for group in duplicates:
            ids = list(RepaymentCollection.objects.filter(provider=group["provider"], provider_reference=group["provider_reference"], payment__isnull=False).values_list("pk", flat=True))
            findings.append({"record": "RepaymentCollection", "ids": ids, "issue": "Multiple posted collections share a provider receipt."})
        for entry in JournalEntry.objects.filter(status="POSTED").prefetch_related("lines").iterator(chunk_size=200):
            lines = list(entry.lines.all())
            if sum(line.debit for line in lines) != sum(line.credit for line in lines):
                findings.append({"record": "JournalEntry", "id": entry.pk, "issue": "Posted journal is unbalanced."})
            if entry.source_type == "LOAN_REPAYMENT" and not entry.reversed_by_id:
                parts = entry.source_key.split(":")
                if len(parts) == 3 and parts[0] == "payment" and parts[1].isdigit():
                    payment = Payment.objects.filter(pk=int(parts[1])).first()
                    if payment is None or payment.is_void or payment.is_pending:
                        findings.append({"record": "JournalEntry", "id": entry.pk, "issue": "Posting needs reversal because the repayment was removed, voided, or returned to pending."})
        if options["report"]:
            path = Path(options["report"])
            with path.open("w", encoding="utf-8") as stream:
                json.dump(findings, stream, indent=2)
            path.chmod(0o600)
        self.stdout.write(f"Financial integrity audit: {len(findings)} finding(s). No records changed.")
        for finding in findings:
            self.stdout.write(f"{finding['record']} {finding.get('id', finding.get('ids'))}: {finding['issue']}")
        if findings and options["fail"]:
            raise CommandError("Historical records require management reconciliation. Use the report before making corrections.")
