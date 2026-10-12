"""Dashboard totals stay accurate as loan and deposit populations grow."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Agent
from apps.company.models import CompanyProfile
from .dashboard_queries import dashboard_loans_and_payments
from .models import Borrower, Loan, Payment, Portfolio, PortfolioAssignment, SecurityDeposit, SecurityDepositTransaction, SecurityDepositTransfer


@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", ARKESEL_API_KEY="")
class DashboardQueryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("dashboard-query-admin", is_staff=True)
        self.portfolio = Portfolio.objects.get(number="01")
        self.agent = Agent.objects.create(agent_id="dashboard-query-agent", name="Officer", location="Accra", phone="")
        PortfolioAssignment.objects.create(portfolio=self.portfolio, agent=self.agent)
        self.borrower = Borrower.objects.create(portfolio=self.portfolio, full_name="Customer", national_id="dashboard-query-id", ghana_card_number="dashboard-query-card", phone="", location="Accra", group_name="Traders", preferred_language="Twi")
        CompanyProfile.get_solo()
        self.client.force_login(self.admin)

    def loan(self, **kwargs):
        values = dict(borrower=self.borrower, agent_name=self.agent, amount=Decimal("1000"), duration_weeks=10, weekly_payment=Decimal("120"), start_date=timezone.localdate()-timedelta(weeks=2))
        values.update(kwargs)
        loan = Loan(**values)
        loan._skip_new_loan_notifications = True
        loan.save()
        return loan

    def test_aggregates_match_receipt_totals_including_customer_credit(self):
        loan = self.loan(security_deposit_applied_total=Decimal("100"))
        Payment.objects.create(loan=loan, amount=Decimal("600"))
        Payment.objects.create(loan=loan, amount=Decimal("50"), is_pending=True)
        Payment.objects.create(loan=loan, amount=Decimal("20"), is_void=True)
        excess = Payment(loan=loan, amount=Decimal("900"))
        excess._legacy_import = True
        excess.save()
        loans, payments = dashboard_loans_and_payments()
        with self.assertNumQueries(0):
            result = loans[0]
            self.assertEqual(result.actual_payments_count, 2)
            self.assertEqual(result.total_cash_received, Decimal("1500"))
            self.assertEqual(result.total_customer_credit, Decimal("400"))
            self.assertEqual(result.total_paid_amount, Decimal("1100"))
            self.assertEqual(result.total_principal_paid, Decimal("900"))
            self.assertEqual(result.total_roic_paid, Decimal("200"))
            self.assertEqual(result.balance_amount, Decimal("0"))
            self.assertEqual(result.principal_outstanding + result.roic_outstanding, Decimal("0"))
            self.assertEqual(len(payments), 2)
            self.assertIs(payments[0].loan, result)

    def test_readiness_includes_refunds_applications_and_both_transfer_directions(self):
        loans = [self.loan() for _ in range(6)]
        source = SecurityDeposit.objects.create(borrower=self.borrower, loan=loans[0], required_amount=Decimal("100"))
        target = SecurityDeposit.objects.create(borrower=self.borrower, loan=loans[1], required_amount=Decimal("100"))
        for action, amount in (("COLLECTION", "100"), ("COLLECTION", "100"), ("REFUND", "20"), ("DEFAULT_APPLICATION", "10")):
            SecurityDepositTransaction.objects.create(deposit=source, action=action, amount=Decimal(amount))
        SecurityDepositTransfer.objects.create(source=source, target=target, amount=Decimal("100"), reference="MOVE-100")
        SecurityDeposit.objects.create(borrower=self.borrower, loan=loans[2], required_amount=Decimal("100"), enforce_before_disbursement=False)
        SecurityDeposit.objects.create(borrower=self.borrower, loan=loans[3], required_amount=Decimal("100"))
        Loan.objects.filter(pk=loans[4].pk).update(disbursed_at=timezone.localdate())
        SecurityDeposit.objects.create(borrower=self.borrower, loan=loans[4], required_amount=Decimal("100"))
        expected = {loan.pk: Loan.objects.get(pk=loan.pk).is_ready_for_disbursement for loan in loans}
        optimized, _payments = dashboard_loans_and_payments()
        with self.assertNumQueries(0):
            self.assertEqual({loan.pk: loan.is_ready_for_disbursement for loan in optimized}, expected)
        self.assertFalse(expected[loans[0].pk])
        self.assertTrue(expected[loans[1].pk])
        self.assertTrue(expected[loans[2].pk])
        self.assertFalse(expected[loans[3].pk])
        self.assertTrue(expected[loans[4].pk])
        self.assertTrue(expected[loans[5].pk])

    def test_rendered_dashboard_query_count_does_not_grow_per_loan(self):
        def add_loan():
            loan = self.loan()
            deposit = SecurityDeposit.objects.create(borrower=self.borrower, loan=loan, required_amount=Decimal("100"))
            SecurityDepositTransaction.objects.create(deposit=deposit, action="COLLECTION", amount=Decimal("100"))
            Payment.objects.create(loan=loan, amount=Decimal("120"))
        add_loan()
        url = reverse("loans:dashboard")
        self.client.get(url)
        with CaptureQueriesContext(connection) as initial:
            self.client.get(url)
        for _ in range(25):
            add_loan()
        with CaptureQueriesContext(connection) as expanded:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(expanded), len(initial))
        self.assertLessEqual(len(expanded), 12)
        self.assertEqual(response.context["total_collected"], Decimal("3120"))
        html = response.content.decode()
        self.assertLess(html.index("Comprehensive Management Reports"), html.index('aria-label="Loan portfolios"'))
