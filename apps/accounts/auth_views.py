from django.contrib.auth.views import LoginView
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import reverse_lazy

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
