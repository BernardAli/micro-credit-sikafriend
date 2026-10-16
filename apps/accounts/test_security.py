import time
from unittest.mock import patch

import pyotp
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.security import client_ip
from .models import Authenticator, AuthenticationThrottle
from .models import Agent
from .security import cipher, new_recovery_codes, reserve_attempt, verify_code


@override_settings(MFA_ENABLED=True, STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountSecurityTests(TestCase):
    def setUp(self):
        self.password = "Strong-passphrase-3927!"
        self.user = User.objects.create_user("security-admin", password=self.password, is_staff=True)
        self.secret = pyotp.random_base32()

    def device(self):
        codes, hashes = new_recovery_codes()
        device = Authenticator.objects.create(user=self.user, secret_ciphertext=cipher().encrypt(self.secret.encode()).decode(),
                                              confirmed_at=timezone.now(), recovery_hashes=hashes)
        return device, codes

    def sign_in(self):
        return self.client.post(reverse("login"), {"username": self.user.username, "password": self.password})

    def test_staff_routes_and_admin_login_cannot_bypass_mfa(self):
        self.sign_in()
        for path in ("/dashboard/", "/admin/", "/private-media/borrowers/missing.jpg", "/loans/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith(reverse("mfa_setup")))
            self.assertIn("no-store", response["Cache-Control"])
        anonymous = Client()
        response = anonymous.post("/admin/login/", {"username": self.user.username, "password": self.password})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", anonymous.session)

    def test_field_officers_require_mfa_even_without_admin_access(self):
        officer = User.objects.create_user('security-officer', password=self.password)
        Agent.objects.create(user=officer, agent_id='SEC-OFFICER', name='Officer', phone='', location='Accra')
        self.client.post(reverse('login'), {'username':officer.username, 'password':self.password})
        response = self.client.get('/dashboard/')
        self.assertTrue(response['Location'].startswith(reverse('mfa_setup')))

    def test_suspended_workforce_cannot_sign_in_or_reuse_an_existing_session(self):
        employee = Agent.objects.create(user=self.user, agent_id='SEC-SUSPENDED', name='Employee', phone='', location='Accra', employment_status='SUSPENDED')
        self.assertEqual(self.sign_in().status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/dashboard/').status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_enrollment_requires_password_and_an_actual_code(self):
        self.sign_in()
        self.client.post(reverse("mfa_setup"), {"password": "wrong"})
        self.assertNotIn("mfa_enrollment", self.client.session)
        response = self.client.post(reverse("mfa_setup"), {"password": self.password})
        self.assertEqual(response.status_code, 200)
        pending = self.client.session["mfa_enrollment"]
        secret = cipher().decrypt(pending["secret"].encode()).decode()
        self.assertNotIn(secret, str(self.client.session.items()))
        response = self.client.post(reverse("mfa_setup"), {"code": pyotp.TOTP(secret).now()})
        self.assertRedirects(response, reverse("mfa_recovery"), fetch_redirect_response=False)
        device = Authenticator.objects.get(user=self.user)
        self.assertNotIn(secret, device.secret_ciphertext)
        self.assertEqual(len(device.recovery_hashes), 10)
        self.assertTrue(device.confirmed_at)
        response = self.client.get(reverse("mfa_recovery"))
        self.assertContains(response, "Save your recovery codes")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("mfa_recovery_codes", self.client.session)
        self.assertRedirects(self.client.get(reverse("mfa_recovery")), reverse("account_security"), fetch_redirect_response=False)

    def test_authenticator_codes_and_recovery_codes_are_single_use(self):
        device, codes = self.device()
        now = time.time()
        code = pyotp.TOTP(self.secret).at(now)
        self.assertIsNotNone(verify_code(self.user, code, at=now))
        self.assertIsNone(verify_code(self.user, code, at=now))
        self.assertIsNotNone(verify_code(self.user, codes[0]))
        self.assertIsNone(verify_code(self.user, codes[0]))
        device.refresh_from_db()
        self.assertEqual(len(device.recovery_hashes), 9)
        self.assertNotIn(codes[0], str(device.recovery_hashes))

    def test_other_local_apps_cannot_replace_enrollment_session(self):
        self.sign_in()
        self.client.post(reverse("mfa_setup"), {"password": self.password})
        pending = self.client.session["mfa_enrollment"]
        secret = cipher().decrypt(pending["secret"].encode()).decode()

        # Another app on a different localhost port sets Django's default cookie.
        self.client.cookies["sessionid"] = "another-app-session"
        response = self.client.post(reverse("mfa_setup"), {"code": pyotp.TOTP(secret).now()}, follow=True)

        self.assertContains(response, "Save your recovery codes")
        self.assertEqual(response.request["PATH_INFO"], reverse("mfa_recovery"))
        self.assertIn("mfa_verified", self.client.session)
        self.assertRedirects(self.client.get(reverse("role_redirect")), "/dashboard/")

    def test_other_local_apps_cannot_replace_csrf_cookie_during_verification(self):
        self.device()
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("login"))
        response = client.post(reverse("login"), {
            "username": self.user.username,
            "password": self.password,
            "csrfmiddlewaretoken": client.cookies[settings.CSRF_COOKIE_NAME].value,
        })
        self.assertEqual(response.status_code, 302)
        client.get(reverse("mfa_verify"))
        csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value

        # Cookies are scoped to the hostname, so another port can set this name.
        client.cookies["csrftoken"] = "a" * 32
        response = client.post(reverse("mfa_verify"), {
            "code": pyotp.TOTP(self.secret).now(),
            "csrfmiddlewaretoken": csrf_token,
        })

        self.assertRedirects(response, reverse("role_redirect"), fetch_redirect_response=False)
        self.assertEqual(client.get("/dashboard/").status_code, 200)

    def test_password_only_session_must_verify_and_next_cannot_leave_site(self):
        self.device()
        self.sign_in()
        self.assertTrue(self.client.get('/dashboard/')["Location"].startswith(reverse("mfa_verify")))
        response = self.client.post(reverse("mfa_verify"), {"code": pyotp.TOTP(self.secret).now(), "next": "https://attacker.invalid/"})
        self.assertRedirects(response, reverse("role_redirect"), fetch_redirect_response=False)
        self.assertEqual(self.client.get('/dashboard/').status_code, 200)

    def test_expired_password_challenge_and_enrollment_require_fresh_password(self):
        self.device()
        self.sign_in()
        session = self.client.session
        session["password_verified_at"] = time.time() - 700
        session.save()
        response = self.client.get(reverse("mfa_verify"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("login")))
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(AUTH_PASSWORD_ATTEMPT_LIMIT=2)
    def test_login_throttle_covers_aliases_and_ignores_spoofed_forwarded_ip(self):
        for username in ('LEGACY__security-admin', 'security-admin'):
            self.assertEqual(self.client.post(reverse("login"), {"username": username, "password": "wrong"}, HTTP_X_FORWARDED_FOR='203.0.113.1').status_code, 200)
        with patch('apps.accounts.forms.authenticate') as authenticate:
            response = self.client.post(reverse("login"), {"username": self.user.username, "password": self.password}, HTTP_X_FORWARDED_FOR='203.0.113.2')
            self.assertEqual(response.status_code, 429)
            self.assertIn("Retry-After", response)
            authenticate.assert_not_called()
        self.assertNotIn(self.user.username, str(list(AuthenticationThrottle.objects.values())))

    def test_attempt_budget_expires(self):
        self.assertEqual(reserve_attempt('test', 'account', 1), 0)
        self.assertGreater(reserve_attempt('test', 'account', 1), 0)
        AuthenticationThrottle.objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))
        self.assertEqual(reserve_attempt('test', 'account', 1), 0)

    @override_settings(AUTH_MFA_ATTEMPT_LIMIT=2)
    def test_mfa_throttle_blocks_even_a_valid_code_after_budget_is_exhausted(self):
        self.device(); self.sign_in()
        for _ in range(2):
            self.assertEqual(self.client.post(reverse("mfa_verify"), {"code": "invalid"}).status_code, 200)
        self.assertEqual(self.client.post(reverse("mfa_verify"), {"code": pyotp.TOTP(self.secret).now()}).status_code, 429)
        self.assertNotIn("mfa_verified", self.client.session)

    def test_reset_does_not_disclose_whether_an_account_exists(self):
        self.user.email = 'admin@example.invalid'; self.user.save()
        for value in ('missing-user', self.user.username):
            response = self.client.post(reverse("password_reset"), {"email": value})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], reverse("password_reset_done"))

    def test_csrf_is_required_for_enrollment_and_verification(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.user)
        self.assertEqual(client.post(reverse("mfa_setup"), {"password": self.password}).status_code, 403)
        self.device()
        self.assertEqual(client.post(reverse("mfa_verify"), {"code": '000000'}).status_code, 403)

    @override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
    def test_forwarded_addresses_are_used_only_from_trusted_peers(self):
        factory = RequestFactory()
        trusted = factory.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='203.0.113.4, 127.0.0.1')
        untrusted = factory.get('/', REMOTE_ADDR='203.0.113.5', HTTP_X_FORWARDED_FOR='203.0.113.4')
        self.assertEqual(client_ip(trusted), '203.0.113.4')
        self.assertEqual(client_ip(untrusted), '203.0.113.5')
