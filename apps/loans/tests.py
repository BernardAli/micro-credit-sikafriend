import tempfile
import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.test import TestCase

from apps.accounts.models import Agent
from apps.company.models import CompanyProfile
from apps.loans.cross_company import empty_cross_company_debt_check, format_cross_company_debt_summary, serialize_cross_company_debt_check
from apps.loans.models import Borrower, Loan, Payment, RepaymentCollection
from apps.loans.payment_gateway import initiate_repayment_collection, process_collection_callback
import requests
from apps.loans.services_sms import _response_detail, normalize_phone, safe_send_sms, send_sms


class StandaloneDataTestCase(TestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Test Credit"
        tenant.owner_email = "owner@example.com"
        tenant.status = "ACTIVE"


class LoanSMSServiceTests(SimpleTestCase):
    def test_normalize_phone_handles_common_ghana_formats(self):
        self.assertEqual(normalize_phone("020 123 4567"), "233201234567")
        self.assertEqual(normalize_phone("+233 20 123 4567"), "233201234567")
        self.assertEqual(normalize_phone("201234567"), "233201234567")

    @override_settings(
        ARKESEL_API_KEY="test-api-key",
        ARKESEL_SENDER_ID="Sikafriend",
        ARKESEL_BASE_URL="https://sms.arkesel.com/api/v2",
    )
    @patch("apps.loans.services_sms.requests.post")
    def test_send_sms_posts_to_arkesel(self, mock_post):
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        send_sms("020 123 4567", "Loan approved")

        mock_post.assert_called_once_with(
            "https://sms.arkesel.com/api/v2/sms/send",
            headers={
                "api-key": "test-api-key",
                "Content-Type": "application/json",
            },
            json={
                "sender": "Sikafriend",
                "message": "Loan approved",
                "recipients": ["233201234567"],
            },
            timeout=20,
        )
        mock_response.raise_for_status.assert_called_once_with()

    @override_settings(
        ARKESEL_API_KEY="",
        ARKESEL_SENDER_ID="Sikafriend",
        ARKESEL_BASE_URL="https://sms.arkesel.com/api/v2",
    )
    @patch("apps.loans.services_sms.requests.post")
    def test_send_sms_skips_when_api_key_missing(self, mock_post):
        send_sms("0201234567", "Loan approved")
        mock_post.assert_not_called()

    @patch("apps.loans.services_sms.logger.warning")
    @patch("apps.loans.services_sms.send_sms")
    def test_safe_send_sms_logs_provider_http_errors_without_traceback(self, mock_send_sms, mock_warning):
        mock_response = Mock(status_code=402)
        mock_response.json.return_value = {"message": "Insufficient balance"}
        mock_send_sms.side_effect = requests.HTTPError(response=mock_response)

        safe_send_sms("0201234567", "Loan approved")

        mock_send_sms.assert_called_once_with("0201234567", "Loan approved")
        mock_warning.assert_called_once_with(
            "Loan SMS delivery skipped: Arkesel returned %s for %s (%s).",
            402,
            "233201234567",
            "Insufficient balance",
        )

    @patch("apps.loans.services_sms.logger.exception")
    @patch("apps.loans.services_sms.send_sms", side_effect=RuntimeError("boom"))
    def test_safe_send_sms_logs_unexpected_errors(self, mock_send_sms, mock_exception):
        safe_send_sms("0201234567", "Loan approved")
        mock_send_sms.assert_called_once_with("0201234567", "Loan approved")
        mock_exception.assert_called_once_with("Loan SMS delivery failed unexpectedly.")

    def test_response_detail_falls_back_to_response_text(self):
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = "Payment Required"

        self.assertEqual(_response_detail(mock_response), "Payment Required")


class CrossCompanyDebtCheckSummaryTests(SimpleTestCase):
    def test_empty_cross_company_debt_check_is_disabled_in_standalone_mode(self):
        summary = empty_cross_company_debt_check()

        self.assertFalse(summary["requires_review"])
        self.assertFalse(summary["has_default"])
        self.assertEqual(summary["company_count"], 0)
        self.assertEqual(summary["open_loan_count"], 0)
        self.assertEqual(summary["total_outstanding"], Decimal("0.00"))
        self.assertIn("disabled in standalone mode", summary["headline"])

    def test_serialize_cross_company_debt_check_returns_standalone_payload(self):
        payload = serialize_cross_company_debt_check(empty_cross_company_debt_check())

        self.assertFalse(payload["requires_review"])
        self.assertEqual(payload["total_outstanding"], "0.00")
        self.assertEqual(payload["companies"], [])
        self.assertIn("disabled in standalone mode", payload["headline"])

    def test_format_cross_company_debt_summary_returns_standalone_message(self):
        message = format_cross_company_debt_summary(empty_cross_company_debt_check())
        self.assertEqual(message, "Cross-company debt checks are disabled in standalone mode.")


@override_settings(
    ARKESEL_API_KEY="global-api-key",
    ARKESEL_SENDER_ID="GlobalSender",
    ARKESEL_BASE_URL="https://sms.arkesel.com/api/v2",
)
class CompanySMSOverrideTests(StandaloneDataTestCase):
    @patch("apps.loans.services_sms.requests.post")
    def test_send_sms_prefers_company_sms_settings(self, mock_post):
        profile = CompanyProfile.get_solo()
        profile.tenant_sms_provider = "ARKESEL"
        profile.tenant_sms_api_key = "tenant-api-key"
        profile.tenant_sms_sender_id = "CompanySender"
        profile.tenant_sms_base_url = "https://tenant-sms.example/api"
        profile.save()

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        send_sms("020 123 4567", "Company flow")

        mock_post.assert_called_once_with(
            "https://tenant-sms.example/api/sms/send",
            headers={
                "api-key": "tenant-api-key",
                "Content-Type": "application/json",
            },
            json={
                "sender": "CompanySender",
                "message": "Company flow",
                "recipients": ["233201234567"],
            },
            timeout=20,
        )


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class DashboardHeroMetricsTests(StandaloneDataTestCase):
    def _uploaded_file(self, name):
        return SimpleUploadedFile(name, b"file", content_type="image/jpeg")

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="password",
            is_staff=True,
            is_superuser=True,
        )
        self.agent = Agent.objects.create(
            agent_id="AG001",
            name="Kwame Agent",
            phone="0200000000",
            location="Accra",
            photo=self._uploaded_file("agent-photo.jpg"),
            ghana_card_front=self._uploaded_file("agent-front.jpg"),
            ghana_card_back=self._uploaded_file("agent-back.jpg"),
            ghana_card_number="AGCARD001",
            group_name="Field Team",
        )
        self.borrower = Borrower.objects.create(
            borrower_id="BW001",
            full_name="Ama Borrower",
            national_id="NAT001",
            phone="0240000000",
            location="Accra",
            photo=self._uploaded_file("borrower-photo.jpg"),
            ghana_card_front=self._uploaded_file("borrower-front.jpg"),
            ghana_card_back=self._uploaded_file("borrower-back.jpg"),
            ghana_card_number="BWCARD001",
            group_name="Market Women",
            preferred_language="Twi",
        )
        self.loan = Loan.objects.create(
            borrower=self.borrower,
            agent_name=self.agent,
            amount=Decimal("1000.00"),
            duration_weeks=10,
            weekly_payment=Decimal("120.00"),
        )
        Payment.objects.create(
            loan=self.loan,
            amount=Decimal("600.00"),
            note="Part payment",
        )

    def test_dashboard_hero_shows_updated_financial_metrics(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("loans:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["hero_total_disbursed"], Decimal("1000.00"))
        self.assertEqual(response.context["hero_total_amount_collected"], Decimal("600.00"))
        self.assertEqual(response.context["hero_roic_collected"], Decimal("100.00"))
        self.assertEqual(response.context["hero_principal_outstanding"], Decimal("500.00"))
        self.assertContains(response, "Total Disbursed")
        self.assertContains(response, "Total Collected")
        self.assertContains(response, "ROIC Collected")
        self.assertContains(response, "Principal Outstanding")

    def test_loans_list_metrics_grid_shows_dashboard_style_financial_metrics(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("loans:loans_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["metrics_total_disbursed"], Decimal("1000.00"))
        self.assertEqual(response.context["metrics_total_amount_collected"], Decimal("600.00"))
        self.assertEqual(response.context["metrics_roic_collected"], Decimal("100.00"))
        self.assertEqual(response.context["metrics_principal_outstanding"], Decimal("500.00"))
        self.assertContains(response, "Total Disbursed")
        self.assertContains(response, "Total Amount Collected")
        self.assertContains(response, "ROIC Collected")
        self.assertContains(response, "Principal Outstanding")
        self.assertNotContains(response, '<div class="stat-label">Loans</div>', html=True)


@override_settings(
    MEDIA_ROOT=tempfile.gettempdir(),
    PAYMENT_WEBHOOK_SECRET="test-webhook-secret",
    ALLOW_INSECURE_PAYMENT_WEBHOOKS=False,
)
class RepaymentCollectionTests(StandaloneDataTestCase):
    def _uploaded_file(self, name):
        return SimpleUploadedFile(name, b"file", content_type="image/jpeg")

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="password",
            is_staff=True,
            is_superuser=True,
        )
        self.borrower_user = User.objects.create_user(
            username="borrower-user",
            password="password",
        )
        self.agent = Agent.objects.create(
            agent_id="AG900",
            name="Automated Agent",
            phone="0209990000",
            location="Accra",
            photo=self._uploaded_file("agent-collection.jpg"),
            ghana_card_front=self._uploaded_file("agent-collection-front.jpg"),
            ghana_card_back=self._uploaded_file("agent-collection-back.jpg"),
            ghana_card_number="AGCOL900",
            group_name="Collections",
        )
        self.borrower = Borrower.objects.create(
            user=self.borrower_user,
            borrower_id="BW900",
            full_name="Collection Borrower",
            national_id="NAT900",
            phone="0249000000",
            location="Accra",
            photo=self._uploaded_file("borrower-collection.jpg"),
            ghana_card_front=self._uploaded_file("borrower-collection-front.jpg"),
            ghana_card_back=self._uploaded_file("borrower-collection-back.jpg"),
            ghana_card_number="BWCOL900",
            group_name="Traders",
            preferred_language="Twi",
        )
        self.loan = Loan.objects.create(
            borrower=self.borrower,
            agent_name=self.agent,
            amount=Decimal("1000.00"),
            duration_weeks=10,
            weekly_payment=Decimal("120.00"),
        )

    def test_successful_collection_callback_posts_payment(self):
        collection = initiate_repayment_collection(
            loan=self.loan,
            amount=Decimal("120.00"),
            payment_method="MOBILE_MONEY",
            submitted_by=self.borrower_user,
            payer_phone="0249000000",
            submitted_reference="MM-123",
        )

        process_collection_callback(
            collection,
            provider_status="success",
            payload={
                "client_reference": collection.client_reference,
                "provider_reference": "GW-123",
                "status": "success",
            },
        )

        collection.refresh_from_db()
        self.loan.refresh_from_db()

        self.assertEqual(collection.status, "RECONCILED")
        self.assertIsNotNone(collection.payment_id)
        self.assertEqual(collection.payment.payment_method, "MOBILE_MONEY")
        self.assertEqual(self.loan.total_paid_amount, Decimal("120.00"))

    def test_overpayment_collection_moves_to_manual_review(self):
        collection = initiate_repayment_collection(
            loan=self.loan,
            amount=Decimal("5000.00"),
            payment_method="BANK",
            submitted_by=self.borrower_user,
            payer_phone="0249000000",
        )

        process_collection_callback(
            collection,
            provider_status="success",
            payload={
                "client_reference": collection.client_reference,
                "provider_reference": "GW-OVERPAY",
                "status": "success",
            },
        )

        collection.refresh_from_db()
        self.assertEqual(collection.status, "MANUAL_REVIEW")
        self.assertIsNone(collection.payment_id)

    def test_webhook_endpoint_reconciles_collection(self):
        collection = initiate_repayment_collection(
            loan=self.loan,
            amount=Decimal("120.00"),
            payment_method="CARD",
            submitted_by=self.borrower_user,
        )

        response = self.client.post(
            reverse("loans:payment_collection_webhook", args=["INTERNAL"]),
            data=json.dumps({
                "client_reference": collection.client_reference,
                "provider_reference": "GW-CARD-1",
                "status": "success",
            }),
            content_type="application/json",
            HTTP_X_WEBHOOK_SECRET="test-webhook-secret",
        )

        collection.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(collection.status, "RECONCILED")
        self.assertIsNotNone(collection.payment_id)

    def test_webhook_endpoint_rejects_missing_secret(self):
        collection = initiate_repayment_collection(
            loan=self.loan,
            amount=Decimal("120.00"),
            payment_method="CARD",
            submitted_by=self.borrower_user,
        )

        response = self.client.post(
            reverse("loans:payment_collection_webhook", args=["INTERNAL"]),
            data=json.dumps({
                "client_reference": collection.client_reference,
                "provider_reference": "GW-CARD-2",
                "status": "success",
            }),
            content_type="application/json",
        )

        collection.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(collection.status, "PENDING")
        self.assertIsNone(collection.payment_id)
