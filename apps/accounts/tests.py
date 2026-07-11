from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from apps.accounts.forms import StandaloneAuthenticationForm, UsernameOrEmailPasswordResetForm
from apps.accounts.usernames import build_portal_username, login_username_candidates, visible_portal_username


class StandaloneUsernameHelperTests(TestCase):
    def test_visible_portal_username_returns_raw_username(self):
        self.assertEqual(
            visible_portal_username("kofi"),
            "kofi",
        )

    def test_build_username_ignores_schema_in_standalone_mode(self):
        self.assertEqual(
            build_portal_username("kofi"),
            "kofi",
        )

    def test_login_candidates_are_plain_usernames(self):
        self.assertEqual(login_username_candidates("kofi"), ["kofi"])

    def test_login_candidates_include_legacy_tenant_username(self):
        User.objects.create_user(username="legacy_schema__kofi", password="SafePass123!")
        self.assertEqual(login_username_candidates("kofi"), ["kofi", "legacy_schema__kofi"])


class StandaloneAuthenticationFormTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_plain_username_authenticates(self):
        user = User.objects.create_user(
            username="kofi",
            email="kofi@example.com",
            password="SafePass123!",
        )
        request = self.factory.post("/login/")

        form = StandaloneAuthenticationForm(
            request=request,
            data={"username": "kofi", "password": "SafePass123!"},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user().pk, user.pk)

    def test_global_username_still_authenticates(self):
        user = User.objects.create_user(
            username="company_owner",
            email="owner@example.com",
            password="SafePass123!",
        )
        request = self.factory.post("/login/")

        form = StandaloneAuthenticationForm(
            request=request,
            data={"username": "company_owner", "password": "SafePass123!"},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user().pk, user.pk)

    def test_legacy_tenant_username_authenticates_with_visible_alias(self):
        user = User.objects.create_user(
            username="legacy_schema__ama",
            password="SafePass123!",
        )
        form = StandaloneAuthenticationForm(
            request=self.factory.post("/login/"),
            data={"username": "ama", "password": "SafePass123!"},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user().pk, user.pk)


class UsernameOrEmailPasswordResetFormTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_username_matches_plain_user_in_standalone_mode(self):
        user = User.objects.create_user(
            username="ama",
            email="ama@example.com",
            password="SafePass123!",
        )
        request = self.factory.post("/password-reset/")

        form = UsernameOrEmailPasswordResetForm(
            data={"email": "ama"},
            request=request,
        )

        self.assertTrue(form.is_valid(), form.errors)
        matched_users = list(form.get_users("ama"))
        self.assertEqual([item.pk for item in matched_users], [user.pk])


class WorkforceCreateViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="workforce-admin",
            password="SafePass123!",
            is_staff=True,
        )
        self.client.force_login(self.admin)
        self.payload = {
            "agent_id": "WF-001",
            "name": "Akosua Mensah",
            "phone": "0200000000",
            "location": "Accra",
            "workforce_role": "AGENT",
            "employment_type": "FULL_TIME",
            "employment_status": "ACTIVE",
            "preferred_payment_method": "BANK",
            "base_salary": "0.00",
            "housing_allowance": "0.00",
            "transport_allowance": "0.00",
            "meal_allowance": "0.00",
            "communication_allowance": "0.00",
            "other_allowance": "0.00",
            "commission_rate": "0.00",
        }

    def test_invalid_submission_displays_location_error_summary(self):
        response = self.client.post("/agents/agents/new/", {**self.payload, "location": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please correct the following before saving")
        self.assertContains(response, "Operational Location: This field is required")

    def test_valid_submission_creates_workforce_member(self):
        response = self.client.post("/agents/agents/new/", self.payload)
        self.assertEqual(response.status_code, 302)
        from apps.accounts.models import Agent
        self.assertTrue(Agent.objects.filter(agent_id="WF-001", name="Akosua Mensah").exists())

    def test_employee_detail_renders_tabbed_sections(self):
        from apps.accounts.models import Agent
        agent = Agent.objects.create(
            agent_id="WF-002",
            name="Yaw Boateng",
            phone="0240000000",
            location="Kumasi",
        )
        response = self.client.get(f"/agents/agents/{agent.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-detail-tab="overview"')
        self.assertContains(response, 'data-detail-tab="payroll"')
        self.assertContains(response, 'data-detail-tab="portfolio"')
        self.assertContains(response, 'data-detail-panel="overview"')
