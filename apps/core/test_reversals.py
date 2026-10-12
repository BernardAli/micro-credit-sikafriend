"""Approval boundaries, atomic ledger offsets and operational reconciliation."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Agent, PayrollLine, PayrollRun
from apps.accounting.models import AccountingPeriod, BankAccount, BankTransaction, Bill, Counterparty, Invoice, JournalEntry, create_journal_entry, get_ledger_account
from apps.accounting.repayments import sync_repayment_entry
from apps.accounting.views import _ensure_accounting_setup, _post_bank_transaction, _post_bill, _post_invoice, _sync_operational_entries
from apps.assets.models import AssetCategory, AssetItem, DepreciationLine, DepreciationRun
from apps.loans.financial_queries import with_deposit_totals
from apps.loans.models import Borrower, Loan, Payment, Portfolio, PortfolioAssignment, SecurityDeposit, SecurityDepositTransaction, SecurityDepositTransfer
from apps.loans.payment_gateway import initiate_repayment_collection, process_collection_callback, reconcile_collection
from apps.loans.statements import account_statement
from .approvals import approve_and_execute_request, reject_approval_request
from .models import ActivityLog, ApprovalRequest, TransactionReversal
from .reversals import describe_source, request_reversal, validate_source


@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", ARKESEL_API_KEY="")
class TransactionReversalTests(TestCase):
    reason = "Incorrect recorded receipt; cash evidence checked against the register."
    review = "Verified the original receipt and reconciliation; correction approved."

    def setUp(self):
        self.today = timezone.localdate()
        self.maker = User.objects.create_user("reversal-maker", is_staff=True, is_superuser=True)
        self.reviewer = User.objects.create_user("reversal-reviewer", is_staff=True)
        self.officer_user = User.objects.create_user("reversal-officer")
        self.customer_user = User.objects.create_user("reversal-customer")
        self.agent = Agent.objects.create(user=self.officer_user, agent_id="REV-AG", name="Reversal officer", phone="", location="Accra")
        self.portfolio = Portfolio.objects.get(number="01")
        PortfolioAssignment.objects.create(portfolio=self.portfolio, agent=self.agent)
        self.customer = Borrower.objects.create(user=self.customer_user, portfolio=self.portfolio, full_name="Reversal sample", national_id="REV-C", phone="", location="Accra", ghana_card_number="REV-CARD", group_name="Group", preferred_language="Twi")
        self.loan = self.new_loan()
        _ensure_accounting_setup()
        self.client.force_login(self.maker)

    def new_loan(self):
        loan = Loan(borrower=self.customer, agent_name=self.agent, amount=Decimal("1000"), duration_weeks=10, weekly_payment=Decimal("120"), start_date=self.today)
        loan._skip_new_loan_notifications = True
        loan.save()
        return loan

    def receipt(self, amount="120", posted=True):
        payment = Payment.objects.create(loan=self.loan, amount=Decimal(amount), payment_date=self.today-timedelta(days=2), reference="REV-SOURCE", collected_by=self.agent)
        if posted:
            sync_repayment_entry(payment, user=self.maker)
        return payment

    def submit(self, kind, source, user=None):
        return request_reversal(kind=kind, source_id=source.pk, user=user or self.maker, reason=self.reason, evidence_reference="RECON-001")

    def approve(self, approval):
        approve_and_execute_request(approval, self.reviewer, note=self.review)
        return TransactionReversal.objects.get(approval=approval)

    def entry(self, amount="100", source_type="GENERAL", source_key=""):
        return create_journal_entry(entry_date=self.today-timedelta(days=2), memo="Reversal original", source_type=source_type, source_key=source_key,
            lines=[{"account": get_ledger_account("1000"), "debit": Decimal(amount)}, {"account": get_ledger_account("3000"), "credit": Decimal(amount)}])

    def deposit(self, loan=None):
        return SecurityDeposit.objects.create(loan=loan or self.loan, borrower=self.customer, required_amount=Decimal("100"), enforce_before_disbursement=False)

    def deposit_transaction(self, deposit, action, amount="100", posted=True):
        tx = SecurityDepositTransaction.objects.create(deposit=deposit, action=action, amount=Decimal(amount), transaction_date=self.today-timedelta(days=2), reference="REV-DEP", approved_by=self.maker)
        if posted:
            liability, cash, principal = get_ledger_account("2065"), get_ledger_account("1000"), get_ledger_account("1300")
            debit, credit = (cash, liability) if action == "COLLECTION" else (liability, cash if action == "REFUND" else principal)
            tx.accounting_entry = create_journal_entry(entry_date=tx.transaction_date, memo="Deposit original", source_type="SECURITY_DEPOSIT", source_key=f"security-deposit:{tx.pk}",
                lines=[{"account": debit, "debit": tx.amount}, {"account": credit, "credit": tx.amount}])
            tx.save(update_fields=["accounting_entry"])
        return tx

    def test_request_does_not_change_money_until_independent_approval(self):
        payment = self.receipt()
        approval = self.submit("PAYMENT", payment, self.officer_user)
        payment.refresh_from_db()
        self.assertFalse(payment.is_void)
        self.assertEqual(self.loan.balance_amount, Decimal("1080"))
        self.assertEqual(get_ledger_account("1000").current_balance, Decimal("120"))
        reversal = self.approve(approval)
        payment.refresh_from_db()
        self.assertTrue(payment.is_void)
        self.assertEqual(payment.reversal, reversal)
        self.assertEqual(payment.amount, Decimal("120"))
        self.assertEqual((payment.principal_paid, payment.roic_paid), (Decimal("100"), Decimal("20")))
        self.assertEqual(self.loan.balance_amount, Decimal("1200"))
        self.assertEqual(get_ledger_account("1000").current_balance, Decimal("0"))
        self.assertTrue(ActivityLog.objects.filter(category="REVERSAL", action="executed", object_id=str(reversal.pk)).exists())

    def test_superuser_cannot_review_own_request_and_review_note_is_required(self):
        approval = self.submit("PAYMENT", self.receipt())
        with self.assertRaisesMessage(ValueError, "different administrator"):
            approve_and_execute_request(approval, self.maker, note=self.review)
        with self.assertRaisesMessage(ValueError, "review note"):
            approve_and_execute_request(approval, self.reviewer)
        with self.assertRaises(PermissionDenied):
            approve_and_execute_request(approval, self.officer_user, note=self.review)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "PENDING")

    def test_rejection_retains_balance_and_allows_a_new_request(self):
        payment = self.receipt()
        approval = self.submit("PAYMENT", payment)
        with self.assertRaises(ValueError):
            reject_approval_request(approval, self.reviewer)
        reject_approval_request(approval, self.reviewer, note="Receipt evidence does not support the requested correction.")
        self.assertFalse(TransactionReversal.objects.exists())
        payment.refresh_from_db()
        self.assertFalse(payment.is_void)
        self.assertNotEqual(self.submit("PAYMENT", payment).pk, approval.pk)

    def test_duplicate_requests_and_repeat_execution_are_blocked(self):
        payment = self.receipt()
        approval = self.submit("PAYMENT", payment)
        with self.assertRaisesMessage(ValueError, "already awaiting"):
            self.submit("PAYMENT", payment)
        self.approve(approval)
        count = JournalEntry.objects.count()
        with self.assertRaisesMessage(ValueError, "Only pending"):
            self.approve(approval)
        with self.assertRaisesMessage(ValueError, "already been reversed"):
            self.submit("PAYMENT", payment)
        self.assertEqual(JournalEntry.objects.count(), count)

    def test_changed_source_fails_without_reversing_anything(self):
        payment = self.receipt()
        approval = self.submit("PAYMENT", payment)
        Payment.objects.filter(pk=payment.pk).update(reference="Changed reference")
        with self.assertRaisesMessage(ValueError, "changed after submission"):
            self.approve(approval)
        approval.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(approval.status, "FAILED")
        self.assertFalse(payment.is_void)
        self.assertFalse(TransactionReversal.objects.exists())

    def test_posting_after_submission_requires_a_new_review(self):
        payment = self.receipt(posted=False)
        approval = self.submit("PAYMENT", payment)
        sync_repayment_entry(payment)
        with self.assertRaisesMessage(ValueError, "changed after submission"):
            self.approve(approval)
        self.assertFalse(TransactionReversal.objects.exists())

    def test_changed_loan_terms_require_a_new_review(self):
        payment = self.receipt()
        approval = self.submit("PAYMENT", payment)
        Loan.objects.filter(pk=self.loan.pk).update(weekly_payment=Decimal("132"))
        with self.assertRaisesMessage(ValueError, "changed after submission"):
            self.approve(approval)
        self.assertFalse(TransactionReversal.objects.exists())

    def test_closed_current_period_rolls_back_all_changes_and_retains_failure(self):
        payment = self.receipt()
        approval = self.submit("PAYMENT", payment)
        AccountingPeriod.objects.update(status="CLOSED")
        with self.assertRaisesMessage(ValueError, "closed accounting period"):
            self.approve(approval)
        approval.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(approval.status, "FAILED")
        self.assertFalse(payment.is_void)
        self.assertFalse(TransactionReversal.objects.exists())
        self.assertIsNone(JournalEntry.objects.get(source_type="LOAN_REPAYMENT").reversed_by_id)

    def test_closed_historical_period_retains_original_and_uses_today(self):
        payment = self.receipt()
        original = JournalEntry.objects.get(source_type="LOAN_REPAYMENT")
        AccountingPeriod.objects.create(name="Historical closed", start_date=original.entry_date, end_date=original.entry_date, status="CLOSED")
        reversal = self.approve(self.submit("PAYMENT", payment))
        original.refresh_from_db()
        self.assertEqual(original.status, "POSTED")
        self.assertEqual(original.reversed_by.entry_date, self.today)
        self.assertEqual(original.reversed_by.source_date, payment.payment_date)
        self.assertEqual(reversal.journal_entries.get(), original.reversed_by)

    def test_unposted_receipt_has_no_offset_and_never_posts_later(self):
        payment = self.receipt(posted=False)
        reversal = self.approve(self.submit("PAYMENT", payment))
        self.assertFalse(reversal.journal_entries.exists())
        payment.refresh_from_db()
        self.assertEqual(sync_repayment_entry(payment), 0)

    def test_credit_reversal_and_statement_running_balance_reconcile(self):
        payment = Payment(loan=self.loan, amount=Decimal("1500"), payment_date=self.today-timedelta(days=2))
        payment._legacy_import = True
        payment.save()
        sync_repayment_entry(payment)
        reversal = self.approve(self.submit("PAYMENT", payment))
        self.assertEqual(get_ledger_account("2066").current_balance, Decimal("0"))
        self.assertEqual(self.customer.customer_credit_balance, Decimal("0"))
        data = account_statement(Loan.objects.filter(pk=self.loan.pk))
        self.assertEqual([row["status"] for row in data["ledger"]], ["Reversed", "Reversal"])
        self.assertEqual([row["amount"] for row in data["ledger"]], [Decimal("1500"), Decimal("-1500")])
        self.assertEqual(data["ledger"][-1]["balance"], data["totals"]["outstanding"])
        self.assertEqual(data["totals"]["credit"], Decimal("0"))
        self.assertIn(reversal.reference, data["ledger"][-1]["description"])
        response = self.client.get(reverse("loans:loan_statement", args=[self.loan.pk]))
        self.assertContains(response, reversal.reference)
        self.assertContains(response, self.reason)
        self.assertEqual(self.client.get(reverse("loans:loan_statement_pdf", args=[self.loan.pk])).status_code, 200)
        self.client.force_login(self.customer_user)
        for url in [reverse("borrower:portal"),reverse("borrower:loan_detail",args=[self.loan.pk])]:
            self.assertContains(self.client.get(url),reversal.reference)

    def test_deposit_collection_dependency_guard_and_zero_effect_after_reversal(self):
        deposit = self.deposit()
        collection = self.deposit_transaction(deposit, "COLLECTION")
        refund = self.deposit_transaction(deposit, "REFUND", "50")
        with self.assertRaisesMessage(ValueError, "later movements"):
            self.submit("DEPOSIT", collection)
        self.approve(self.submit("DEPOSIT", refund))
        self.approve(self.submit("DEPOSIT", collection))
        self.assertEqual(deposit.held_amount, Decimal("0"))
        self.assertEqual(get_ledger_account("2065").current_balance, Decimal("0"))
        summary = with_deposit_totals(SecurityDeposit.objects.filter(pk=deposit.pk)).get()
        self.assertEqual(summary.collected, Decimal("0"))
        data = account_statement(Loan.objects.filter(pk=self.loan.pk))
        self.assertEqual(data["deposit_movements"][-1]["held"], Decimal("0"))
        self.assertEqual(len(data["deposit_movements"]), 4)

    def test_deposit_application_reversal_restores_principal_and_held_funds(self):
        deposit = self.deposit()
        self.deposit_transaction(deposit, "COLLECTION")
        application = self.deposit_transaction(deposit, "DEFAULT_APPLICATION")
        Loan.objects.filter(pk=self.loan.pk).update(security_deposit_applied_total=Decimal("100"))
        self.approve(self.submit("DEPOSIT", application))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.security_deposit_applied_amount, Decimal("0"))
        self.assertEqual(self.loan.balance_amount, Decimal("1200"))
        self.assertEqual(deposit.held_amount, Decimal("100"))
        data = account_statement(Loan.objects.filter(pk=self.loan.pk))
        self.assertEqual([row["applied"] for row in data["ledger"]], [Decimal("100"), Decimal("-100")])
        self.assertEqual(data["ledger"][-1]["balance"], data["totals"]["outstanding"])

    def test_transfer_reversal_restores_both_deposits_and_blocks_spent_funds(self):
        source, target = self.deposit(), self.deposit(self.new_loan())
        self.deposit_transaction(source, "COLLECTION")
        transfer = SecurityDepositTransfer.objects.create(source=source, target=target, amount=Decimal("100"), reference="REV-TRANSFER")
        application = self.deposit_transaction(target, "DEFAULT_APPLICATION", "50", posted=False)
        Loan.objects.filter(pk=target.loan_id).update(security_deposit_applied_total=Decimal("50"))
        with self.assertRaisesMessage(ValueError, "later movements"):
            self.submit("TRANSFER", transfer)
        self.approve(self.submit("DEPOSIT", application))
        reversal = self.approve(self.submit("TRANSFER", transfer))
        self.assertFalse(reversal.journal_entries.exists())
        self.assertEqual((source.held_amount, target.held_amount), (Decimal("100"), Decimal("0")))
        summaries = {row.pk: row for row in with_deposit_totals(SecurityDeposit.objects.all())}
        self.assertEqual(summaries[target.pk].incoming, Decimal("0"))
        self.assertEqual(summaries[source.pk].outgoing, Decimal("0"))
        data = account_statement(Loan.objects.filter(borrower=self.customer))
        self.assertEqual(data["totals"]["deposit_held"], Decimal("100"))

    def test_bank_transfer_offsets_both_accounts_and_retains_original(self):
        bank = BankAccount.objects.create(name="Source bank", linked_account=get_ledger_account("1010"))
        target = BankAccount.objects.create(name="Target bank", linked_account=get_ledger_account("1005"))
        tx = BankTransaction.objects.create(bank_account=bank, target_bank_account=target, transaction_type="TRANSFER_OUT", amount=Decimal("100"), transaction_date=self.today)
        _post_bank_transaction(tx, self.maker)
        self.approve(self.submit("BANK", tx))
        tx.refresh_from_db()
        self.assertIsNotNone(tx.posted_entry_id)
        self.assertIsNotNone(tx.reversal_id)
        self.assertEqual(get_ledger_account("1010").current_balance, Decimal("0"))
        self.assertEqual(get_ledger_account("1005").current_balance, Decimal("0"))

    def test_unsettled_invoice_and_bill_are_voided_and_removed_from_aging(self):
        party = Counterparty.objects.create(name="Example company", counterparty_type="OTHER")
        for kind, Model, number, accounts, post in [
            ("INVOICE", Invoice, "invoice_number", {"income_account":get_ledger_account("4000"), "receivable_account":get_ledger_account("1300")}, _post_invoice),
            ("BILL", Bill, "bill_number", {"expense_account":get_ledger_account("5000"), "payable_account":get_ledger_account("2060")}, _post_bill)]:
            with self.subTest(kind=kind):
                document = Model.objects.create(counterparty=party, **{number:"REV-DOC"}, issue_date=self.today, due_date=self.today, amount=Decimal("100"), description="Recorded in error", settlement_account=get_ledger_account("1010"), **accounts)
                post(document, self.maker)
                self.approve(self.submit(kind, document))
                document.refresh_from_db()
                self.assertEqual(document.status, "VOID")
                self.assertEqual(document.outstanding_amount, Decimal("0"))
                self.assertIsNotNone(document.posted_entry.reversed_by_id)

    def test_settled_invoice_is_blocked(self):
        party = Counterparty.objects.create(name="Paid company", counterparty_type="CUSTOMER")
        invoice = Invoice.objects.create(counterparty=party, invoice_number="PAID-DOC", due_date=self.today, amount=Decimal("100"), description="Paid", status="PAID", income_account=get_ledger_account("4000"), receivable_account=get_ledger_account("1300"), settlement_account=get_ledger_account("1010"))
        _post_invoice(invoice, self.maker)
        with self.assertRaisesMessage(ValueError, "unsettled"):
            self.submit("INVOICE", invoice)

    def test_paid_payroll_cannot_cancel_directly_and_reversal_retains_lines(self):
        run = PayrollRun.objects.create(title="Paid sample payroll", period_start=self.today, period_end=self.today, pay_date=self.today, paid_at=timezone.now(), status="PAID")
        PayrollLine.objects.create(run=run, employee=self.agent, base_salary=Decimal("1000"), gross_pay=Decimal("1000"), other_deductions=Decimal("200"), total_deductions=Decimal("200"), net_pay=Decimal("800"))
        entry = create_journal_entry(entry_date=self.today, memo="Payroll", source_type="PAYROLL", source_key=f"payroll:{run.pk}:paid", lines=[
            {"account":get_ledger_account("5000"), "debit":Decimal("1000")}, {"account":get_ledger_account("2060"), "credit":Decimal("200")}, {"account":get_ledger_account("1010"), "credit":Decimal("800")}])
        response = self.client.post(reverse("payroll_run_detail", args=[run.pk]), {"action":"cancel"})
        self.assertRedirects(response, reverse("core:reversal_request", args=["PAYROLL",run.pk]))
        run.refresh_from_db()
        self.assertEqual(run.status, "PAID")
        run.status = "CANCELLED"
        with self.assertRaises(ValidationError):
            run.save()
        run.refresh_from_db()
        original_paid_at = run.paid_at
        self.approve(self.submit("PAYROLL", run))
        run.refresh_from_db()
        self.assertEqual(run.status, "CANCELLED")
        self.assertEqual(run.paid_at, original_paid_at)
        self.assertEqual(run.lines.count(), 1)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.reversed_by_id)
        response = self.client.get(reverse("agent_statement", args=[self.agent.pk]))
        self.assertEqual(response.context["earnings"]["net"], Decimal("0"))
        self.assertContains(response, run.reversal.reference)

    def test_manual_journal_reverses_but_operational_postings_cannot_bypass_source_controls(self):
        entry = self.entry()
        reversal = self.approve(self.submit("JOURNAL", entry))
        entry.refresh_from_db()
        self.assertIsNotNone(entry.reversed_by_id)
        self.assertContains(self.client.get(reverse("core:reversals"), {"type":"JOURNAL", "state":"all"}), reversal.reference)
        with self.assertRaises(ValueError):
            self.submit("JOURNAL", entry.reversed_by)
        for source_type in ["LOAN_DISBURSEMENT", "LOAN_REPAYMENT", "SECURITY_DEPOSIT", "PAYROLL", "ADJUSTMENT"]:
            with self.subTest(source_type=source_type), self.assertRaisesMessage(ValueError, "source transaction"):
                self.submit("JOURNAL", self.entry(source_type=source_type))

    def test_linked_manual_journal_must_reverse_from_its_bank_source(self):
        entry = self.entry()
        bank = BankAccount.objects.create(name="Linked bank", linked_account=get_ledger_account("1000"))
        tx = BankTransaction.objects.create(bank_account=bank, transaction_type="DEPOSIT", amount=Decimal("100"), posted_entry=entry)
        with self.assertRaisesMessage(ValueError, "operational source"):
            self.submit("JOURNAL", entry)
        with self.assertRaises(ProtectedError):
            bank.delete()
        self.approve(self.submit("BANK", tx))

    def test_source_posting_must_match_the_recorded_amount(self):
        payment = self.receipt()
        entry = JournalEntry.objects.get(source_type="LOAN_REPAYMENT")
        entry.lines.filter(debit__gt=0).update(debit=Decimal("60"))
        entry.lines.filter(credit__gt=0).update(credit=Decimal("30"))
        with self.assertRaisesMessage(ValueError, "does not match"):
            self.submit("PAYMENT", payment)
        self.assertFalse(ApprovalRequest.objects.filter(workflow_type="TRANSACTION_REVERSAL").exists())

    def test_settled_receipt_financial_fields_cannot_be_amended_without_reversal(self):
        payment = self.receipt()
        for field, value in [("amount",Decimal("60")),("payment_date",self.today),("payment_method","BANK"),("is_pending",True)]:
            payment.refresh_from_db()
            setattr(payment,field,value)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                payment.save()

    def test_depreciation_dependency_guard_and_restored_asset_book_value(self):
        accounts = {"asset_account":get_ledger_account("1500"), "accumulated_depreciation_account":get_ledger_account("1590"), "depreciation_expense_account":get_ledger_account("5091"), "maintenance_expense_account":get_ledger_account("5092")}
        category = AssetCategory.objects.create(code="REV-ASSET", name="Reversal assets", **accounts)
        asset = AssetItem.objects.create(asset_code="REV-A1", name="Equipment", category=category, acquisition_date=self.today, purchase_cost=Decimal("1000"), useful_life_months=10, status="ACTIVE", **accounts)
        runs = []
        for index in range(2):
            entry = create_journal_entry(entry_date=self.today, memo="Depreciation", source_type="ADJUSTMENT", source_key=f"asset:depreciation:{index}", lines=[{"account":accounts["depreciation_expense_account"], "debit":Decimal("100")}, {"account":accounts["accumulated_depreciation_account"], "credit":Decimal("100")}])
            run = DepreciationRun.objects.create(title=f"Depreciation {index}", period_start=self.today, period_end=self.today, posting_date=self.today, posted_entry=entry)
            DepreciationLine.objects.create(run=run, asset=asset, depreciation_amount=Decimal("100"))
            runs.append(run)
        with self.assertRaisesMessage(ValueError, "Later depreciation"):
            self.submit("DEPRECIATION", runs[0])
        self.approve(self.submit("DEPRECIATION", runs[1]))
        self.approve(self.submit("DEPRECIATION", runs[0]))
        self.assertEqual(asset.posted_accumulated_depreciation, Decimal("0"))
        self.assertEqual(asset.net_book_value, Decimal("1000"))

    def test_approval_failure_after_offset_rolls_back_everything(self):
        payment = self.receipt()
        approval = self.submit("PAYMENT", payment)
        with patch("apps.loans.models.Loan.refresh_status", side_effect=ValueError("Forced status failure")):
            with self.assertRaisesMessage(ValueError, "Forced status failure"):
                self.approve(approval)
        payment.refresh_from_db()
        self.assertFalse(payment.is_void)
        self.assertFalse(TransactionReversal.objects.exists())
        self.assertIsNone(JournalEntry.objects.get(source_type="LOAN_REPAYMENT").reversed_by_id)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "FAILED")

    def test_provider_retries_and_reconciliation_do_not_restore_reversed_receipt(self):
        collection = initiate_repayment_collection(loan=self.loan, amount=Decimal("120"), payment_method="BANK")
        _collection, payment, _created = process_collection_callback(collection, provider_status="success", payload={"provider_reference":"REV-PROVIDER"})
        collection.refresh_from_db()
        collection.reconciliation_notes = "Initial staff verification retained."
        collection.save(update_fields=["reconciliation_notes"])
        self.approve(self.submit("PAYMENT", payment))
        collection.refresh_from_db()
        self.assertEqual(collection.status, "CANCELLED")
        self.assertIn("Initial staff verification retained.",collection.reconciliation_notes)
        process_collection_callback(collection, provider_status="success")
        reconcile_collection(collection, reviewer=self.reviewer, force=True)
        collection.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(collection.status, "CANCELLED")
        self.assertTrue(payment.is_void)
        self.assertEqual(Payment.objects.count(), 1)

    def test_source_permission_csrf_withdrawal_and_admin_review_views(self):
        payment = self.receipt()
        url = reverse("core:reversal_request", args=["PAYMENT", payment.pk])
        self.client.force_login(self.customer_user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:reversals")).status_code, 403)
        self.client.force_login(self.officer_user)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:reversals"), {"type":"PAYROLL"}).status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.maker)
        self.assertEqual(csrf_client.post(url, {"reason":self.reason,"verified":"on"}).status_code, 403)
        self.assertFalse(ApprovalRequest.objects.filter(workflow_type="TRANSACTION_REVERSAL").exists())
        response = self.client.post(url, {"reason":self.reason,"verified":"on"})
        approval = ApprovalRequest.objects.get(workflow_type="TRANSACTION_REVERSAL")
        detail = reverse("core:reversal_detail", args=[approval.pk])
        self.assertRedirects(response, detail)
        self.assertEqual(self.client.post(detail, {"action":"approve","note":self.review}).status_code, 403)
        self.assertRedirects(self.client.post(detail, {"action":"cancel"}), detail)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "CANCELLED")
        approval = self.submit("PAYMENT", payment, self.officer_user)
        self.client.force_login(self.reviewer)
        detail = reverse("core:reversal_detail", args=[approval.pk])
        self.assertContains(self.client.get(detail), "Offset debit")
        self.assertRedirects(self.client.post(detail, {"action":"approve","note":self.review}), detail)
        self.assertContains(self.client.get(detail), "REV-")

    def test_revoked_portfolio_access_and_unknown_roles_are_denied(self):
        payment = self.receipt()
        PortfolioAssignment.objects.filter(agent=self.agent).update(ended_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.submit("PAYMENT", payment, self.officer_user)
        self.client.force_login(self.officer_user)
        self.assertEqual(self.client.get(reverse("core:reversal_request", args=["PAYMENT",payment.pk])).status_code,403)

    def test_customer_transfer_does_not_grant_access_to_an_old_portfolio_receipt(self):
        payment = self.receipt()
        other_portfolio, _created = Portfolio.objects.get_or_create(number="90",defaults={"name":"Other portfolio"})
        other_user = User.objects.create_user("new-portfolio-officer")
        other_agent = Agent.objects.create(user=other_user,agent_id="REV-OTHER",name="Other officer",phone="",location="Accra")
        PortfolioAssignment.objects.create(portfolio=other_portfolio,agent=other_agent)
        Borrower.objects.filter(pk=self.customer.pk).update(portfolio=other_portfolio)
        with self.assertRaises(PermissionDenied):
            self.submit("PAYMENT",payment,other_user)
        approval = self.submit("PAYMENT",payment,self.officer_user)
        self.assertEqual(approval.status,"PENDING")
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(reverse("core:reversal_detail",args=[approval.pk])).status_code,403)

    def test_reversed_evidence_and_financial_admin_shortcuts_are_read_only(self):
        payment = self.receipt()
        payment.is_void = True
        with self.assertRaises(ValidationError):
            payment.save()
        payment.refresh_from_db()
        with self.assertRaises(ValidationError):
            payment.delete()
        reversal = self.approve(self.submit("PAYMENT", payment))
        payment.refresh_from_db()
        payment.is_void = False
        with self.assertRaises(ValidationError):
            payment.save()
        reversal.reason = "Changed evidence"
        with self.assertRaises(ValidationError):
            reversal.save()
        request = type("Request", (), {"user":self.maker})()
        for Model in [Payment, ApprovalRequest, TransactionReversal, BankTransaction, Invoice, Bill, PayrollRun, DepreciationRun]:
            controller = admin.site._registry[Model]
            self.assertFalse(controller.has_change_permission(request))
            self.assertFalse(controller.has_delete_permission(request))
        with self.assertRaises(ProtectedError):
            self.loan.delete()
        self.assertEqual(self.client.get(reverse("admin:loans_payment_change", args=[payment.pk])).status_code, 200)

    def test_historical_repair_preserves_reversal_evidence(self):
        payment = self.receipt()
        self.approve(self.submit("PAYMENT", payment))
        payment.refresh_from_db()
        components = payment.principal_paid, payment.roic_paid, payment.customer_credit
        call_command("repair_payment_allocations", apply=True, stdout=StringIO())
        payment.refresh_from_db()
        self.assertEqual((payment.principal_paid, payment.roic_paid, payment.customer_credit), components)

    def test_all_registers_render_with_search_pagination_and_history(self):
        payment = self.receipt()
        self.approve(self.submit("PAYMENT", payment))
        for kind in ["PAYMENT", "DEPOSIT", "TRANSFER", "BANK", "INVOICE", "BILL", "PAYROLL", "JOURNAL", "DEPRECIATION"]:
            with self.subTest(kind=kind):
                response = self.client.get(reverse("core:reversals"), {"type":kind,"state":"all","q":"REV"})
                self.assertEqual(response.status_code,200)
                self.assertContains(response,"Transaction reversals")
        response = self.client.get(reverse("core:approvals"))
        self.assertContains(response,"Review transaction & reversal evidence")
