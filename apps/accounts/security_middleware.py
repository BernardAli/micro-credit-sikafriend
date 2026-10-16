"""Enforce MFA on every staff route, including Django admin and authenticated media."""
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.http import HttpResponseForbidden
from django.contrib.auth import logout
from django.urls import reverse
from django.utils.cache import patch_cache_control

from .models import Authenticator
from .security import session_verified


class AccountSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        was_authenticated = request.user.is_authenticated
        response = None
        if settings.MFA_ENABLED:
            if request.path == reverse("admin:login"):
                response = redirect(reverse("login") + "?" + urlencode({"next": reverse("admin:index")}))
            elif request.user.is_authenticated:
                employee = getattr(request.user, "agent_profile", None)
                if employee and employee.employment_status in {"SUSPENDED", "EXITED"}:
                    logout(request)
                    response = HttpResponseForbidden("Your workforce account is inactive. Contact management.")
                device = Authenticator.objects.only("user_id", "confirmed_at", "revision").filter(user_id=request.user.pk).first()
                request.mfa_device = device
                needed = bool(device and device.confirmed_at) or (
                    settings.STAFF_MFA_REQUIRED and (request.user.is_staff or request.user.is_superuser or employee is not None)
                )
                allowed = {reverse(name) for name in ("mfa_setup", "mfa_verify", "logout", "login")}
                if response is None and needed and not session_verified(request, device) and request.path not in allowed:
                    target = "mfa_verify" if device and device.confirmed_at else "mfa_setup"
                    response = redirect(reverse(target) + "?" + urlencode({"next": request.get_full_path()}))
        if response is None:
            response = self.get_response(request)
        if was_authenticated or request.user.is_authenticated or request.path.startswith(("/login/", "/password-reset/", "/reset/", "/account-security/", "/admin/")):
            patch_cache_control(response, private=True, no_cache=True, no_store=True, must_revalidate=True)
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response
