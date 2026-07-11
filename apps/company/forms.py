import json
from django import forms
from django.forms import modelformset_factory

from .models import CompanyDocument, CompanyProfile, THEME_CHOICES, CURRENCY_CHOICES, REPAYMENT_CYCLE_CHOICES
from .statutory import default_payroll_tax_brackets, normalize_tax_brackets


# ── JSON textarea helpers ────────────────────────────────────────────────────

def _json_placeholder(example: str) -> str:
    return f"JSON array, e.g.:\n{example}"


CORE_VALUES_PLACEHOLDER = _json_placeholder(
    '[{"icon":"🤝","title":"Integrity","description":"We act with honesty..."},\n'
    ' {"icon":"🌱","title":"Growth","description":"We invest in our community..."}]'
)
HOW_STEPS_PLACEHOLDER = _json_placeholder(
    '[{"icon":"📋","title":"Register","description":"Visit us with your ID..."},\n'
    ' {"icon":"✅","title":"Get Approved","description":"We review within 24hrs..."}]'
)
PARTNERS_PLACEHOLDER = _json_placeholder(
    '[{"name":"Acme Bank","website":"https://acmebank.com"},\n'
    ' {"name":"FinTech Ghana","website":"https://fintechghana.org"}]'
)
CERTIFICATIONS_PLACEHOLDER = _json_placeholder(
    '[{"icon":"🏅","name":"Ghana Microfinance Association","year":2019},\n'
    ' {"icon":"📜","name":"Bank of Ghana Licensed","year":2017}]'
)
AWARDS_PLACEHOLDER = _json_placeholder(
    '[{"title":"Best MFI of the Year","issuer":"Finance Awards Ghana","year":2023},\n'
    ' {"title":"Community Impact Award","issuer":"GIZ","year":2022}]'
)
BUSINESS_HOURS_PLACEHOLDER = _json_placeholder(
    '[{"day":"Monday","open":"8:00 AM","close":"5:00 PM","closed":false},\n'
    ' {"day":"Saturday","open":"9:00 AM","close":"1:00 PM","closed":false},\n'
    ' {"day":"Sunday","open":"","close":"","closed":true}]'
)
MANAGEMENT_PLACEHOLDER = _json_placeholder(
    '[{"name":"Kwame Mensah","title":"CEO & Founder","bio":"15 years in microfinance...","initials":"KM"},\n'
    ' {"name":"Abena Osei","title":"Head of Operations","bio":"Specialist in field...","initials":"AO"}]'
)
SERVICES_PLACEHOLDER = _json_placeholder(
    '[{"icon":"⚡","title":"Quick Loans","description":"Fast personal loans...","highlight":false},\n'
    ' {"icon":"🏢","title":"Business Loans","description":"Capital for growth...","highlight":true}]'
)
TESTIMONIALS_PLACEHOLDER = _json_placeholder(
    '[{"name":"Ama Owusu","role":"Trader, Kumasi","quote":"This loan changed my business...","avatar_initials":"AO"},\n'
    ' {"name":"Kofi Adu","role":"Farmer, Ashanti","quote":"Fast approval, honest terms...","avatar_initials":"KA"}]'
)
FAQS_PLACEHOLDER = _json_placeholder(
    '[{"question":"How do I apply for a loan?","answer":"Visit our nearest branch or contact your agent..."},\n'
    ' {"question":"What documents do I need?","answer":"Valid ID, proof of business/income..."}]'
)
GOALS_PLACEHOLDER = _json_placeholder(
    '[{"icon":"🎯","title":"Financial Inclusion","description":"Making credit accessible to all..."},\n'
    ' {"icon":"🌍","title":"Community Development","description":"Building stronger communities..."}]'
)
BRANCHES_PLACEHOLDER = _json_placeholder(
    '[{"name":"Head Office","address":"123 Main St, Accra","phone":"+233244000000",'
    '"email":"hq@company.com","lat":"5.6037","lng":"-0.1870","is_head_office":true}]'
)
HERO_SLIDES_PLACEHOLDER = _json_placeholder(
    '[\n'
    '  {"headline":"Financial Freedom Starts Here","subheadline":"Fast, fair micro-credit...","cta_text":"Apply for a Loan","cta_url":"","overlay":"0.70"},\n'
    '  {"headline":"Grow Your Business Today","subheadline":"Working capital for SMEs...","cta_text":"Learn More","cta_url":"","overlay":"0.65"},\n'
    '  {"headline":"Join Thousands of Borrowers","subheadline":"Trusted by communities across Ghana...","cta_text":"Get Started","cta_url":"","overlay":"0.60"}\n'
    ']'
)
PAYROLL_TAX_BRACKETS_PLACEHOLDER = _json_placeholder(
    '[\n'
    '  {"up_to":"490.00","rate":"0.00","label":"First 490"},\n'
    '  {"up_to":"600.00","rate":"5.00","label":"Next 110"},\n'
    '  {"up_to":"730.00","rate":"10.00","label":"Next 130"},\n'
    '  {"up_to":"3896.67","rate":"17.50","label":"Next 3,166.67"},\n'
    '  {"up_to":"19896.67","rate":"25.00","label":"Next 16,000"},\n'
    '  {"up_to":"50416.67","rate":"30.00","label":"Next 30,520"},\n'
    '  {"up_to":null,"rate":"35.00","label":"Exceeding 50,416.67"}\n'
    ']'
)


class CompanyProfileForm(forms.ModelForm):
    """
    Full setup / edit form for CompanyProfile.
    Friendly textarea fields convert JSON ↔ text.
    """

    # ── Loan tiers (one line per tier) ────────────────────────
    tier_labels = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "Bronze\nSilver\nGold\nPlatinum\nDiamond\nExecutive"}),
        required=False, label="Tier Names (one per line)",
        help_text="Each line becomes one loan tier label (top = lowest, bottom = highest).",
    )
    tier_maxes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "3000\n5000\n10000\n15000\n20000\n999999999"}),
        required=False, label="Tier Max Amounts (one per line, same order)",
        help_text="Maximum principal for each tier.",
    )

    # ── Languages ─────────────────────────────────────────────
    languages_text = forms.CharField(
        widget=forms.TextInput(attrs={"placeholder": "Twi, Ewe, Ga, Hausa"}),
        required=False, label="Borrower Languages (comma-separated)",
        help_text="Languages available on borrower records.",
    )

    # ── JSON content fields ───────────────────────────────────
    core_values_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": CORE_VALUES_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Core Values (JSON)",
        help_text='Array of {icon, title, description} objects.',
    )
    how_steps_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": HOW_STEPS_PLACEHOLDER, "class": "json-field"}),
        required=False, label="How It Works Steps (JSON)",
        help_text='Array of {icon, title, description} objects (4 recommended).',
    )
    partners_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": PARTNERS_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Partners / Sponsors (JSON)",
        help_text='Array of {name, website} objects.',
    )
    certifications_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": CERTIFICATIONS_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Certifications & Memberships (JSON)",
        help_text='Array of {icon, name, year} objects.',
    )
    awards_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": AWARDS_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Awards & Recognition (JSON)",
        help_text='Array of {title, issuer, year} objects.',
    )
    business_hours_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": BUSINESS_HOURS_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Business Hours (JSON)",
        help_text='Array of {day, open, close, closed} objects (one per day).',
    )
    services_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": SERVICES_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Website Services / Products (JSON)",
        help_text='Array of {icon, title, description, highlight} objects.',
    )
    testimonials_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": TESTIMONIALS_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Client Testimonials (JSON)",
        help_text='Array of {name, role, quote, avatar_initials} objects.',
    )
    faqs_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": FAQS_PLACEHOLDER, "class": "json-field"}),
        required=False, label="FAQs (JSON)",
        help_text='Array of {question, answer} objects.',
    )
    goals_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": GOALS_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Strategic Goals (JSON)",
        help_text='Array of {icon, title, description} objects shown on About page.',
    )
    management_team_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": MANAGEMENT_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Management Team (JSON)",
        help_text='Array of {name, title, bio, initials} objects.',
    )
    branches_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": BRANCHES_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Branches / Locations (JSON)",
        help_text='Array of {name, address, phone, email, lat, lng, is_head_office} objects.',
    )
    hero_slides_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 12, "placeholder": HERO_SLIDES_PLACEHOLDER, "class": "json-field"}),
        required=False, label="Hero Carousel Slides (JSON)",
        help_text='Array of up to 3 slide objects: {headline, subheadline, cta_text, cta_url, overlay}.',
    )
    payroll_tax_brackets_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 10, "placeholder": PAYROLL_TAX_BRACKETS_PLACEHOLDER, "class": "json-field"}),
        required=False,
        label="Monthly Payroll Tax Brackets (JSON)",
        help_text='Array of tax bands using {up_to, rate, label}. Use null for the final open-ended band.',
    )

    class Meta:
        model  = CompanyProfile
        fields = [
            # Identity
            "company_name", "tagline", "description", "logo", "favicon",
            # Contact
            "phone", "email", "address", "website",
            # Company messaging integrations
            "tenant_email_from_address", "tenant_email_host", "tenant_email_port",
            "tenant_email_host_user", "tenant_email_host_password",
            "tenant_email_use_tls", "tenant_email_use_ssl",
            "tenant_sms_provider", "tenant_sms_api_key", "tenant_sms_sender_id", "tenant_sms_base_url",
            "tenant_ussd_provider", "tenant_ussd_api_key", "tenant_ussd_shortcode",
            "tenant_ussd_username", "tenant_ussd_callback_token",
            # Locale
            "currency_code", "currency_symbol", "country", "timezone_name",
            # Operations
            "repayment_cycle", "default_loan_duration", "overdue_grace_periods",
            # Statutory and tax
            "payroll_tax_enabled", "payroll_employee_pension_enabled",
            "payroll_employer_pension_enabled", "payroll_welfare_enabled",
            "payroll_personal_relief_amount", "payroll_employee_pension_rate",
            "payroll_employer_pension_rate", "payroll_welfare_deduction_rate",
            "payroll_welfare_fixed_amount", "paye_payable_account_code",
            "employee_pension_payable_account_code", "employer_pension_payable_account_code",
            "welfare_payable_account_code", "employer_statutory_expense_account_code",
            "vat_rate", "nhil_rate", "getfund_rate", "withholding_tax_rate",
            "corporate_income_tax_rate",
            # Appearance
            "color_theme",
            # Hero
            "hero_layout", "hero_headline", "hero_subheadline",
            "hero_image", "hero_cta_text", "hero_cta_url", "hero_overlay_opacity",
            # Hero carousel
            "show_hero_carousel", "hero_slide_2_image", "hero_slide_3_image",
            "hero_slide_1_feature_image", "hero_slide_2_feature_image", "hero_slide_3_feature_image",
            # About / mission
            "mission_statement", "vision_statement",
            "years_in_business", "clients_served", "loans_disbursed_display",
            "about_image", "about_image_2", "about_image_3",
            # Business identity extras
            "founded_year", "license_number", "registration_number",
            # SEO
            "meta_title", "meta_description",
            # Page headlines
            "about_headline", "about_subheadline",
            "services_headline", "services_subheadline",
            "team_headline", "team_subheadline",
            "contact_headline", "contact_subheadline",
            # CTA section
            "cta_headline", "cta_body", "cta_button_text",
            # Social
            "whatsapp_number", "facebook_url", "instagram_url", "twitter_url", "youtube_url",
            # Section visibility
            "show_loan_calculator", "show_testimonials", "show_faqs",
            "show_stats_band", "show_how_section",
            "show_trust_strip",
            "show_partners_section", "show_certifications_section",
            "show_awards_section", "show_gallery_section",
            "show_agents_on_team", "show_topbar",
            # Branding / colours
            "site_primary_color", "site_secondary_color", "site_bg_color",
            "site_text_color", "site_nav_bg", "site_footer_bg", "site_section_alt_bg",
            "site_font", "primary_cta_color",
            # Page hero images
            "about_hero_image", "services_hero_image", "team_hero_image", "contact_hero_image",
            # Gallery
            "gallery_image_1","gallery_caption_1","gallery_image_2","gallery_caption_2",
            "gallery_image_3","gallery_caption_3","gallery_image_4","gallery_caption_4",
            "gallery_image_5","gallery_caption_5","gallery_image_6","gallery_caption_6",
            "gallery_image_7","gallery_caption_7","gallery_image_8","gallery_caption_8",
            "gallery_image_9","gallery_caption_9","gallery_image_10","gallery_caption_10",
            # Contact
            "contact_intro", "maps_embed_url",
        ]
        widgets = {
            "description":          forms.Textarea(attrs={"rows": 3}),
            "address":              forms.Textarea(attrs={"rows": 2}),
            "tenant_email_host_password": forms.PasswordInput(render_value=True, attrs={"placeholder": "SMTP password or API secret"}),
            "tenant_sms_api_key":   forms.PasswordInput(render_value=True, attrs={"placeholder": "Company SMS API key"}),
            "tenant_ussd_api_key":  forms.PasswordInput(render_value=True, attrs={"placeholder": "Company USSD API key"}),
            "tenant_ussd_callback_token": forms.PasswordInput(render_value=True, attrs={"placeholder": "Optional callback token"}),
            "mission_statement":    forms.Textarea(attrs={"rows": 3}),
            "vision_statement":     forms.Textarea(attrs={"rows": 2}),
            "hero_subheadline":     forms.Textarea(attrs={"rows": 2}),
            "contact_intro":        forms.Textarea(attrs={"rows": 2}),
            "maps_embed_url":       forms.Textarea(attrs={"rows": 2, "placeholder": "https://www.google.com/maps/embed?..."}),
            "meta_description":     forms.Textarea(attrs={"rows": 2, "placeholder": "150–160 character summary for search engines..."}),
            "about_subheadline":    forms.Textarea(attrs={"rows": 2}),
            "services_subheadline": forms.Textarea(attrs={"rows": 2}),
            "team_subheadline":     forms.Textarea(attrs={"rows": 2}),
            "contact_subheadline":  forms.Textarea(attrs={"rows": 2}),
            "cta_body":             forms.Textarea(attrs={"rows": 3}),
            # Brand colours — colour picker + hex text, matched by data-hex
            "site_primary_color":   forms.TextInput(attrs={"placeholder": "#3a5a1e", "class": "hex-input", "data-default": "#3a5a1e", "maxlength": 20}),
            "site_secondary_color": forms.TextInput(attrs={"placeholder": "#b88620", "class": "hex-input", "data-default": "#b88620", "maxlength": 20}),
            "site_bg_color":        forms.TextInput(attrs={"placeholder": "#f7f8fa", "class": "hex-input", "data-default": "#f7f8fa", "maxlength": 20}),
            "site_text_color":      forms.TextInput(attrs={"placeholder": "#0f1923", "class": "hex-input", "data-default": "#0f1923", "maxlength": 20}),
            "site_nav_bg":          forms.TextInput(attrs={"placeholder": "#ffffff", "class": "hex-input", "data-default": "#ffffff", "maxlength": 20}),
            "site_footer_bg":       forms.TextInput(attrs={"placeholder": "#0d1f0a", "class": "hex-input", "data-default": "#0d1f0a", "maxlength": 20}),
            "site_section_alt_bg":  forms.TextInput(attrs={"placeholder": "#f0f4f8", "class": "hex-input", "data-default": "#f0f4f8", "maxlength": 20}),
            "primary_cta_color":    forms.TextInput(attrs={"placeholder": "#3a5a1e", "class": "hex-input", "data-default": "#3a5a1e", "maxlength": 20}),
            "tenant_email_from_address": forms.EmailInput(attrs={"placeholder": "no-reply@yourcompany.com"}),
            "tenant_email_host":    forms.TextInput(attrs={"placeholder": "smtp.yourmailhost.com"}),
            "tenant_email_port":    forms.NumberInput(attrs={"placeholder": "587", "min": 1}),
            "tenant_email_host_user": forms.TextInput(attrs={"placeholder": "SMTP username"}),
            "tenant_sms_provider":  forms.TextInput(attrs={"placeholder": "ARKESEL"}),
            "tenant_sms_sender_id": forms.TextInput(attrs={"placeholder": "YourSenderID"}),
            "tenant_sms_base_url":  forms.URLInput(attrs={"placeholder": "https://sms.arkesel.com/api/v2"}),
            "tenant_ussd_provider": forms.TextInput(attrs={"placeholder": "HUBTEL"}),
            "tenant_ussd_shortcode": forms.TextInput(attrs={"placeholder": "*123#"}),
            "tenant_ussd_username": forms.TextInput(attrs={"placeholder": "USSD account username or client ID"}),
        }

    # ── Pre-populate from stored JSON ─────────────────────────
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        self.fields["payroll_tax_brackets_text"].initial = json.dumps(
            default_payroll_tax_brackets(),
            indent=2,
            ensure_ascii=False,
        )
        if inst and inst.pk:
            # Tiers
            tiers = inst.loan_tiers or []
            if tiers:
                self.fields["tier_labels"].initial = "\n".join(t.get("label", "") for t in tiers)
                self.fields["tier_maxes"].initial  = "\n".join(str(t.get("max", "")) for t in tiers)
            # Languages
            langs = inst.borrower_languages or []
            self.fields["languages_text"].initial = ", ".join(langs)
            # JSON fields
            _json_fields = {
                "core_values_text":      "core_values",
                "how_steps_text":        "how_steps",
                "partners_text":         "partners",
                "certifications_text":   "certifications",
                "awards_text":           "awards",
                "business_hours_text":   "business_hours",
                "services_text":         "services",
                "testimonials_text":     "testimonials",
                "faqs_text":             "faqs",
                "goals_text":            "goals",
                "management_team_text":  "management_team",
                "branches_text":         "branches",
                "hero_slides_text":      "hero_slides",
            }
            for form_field, model_field in _json_fields.items():
                data = getattr(inst, model_field, None)
                if data:
                    self.fields[form_field].initial = json.dumps(data, indent=2, ensure_ascii=False)
            self.fields["payroll_tax_brackets_text"].initial = json.dumps(
                inst.payroll_tax_brackets or default_payroll_tax_brackets(),
                indent=2,
                ensure_ascii=False,
            )

    # ── Validate & convert ────────────────────────────────────
    def _parse_json_field(self, field_name: str, cleaned: dict) -> list:
        raw = cleaned.get(field_name, "").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                raise forms.ValidationError(f"{field_name}: must be a JSON array [...].")
            return data
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"{field_name}: invalid JSON — {exc}")

    def clean(self):
        cleaned = super().clean()

        # Loan tiers
        raw_labels = cleaned.get("tier_labels", "")
        raw_maxes  = cleaned.get("tier_maxes", "")
        labels = [l.strip() for l in raw_labels.strip().splitlines() if l.strip()]
        maxes  = [m.strip() for m in raw_maxes.strip().splitlines()  if m.strip()]
        if labels:
            if len(labels) != len(maxes):
                raise forms.ValidationError(
                    "Tier names and tier max amounts must have the same number of lines."
                )
            tiers, prev = [], -1
            for label, max_str in zip(labels, maxes):
                try:
                    max_val = int(float(max_str.replace(",", "")))
                except ValueError:
                    raise forms.ValidationError(f"Tier max '{max_str}' is not a valid number.")
                if max_val <= prev:
                    raise forms.ValidationError(
                        f"Tier max amounts must be strictly increasing. '{label}' ({max_val}) ≤ previous ({prev})."
                    )
                code = label.upper().replace(" ", "_")[:20]
                tiers.append({"code": code, "label": label, "min": prev + 1, "max": max_val})
                prev = max_val
            cleaned["_loan_tiers"] = tiers

        # Languages
        raw_langs = cleaned.get("languages_text", "")
        if raw_langs.strip():
            cleaned["_languages"] = [l.strip() for l in raw_langs.split(",") if l.strip()]

        # JSON fields
        _json_map = {
            "core_values_text":     "_core_values",
            "how_steps_text":       "_how_steps",
            "partners_text":        "_partners",
            "certifications_text":  "_certifications",
            "awards_text":          "_awards",
            "business_hours_text":  "_business_hours",
            "services_text":        "_services",
            "testimonials_text":    "_testimonials",
            "faqs_text":            "_faqs",
            "goals_text":           "_goals",
            "management_team_text": "_management_team",
            "branches_text":        "_branches",
            "hero_slides_text":     "_hero_slides",
        }
        for form_field, store_key in _json_map.items():
            try:
                cleaned[store_key] = self._parse_json_field(form_field, cleaned)
            except forms.ValidationError as exc:
                self.add_error(form_field, exc)

        try:
            cleaned["_payroll_tax_brackets"] = normalize_tax_brackets(
                self._parse_json_field("payroll_tax_brackets_text", cleaned)
                or default_payroll_tax_brackets()
            )
        except forms.ValidationError as exc:
            self.add_error("payroll_tax_brackets_text", exc)
        except ValueError as exc:
            self.add_error("payroll_tax_brackets_text", str(exc))

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)

        if "_loan_tiers" in self.cleaned_data:
            instance.loan_tiers = self.cleaned_data["_loan_tiers"]
        if "_languages" in self.cleaned_data:
            instance.borrower_languages = self.cleaned_data["_languages"]

        _model_map = {
            "_core_values":    "core_values",
            "_how_steps":      "how_steps",
            "_partners":       "partners",
            "_certifications": "certifications",
            "_awards":         "awards",
            "_business_hours": "business_hours",
            "_services":       "services",
            "_testimonials":   "testimonials",
            "_faqs":           "faqs",
            "_goals":          "goals",
            "_management_team":"management_team",
            "_branches":       "branches",
            "_hero_slides":    "hero_slides",
        }
        for store_key, model_field in _model_map.items():
            if store_key in self.cleaned_data:
                val = self.cleaned_data[store_key]
                if val or getattr(instance, model_field):
                    setattr(instance, model_field, val)

        if "_payroll_tax_brackets" in self.cleaned_data:
            instance.payroll_tax_brackets = self.cleaned_data["_payroll_tax_brackets"]

        if commit:
            instance.save()
        return instance


class CompanyDocumentForm(forms.ModelForm):
    class Meta:
        model = CompanyDocument
        fields = ["title", "description", "file", "is_public", "sort_order"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Document title"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Optional short description"}),
            "file": forms.ClearableFileInput(attrs={"accept": ".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.png,.jpg,.jpeg"}),
            "sort_order": forms.NumberInput(attrs={"min": 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("title", "file", "sort_order"):
            self.fields[field_name].required = False

    def _has_document_input(self):
        if self.instance and self.instance.pk:
            return True
        if not self.is_bound:
            return False
        title = (self.data.get(self.add_prefix("title")) or "").strip()
        description = (self.data.get(self.add_prefix("description")) or "").strip()
        sort_order = (self.data.get(self.add_prefix("sort_order")) or "").strip()
        uploaded = bool(self.files.get(self.add_prefix("file")))
        return bool(title or description or sort_order or uploaded)

    def has_changed(self):
        if not self._has_document_input():
            return False
        return super().has_changed()

    def clean(self):
        cleaned = super().clean()
        if not self._has_document_input():
            return cleaned
        if not (cleaned.get("title") or "").strip():
            self.add_error("title", "Document title is required.")
        if not cleaned.get("file") and not getattr(self.instance, "file", None):
            self.add_error("file", "Upload a document file.")
        if cleaned.get("sort_order") is None:
            cleaned["sort_order"] = 0
        return cleaned


CompanyDocumentFormSet = modelformset_factory(
    CompanyDocument,
    form=CompanyDocumentForm,
    extra=3,
    can_delete=True,
)
