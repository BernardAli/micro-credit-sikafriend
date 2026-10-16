from django.contrib.auth.views import LoginView
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import reverse_lazy
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.db import transaction
from django.utils import timezone
from cryptography.fernet import InvalidToken
import base64
import io
import json
import time
import uuid
import pyotp
import qrcode

from apps.core.audit import log_activity
from .models import Authenticator
from .security import (account_identifier, cipher, clear_attempts, mark_verified,
                       new_recovery_codes, reserve_request, session_verified, verify_code)

from apps.company.models import CompanyProfile

from .forms import (
    StyledSetPasswordForm,
    StandaloneAuthenticationForm,
    UsernameOrEmailPasswordResetForm,
)


def _company_recovery_context():
    try:
        profile = CompanyProfile.get_solo()
    except Exception:
        profile = None

    if profile is None:
        return {
            "company_name": "MicroCredit",
            "support_email": "",
            "support_phone": "",
        }

    return {
        "company_name": profile.company_name,
        "support_email": (profile.email or "").strip(),
        "support_phone": (profile.phone or "").strip(),
    }


class PasswordResetRequestView(PasswordResetView):
    form_class = UsernameOrEmailPasswordResetForm
    template_name = "registration/tenant_password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def post(self, request, *args, **kwargs):
        wait = reserve_request(request, "password-reset", account_identifier(request.POST.get("email")), settings.AUTH_RESET_ATTEMPT_LIMIT)
        if wait:
            form = self.form_class(request=request)
            form.cleaned_data = {}
            form.add_error(None, "Too many attempts. Please wait before trying again.")
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response["Retry-After"] = str(wait)
            return response
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_company_recovery_context())
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        self.extra_email_context = _company_recovery_context()
        return super().form_valid(form)


class TenantLoginPageView(LoginView):
    form_class = StandaloneAuthenticationForm

    def post(self, request, *args, **kwargs):
        wait = reserve_request(request, "password", account_identifier(request.POST.get("username")), settings.AUTH_PASSWORD_ATTEMPT_LIMIT)
        if wait:
            form = self.form_class(request=request)
            form.cleaned_data = {}
            form.add_error(None, "Too many sign-in attempts. Please wait before trying again.")
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response["Retry-After"] = str(wait)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.pop("mfa_verified", None)
        self.request.session["password_verified_at"] = time.time()
        clear_attempts("password", account_identifier(form.cleaned_data["username"]))
        return response


class PasswordResetDonePageView(PasswordResetDoneView):
    template_name = "registration/tenant_password_reset_done.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_company_recovery_context())
        return context


class PasswordResetConfirmPageView(PasswordResetConfirmView):
    form_class = StyledSetPasswordForm
    template_name = "registration/tenant_password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_company_recovery_context())
        return context


class PasswordResetCompletePageView(PasswordResetCompleteView):
    template_name = "registration/tenant_password_reset_complete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_company_recovery_context())
        return context


def _next(request):
    target = request.POST.get("next") or request.GET.get("next") or reverse("role_redirect")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return reverse("role_redirect")
    if target.split("?", 1)[0] in {reverse(name) for name in ("login", "mfa_setup", "mfa_verify")}:
        return reverse("role_redirect")
    return target


def _auth_event(request, action):
    log_activity(category="SYSTEM", action=action, actor=request.user,
                 message="Account security settings updated.", object_type="User", object_id=request.user.pk,
                 request=request)


@login_required
@never_cache
@sensitive_post_parameters("password", "code")
@sensitive_variables("secret", "codes", "pending")
def mfa_setup(request):
    device = Authenticator.objects.filter(user=request.user, confirmed_at__isnull=False).first()
    target = _next(request)
    if device:
        return redirect("mfa_verify") if not session_verified(request, device) else redirect("account_security")
    now = time.time()
    pending = request.session.get("mfa_enrollment", {})
    if pending.get("user") != request.user.pk or not 0 <= now - pending.get("at", 0) < settings.MFA_ENROLLMENT_MAX_AGE:
        pending = {}
        request.session.pop("mfa_enrollment", None)
    error = None
    if request.method == "POST":
        wait = reserve_request(request, "mfa", str(request.user.pk), settings.AUTH_MFA_ATTEMPT_LIMIT)
        if wait:
            response = render(request, "registration/mfa_setup.html", {"error": "Too many attempts. Please wait before trying again.", "next": target}, status=429)
            response["Retry-After"] = str(wait)
            return response
        if not pending:
            if request.user.check_password(request.POST.get("password", "")):
                secret = pyotp.random_base32()
                pending = {"user": request.user.pk, "at": now, "secret": cipher().encrypt(secret.encode()).decode()}
                request.session["mfa_enrollment"] = pending
                request.session["password_verified_at"] = now
                clear_attempts("mfa", str(request.user.pk))
            else:
                error = "The password could not be verified."
        else:
            secret = cipher().decrypt(pending["secret"].encode()).decode()
            code = request.POST.get("code", "").strip()
            otp = pyotp.TOTP(secret)
            step = int(now // 30)
            accepted = next((candidate for candidate in (step, step - 1, step + 1)
                             if len(code) == 6 and code.isascii() and code.isdigit() and
                             pyotp.utils.strings_equal(otp.at(candidate * 30), code)), None)
            if accepted is not None:
                codes, hashes = new_recovery_codes()
                with transaction.atomic():
                    device, _ = Authenticator.objects.get_or_create(user=request.user, defaults={"secret_ciphertext": pending["secret"]})
                    device = Authenticator.objects.select_for_update().get(pk=device.pk)
                    if device.confirmed_at:
                        return redirect("mfa_verify")
                    device.secret_ciphertext = pending["secret"]
                    device.confirmed_at = timezone.now()
                    device.last_step = accepted
                    device.recovery_hashes = hashes
                    device.save()
                    _auth_event(request, "MFA_ENROLLED")
                request.session.pop("mfa_enrollment", None)
                mark_verified(request, device)
                request.session["mfa_recovery_codes"] = cipher().encrypt(json.dumps(codes).encode()).decode()
                request.session["mfa_next"] = target
                return redirect("mfa_recovery")
            error = "The code is invalid or expired. Check your authenticator and try again."
    context = {"error": error, "next": target, "enrolling": bool(pending)}
    if pending:
        secret = cipher().decrypt(pending["secret"].encode()).decode()
        uri = pyotp.TOTP(secret).provisioning_uri(name=request.user.get_username(), issuer_name="SikaFriend")
        buffer = io.BytesIO()
        qr_image = qrcode.make(uri, box_size=6, border=4)
        qr_image.save(buffer, format="PNG")
        context.update(secret=secret, qr=base64.b64encode(buffer.getvalue()).decode(), qr_size=qr_image.size[0])
    return render(request, "registration/mfa_setup.html", context)


@login_required
@never_cache
@sensitive_post_parameters("code")
def mfa_verify(request):
    device = Authenticator.objects.filter(user=request.user, confirmed_at__isnull=False).first()
    if not device:
        return redirect(reverse("mfa_setup") + "?next=" + _next(request))
    if not 0 <= time.time() - request.session.get("password_verified_at", 0) < settings.MFA_ENROLLMENT_MAX_AGE:
        target = _next(request)
        logout(request)
        from urllib.parse import urlencode
        return redirect(reverse("login") + "?" + urlencode({"next": target}))
    error = None
    if request.method == "POST":
        wait = reserve_request(request, "mfa", str(request.user.pk), settings.AUTH_MFA_ATTEMPT_LIMIT)
        if wait:
            response = render(request, "registration/mfa_verify.html", {"error": "Too many attempts. Please wait before trying again.", "next": _next(request)}, status=429)
            response["Retry-After"] = str(wait)
            return response
        try:
            verified = verify_code(request.user, request.POST.get("code", "")[:64])
        except InvalidToken:
            verified = None
        if verified:
            mark_verified(request, verified)
            return redirect(_next(request))
        error = "The code is invalid, expired or already used."
    return render(request, "registration/mfa_verify.html", {"error": error, "next": _next(request)})


@login_required
@never_cache
@sensitive_variables("codes")
def mfa_recovery(request):
    encrypted = request.session.pop("mfa_recovery_codes", None)
    if not encrypted:
        return redirect("account_security")
    codes = json.loads(cipher().decrypt(encrypted.encode()))
    return render(request, "registration/mfa_recovery.html", {"codes": codes, "next": request.session.pop("mfa_next", reverse("role_redirect"))})


@login_required
@never_cache
@sensitive_post_parameters("password", "code")
@sensitive_variables("codes")
def account_security(request):
    device = Authenticator.objects.filter(user=request.user, confirmed_at__isnull=False).first()
    if not device:
        return redirect("mfa_setup")
    if not session_verified(request, device):
        return redirect("mfa_verify")
    error = None
    if request.method == "POST":
        wait = reserve_request(request, "mfa", str(request.user.pk), settings.AUTH_MFA_ATTEMPT_LIMIT)
        if wait:
            response = render(request, "registration/account_security.html", {"device": device, "error": "Too many attempts. Please wait."}, status=429)
            response["Retry-After"] = str(wait)
            return response
        if request.user.check_password(request.POST.get("password", "")) and verify_code(request.user, request.POST.get("code", "")[:64], allow_recovery=False):
            codes, hashes = new_recovery_codes()
            with transaction.atomic():
                device = Authenticator.objects.select_for_update().get(pk=device.pk)
                device.recovery_hashes = hashes
                device.revision = uuid.uuid4()
                device.save(update_fields=["recovery_hashes", "revision"])
                _auth_event(request, "MFA_RECOVERY_REGENERATED")
            mark_verified(request, device)
            request.session["mfa_recovery_codes"] = cipher().encrypt(json.dumps(codes).encode()).decode()
            return redirect("mfa_recovery")
        error = "Verify your current password and a fresh authenticator code."
    return render(request, "registration/account_security.html", {"device": device, "error": error})
