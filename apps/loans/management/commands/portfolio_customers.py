"""Review/export customer ownership and replay confirmed assignments on another database."""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.loans.models import Borrower, Portfolio
from apps.loans.portfolios import assign_customer


class Command(BaseCommand):
    help = "Export customer assignments, or validate/apply a reviewed CSV. Import defaults to a rollback-only dry run."

    def add_arguments(self, parser):
        operation = parser.add_mutually_exclusive_group(required=True)
        operation.add_argument("--export", metavar="FILE")
        operation.add_argument("--import", dest="import_file", metavar="FILE")
        parser.add_argument("--apply", action="store_true", help="Commit validated assignments; otherwise roll back every change.")

    def handle(self, *args, **options):
        if options["export"]:
            path = Path(options["export"])
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["borrower_pk", "legacy_reference", "full_name", "portfolio_number", "customer_id"])
                for borrower in Borrower.objects.select_related("portfolio").order_by("pk"):
                    writer.writerow([borrower.pk, borrower.legacy_borrower_id or borrower.borrower_id, borrower.full_name,
                                     borrower.portfolio.number if borrower.portfolio_id else "",
                                     borrower.borrower_id if hasattr(borrower, "identity") else ""])
            path.chmod(0o600)
            self.stdout.write(f"Exported {Borrower.objects.count()} customers to {path}.")
            return
        try:
            with Path(options["import_file"]).open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                required = {"borrower_pk", "legacy_reference", "full_name", "portfolio_number", "customer_id"}
                if not required.issubset(reader.fieldnames or []):
                    raise CommandError("CSV is missing required columns. Export a template first.")
                rows = list(reader)
            seen = set()
            changed = skipped = 0
            with transaction.atomic():
                for index, row in enumerate(rows, start=2):
                    try:
                        pk = int(row["borrower_pk"])
                        if pk in seen:
                            raise ValueError("Duplicate customer row.")
                        seen.add(pk)
                        borrower = Borrower.objects.select_for_update().get(pk=pk)
                        reference = row["legacy_reference"].strip()
                        if reference not in {borrower.borrower_id, borrower.legacy_borrower_id} or row["full_name"].strip() != borrower.full_name.strip():
                            raise ValueError("Customer identity differs from the target database; refusing to assign this row.")
                        number = row["portfolio_number"].strip()
                        if not number:
                            skipped += 1
                            continue
                        number = number.zfill(2)
                        portfolio = Portfolio.objects.get(number=number, is_active=True)
                        customer_id = row["customer_id"].strip().upper()
                        assign_customer(borrower, portfolio, customer_id=customer_id)
                        changed += 1
                    except Exception as exc:
                        raise CommandError(f"Row {index}: {exc}") from exc
                if not options["apply"]:
                    transaction.set_rollback(True)
            mode = "Applied" if options["apply"] else "Dry run passed (all changes rolled back):"
            self.stdout.write(f"{mode} {changed} assignment(s); {skipped} unreviewed row(s) skipped.")
        except OSError as exc:
            raise CommandError(str(exc)) from exc
