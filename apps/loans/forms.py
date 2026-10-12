from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.usernames import portal_username_exists, validate_portal_username

from .models import Borrower, Loan, Payment, SecurityDeposit, Portfolio
from .portfolios import agent_portfolio_ids, agent_can_access

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
        raise forms.ValidationError("That email address is already linked to another login account.")

    return email


def _get_category_label_dynamic(amount):
    """Get tier label from company profile or fall back to hardcoded defaults."""
    amount = Decimal(str(amount or "0"))
    try:
        from apps.company.models import CompanyProfile
        tiers = CompanyProfile.get_solo().tiers_for_template
        for tier in tiers:
            if amount <= Decimal(str(tier["max"])):
                return tier["label"]
        return tiers[-1]["label"] if tiers else "Executive"
    except Exception:
        pass
    if amount <= Decimal("3000.00"): return "Bronze"
    elif amount <= Decimal("5000.00"): return "Silver"
    elif amount <= Decimal("10000.00"): return "Gold"
    elif amount <= Decimal("15000.00"): return "Platinum"
    elif amount <= Decimal("20000.00"): return "Diamond"
    return "Executive"


class BorrowerForm(forms.ModelForm):
    """
    Borrower profile form.
    Also creates a portal login account — username is required, password is
    auto-generated and shown to the creator after save.
    Set `creating=True` in kwargs when creating (not editing) a borrower.
    """

    # ── Portal login credentials ──────────────────────────────
    portal_username = forms.CharField(
        max_length=150,
        label="Portal Username",
        help_text="Username the borrower will use to log in to their portal.",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. kofi.mensah"}),
    )

    def __init__(self, *args, creating=True, agent_override=None, **kwargs):
        self.creating = creating
        super().__init__(*args, **kwargs)
        self.fields["portfolio"].required = True
        self.fields["portfolio"].queryset = Portfolio.objects.filter(is_active=True)
        if agent_override:
            self.fields["portfolio"].queryset = self.fields["portfolio"].queryset.filter(pk__in=agent_portfolio_ids(agent_override))

        # On edit, hide the portal_username field (login already exists)
        if not creating:
            self.fields.pop("portal_username", None)

        # Dynamically set language choices from company profile
        try:
            from apps.company.models import CompanyProfile
            langs = CompanyProfile.get_solo().languages_for_template
            choices = [("", "---------")] + [(l, l) for l in langs]
            self.fields["preferred_language"].widget = forms.Select(attrs={"class": "form-select"})
            self.fields["preferred_language"].choices = choices
        except Exception:
            pass

    def clean_portal_username(self):
        username = self.cleaned_data.get("portal_username", "").strip()
        try:
            username = validate_portal_username(username)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))
        if portal_username_exists(username):
            raise forms.ValidationError("That username is already taken in this company. Choose a different one.")
        return username

    class Meta:
        model = Borrower
        fields = [
            "portfolio",
            "full_name",
            "national_id",
            "gender",
            "date_of_birth",
            "borrower_type",
            "phone",
            "alternative_phone",
            "email",
            "location",
            "digital_address",
            "nearest_landmark",
            "residence_directions",
            "years_at_residence",
            "residence_status",
            "residence_status_other",
            "photo",
            "ghana_card_front",
            "ghana_card_back",
            "ghana_card_number",
            "group_name",
            "preferred_language",
        ]
        widgets = {
            "portfolio": forms.Select(attrs={"class": "form-select"}),
            "full_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter full name"}),
            "national_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ghana Card / Passport number"}),
            "gender": forms.Select(attrs={"class": "form-select"}),
            "date_of_birth": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "borrower_type": forms.Select(attrs={"class": "form-select"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter phone number"}),
            "alternative_phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Family or emergency phone number"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Enter email address for recovery"}),
            "location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter location"}),
            "digital_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "House number or GhanaPost GPS address"}),
            "nearest_landmark": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nearest landmark"}),
            "residence_directions": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Detailed directions with turns, junctions, or notable signs"}),
            "years_at_residence": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 2 years, 6 months"}),
            "residence_status": forms.Select(attrs={"class": "form-select"}),
            "residence_status_other": forms.TextInput(attrs={"class": "form-control", "placeholder": "Specify if other"}),
            "ghana_card_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Ghana Card number"}),
            "group_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter group name"}),
            "preferred_language": forms.Select(attrs={"class": "form-select"}),
            "photo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "ghana_card_front": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "ghana_card_back": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        return phone

    def clean_email(self):
        email = _normalize_email(self.cleaned_data.get("email"))
        exclude_user_id = self.instance.user_id if getattr(self.instance, "pk", None) else None
        return _validate_unique_user_email(email, exclude_user_id=exclude_user_id)

    def clean_full_name(self):
        full_name = (self.cleaned_data.get("full_name") or "").strip()
        return full_name

    def clean(self):
        cleaned_data = super().clean()
        portfolio = cleaned_data.get("portfolio")
        if portfolio and (not self.instance.pk or not hasattr(self.instance, "identity")) and portfolio.next_customer_number > 1000:
            self.add_error("portfolio", "This portfolio has issued all 1,000 Customer IDs.")
        residence_status = cleaned_data.get("residence_status")
        residence_status_other = (cleaned_data.get("residence_status_other") or "").strip()
        if residence_status == "OTHER" and not residence_status_other:
            self.add_error("residence_status_other", "Specify the residence status when 'Other' is selected.")
        return cleaned_data


class BorrowerBulkImportForm(forms.Form):
    FILE_TYPE_CHOICES = [
        ("auto", "Auto-detect from file name"),
        ("csv", "CSV (.csv)"),
        ("excel", "Excel (.xlsx)"),
        ("json", "JSON (.json)"),
        ("xml", "XML (.xml)"),
    ]

    IMPORT_MODE_CHOICES = [
        ("create_only", "Create new borrowers only"),
        ("upsert", "Create new or update matching borrower IDs"),
    ]

    data_file = forms.FileField(
        label="Borrower import file",
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
        help_text="Use update mode when you want matching borrower IDs to be refreshed instead of rejected.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class LoanBulkImportForm(forms.Form):
    FILE_TYPE_CHOICES = [
        ("auto", "Auto-detect from file name"),
        ("csv", "CSV (.csv)"),
        ("excel", "Excel (.xlsx)"),
        ("json", "JSON (.json)"),
        ("xml", "XML (.xml)"),
    ]

    IMPORT_MODE_CHOICES = [
        ("create_only", "Create new loans only"),
        ("upsert", "Create new loans or update matching loan IDs"),
    ]

    data_file = forms.FileField(
        label="Loan import file",
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
        help_text="Use update mode only when your file includes existing database loan IDs for rows that should be refreshed.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class LoanForm(forms.ModelForm):
    start_date = forms.DateField(
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"},
            format="%Y-%m-%d"
        )
    )

    loan_category_display = forms.CharField(
        required=False,
        label="Loan Category",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "readonly": "readonly",
                "placeholder": "Auto-calculated from amount",
            }
        ),
    )

    class Meta:
        model = Loan
        fields = [
            "borrower",
            "agent_name",
            "amount",
            "loan_acquisition_date",
            "repayment_frequency",
            "sector",
            "sector_other",
            "duration_months",
            "duration_weeks",
            "start_date",
            "weekly_payment",
            "borrower_declaration_accepted",
            "borrower_signature_name",
            "borrower_signed_date",
            "guarantor_name",
            "guarantor_id_number",
            "guarantor_signature_name",
            "guarantor_signed_date",
            "collateral_type",
            "collateral_details",
            "collateral_estimated_value",
            "collateral_location",
            "collateral_borrower_consent_accepted",
            "collateral_borrower_signed_date",
            "collateral_guarantor_signature_name",
            "collateral_guarantor_signed_date",
            "application_received_by",
            "application_received_date",
            "approved_amount",
            "approved_repayment_plan",
            "loan_officer_signature_name",
            "approval_manager_signature_name",
            "approval_date",
        ]
        widgets = {
            "borrower": forms.Select(attrs={"class": "form-select"}),
            "agent_name": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "loan_acquisition_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "repayment_frequency": forms.Select(attrs={"class": "form-select"}),
            "sector": forms.Select(attrs={"class": "form-select"}),
            "sector_other": forms.TextInput(attrs={"class": "form-control", "placeholder": "Specify sector"}),
            "duration_months": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "duration_weeks": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "weekly_payment": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "borrower_declaration_accepted": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "borrower_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Borrower's signed name"}),
            "borrower_signed_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "guarantor_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Guarantor or group leader name"}),
            "guarantor_id_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Guarantor ID number"}),
            "guarantor_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Guarantor signed name"}),
            "guarantor_signed_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "collateral_type": forms.TextInput(attrs={"class": "form-control", "placeholder": "Vehicle, land, electronics, jewelry"}),
            "collateral_details": forms.TextInput(attrs={"class": "form-control", "placeholder": "Identification number or details"}),
            "collateral_estimated_value": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "collateral_location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Collateral location"}),
            "collateral_borrower_consent_accepted": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "collateral_borrower_signed_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "collateral_guarantor_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Guarantor signed name"}),
            "collateral_guarantor_signed_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "application_received_by": forms.TextInput(attrs={"class": "form-control", "placeholder": "Staff name"}),
            "application_received_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "approved_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "approved_repayment_plan": forms.TextInput(attrs={"class": "form-control", "placeholder": "Approved repayment plan"}),
            "loan_officer_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Loan officer signed name"}),
            "approval_manager_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Approval manager signed name"}),
            "approval_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, agent_override=None, **kwargs):
        """
        agent_override: Agent instance. When set the agent_name field is hidden
        and locked — the agent can only issue loans under their own name.
        """
        super().__init__(*args, **kwargs)

        if agent_override is not None:
            # Lock agent_name to this agent; hide the dropdown
            self.fields["agent_name"].initial  = agent_override.pk
            self.fields["agent_name"].widget   = forms.HiddenInput()
            self.fields["agent_name"].required = False
            self.agent_override = agent_override
            self.fields["agent_name"].disabled = True
            self.fields["borrower"].queryset = Borrower.objects.filter(portfolio_id__in=agent_portfolio_ids(agent_override))
        else:
            self.agent_override = None

        amount = None
        if self.is_bound:
            raw_amount = self.data.get(self.add_prefix("amount")) or self.data.get("amount")
            try:
                amount = Decimal(str(raw_amount))
            except Exception:
                amount = None
        elif self.instance and self.instance.pk:
            amount = self.instance.amount

        if amount is not None:
            self.fields["loan_category_display"].initial = self.get_category_label(amount)

        self.order_fields([
            "borrower",
            "agent_name",
            "amount",
            "loan_category_display",
            "loan_acquisition_date",
            "repayment_frequency",
            "weekly_payment",
            "duration_months",
            "duration_weeks",
            "start_date",
            "sector",
            "sector_other",
            "borrower_declaration_accepted",
            "borrower_signature_name",
            "borrower_signed_date",
            "guarantor_name",
            "guarantor_id_number",
            "guarantor_signature_name",
            "guarantor_signed_date",
            "collateral_type",
            "collateral_details",
            "collateral_estimated_value",
            "collateral_location",
            "collateral_borrower_consent_accepted",
            "collateral_borrower_signed_date",
            "collateral_guarantor_signature_name",
            "collateral_guarantor_signed_date",
            "application_received_by",
            "application_received_date",
            "approved_amount",
            "approved_repayment_plan",
            "loan_officer_signature_name",
            "approval_manager_signature_name",
            "approval_date",
        ])

    @staticmethod
    def get_category_label(amount):
        return _get_category_label_dynamic(amount)

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None:
            raise forms.ValidationError("Loan amount is required.")
        if amount <= Decimal("0.00"):
            raise forms.ValidationError("Loan amount must be greater than 0.")
        return amount

    def clean_duration_weeks(self):
        duration_weeks = self.cleaned_data.get("duration_weeks")
        if duration_weeks is None:
            return 0
        if duration_weeks < 0:
            raise forms.ValidationError("Duration in weeks cannot be negative.")
        return duration_weeks

    def clean_duration_months(self):
        duration_months = self.cleaned_data.get("duration_months")
        if duration_months is None:
            return 0
        if duration_months < 0:
            raise forms.ValidationError("Duration in months cannot be negative.")
        return duration_months

    def clean_weekly_payment(self):
        weekly_payment = self.cleaned_data.get("weekly_payment")
        if weekly_payment is None:
            raise forms.ValidationError("Repayment amount is required.")
        if weekly_payment <= Decimal("0.00"):
            raise forms.ValidationError("Repayment amount must be greater than 0.")
        return weekly_payment

    def clean(self):
        cleaned_data = super().clean()
        borrower = cleaned_data.get("borrower")
        agent = self.agent_override or cleaned_data.get("agent_name")
        if borrower and not borrower.portfolio_id:
            self.add_error("borrower", "Assign this customer to a portfolio first.")
        elif borrower and agent and not agent_can_access(agent, borrower):
            self.add_error("agent_name", "Select an officer currently assigned to this customer's portfolio.")
        months = cleaned_data.get("duration_months") or 0
        weeks = cleaned_data.get("duration_weeks") or 0
        sector = cleaned_data.get("sector")
        sector_other = (cleaned_data.get("sector_other") or "").strip()
        if months <= 0 and weeks <= 0:
            self.add_error("duration_weeks", "Enter a duration in months, weeks, or both.")
        if sector == "OTHER" and not sector_other:
            self.add_error("sector_other", "Specify the sector when 'Other' is selected.")
        return cleaned_data


class PaymentForm(forms.ModelForm):
    payment_date = forms.DateField(
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"},
            format="%Y-%m-%d"
        )
    )

    class Meta:
        model = Payment
        fields = ["loan", "payment_date", "amount", "reference", "note"]
        widgets = {
            "loan": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "reference": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter payment reference"}),
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None:
            raise forms.ValidationError("Payment amount is required.")
        if amount <= Decimal("0.00"):
            raise forms.ValidationError("Payment amount must be greater than 0.")
        return amount


class LoanCreateForBorrowerForm(forms.ModelForm):
    start_date = forms.DateField(
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"},
            format="%Y-%m-%d"
        )
    )

    loan_category_display = forms.CharField(
        required=False,
        label="Loan Category",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "readonly": "readonly",
                "placeholder": "Auto-calculated from amount",
            }
        ),
    )

    class Meta:
        model = Loan
        fields = [
            "agent_name",
            "amount",
            "loan_acquisition_date",
            "repayment_frequency",
            "sector",
            "sector_other",
            "duration_months",
            "duration_weeks",
            "start_date",
            "weekly_payment",
            "borrower_declaration_accepted",
            "borrower_signature_name",
            "borrower_signed_date",
            "guarantor_name",
            "guarantor_id_number",
            "guarantor_signature_name",
            "guarantor_signed_date",
            "collateral_type",
            "collateral_details",
            "collateral_estimated_value",
            "collateral_location",
            "collateral_borrower_consent_accepted",
            "collateral_borrower_signed_date",
            "collateral_guarantor_signature_name",
            "collateral_guarantor_signed_date",
            "application_received_by",
            "application_received_date",
            "approved_amount",
            "approved_repayment_plan",
            "loan_officer_signature_name",
            "approval_manager_signature_name",
            "approval_date",
        ]
        widgets = {
            "agent_name": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "loan_acquisition_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "repayment_frequency": forms.Select(attrs={"class": "form-select"}),
            "sector": forms.Select(attrs={"class": "form-select"}),
            "sector_other": forms.TextInput(attrs={"class": "form-control", "placeholder": "Specify sector"}),
            "duration_months": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "duration_weeks": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "weekly_payment": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "borrower_declaration_accepted": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "borrower_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Borrower's signed name"}),
            "borrower_signed_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "guarantor_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Guarantor or group leader name"}),
            "guarantor_id_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Guarantor ID number"}),
            "guarantor_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Guarantor signed name"}),
            "guarantor_signed_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "collateral_type": forms.TextInput(attrs={"class": "form-control", "placeholder": "Vehicle, land, electronics, jewelry"}),
            "collateral_details": forms.TextInput(attrs={"class": "form-control", "placeholder": "Identification number or details"}),
            "collateral_estimated_value": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "collateral_location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Collateral location"}),
            "collateral_borrower_consent_accepted": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "collateral_borrower_signed_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "collateral_guarantor_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Guarantor signed name"}),
            "collateral_guarantor_signed_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "application_received_by": forms.TextInput(attrs={"class": "form-control", "placeholder": "Staff name"}),
            "application_received_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "approved_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "approved_repayment_plan": forms.TextInput(attrs={"class": "form-control", "placeholder": "Approved repayment plan"}),
            "loan_officer_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Loan officer signed name"}),
            "approval_manager_signature_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Approval manager signed name"}),
            "approval_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, agent_override=None, borrower=None, **kwargs):
        """
        agent_override: Agent instance. When set the agent_name field is hidden
        and locked — the agent issues the loan under their own name automatically.
        """
        super().__init__(*args, **kwargs)
        self.borrower = borrower

        if agent_override is not None:
            self.fields["agent_name"].initial  = agent_override.pk
            self.fields["agent_name"].widget   = forms.HiddenInput()
            self.fields["agent_name"].required = False
            self.agent_override = agent_override
            self.fields["agent_name"].disabled = True
        else:
            self.agent_override = None

        amount = None
        if self.is_bound:
            raw_amount = self.data.get(self.add_prefix("amount")) or self.data.get("amount")
            try:
                amount = Decimal(str(raw_amount))
            except Exception:
                amount = None
        elif self.instance and self.instance.pk:
            amount = self.instance.amount

        if amount is not None:
            self.fields["loan_category_display"].initial = self.get_category_label(amount)

        self.order_fields([
            "agent_name",
            "amount",
            "loan_category_display",
            "loan_acquisition_date",
            "repayment_frequency",
            "weekly_payment",
            "duration_months",
            "duration_weeks",
            "start_date",
            "sector",
            "sector_other",
            "borrower_declaration_accepted",
            "borrower_signature_name",
            "borrower_signed_date",
            "guarantor_name",
            "guarantor_id_number",
            "guarantor_signature_name",
            "guarantor_signed_date",
            "collateral_type",
            "collateral_details",
            "collateral_estimated_value",
            "collateral_location",
            "collateral_borrower_consent_accepted",
            "collateral_borrower_signed_date",
            "collateral_guarantor_signature_name",
            "collateral_guarantor_signed_date",
            "application_received_by",
            "application_received_date",
            "approved_amount",
            "approved_repayment_plan",
            "loan_officer_signature_name",
            "approval_manager_signature_name",
            "approval_date",
        ])

    @staticmethod
    def get_category_label(amount):
        return _get_category_label_dynamic(amount)

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None:
            raise forms.ValidationError("Loan amount is required.")
        if amount <= Decimal("0.00"):
            raise forms.ValidationError("Loan amount must be greater than 0.")
        return amount

    def clean_duration_weeks(self):
        duration_weeks = self.cleaned_data.get("duration_weeks")
        if duration_weeks is None:
            return 0
        if duration_weeks < 0:
            raise forms.ValidationError("Duration in weeks cannot be negative.")
        return duration_weeks

    def clean_duration_months(self):
        duration_months = self.cleaned_data.get("duration_months")
        if duration_months is None:
            return 0
        if duration_months < 0:
            raise forms.ValidationError("Duration in months cannot be negative.")
        return duration_months

    def clean_weekly_payment(self):
        weekly_payment = self.cleaned_data.get("weekly_payment")
        if weekly_payment is None:
            raise forms.ValidationError("Repayment amount is required.")
        if weekly_payment <= Decimal("0.00"):
            raise forms.ValidationError("Repayment amount must be greater than 0.")
        return weekly_payment

    def clean(self):
        cleaned_data = super().clean()
        agent = self.agent_override or cleaned_data.get("agent_name")
        if self.borrower and not self.borrower.portfolio_id:
            self.add_error(None, "Assign this customer to a portfolio first.")
        elif self.borrower and agent and not agent_can_access(agent, self.borrower):
            self.add_error("agent_name", "Select an officer currently assigned to this customer's portfolio.")
        months = cleaned_data.get("duration_months") or 0
        weeks = cleaned_data.get("duration_weeks") or 0
        sector = cleaned_data.get("sector")
        sector_other = (cleaned_data.get("sector_other") or "").strip()
        if months <= 0 and weeks <= 0:
            self.add_error("duration_weeks", "Enter a duration in months, weeks, or both.")
        if sector == "OTHER" and not sector_other:
            self.add_error("sector_other", "Specify the sector when 'Other' is selected.")
        return cleaned_data


class PaymentCreateForm(forms.ModelForm):
    def __init__(self, *args, loan=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.loan = loan

    payment_date = forms.DateField(
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"},
            format="%Y-%m-%d"
        )
    )

    class Meta:
        model = Payment
        fields = ["payment_date", "amount", "reference", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "reference": forms.TextInput(attrs={"class": "form-control", "placeholder": "eg. MOMO/Bank ref"}),
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "optional"}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None:
            raise forms.ValidationError("Payment amount is required.")
        if amount <= Decimal("0.00"):
            raise forms.ValidationError("Payment amount must be greater than 0.")
        if self.loan is not None and amount > self.loan.balance_amount:
            raise forms.ValidationError(f"Payment cannot exceed the outstanding balance of {self.loan.balance_amount:,.2f}.")
        return amount


class SecurityDepositActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            ("COLLECTION", "Collect security deposit"),
            ("REFUND", "Refund security deposit"),
            ("DEFAULT_APPLICATION", "Apply deposit against loan default"),
            ("CARRY_FORWARD", "Apply a previous deposit to this loan"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2, max_digits=12, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}))
    transaction_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    payment_method = forms.ChoiceField(choices=Payment.PAYMENT_METHOD_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    reference = forms.CharField(max_length=120, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Receipt, MoMo, or bank reference"}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))
    verified_customer_name = forms.CharField(max_length=160, widget=forms.TextInput(attrs={"class": "form-control"}))
    verified_customer_phone = forms.CharField(max_length=30, widget=forms.TextInput(attrs={"class": "form-control"}))
    verified_customer_reference = forms.CharField(max_length=80, widget=forms.TextInput(attrs={"class": "form-control", "help_text": "Borrower ID or loan number."}))
    customer_authorized = forms.BooleanField(required=True, label="Customer identity and authorization have been confirmed")

    def __init__(self, *args, deposit: SecurityDeposit, **kwargs):
        self.deposit = deposit
        super().__init__(*args, **kwargs)
        self.fields["transaction_date"].initial = timezone.localdate()
        self.fields["source_deposit"] = forms.ModelChoiceField(
            required=False,
            queryset=SecurityDeposit.objects.filter(borrower=deposit.borrower, loan__status="CLOSED").exclude(pk=deposit.pk),
            widget=forms.Select(attrs={"class": "form-select"}),
            label="Previous completed-loan deposit to carry forward",
        )

    @staticmethod
    def _normalise_phone(value):
        return "".join(char for char in (value or "") if char.isdigit()).lstrip("0")

    def clean(self):
        cleaned = super().clean()
        borrower = self.deposit.borrower
        action = cleaned.get("action")
        amount = cleaned.get("amount") or Decimal("0.00")
        reference = (cleaned.get("reference") or "").strip()
        verified_name = (cleaned.get("verified_customer_name") or "").strip()
        verified_phone = self._normalise_phone(cleaned.get("verified_customer_phone"))
        verified_reference = (cleaned.get("verified_customer_reference") or "").strip()

        if verified_name.casefold() != borrower.full_name.strip().casefold():
            self.add_error("verified_customer_name", "Enter the borrower name exactly as recorded.")
        if verified_phone != self._normalise_phone(borrower.phone):
            self.add_error("verified_customer_phone", "The verified phone number does not match this borrower.")
        valid_references = {borrower.borrower_id, str(self.deposit.loan_id), f"LOAN-{self.deposit.loan_id}"}
        if verified_reference.upper() not in {value.upper() for value in valid_references}:
            self.add_error("verified_customer_reference", "Enter this borrower ID or the linked loan number.")
        if not reference:
            self.add_error("reference", "A verified collection or payout reference is required.")

        if action == "COLLECTION" and amount > self.deposit.amount_due:
            self.add_error("amount", f"Collection cannot exceed the outstanding deposit of GHS {self.deposit.amount_due:,.2f}.")
        if action == "REFUND":
            if self.deposit.loan.status != "CLOSED":
                self.add_error("action", "A security deposit can be refunded only after the loan is closed.")
            elif amount > self.deposit.held_amount:
                self.add_error("amount", "Refund cannot exceed the deposit held for this customer.")
        if action == "DEFAULT_APPLICATION":
            if self.deposit.loan.status != "DEFAULT":
                self.add_error("action", "A deposit can be applied only to a defaulted loan.")
            elif amount > min(self.deposit.held_amount, self.deposit.loan.principal_outstanding):
                self.add_error("amount", "Application cannot exceed the held deposit or loan balance.")
        if action == "CARRY_FORWARD":
            source = cleaned.get("source_deposit")
            if not source:
                self.add_error("source_deposit", "Select the completed-loan deposit being applied to this loan.")
            elif amount > source.held_amount:
                self.add_error("amount", "The selected previous deposit does not hold that amount.")
            elif amount > self.deposit.amount_due:
                self.add_error("amount", "Carry-forward cannot exceed this loan's remaining deposit requirement.")
        return cleaned
