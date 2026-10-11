import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.test import TestCase

from apps.accounts.models import Agent
from apps.company.models import CompanyProfile
from apps.communication.services_sms import normalize_phone as communication_normalize_phone
from apps.communication.views import build_recipients
from apps.loans.models import Portfolio, PortfolioAssignment, Borrower, Loan, Payment


class StandaloneDataTestCase(TestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Test Credit"
        tenant.owner_email = "owner@example.com"
        tenant.status = "ACTIVE"


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ManagementMessageCenterTests(StandaloneDataTestCase):
    def _uploaded_file(self, name):
        return SimpleUploadedFile(name, b"file", content_type="image/jpeg")

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="password",
            is_staff=True,
            is_superuser=True,
        )
        self.agent_user = User.objects.create_user(username="agent-user", password="password")
        self.agent = Agent.objects.create(
            user=self.agent_user,
            agent_id="AG001",
            name="Kwame Agent",
            phone="020 123 4567",
            location="Accra",
            photo=self._uploaded_file("agent-photo.jpg"),
            ghana_card_front=self._uploaded_file("agent-front.jpg"),
            ghana_card_back=self._uploaded_file("agent-back.jpg"),
            ghana_card_number="AGCARD001",
            group_name="Field Team",
        )
        PortfolioAssignment.objects.get_or_create(portfolio=Portfolio.objects.get(number="01"), agent=self.agent)
        self.borrower = Borrower.objects.create(
            portfolio=Portfolio.objects.get(number="01"),
            borrower_id="BW001",
            full_name="Ama Borrower",
            national_id="NAT001",
            phone="024 111 2222",
            location="Accra",
            photo=self._uploaded_file("borrower-photo.jpg"),
            ghana_card_front=self._uploaded_file("borrower-front.jpg"),
            ghana_card_back=self._uploaded_file("borrower-back.jpg"),
            ghana_card_number="BWCARD001",
            group_name="Market Women",
            preferred_language="Twi",
            status="ACTIVE",
        )
        self.loan = Loan.objects.create(
            borrower=self.borrower,
            agent_name=self.agent,
            amount=Decimal("1000.00"),
            duration_weeks=10,
            weekly_payment=Decimal("120.00"),
            status="ACTIVE",
        )

    def test_build_recipients_all_users_uses_related_profile_phone(self):
        recipients = build_recipients(
            {
                "recipient_group": "ALL_USERS",
                "agent": None,
                "borrower_status": "",
                "loan_status": "",
                "loan_category": "",
                "location": "",
                "group_name": "",
                "preferred_language": "",
                "manual_numbers": "",
            }
        )

        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0].label, "Kwame Agent")
        self.assertEqual(recipients[0].phone, "233201234567")

    def test_build_recipients_borrower_filters_match_normalized_phone(self):
        recipients = build_recipients(
            {
                "recipient_group": "ALL_BORROWERS",
                "agent": None,
                "borrower_status": "ACTIVE",
                "loan_status": "ACTIVE",
                "loan_category": "",
                "location": "",
                "group_name": "",
                "preferred_language": "",
                "manual_numbers": "",
            }
        )

        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0].label, "Ama Borrower")
        self.assertEqual(recipients[0].phone, "233241112222")

    def test_communication_sms_uses_gateway_phone_normalization(self):
        self.assertEqual(communication_normalize_phone("020 123 4567"), "233201234567")
        self.assertEqual(communication_normalize_phone("+233 20 123 4567"), "233201234567")

    @patch("apps.communication.views.safe_send_sms")
    def test_send_action_sends_to_deduped_manual_numbers(self, mock_send_sms):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("communications:management_message_center"),
            {
                "recipient_group": "MANUAL_NUMBERS",
                "manual_numbers": "0201234567, 0201234567\n0240000000",
                "message": "Portfolio update",
                "action": "send",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_send_sms.call_count, 2)
        self.assertEqual(response.context["preview_count"], 2)
        self.assertEqual(response.context["sent_count"], 2)


@override_settings(MEDIA_ROOT=tempfile.gettempdir(), DEBUG=True, ALLOW_INSECURE_USSD_CALLBACKS=True)
class HubtelUSSDTests(StandaloneDataTestCase):
    def _uploaded_file(self, name):
        return SimpleUploadedFile(name, b"file", content_type="image/jpeg")

    def setUp(self):
        self.agent = Agent.objects.create(
            agent_id="AG100",
            name="Kojo Agent",
            phone="020 333 4444",
            location="Accra",
            photo=self._uploaded_file("agent-photo-ussd.jpg"),
            ghana_card_front=self._uploaded_file("agent-front-ussd.jpg"),
            ghana_card_back=self._uploaded_file("agent-back-ussd.jpg"),
            ghana_card_number="AGCARD100",
            group_name="Field Team",
        )
        PortfolioAssignment.objects.get_or_create(portfolio=Portfolio.objects.get(number="01"), agent=self.agent)
        self.borrower = Borrower.objects.create(
            portfolio=Portfolio.objects.get(number="01"),
            borrower_id="BW100",
            full_name="Adwoa Mensah",
            national_id="NAT100",
            phone="024 555 6666",
            location="Accra",
            photo=self._uploaded_file("borrower-photo-ussd.jpg"),
            ghana_card_front=self._uploaded_file("borrower-front-ussd.jpg"),
            ghana_card_back=self._uploaded_file("borrower-back-ussd.jpg"),
            ghana_card_number="BWCARD100",
            group_name="Market Women",
            preferred_language="Twi",
            status="ACTIVE",
        )
        self.loan = Loan.objects.create(
            borrower=self.borrower,
            agent_name=self.agent,
            amount=Decimal("1000.00"),
            duration_weeks=10,
            weekly_payment=Decimal("120.00"),
            status="ACTIVE",
        )
        Payment.objects.create(
            loan=self.loan,
            amount=Decimal("240.00"),
            note="Initial repayment",
        )

        profile = CompanyProfile.get_solo()
        profile.company_name = "SikaFriend Micro-Credit"
        profile.phone = "+233 30 123 4567"
        profile.email = "support@sikafriend.test"
        profile.address = "Accra Central"
        profile.save()

    def test_ussd_root_menu_shows_requested_options(self):
        response = self.client.post(
            reverse("communications:hubtel_ussd"),
            {"Mobile": "0245556666", "Message": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CON Welcome to SikaFriend Micro-Credit")
        self.assertContains(response, "1. Loan Repayment")
        self.assertContains(response, "2. Loan Disbursement Confirmation")
        self.assertContains(response, "3. Check Balance")
        self.assertContains(response, "4. Referrals")
        self.assertContains(response, "5. Contact Us")

    def test_loan_repayment_option_returns_due_amount(self):
        response = self.client.post(
            reverse("communications:hubtel_ussd"),
            {"Mobile": "+233245556666", "Message": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your current repayment due is GHS 120.00")
        self.assertContains(response, "Outstanding balance: GHS 960.00")

    def test_disbursement_confirmation_option_returns_loan_details(self):
        response = self.client.post(
            reverse("communications:hubtel_ussd"),
            {"Mobile": "0245556666", "Message": "2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your loan disbursement of GHS 1,000.00 is on record.")
        self.assertContains(response, "Loan status: ACTIVE.")

    def test_check_balance_option_returns_balance_and_installments(self):
        response = self.client.post(
            reverse("communications:hubtel_ussd"),
            {"Mobile": "0245556666", "Message": "3"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Balance: GHS 960.00.")
        self.assertContains(response, "Paid: 1/10 installments.")
        self.assertContains(response, "Remaining: 9.")

    def test_contact_option_returns_company_contact_details(self):
        response = self.client.post(
            reverse("communications:hubtel_ussd"),
            {"Mobile": "0245556666", "Message": "5"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Phone: +233 30 123 4567")
        self.assertContains(response, "Email: support@sikafriend.test")
        self.assertContains(response, "Address: Accra Central")

    def test_arkesel_route_remains_compatible_with_hubtel_handler(self):
        response = self.client.post(
            reverse("communications:arkesel_ussd"),
            {"phoneNumber": "0245556666", "text": "3"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Balance: GHS 960.00.")

    def test_hubtel_ussd_response_is_trimmed_to_session_limit(self):
        profile = CompanyProfile.get_solo()
        profile.address = "A" * 250
        profile.save()

        response = self.client.post(
            reverse("communications:hubtel_ussd"),
            {"Mobile": "0245556666", "Message": "5"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.decode().startswith("END "))
        self.assertLessEqual(len(response.content.decode()), 182)
