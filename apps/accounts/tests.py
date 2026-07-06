from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.accounts.forms import TenantAwareAuthenticationForm, UsernameOrEmailPasswordResetForm
from apps.accounts.tenant_usernames import build_tenant_scoped_username, visible_portal_username


class TenantUsernameHelperTests(SimpleTestCase):
    def test_visible_portal_username_hides_current_tenant_prefix(self):
        self.assertEqual(
            visible_portal_username("alpha__kofi", schema_name="alpha"),
            "kofi",
        )

    def test_build_tenant_scoped_username_prefixes_tenant_schema(self):
        self.assertEqual(
            build_tenant_scoped_username("kofi", schema_name="alpha"),
            "alpha__kofi",
        )


class TenantAwareAuthenticationFormTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_alias_login_authenticates_namespaced_borrower_username(self):
        user = User.objects.create_user(
            username="alpha__kofi",
            email="kofi@example.com",
            password="SafePass123!",
        )
        request = self.factory.post("/login/")
        request.tenant = SimpleNamespace(schema_name="alpha")

        form = TenantAwareAuthenticationForm(
            request=request,
            data={"username": "kofi", "password": "SafePass123!"},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user().pk, user.pk)

    def test_plain_global_username_still_authenticates(self):
        user = User.objects.create_user(
            username="company_owner",
            email="owner@example.com",
            password="SafePass123!",
        )
        request = self.factory.post("/login/")
        request.tenant = SimpleNamespace(schema_name="alpha")

        form = TenantAwareAuthenticationForm(
            request=request,
            data={"username": "company_owner", "password": "SafePass123!"},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user().pk, user.pk)


class UsernameOrEmailPasswordResetFormTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_username_alias_matches_namespaced_user_in_current_tenant(self):
        user = User.objects.create_user(
            username="alpha__ama",
            email="ama@example.com",
            password="SafePass123!",
        )
        request = self.factory.post("/password-reset/")
        request.tenant = SimpleNamespace(schema_name="alpha")

        form = UsernameOrEmailPasswordResetForm(
            data={"email": "ama"},
            request=request,
        )

        self.assertTrue(form.is_valid(), form.errors)
        matched_users = list(form.get_users("ama"))
        self.assertEqual([item.pk for item in matched_users], [user.pk])
