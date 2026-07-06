from django import forms
from apps.accounts.models import Agent
from apps.loans.models import Borrower, Loan
from apps.company.models import CompanyProfile
from .models import MarketingTemplate, WebsiteMarketingPopup, WebsiteLead


class ManagementSMSForm(forms.Form):
    RECIPIENT_GROUP_CHOICES = (
        ("ALL_USERS", "All Users"),
        ("STAFF_USERS", "Staff Users"),
        ("ALL_AGENTS", "All Agents"),
        ("AGENTS_WITH_ACTIVE_LOANS", "Agents With Active Loans"),
        ("AGENTS_WITH_DEFAULT_LOANS", "Agents With Default Loans"),
        ("ALL_BORROWERS", "All Borrowers"),
        ("BORROWERS_ACTIVE", "Borrowers With ACTIVE Status"),
        ("BORROWERS_CLOSED", "Borrowers With CLOSED Status"),
        ("BORROWERS_BAD", "Borrowers With BAD Status"),
        ("BORROWERS_WITH_ACTIVE_LOANS", "Borrowers With Active Loans"),
        ("BORROWERS_WITH_DEFAULT_LOANS", "Borrowers With Default Loans"),
        ("BORROWERS_BY_LOAN_CATEGORY", "Borrowers By Loan Category"),
        ("BORROWERS_BY_AGENT", "Borrowers Under Specific Agent"),
        ("BORROWERS_BY_LOCATION", "Borrowers By Location"),
        ("BORROWERS_BY_GROUP", "Borrowers By Group Name"),
        ("BORROWERS_BY_LANGUAGE", "Borrowers By Preferred Language"),
        ("MANUAL_NUMBERS", "Manual Phone Numbers"),
    )

    recipient_group = forms.ChoiceField(
        choices=RECIPIENT_GROUP_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    agent = forms.ModelChoiceField(
        queryset=Agent.objects.all().order_by("name"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    borrower_status = forms.ChoiceField(
        choices=[("", "All Borrower Statuses")] + list(Borrower.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    loan_status = forms.ChoiceField(
        choices=[("", "All Loan Statuses")] + list(Loan.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    loan_category = forms.ChoiceField(
        choices=[("", "All Loan Categories")] + list(getattr(Loan, "LOAN_CATEGORY_CHOICES", [])),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Accra"})
    )

    group_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Group A"})
    )

    preferred_language = forms.ChoiceField(
        choices=[("", "All Languages")] + list(Borrower.LANGUAGE_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    manual_numbers = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "placeholder": "Enter phone numbers separated by commas, spaces, or new lines"
        })
    )

    message = forms.CharField(
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 7,
            "placeholder": "Type the SMS message here..."
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["agent"].queryset = Agent.objects.all().order_by("name")

        try:
            profile = CompanyProfile.get_solo()
            tier_choices = [(tier["code"], tier["label"]) for tier in profile.tiers_for_template]
            language_choices = [(language, language) for language in profile.languages_for_template]
        except Exception:
            tier_choices = list(getattr(Loan, "LOAN_CATEGORY_CHOICES", []))
            language_choices = list(Borrower.LANGUAGE_CHOICES)

        self.fields["loan_category"].choices = [("", "All Loan Categories")] + tier_choices
        self.fields["preferred_language"].choices = [("", "All Languages")] + language_choices

    def clean(self):
        cleaned = super().clean()
        group = cleaned.get("recipient_group")
        manual_numbers = (cleaned.get("manual_numbers") or "").strip()

        if group == "MANUAL_NUMBERS" and not manual_numbers:
            self.add_error("manual_numbers", "Please enter at least one phone number.")

        if group == "BORROWERS_BY_AGENT" and not cleaned.get("agent"):
            self.add_error("agent", "Please select an agent.")

        if group == "BORROWERS_BY_LOCATION" and not cleaned.get("location"):
            self.add_error("location", "Please enter a location.")

        if group == "BORROWERS_BY_GROUP" and not cleaned.get("group_name"):
            self.add_error("group_name", "Please enter a group name.")

        if group == "BORROWERS_BY_LANGUAGE" and not cleaned.get("preferred_language"):
            self.add_error("preferred_language", "Please select a language.")

        if group == "BORROWERS_BY_LOAN_CATEGORY" and not cleaned.get("loan_category"):
            self.add_error("loan_category", "Please select a loan category.")

        return cleaned


class MarketingTemplateForm(forms.ModelForm):
    class Meta:
        model = MarketingTemplate
        fields = [
            "title",
            "channel",
            "category",
            "objective",
            "audience_hint",
            "subject",
            "body",
            "cta_label",
            "cta_url",
            "is_featured",
            "is_active",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. End-of-Month Trader Boost"}),
            "channel": forms.Select(attrs={"class": "form-select"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "objective": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Drive repeat borrowing from good payers"}),
            "audience_hint": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. ACTIVE borrowers in Accra"}),
            "subject": forms.TextInput(attrs={"class": "form-control", "placeholder": "Email subject or campaign label"}),
            "body": forms.Textarea(attrs={"class": "form-control", "rows": 6, "placeholder": "Write the reusable marketing message here..."}),
            "cta_label": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Apply Now"}),
            "cta_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "is_featured": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class MarketingCampaignLauncherForm(forms.Form):
    CHANNEL_CHOICES = [
        ("SMS", "SMS Campaign"),
        ("EMAIL", "Email Campaign"),
        ("WHATSAPP", "WhatsApp Copy Campaign"),
    ]

    AUDIENCE_CHOICES = [
        ("ALL_CONTACTS", "All Reachable Contacts"),
        ("ALL_BORROWERS", "All Borrowers"),
        ("ACTIVE_BORROWERS", "Borrowers With ACTIVE Status"),
        ("CLOSED_BORROWERS", "Borrowers With CLOSED Status"),
        ("BAD_BORROWERS", "Borrowers With BAD Status"),
        ("BORROWERS_BY_AGENT", "Borrowers Under Specific Agent"),
        ("BORROWERS_BY_LOCATION", "Borrowers By Location"),
        ("BORROWERS_BY_GROUP", "Borrowers By Group Name"),
        ("BORROWERS_BY_LANGUAGE", "Borrowers By Preferred Language"),
        ("BORROWERS_BY_LOAN_CATEGORY", "Borrowers By Loan Category"),
        ("ALL_AGENTS", "All Agents"),
        ("AGENTS_WITH_ACTIVE_LOANS", "Agents With Active Loans"),
        ("AGENTS_WITH_DEFAULT_LOANS", "Agents With Default Loans"),
        ("ALL_WEBSITE_LEADS", "All Website Leads"),
        ("WEBSITE_LEADS_BY_STATUS", "Website Leads By Status"),
        ("MANUAL_CONTACTS", "Manual Contacts"),
    ]

    OBJECTIVE_CHOICES = [
        ("ACQUISITION", "Customer Acquisition"),
        ("PROMOTION", "Promotional Push"),
        ("REFERRAL", "Referral Drive"),
        ("REACTIVATION", "Dormant Client Reactivation"),
        ("LOYALTY", "Loyalty / Repeat Borrowing"),
        ("AWARENESS", "Brand Awareness"),
        ("ANNOUNCEMENT", "Operational Announcement"),
    ]

    template_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    title = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Good Payers Top-Up Offer"}),
    )
    channel = forms.ChoiceField(choices=CHANNEL_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    objective = forms.ChoiceField(choices=OBJECTIVE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    audience = forms.ChoiceField(choices=AUDIENCE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    subject = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Required for email campaigns"}),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 7, "placeholder": "Compose the campaign message..."}),
    )
    cta_label = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional CTA label"}),
    )
    cta_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={"class": "form-control", "placeholder": "Optional CTA URL"}),
    )
    agent = forms.ModelChoiceField(
        queryset=Agent.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    borrower_status = forms.ChoiceField(
        choices=[("", "All Borrower Statuses")] + list(Borrower.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    loan_status = forms.ChoiceField(
        choices=[("", "All Loan Statuses")] + list(Loan.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    loan_category = forms.ChoiceField(
        choices=[("", "All Loan Categories")] + list(getattr(Loan, "LOAN_CATEGORY_CHOICES", [])),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Accra"}),
    )
    group_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Makola Traders"}),
    )
    preferred_language = forms.ChoiceField(
        choices=[("", "All Languages")] + list(Borrower.LANGUAGE_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    lead_status = forms.ChoiceField(
        choices=[("", "All Lead Statuses")] + list(WebsiteLead.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    manual_contacts = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Enter phone numbers and/or email addresses separated by commas or new lines",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["agent"].queryset = Agent.objects.all().order_by("name")

        try:
            profile = CompanyProfile.get_solo()
            tier_choices = [(tier["code"], tier["label"]) for tier in profile.tiers_for_template]
            language_choices = [(language, language) for language in profile.languages_for_template]
        except Exception:
            tier_choices = list(getattr(Loan, "LOAN_CATEGORY_CHOICES", []))
            language_choices = list(Borrower.LANGUAGE_CHOICES)

        self.fields["loan_category"].choices = [("", "All Loan Categories")] + tier_choices
        self.fields["preferred_language"].choices = [("", "All Languages")] + language_choices

    def clean(self):
        cleaned = super().clean()
        audience = cleaned.get("audience")
        channel = cleaned.get("channel")

        if channel == "EMAIL" and not (cleaned.get("subject") or "").strip():
            self.add_error("subject", "Email campaigns require a subject line.")

        if audience == "BORROWERS_BY_AGENT" and not cleaned.get("agent"):
            self.add_error("agent", "Please select an agent.")

        if audience == "BORROWERS_BY_LOCATION" and not (cleaned.get("location") or "").strip():
            self.add_error("location", "Please enter a location.")

        if audience == "BORROWERS_BY_GROUP" and not (cleaned.get("group_name") or "").strip():
            self.add_error("group_name", "Please enter a group name.")

        if audience == "BORROWERS_BY_LANGUAGE" and not cleaned.get("preferred_language"):
            self.add_error("preferred_language", "Please select a preferred language.")

        if audience == "BORROWERS_BY_LOAN_CATEGORY" and not cleaned.get("loan_category"):
            self.add_error("loan_category", "Please select a loan category.")

        if audience == "WEBSITE_LEADS_BY_STATUS" and not cleaned.get("lead_status"):
            self.add_error("lead_status", "Please select a lead status.")

        if audience == "MANUAL_CONTACTS" and not (cleaned.get("manual_contacts") or "").strip():
            self.add_error("manual_contacts", "Please enter at least one phone number or email address.")

        return cleaned


class WebsiteMarketingPopupForm(forms.ModelForm):
    class Meta:
        model = WebsiteMarketingPopup
        fields = [
            "name",
            "badge",
            "headline",
            "body",
            "cta_label",
            "cta_url",
            "secondary_label",
            "secondary_url",
            "image",
            "theme",
            "is_active",
            "show_once_per_browser",
            "start_at",
            "end_at",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. June Trader Promo Popup"}),
            "badge": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Limited Offer"}),
            "headline": forms.TextInput(attrs={"class": "form-control", "placeholder": "Headline shown on the popup"}),
            "body": forms.Textarea(attrs={"class": "form-control", "rows": 5, "placeholder": "Marketing message shown to first-time visitors"}),
            "cta_label": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Apply Now"}),
            "cta_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "secondary_label": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. View Loan Products"}),
            "secondary_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "theme": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "show_once_per_browser": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "start_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        }
