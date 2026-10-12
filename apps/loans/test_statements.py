"""Statement permissions, financial reconciliation, PDFs and query scaling."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from django.core.files.base import ContentFile
from weasyprint import default_url_fetcher

from apps.accounts.models import Agent, PayrollLine, PayrollRun
from apps.company.models import CompanyProfile
from .models import Borrower, Loan, Payment, Portfolio, PortfolioAssignment, SecurityDeposit, SecurityDepositTransaction, SecurityDepositTransfer
from .statements import account_statement


@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", ARKESEL_API_KEY="")
class StatementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('statement-manager', is_staff=True)
        self.officer_user = User.objects.create_user('statement-officer')
        self.borrower_user = User.objects.create_user('statement-customer')
        self.other_user = User.objects.create_user('statement-other')
        self.orphan = User.objects.create_user('statement-orphan')
        self.agent = Agent.objects.create(user=self.officer_user, agent_id='ST-01', name='Statement Officer', phone='', location='Accra')
        self.portfolio = Portfolio.objects.get(number='01')
        PortfolioAssignment.objects.create(portfolio=self.portfolio, agent=self.agent)
        self.borrower = Borrower.objects.create(user=self.borrower_user, portfolio=self.portfolio, full_name='Statement Customer', national_id='ST-CUSTOMER', ghana_card_number='ST-CARD', phone='0200000000', location='Accra', group_name='Traders', preferred_language='Twi')
        self.loan = self.new_loan()
        CompanyProfile.get_solo()
        self.client.force_login(self.admin)

    def new_loan(self):
        loan = Loan(borrower=self.borrower, agent_name=self.agent, amount=Decimal('1000'), duration_weeks=10, weekly_payment=Decimal('120'), start_date=timezone.localdate()-timedelta(weeks=10))
        loan._skip_new_loan_notifications = True
        loan.save()
        return loan

    def routes(self, pdf=False):
        suffix = '_pdf' if pdf else ''
        return [reverse('loans:loan_statement'+suffix, args=[self.loan.pk]), reverse('loans:borrower_statement'+suffix, args=[self.borrower.pk]), reverse('agent_statement'+suffix, args=[self.agent.pk])]

    def test_statements_keep_credit_pending_and_void_amounts_separate(self):
        Payment.objects.create(loan=self.loan, amount=Decimal('600'))
        Payment.objects.create(loan=self.loan, amount=Decimal('90'), is_pending=True)
        Payment.objects.create(loan=self.loan, amount=Decimal('80'), is_void=True)
        excess = Payment(loan=self.loan, amount=Decimal('900'))
        excess._legacy_import = True
        excess.save()
        data = account_statement(Loan.objects.filter(pk=self.loan.pk))
        self.assertEqual(data['totals']['cash'], Decimal('1500'))
        self.assertEqual(data['totals']['paid'], Decimal('1200'))
        self.assertEqual(data['totals']['credit'], Decimal('300'))
        self.assertEqual(data['totals']['pending'], Decimal('90'))
        self.assertEqual(data['totals']['outstanding'], Decimal('0'))
        self.assertEqual([row['status'] for row in data['ledger']], ['Settled', 'Pending', 'Void', 'Settled'])
        self.assertEqual([row['balance'] for row in data['ledger']], [Decimal('600'), Decimal('600'), Decimal('600'), Decimal('0')])

    def test_dated_applications_and_undated_opening_adjustments_reconcile(self):
        deposit = SecurityDeposit.objects.create(loan=self.loan, borrower=self.borrower, required_amount=Decimal('100'), enforce_before_disbursement=False)
        SecurityDepositTransaction.objects.create(deposit=deposit, action='COLLECTION', amount=Decimal('100'))
        Payment.objects.create(loan=self.loan, amount=Decimal('120'), payment_date=timezone.localdate()-timedelta(days=2))
        SecurityDepositTransaction.objects.create(deposit=deposit, action='DEFAULT_APPLICATION', amount=Decimal('50'), transaction_date=timezone.localdate()-timedelta(days=1))
        Loan.objects.filter(pk=self.loan.pk).update(security_deposit_applied_total=Decimal('100'))
        data = account_statement(Loan.objects.filter(pk=self.loan.pk))
        self.assertIsNone(data['ledger'][0]['date'])
        self.assertEqual([row['balance'] for row in data['ledger']], [Decimal('1150'), Decimal('1030'), Decimal('980')])
        self.assertEqual(data['ledger'][-1]['balance'], data['totals']['outstanding'])
        self.assertEqual(data['deposits'][0]['held'], Decimal('50'))

    def test_deposit_transfers_preserve_both_accounts_and_do_not_repay_loans(self):
        other = self.new_loan()
        source = SecurityDeposit.objects.create(loan=self.loan, borrower=self.borrower, required_amount=Decimal('100'))
        target = SecurityDeposit.objects.create(loan=other, borrower=self.borrower, required_amount=Decimal('100'))
        SecurityDepositTransaction.objects.create(deposit=source, action='COLLECTION', amount=Decimal('200'))
        SecurityDepositTransfer.objects.create(source=source, target=target, amount=Decimal('100'), reference='ST-CARRY')
        data = account_statement(Loan.objects.filter(borrower=self.borrower))
        self.assertEqual(data['totals']['deposit_held'], Decimal('200'))
        self.assertEqual(data['totals']['paid'], Decimal('0'))
        self.assertEqual(data['totals']['outstanding'], Decimal('2400'))
        self.assertEqual(len(data['deposit_movements']), 3)

    def test_access_is_checked_for_print_previews_and_pdfs(self):
        for user in (self.other_user, self.orphan):
            self.client.force_login(user)
            for url in self.routes()+self.routes(pdf=True):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.borrower_user)
        for url in self.routes()[:2]:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(self.routes()[2]).status_code, 404)
        other_agent_user = User.objects.create_user('statement-other-officer')
        Agent.objects.create(user=other_agent_user, agent_id='ST-02', name='Other officer', phone='', location='Accra')
        self.client.force_login(other_agent_user)
        for url in self.routes()+self.routes(pdf=True):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.officer_user)
        self.assertEqual(self.client.get(self.routes()[0]).status_code, 200)
        self.assertEqual(self.client.get(self.routes()[1]).status_code, 200)
        self.assertEqual(self.client.get(self.routes()[2]).status_code, 200)
        PortfolioAssignment.objects.filter(portfolio=self.portfolio, agent=self.agent).update(ended_at=timezone.now())
        self.assertEqual(self.client.get(self.routes()[0]).status_code, 404)
        self.assertEqual(self.client.get(self.routes()[1]).status_code, 404)

    def test_agent_statement_distinguishes_paid_and_approved_payroll(self):
        today = timezone.localdate()
        for status, net in [('PAID', '800'), ('APPROVED', '900'), ('DRAFT', '1000')]:
            run = PayrollRun.objects.create(title=status, period_start=today, period_end=today, pay_date=today, status=status)
            PayrollLine.objects.create(run=run, employee=self.agent, gross_pay=Decimal('1000'), total_deductions=Decimal('200'), net_pay=Decimal(net))
        response = self.client.get(self.routes()[2])
        self.assertEqual(response.context['earnings']['net'], Decimal('800'))
        self.assertEqual(response.context['earnings']['awaiting'], Decimal('900'))
        self.assertContains(response, 'Officer earnings & payroll history', html=False)

    def test_all_pdf_types_render_and_offer_download_without_external_resources(self):
        image = BytesIO()
        Image.new('RGB', (30, 30), 'green').save(image, format='PNG')
        company = CompanyProfile.get_solo()
        company.logo.save('statement-logo.png', ContentFile(image.getvalue()), save=True)
        for url in self.routes(pdf=True):
            with self.subTest(url=url), patch('apps.loans.statement_views.default_url_fetcher', wraps=default_url_fetcher) as fetch:
                response = self.client.get(url, {'download':'1'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b'%PDF'))
            self.assertIn('attachment', response['Content-Disposition'])
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertTrue(fetch.called)
            self.assertTrue(all(call.args[0].startswith('data:') for call in fetch.call_args_list))

    def test_print_views_escape_names_and_do_not_truncate_receipts(self):
        self.borrower.full_name = '<script>unsafe()</script>'
        self.borrower.save()
        for number in range(40):
            Payment.objects.create(loan=self.loan, amount=Decimal('1'), reference=f'ST-RECEIPT-{number}')
        response = self.client.get(self.routes()[1])
        self.assertContains(response, 'ST-RECEIPT-39')
        self.assertContains(response, '&lt;script&gt;unsafe()&lt;/script&gt;')
        self.assertNotContains(response, '<script>unsafe()</script>')
        self.assertContains(response, 'window.print()')
        self.assertEqual(len(response.context['ledger']), 40)

    def test_borrower_statement_query_count_does_not_grow_per_loan(self):
        url = self.routes()[1]
        self.client.get(url)
        with CaptureQueriesContext(connection) as initial:
            self.client.get(url)
        for _ in range(15):
            loan = self.new_loan()
            Payment.objects.create(loan=loan, amount=Decimal('120'))
        with CaptureQueriesContext(connection) as expanded:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(expanded), len(initial))

    def test_recorded_terms_requiring_management_review_are_not_changed(self):
        Loan.objects.filter(pk=self.loan.pk).update(duration_weeks=4)
        response = self.client.get(self.routes()[0])
        self.assertContains(response, 'Management review required')
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.duration_weeks, 4)
