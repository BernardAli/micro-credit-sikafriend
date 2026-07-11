from django.core.checks import run_checks
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse
from django.template.loader import get_template
from unittest.mock import patch

from apps.accounts.models import Agent
from apps.core.approvals import approve_and_execute_request, reject_approval_request
from apps.core.models import ApprovalRequest


class DatabaseEngineChecksTests(SimpleTestCase):
    def test_check_passes_for_mysql_engine(self):
        with override_settings(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.mysql",
                    "NAME": "mirco_credit_db",
                }
            }
        ):
            errors = run_checks()

        self.assertFalse([error for error in errors if error.id == "core.E001"])
    def test_check_passes_for_sqlite_engine_in_standalone_mode(self):
        with override_settings(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": "db.sqlite3",
                }
            }
        ):
            errors = run_checks()

        self.assertFalse([error for error in errors if error.id == "core.E001"])


class CoreUrlTests(SimpleTestCase):
    def test_approval_namespace_is_registered(self):
        self.assertEqual(reverse("core:approvals"), "/approvals/")
        self.assertEqual(resolve("/approvals/").view_name, "core:approvals")
        self.assertEqual(reverse("core:loan_requests"), "/loan-requests/")


class CorePageRenderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="core-admin",
            password="SafePass123!",
            is_staff=True,
        )
        self.client.force_login(self.admin)

    def test_approval_hub_renders(self):
        response = self.client.get(reverse("core:approvals"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approval Controls")
        self.assertContains(response, "No approval requests match these filters")

    def test_audit_trail_renders(self):
        response = self.client.get(reverse("core:audit_trail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Audit Trail")

    def test_loan_requests_and_other_approvals_are_separate(self):
        ApprovalRequest.objects.create(workflow_type="LOAN_CREATION", title="Loan for Ama")
        ApprovalRequest.objects.create(workflow_type="PAYROLL_RUN_APPROVAL", title="July payroll")

        loan_response = self.client.get(reverse("core:loan_requests"))
        self.assertContains(loan_response, "Loan for Ama")
        self.assertNotContains(loan_response, "July payroll")

        approval_response = self.client.get(reverse("core:approvals"))
        self.assertContains(approval_response, "July payroll")
        self.assertNotContains(approval_response, "Loan for Ama")

    @override_settings(DEBUG=False)
    def test_custom_404_page_renders(self):
        response = self.client.get("/this-page-does-not-exist/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "This page could not be found", status_code=404)

    def test_custom_500_template_is_available(self):
        template = get_template("500.html")
        rendered = template.render({})
        self.assertIn("We could not complete that request", rendered)


class ApprovalSelfReviewTests(TestCase):
    def test_regular_submitter_cannot_self_approve(self):
        user = User.objects.create_user(username="ordinary", is_staff=True)
        approval = ApprovalRequest.objects.create(
            workflow_type="ASSET_DISPOSAL",
            title="Dispose old laptop",
            submitted_by=user,
        )
        with self.assertRaisesMessage(ValueError, "Only management or a superuser"):
            approve_and_execute_request(approval, user)

    @patch("apps.core.approvals._execute_asset_disposal", return_value={"message": "Approved"})
    def test_management_submitter_can_self_approve(self, _execute):
        user = User.objects.create_user(username="manager", is_staff=True)
        Agent.objects.create(
            user=user,
            agent_id="MGT-001",
            name="Management User",
            phone="0200000000",
            location="Accra",
            workforce_role="MANAGEMENT",
        )
        approval = ApprovalRequest.objects.create(
            workflow_type="ASSET_DISPOSAL",
            title="Dispose old laptop",
            submitted_by=user,
        )
        approve_and_execute_request(approval, user, note="Reviewed")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "EXECUTED")
        self.assertEqual(approval.reviewed_by, user)

    def test_superuser_submitter_can_self_reject(self):
        user = User.objects.create_superuser(username="owner", password="SafePass123!")
        approval = ApprovalRequest.objects.create(
            workflow_type="ACCOUNTING_JOURNAL",
            title="Reverse journal",
            submitted_by=user,
        )
        reject_approval_request(approval, user, note="Withdrawn")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "REJECTED")
