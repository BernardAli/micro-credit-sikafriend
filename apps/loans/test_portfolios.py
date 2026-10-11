import csv
from io import StringIO
import tempfile
from pathlib import Path
from unittest.mock import patch
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Agent
from apps.accounts.views import _employee_period_metrics
from apps.communication.views import _build_ussd_response
from .borrower_imports import import_borrower_rows
from .models import Borrower, CustomerIdentity, Loan, Payment, Portfolio, PortfolioAssignment
from .portfolios import assign_customer, agent_can_access, set_portfolio_agents


class PortfolioTests(TestCase):
    def setUp(self):
        self.portfolio = Portfolio.objects.get(number="07")
        self.other = Portfolio.objects.get(number="01")
        self.admin = User.objects.create_user("portfolio-admin", is_staff=True)
        self.user = User.objects.create_user("portfolio-officer")
        self.agent = Agent.objects.create(user=self.user, agent_id="PF-1", name="Officer One", phone="0240000000", location="Accra")
        self.replacement_user = User.objects.create_user("replacement")
        self.replacement = Agent.objects.create(user=self.replacement_user, agent_id="PF-2", name="Officer Two", phone="0240000001", location="Accra")
        set_portfolio_agents(self.portfolio, [self.agent], actor=self.admin)

    def customer(self, suffix="1", **kwargs):
        values = dict(portfolio=self.portfolio, full_name=f"Customer {suffix}", national_id=f"N-{suffix}", phone="0241111111", location="Accra", ghana_card_number=f"G-{suffix}", group_name="Traders", preferred_language="Twi")
        values.update(kwargs)
        return Borrower.objects.create(**values)

    def loan(self, borrower):
        loan = Loan(borrower=borrower, agent_name=self.agent, amount="1000", duration_weeks=10, weekly_payment="120")
        loan._skip_new_loan_notifications = True
        loan.save()
        return loan

    def test_seeds_all_named_portfolios(self):
        self.assertEqual(Portfolio.objects.count(), 11)
        self.assertEqual(self.portfolio.name, "Wisdom")

    def test_automatic_ids_and_legacy_reference(self):
        first = self.customer(borrower_id="OLD-1")
        second = self.customer("2")
        self.assertEqual(first.borrower_id, "SF070001")
        self.assertEqual(first.legacy_borrower_id, "OLD-1")
        self.assertEqual(second.borrower_id, "SF070002")
        self.assertEqual(CustomerIdentity.objects.count(), 2)

    def test_customer_number_1000_and_capacity(self):
        Portfolio.objects.filter(pk=self.portfolio.pk).update(next_customer_number=1000)
        self.assertEqual(self.customer().borrower_id, "SF071000")
        with self.assertRaises(ValidationError):
            self.customer("2")
        self.assertEqual(Borrower.objects.count(), 1)

    def test_new_customer_requires_portfolio(self):
        with self.assertRaises(ValidationError):
            self.customer(portfolio=None)

    def test_id_cannot_be_edited(self):
        borrower = self.customer()
        borrower.borrower_id = "SF070777"
        with self.assertRaises(ValidationError):
            borrower.save()
        borrower.refresh_from_db()
        self.assertEqual(borrower.borrower_id, "SF070001")

    def test_deleted_customer_id_cannot_be_reused(self):
        borrower = self.customer()
        borrower.delete()
        self.assertIsNone(CustomerIdentity.objects.get(customer_id="SF070001").borrower)
        with self.assertRaises(ValidationError):
            self.customer("2", borrower_id="SF070001")
        self.assertEqual(self.customer("3").borrower_id, "SF070002")

    def test_portfolio_number_is_permanent_and_rename_preserves_counter(self):
        self.customer()
        self.portfolio.name = "Renamed Wisdom"
        self.portfolio.save()
        self.assertEqual(self.customer("2").borrower_id, "SF070002")
        self.portfolio.number = "12"
        with self.assertRaises(ValidationError):
            self.portfolio.save()

    def test_transfer_preserves_id_and_moves_loans(self):
        borrower = self.customer()
        loan = self.loan(borrower)
        borrower = assign_customer(borrower, self.other, actor=self.admin)
        loan.refresh_from_db()
        self.assertEqual(borrower.borrower_id, "SF070001")
        self.assertEqual(loan.portfolio, self.other)
        self.assertEqual(borrower.identity.portfolio, self.portfolio)

    def test_agent_replacement_changes_access_and_retains_history(self):
        borrower = self.customer()
        loan = self.loan(borrower)
        self.assertTrue(agent_can_access(self.agent, loan))
        set_portfolio_agents(self.portfolio, [self.replacement], actor=self.admin)
        self.assertFalse(agent_can_access(self.agent, loan))
        self.assertTrue(agent_can_access(self.replacement, loan))
        loan.refresh_from_db()
        self.assertEqual(loan.agent_name, self.agent)
        self.assertEqual(self.portfolio.assignments.filter(ended_at__isnull=False).count(), 1)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("loans:loan_detail", args=[loan.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse("loans:loan_statement", args=[loan.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("loans:loan_statement_pdf", args=[loan.pk])).status_code, 404)
        self.client.force_login(self.replacement_user)
        self.assertEqual(self.client.get(reverse("loans:loan_detail", args=[loan.pk])).status_code, 200)

    def test_multiple_agents_and_multiple_portfolios(self):
        set_portfolio_agents(self.portfolio, [self.agent, self.replacement])
        set_portfolio_agents(self.other, [self.agent])
        self.assertTrue(agent_can_access(self.replacement, self.customer()))
        self.assertTrue(agent_can_access(self.agent, self.customer("2", portfolio=self.other)))

    def test_customer_without_loans_is_visible_to_assigned_officer(self):
        borrower = self.customer()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("loans:borrower_detail", args=[borrower.pk])).status_code, 200)

    def test_payment_collector_and_payroll_survive_reassignment(self):
        from django.utils import timezone
        from decimal import Decimal
        borrower = self.customer()
        loan = self.loan(borrower)
        first = Payment.objects.create(loan=loan, amount="120", submitted_by=self.user)
        set_portfolio_agents(self.portfolio, [self.replacement])
        second = Payment.objects.create(loan=loan, amount="120", submitted_by=self.replacement_user)
        self.assertEqual(first.collected_by, self.agent)
        self.assertEqual(second.collected_by, self.replacement)
        today = timezone.localdate()
        self.assertEqual(_employee_period_metrics(self.agent, today, today)["collections"], Decimal("120.00"))
        self.assertEqual(_employee_period_metrics(self.replacement, today, today)["collections"], Decimal("120.00"))

    def test_ussd_customer_lookup_requires_registered_phone(self):
        borrower = self.customer()
        self.loan(borrower)
        self.assertIn("CON", _build_ussd_response(borrower.phone, "6"))
        self.assertIn("Balance:", _build_ussd_response(borrower.phone, "6*" + borrower.borrower_id))
        self.assertIn("could not be verified", _build_ussd_response("0242222222", "6*" + borrower.borrower_id))

    def test_staff_management_pages_and_csv(self):
        self.customer()
        self.client.force_login(self.admin)
        for name, args in (("portfolio_list", []), ("portfolio_update", [self.portfolio.pk]), ("portfolio_customers", []), ("portfolio_export", [])):
            self.assertEqual(self.client.get(reverse("loans:" + name, args=args)).status_code, 200)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("loans:portfolio_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("loans:portfolio_update", args=[self.portfolio.pk])).status_code, 302)

    def test_import_generates_id_and_updates_using_legacy_reference(self):
        row = dict(borrower_id="LEGACY-IMPORT", portfolio_number="07", full_name="Imported", national_id="IM-N", phone="0241111111", location="Accra", ghana_card_number="IM-G", group_name="Traders")
        result = import_borrower_rows([row])
        self.assertEqual(result["created"], 1, result["errors"])
        row["full_name"] = "Updated"
        result = import_borrower_rows([row], import_mode="update_existing")
        self.assertEqual(result["updated"], 1, result["errors"])
        self.assertEqual(Borrower.objects.get().borrower_id, "SF070001")

    def test_csv_dry_run_apply_and_identity_mismatch_rollback(self):
        borrower = self.customer()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assignments.csv"
            call_command("portfolio_customers", export=str(path), stdout=StringIO())
            rows = list(csv.DictReader(path.open()))
            rows[0]["portfolio_number"] = "01"
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            call_command("portfolio_customers", import_file=str(path), stdout=StringIO())
            borrower.refresh_from_db()
            self.assertEqual(borrower.portfolio, self.portfolio)
            call_command("portfolio_customers", import_file=str(path), apply=True, stdout=StringIO())
            call_command("portfolio_customers", import_file=str(path), apply=True, stdout=StringIO())
            borrower.refresh_from_db()
            self.assertEqual(borrower.portfolio, self.other)
            self.assertEqual(borrower.borrower_id, "SF070001")
            rows[0]["full_name"] = "Wrong customer"
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaises(CommandError):
                call_command("portfolio_customers", import_file=str(path), apply=True, stdout=StringIO())

    def test_legacy_assignment_imports_already_issued_id_and_preserves_reference(self):
        borrower = Borrower(borrower_id="OLD-LEGACY", full_name="Legacy Customer", national_id="LEG-N", phone="0241111111", location="Accra", ghana_card_number="LEG-G", group_name="Traders", preferred_language="Twi")
        Borrower.objects.bulk_create([borrower])  # Simulate a pre-upgrade database row.
        borrower = Borrower.objects.get(borrower_id="OLD-LEGACY")
        borrower = assign_customer(borrower, self.portfolio, customer_id="SF070428")
        self.assertEqual(borrower.legacy_borrower_id, "OLD-LEGACY")
        self.assertEqual(borrower.borrower_id, "SF070428")
        self.assertEqual(self.customer("next").borrower_id, "SF070429")

    def test_legacy_assignment_error_rolls_back_original_id(self):
        borrower = Borrower(borrower_id="OLD-LEGACY", full_name="Legacy Customer", national_id="LEG-N", phone="0241111111", location="Accra", ghana_card_number="LEG-G", group_name="Traders", preferred_language="Twi")
        Borrower.objects.bulk_create([borrower])
        borrower = Borrower.objects.get(borrower_id="OLD-LEGACY")
        with self.assertRaises(ValidationError):
            assign_customer(borrower, self.portfolio, customer_id="SF010428")
        borrower.refresh_from_db()
        self.assertEqual(borrower.borrower_id, "OLD-LEGACY")
        self.assertIsNone(borrower.portfolio)

    def test_loan_form_rejects_customer_from_another_portfolio(self):
        from .forms import LoanForm
        borrower = self.customer(portfolio=self.other)
        form = LoanForm({"borrower": borrower.pk, "agent_name": self.replacement.pk, "amount": "1000", "weekly_payment": "120", "duration_weeks": "10", "start_date": "2026-10-11", "repayment_frequency": "WEEKLY"}, agent_override=self.agent)
        self.assertFalse(form.is_valid())
        self.assertIn("borrower", form.errors)

    def test_collection_report_credits_the_actual_collector(self):
        from django.utils import timezone
        from .reports import build_report, resolve_report_period
        borrower = self.customer()
        loan = self.loan(borrower)
        set_portfolio_agents(self.portfolio, [self.replacement])
        Payment.objects.create(loan=loan, amount="120", submitted_by=self.replacement_user)
        today = timezone.localdate().isoformat()
        report = build_report("collections", resolve_report_period({"period_type": "custom", "date_from": today, "date_to": today}))
        report_text = str(report)
        self.assertIn(self.replacement.name, report_text)
        self.assertNotIn(self.agent.name, report_text)
        self.assertIn(borrower.borrower_id, report_text)


@skipUnless(connection.vendor == "mysql", "Row lock concurrency is verified on MySQL.")
class ConcurrentCustomerIDTests(TransactionTestCase):
    def test_parallel_registrations_issue_unique_numbers(self):
        portfolio, _ = Portfolio.objects.get_or_create(number="07", defaults={"name": "Wisdom"})
        def register(number):
            close_old_connections()
            try:
                borrower = Borrower.objects.create(portfolio_id=portfolio.pk, full_name=f"Concurrent {number}", national_id=f"CON-N-{number}", ghana_card_number=f"CON-G-{number}", phone="0240000000", location="Accra", group_name="Traders", preferred_language="Twi")
                return borrower.borrower_id
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=4) as workers:
            ids = list(workers.map(register, range(8)))
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(sorted(ids), [f"SF07{number:04d}" for number in range(1, 9)])
