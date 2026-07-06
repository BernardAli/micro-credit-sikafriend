from django.contrib import admin
from .models import CompanyDocument, CompanyProfile


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Identity", {
            "fields": ("company_name", "tagline", "description", "logo", "favicon"),
        }),
        ("Contact", {
            "fields": ("phone", "email", "address", "website"),
            "classes": ("collapse",),
        }),
        ("Messaging Integrations", {
            "fields": (
                "tenant_email_from_address",
                "tenant_email_host",
                "tenant_email_port",
                "tenant_email_host_user",
                "tenant_email_host_password",
                "tenant_email_use_tls",
                "tenant_email_use_ssl",
                "tenant_sms_provider",
                "tenant_sms_api_key",
                "tenant_sms_sender_id",
                "tenant_sms_base_url",
                "tenant_ussd_provider",
                "tenant_ussd_api_key",
                "tenant_ussd_shortcode",
                "tenant_ussd_username",
                "tenant_ussd_callback_token",
            ),
            "classes": ("collapse",),
        }),
        ("Locale & Currency", {
            "fields": ("currency_code", "currency_symbol", "country", "timezone_name"),
        }),
        ("Operations", {
            "fields": (
                "repayment_cycle",
                "default_loan_duration",
                "overdue_grace_periods",
                "loan_tiers",
                "borrower_languages",
            ),
        }),
        ("Statutory & Tax", {
            "fields": (
                "payroll_tax_enabled",
                "payroll_employee_pension_enabled",
                "payroll_employer_pension_enabled",
                "payroll_welfare_enabled",
                "payroll_personal_relief_amount",
                "payroll_employee_pension_rate",
                "payroll_employer_pension_rate",
                "payroll_welfare_deduction_rate",
                "payroll_welfare_fixed_amount",
                "payroll_tax_brackets",
                "paye_payable_account_code",
                "employee_pension_payable_account_code",
                "employer_pension_payable_account_code",
                "welfare_payable_account_code",
                "employer_statutory_expense_account_code",
                "vat_rate",
                "nhil_rate",
                "getfund_rate",
                "withholding_tax_rate",
                "corporate_income_tax_rate",
            ),
            "classes": ("collapse",),
        }),
        ("Appearance", {
            "fields": ("color_theme", "primary_cta_color"),
        }),
        ("Website — Hero", {
            "fields": ("hero_headline", "hero_subheadline", "hero_image", "hero_cta_text", "hero_cta_url"),
            "classes": ("collapse",),
        }),
        ("Website — About & Stats", {
            "fields": ("mission_statement", "vision_statement", "years_in_business",
                       "clients_served", "loans_disbursed_display", "about_image"),
            "classes": ("collapse",),
        }),
        ("Website — Social & Contact", {
            "fields": ("whatsapp_number", "facebook_url", "instagram_url", "twitter_url", "youtube_url"),
            "classes": ("collapse",),
        }),
        ("Website — Content Sections", {
            "fields": ("services", "tier_descriptions", "testimonials", "faqs",
                       "show_loan_calculator", "show_testimonials", "show_faqs"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request):
        return not CompanyProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CompanyDocument)
class CompanyDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "is_public", "sort_order", "created_at", "updated_at")
    list_filter = ("is_public", "created_at", "updated_at")
    search_fields = ("title", "description", "file")
    ordering = ("sort_order", "title")
