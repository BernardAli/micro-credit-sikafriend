"""Exercise row locking on MySQL/PostgreSQL rather than SQLite's no-op locks."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.contrib.auth.models import User
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature

from apps.accounts.models import Agent
from apps.core.approvals import approve_and_execute_request
from apps.core.models import ApprovalRequest
from apps.loans.models import Borrower, Loan, Payment, Portfolio, PortfolioAssignment, RepaymentCollection
from apps.loans.payment_gateway import initiate_repayment_collection, process_collection_callback
from apps.loans.views import _loan_approval_payload


@skipUnlessDBFeature('has_select_for_update')
@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', ARKESEL_API_KEY='')
class FinancialConcurrencyTests(TransactionTestCase):
    def setUp(self):
        portfolio = Portfolio.objects.create(number='80', name='Concurrency')
        self.agent = Agent.objects.create(agent_id='concurrency', name='Officer', phone='', location='Accra')
        PortfolioAssignment.objects.create(portfolio=portfolio, agent=self.agent)
        self.borrower = Borrower.objects.create(portfolio=portfolio, full_name='Customer', national_id='concurrency', phone='', location='Accra', ghana_card_number='concurrency', group_name='Group', preferred_language='Twi')
        self.loan = Loan.objects.create(borrower=self.borrower, agent_name=self.agent, amount=Decimal('1000'), duration_weeks=10, weekly_payment=Decimal('120'))
        self.reviewer = User.objects.create_user('concurrency-reviewer', is_superuser=True)

    def concurrent(self, operation):
        barrier = Barrier(2)
        def worker(index):
            close_old_connections()
            try:
                return operation(index, barrier)
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(worker, range(2)))

    def test_simultaneous_approval_executes_once(self):
        approval = ApprovalRequest.objects.create(workflow_type='LOAN_CREATION', title='Concurrent approval', payload=_loan_approval_payload(self.loan))
        def operation(index, barrier):
            request = ApprovalRequest.objects.get(pk=approval.pk)
            reviewer = User.objects.get(pk=self.reviewer.pk)
            barrier.wait(timeout=10)
            try:
                approve_and_execute_request(request, reviewer)
                return 'executed'
            except ValueError as exc:
                if 'Only pending' not in str(exc):
                    raise
                return 'already executed'
        results = self.concurrent(operation)
        self.assertEqual(results.count('executed'), 1)
        self.assertEqual(Loan.objects.count(), 2)

    def test_simultaneous_callbacks_post_once(self):
        collection = initiate_repayment_collection(loan=self.loan, amount=Decimal('120'), payment_method='BANK')
        def operation(index, barrier):
            request = RepaymentCollection.objects.get(pk=collection.pk)
            barrier.wait(timeout=10)
            return process_collection_callback(request, provider_status='success')[2]
        self.assertEqual(self.concurrent(operation).count(True), 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_simultaneous_reversal_requests_create_one_pending_case(self):
        from apps.core.reversals import request_reversal
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('120'))
        def operation(index, barrier):
            barrier.wait(timeout=10)
            try:
                request_reversal(kind='PAYMENT', source_id=payment.pk, user=User.objects.get(pk=self.reviewer.pk), reason='Verified duplicate receipt in the register.')
                return 'submitted'
            except ValueError as exc:
                if 'already awaiting' not in str(exc):
                    raise
                return 'duplicate blocked'
        results = self.concurrent(operation)
        self.assertEqual(results.count('submitted'), 1)
        self.assertEqual(ApprovalRequest.objects.filter(workflow_type='TRANSACTION_REVERSAL', status='PENDING').count(), 1)

    def test_simultaneous_reversal_approval_offsets_once(self):
        from apps.core.reversals import request_reversal
        from apps.core.models import TransactionReversal
        from apps.accounting.models import JournalEntry, ensure_default_accounting_period, ensure_default_ledger_accounts, get_ledger_account
        from apps.accounting.repayments import sync_repayment_entry
        maker = User.objects.create_user('reversal-concurrent-maker', is_staff=True)
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('120'))
        ensure_default_accounting_period()
        ensure_default_ledger_accounts()
        sync_repayment_entry(payment)
        approval = request_reversal(kind='PAYMENT', source_id=payment.pk, user=maker, reason='Verified duplicate receipt in the register.')
        def operation(index, barrier):
            pending = ApprovalRequest.objects.get(pk=approval.pk)
            reviewer = User.objects.get(pk=self.reviewer.pk)
            barrier.wait(timeout=10)
            try:
                approve_and_execute_request(pending, reviewer, note='Verified the source evidence; correction approved.')
                return 'executed'
            except ValueError as exc:
                if 'Only pending' not in str(exc):
                    raise
                return 'already executed'
        results = self.concurrent(operation)
        self.assertEqual(results.count('executed'), 1)
        self.assertEqual(TransactionReversal.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.filter(source_key__startswith='reversal:').count(), 1)
        self.assertEqual(get_ledger_account('1000').current_balance, Decimal('0'))

    def test_one_provider_receipt_cannot_settle_two_loans_concurrently(self):
        second = Loan.objects.create(borrower=self.borrower, agent_name=self.agent, amount=Decimal('1000'), duration_weeks=10, weekly_payment=Decimal('120'))
        collections = [initiate_repayment_collection(loan=loan, amount=Decimal('120'), payment_method='BANK') for loan in (self.loan, second)]
        def operation(index, barrier):
            request = RepaymentCollection.objects.get(pk=collections[index].pk)
            barrier.wait(timeout=10)
            return process_collection_callback(request, provider_status='success', payload={'provider_reference':'ONE-VERIFIED-RECEIPT'})[2]
        results = self.concurrent(operation)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(Payment.objects.count(), 1)
