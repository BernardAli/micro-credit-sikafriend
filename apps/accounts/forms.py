from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Agent, PayrollAdjustment, PayrollRun
from .tenant_usernames import (
    current_schema_name,
    login_username_candidates,
    tenant_username_exists,
    validate_tenant_scoped_username,
)

UserModel = get_user_model()


def _normalize_email(value):
    return (value or "").strip().lower()


def _validate_unique_user_email(email, *, exclude_user_id=None):
    email = _normalize_email(email)
    if not email:
        return email

    users = UserModel._default_manager.filter(email__iexact=email)
    if exclude_user_id:
        users = users.exclude(pk=exclude_user_id)

    if users.exists():
        raise ValidationError("That email address is already linked to another login account.")

    return email


class TenantAwareAuthenticationForm(AuthenticationForm):
    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username is None:
            username = ""

        if username and password:
            schema_name = current_schema_name(self.request)
            self.user_cache = None
            for candidate in login_username_candidates(username, schema_name=schema_name):
                self.user_cache = authenticate(self.request, username=candidate, password=password)
                if self.user_cache is not None:
                    break

            if self.user_cache is None:
                raise self.get_invalid_login_error()

            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class AgentForm(forms.ModelForm):
    """Edit existing agent — no login fields."""
    class Meta:
        model = Agent
        fields = [
            "agent_id", "name", "phone", "email", "location",
            "workforce_role", "department", "job_title", "employment_type",
            "employment_status", "hire_date", "date_of_birth", "group_name",
            "supervisor", "residential_address", "emergency_contact_name",
            "emergency_contact_phone", "has_admin_access", "payroll_active",
            "preferred_payment_method", "bank_name", "bank_account_name",
            "bank_account_number", "mobile_money_name", "mobile_money_number",
            "tax_number", "social_security_number", "base_salary",
            "housing_allowance", "transport_allowance", "meal_allowance",
            "communication_allowance", "other_allowance", "commission_rate",
            "photo", "ghana_card_front", "ghana_card_back",
            "ghana_card_number", "notes",
        ]
        widgets = {
            "agent_id":          forms.TextInput(attrs={"placeholder": "e.g. AGT-001"}),
            "name":              forms.TextInput(attrs={"placeholder": "Full name"}),
            "phone":             forms.TextInput(attrs={"placeholder": "Phone number"}),
            "email":             forms.EmailInput(attrs={"placeholder": "Email address for recovery"}),
            "location":          forms.TextInput(attrs={"placeholder": "Location / area"}),
            "workforce_role":    forms.Select(),
            "department":        forms.TextInput(attrs={"placeholder": "e.g. Field Operations, HR, Finance"}),
            "job_title":         forms.TextInput(attrs={"placeholder": "e.g. Senior Recovery Officer"}),
            "employment_type":   forms.Select(),
            "employment_status": forms.Select(),
            "hire_date":         forms.DateInput(attrs={"type": "date"}),
            "date_of_birth":     forms.DateInput(attrs={"type": "date"}),
            "group_name":        forms.TextInput(attrs={"placeholder": "Branch, team, or field cluster"}),
            "supervisor":        forms.Select(),
            "residential_address": forms.Textarea(attrs={"rows": 3, "placeholder": "Residential address"}),
            "emergency_contact_name": forms.TextInput(attrs={"placeholder": "Emergency contact name"}),
            "emergency_contact_phone": forms.TextInput(attrs={"placeholder": "Emergency contact phone"}),
            "preferred_payment_method": forms.Select(),
            "bank_name":         forms.TextInput(attrs={"placeholder": "Bank name"}),
            "bank_account_name": forms.TextInput(attrs={"placeholder": "Account name"}),
            "bank_account_number": forms.TextInput(attrs={"placeholder": "Account number"}),
            "mobile_money_name": forms.TextInput(attrs={"placeholder": "Mobile money account name"}),
            "mobile_money_number": forms.TextInput(attrs={"placeholder": "Mobile money number"}),
            "tax_number":        forms.TextInput(attrs={"placeholder": "Tax number"}),
            "social_security_number": forms.TextInput(attrs={"placeholder": "SSNIT / social security number"}),
            "base_salary":       forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "housing_allowance": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "transport_allowance": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "meal_allowance":    forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "communication_allowance": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "other_allowance":   forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "commission_rate":   forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100"}),
            "ghana_card_number": forms.TextInput(attrs={"placeholder": "Ghana Card number"}),
            "notes":             forms.Textarea(attrs={"rows": 4, "placeholder": "Internal HR, payroll, or operational notes"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = Agent.objects.order_by("name")
        self.fields["supervisor"].required = False

    def clean_email(self):
        email = _normalize_email(self.cleaned_data.get("email"))
        exclude_user_id = self.instance.user_id if getattr(self.instance, "pk", None) else None
        return _validate_unique_user_email(email, exclude_user_id=exclude_user_id)

    def clean_ghana_card_number(self):
        value = (self.cleaned_data.get("ghana_card_number") or "").strip().upper()
        if not value:
            return None
        return value


class AgentBulkImportForm(forms.Form):
    FILE_TYPE_CHOICES = [
        ("auto", "Auto-detect from file name"),
        ("csv", "CSV (.csv)"),
        ("excel", "Excel (.xlsx)"),
        ("json", "JSON (.json)"),
        ("xml", "XML (.xml)"),
    ]

    IMPORT_MODE_CHOICES = [
        ("create_only", "Create new agents only"),
        ("upsert", "Create new or update matching agent IDs"),
    ]

    data_file = forms.FileField(
        label="Agent import file",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".csv,.xlsx,.json,.xml",
            }
        ),
    )
    file_type = forms.ChoiceField(
        choices=FILE_TYPE_CHOICES,
        initial="auto",
        help_text="Choose a format explicitly or let the system infer it from the uploaded file name.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    import_mode = forms.ChoiceField(
        choices=IMPORT_MODE_CHOICES,
        initial="create_only",
        help_text="Use update mode when you want matching agent IDs to be refreshed instead of rejected.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class AgentRegisterForm(forms.ModelForm):
    """
    Admin-only form: create an Agent and its Django login account in one step.
    """
    # ── Login credentials ──────────────────────────────────────
    username   = forms.CharField(
        max_length=150,
        help_text="Username the agent will use to log in.",
    )
    password   = forms.CharField(
        widget=forms.PasswordInput,
        help_text="Initial password. Agent should change it after first login.",
    )
    password2  = forms.CharField(
        widget=forms.PasswordInput,
        label="Confirm password",
    )

    class Meta:
        model = Agent
        fields = [
            "agent_id", "name", "phone", "email", "location",
            "workforce_role", "department", "job_title", "employment_type",
            "employment_status", "hire_date", "date_of_birth", "group_name",
            "supervisor", "residential_address", "emergency_contact_name",
            "emergency_contact_phone", "has_admin_access", "payroll_active",
            "preferred_payment_method", "bank_name", "bank_account_name",
            "bank_account_number", "mobile_money_name", "mobile_money_number",
            "tax_number", "social_security_number", "base_salary",
            "housing_allowance", "transport_allowance", "meal_allowance",
            "communication_allowance", "other_allowance", "commission_rate",
            "photo", "ghana_card_front", "ghana_card_back",
            "ghana_card_number", "notes",
        ]
        widgets = {
            "agent_id":          forms.TextInput(attrs={"placeholder": "e.g. AGT-001"}),
            "name":              forms.TextInput(attrs={"placeholder": "Full name"}),
            "phone":             forms.TextInput(attrs={"placeholder": "Phone number"}),
            "email":             forms.EmailInput(attrs={"placeholder": "Email address for recovery"}),
            "location":          forms.TextInput(attrs={"placeholder": "Location / area"}),
            "workforce_role":    forms.Select(),
            "department":        forms.TextInput(attrs={"placeholder": "e.g. Field Operations, HR, Finance"}),
            "job_title":         forms.TextInput(attrs={"placeholder": "Job title"}),
            "employment_type":   forms.Select(),
            "employment_status": forms.Select(),
            "hire_date":         forms.DateInput(attrs={"type": "date"}),
            "date_of_birth":     forms.DateInput(attrs={"type": "date"}),
            "group_name":        forms.TextInput(attrs={"placeholder": "Branch, team, or field cluster"}),
            "supervisor":        forms.Select(),
            "residential_address": forms.Textarea(attrs={"rows": 3, "placeholder": "Residential address"}),
            "emergency_contact_name": forms.TextInput(attrs={"placeholder": "Emergency contact name"}),
            "emergency_contact_phone": forms.TextInput(attrs={"placeholder": "Emergency contact phone"}),
            "preferred_payment_method": forms.Select(),
            "bank_name":         forms.TextInput(attrs={"placeholder": "Bank name"}),
            "bank_account_name": forms.TextInput(attrs={"placeholder": "Account name"}),
            "bank_account_number": forms.TextInput(attrs={"placeholder": "Account number"}),
            "mobile_money_name": forms.TextInput(attrs={"placeholder": "Mobile money account name"}),
            "mobile_money_number": forms.TextInput(attrs={"placeholder": "Mobile money number"}),
            "tax_number":        forms.TextInput(attrs={"placeholder": "Tax number"}),
            "social_security_number": forms.TextInput(attrs={"placeholder": "SSNIT / social security number"}),
            "base_salary":       forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "housing_allowance": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "transport_allowance": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "meal_allowance":    forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "communication_allowance": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "other_allowance":   forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "commission_rate":   forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100"}),
            "ghana_card_number": forms.TextInput(attrs={"placeholder": "Ghana Card number"}),
            "notes":             forms.Textarea(attrs={"rows": 4, "placeholder": "Internal HR, payroll, or operational notes"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = Agent.objects.order_by("name")
        self.fields["supervisor"].required = False

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError("That username is already taken.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned

    def clean_email(self):
        return _validate_unique_user_email(self.cleaned_data.get("email"))

    def clean_ghana_card_number(self):
        value = (self.cleaned_data.get("ghana_card_number") or "").strip().upper()
        if not value:
            return None
        return value

    def save(self, commit=True):
        agent = super().save(commit=False)
        # Create the Django User
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            email=_normalize_email(self.cleaned_data.get("email")),
            password=self.cleaned_data["password"],
            first_name=agent.name.split()[0] if agent.name else "",
            last_name=" ".join(agent.name.split()[1:]) if agent.name else "",
        )
        user.is_staff = agent.has_admin_access
        user.save()
        agent.user = user
        if commit:
            agent.save()
        return agent


class AgentResetPasswordForm(forms.Form):
    """Admin-only: reset an agent's login password."""
    new_password  = forms.CharField(widget=forms.PasswordInput, label="New password")
    new_password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm new password")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_password") != cleaned.get("new_password2"):
            self.add_error("new_password2", "Passwords do not match.")
        return cleaned


class PayrollRunForm(forms.ModelForm):
    class Meta:
        model = PayrollRun
        fields = [
            "title",
            "period_start",
            "period_end",
            "pay_date",
            "include_active_only",
            "include_commissions",
            "include_loan_recovery",
            "notes",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. April 2026 Payroll"}),
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
            "pay_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional payroll notes"}),
        }

    def clean(self):
        cleaned = super().clean()
        period_start = cleaned.get("period_start")
        period_end = cleaned.get("period_end")
        pay_date = cleaned.get("pay_date")
        if period_start and period_end and period_end < period_start:
            self.add_error("period_end", "Period end must be on or after the period start.")
        if pay_date and period_end and pay_date < period_end:
            self.add_error("pay_date", "Pay date should be on or after the payroll period end.")
        return cleaned


class PayrollAdjustmentForm(forms.ModelForm):
    class Meta:
        model = PayrollAdjustment
        fields = [
            "employee",
            "adjustment_type",
            "category",
            "label",
            "amount",
            "is_recurring",
            "is_active",
            "effective_from",
            "effective_to",
            "notes",
        ]
        widgets = {
            "employee": forms.Select(),
            "adjustment_type": forms.Select(),
            "category": forms.Select(),
            "label": forms.TextInput(attrs={"placeholder": "e.g. Performance bonus"}),
            "amount": forms.NumberInput(attrs={"step": "0.01"}),
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "effective_to": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional payroll adjustment notes"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Agent.objects.order_by("name")

    def clean(self):
        cleaned = super().clean()
        effective_from = cleaned.get("effective_from")
        effective_to = cleaned.get("effective_to")
        if effective_from and effective_to and effective_to < effective_from:
            self.add_error("effective_to", "Effective end date cannot be earlier than the start date.")
        return cleaned


class BorrowerCreateLoginForm(forms.Form):
    """Admin creates a portal login for a borrower."""
    username  = forms.CharField(max_length=150, help_text="Username the borrower will use to log in.")
    password  = forms.CharField(widget=forms.PasswordInput, help_text="Initial password.")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        schema_name = current_schema_name()
        try:
            username = validate_tenant_scoped_username(username, schema_name=schema_name)
        except ValueError as exc:
            raise ValidationError(str(exc))
        if tenant_username_exists(username, schema_name=schema_name):
            raise ValidationError("That username is already taken in this company.")
        return username

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password2"):
            self.add_error("password2", "Passwords do not match.")
        return cleaned


class UsernameOrEmailPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    email = forms.CharField(
        label="Username or email",
        max_length=254,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter your username or email",
                "autocomplete": "username",
            }
        ),
    )

    error_messages = {
        "unknown_account": "We could not find an active account with those details.",
        "missing_email": (
            "This account does not have a recovery email address on file yet. "
            "Please contact your administrator for a manual password reset."
        ),
    }

    def _matching_users(self, identifier):
        identifier = (identifier or "").strip()
        if not identifier:
            return []

        if "@" in identifier:
            return list(UserModel._default_manager.filter(
                email__iexact=identifier,
                is_active=True,
            ))

        schema_name = current_schema_name(self.request)
        for candidate in login_username_candidates(identifier, schema_name=schema_name):
            matches = list(UserModel._default_manager.filter(username__iexact=candidate, is_active=True).order_by("id"))
            if matches:
                return matches
        return []

    def _user_can_reset(self, user):
        return bool((user.email or "").strip()) and user.has_usable_password()

    def clean_email(self):
        identifier = (self.cleaned_data.get("email") or "").strip()
        matches = list(self._matching_users(identifier))
        if not matches:
            raise ValidationError(self.error_messages["unknown_account"])

        if not any(self._user_can_reset(user) for user in matches):
            raise ValidationError(self.error_messages["missing_email"])

        return identifier

    def get_users(self, email):
        for user in self._matching_users(email):
            if self._user_can_reset(user):
                yield user


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {
                "placeholder": "Enter a new password",
                "autocomplete": "new-password",
            }
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "placeholder": "Confirm the new password",
                "autocomplete": "new-password",
            }
        )
