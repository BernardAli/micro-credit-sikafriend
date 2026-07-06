from django.contrib import admin
from django.utils.html import format_html

from .models import Agent, PayrollAdjustment, PayrollLine, PayrollRun


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = (
        "agent_id",
        "name",
        "workforce_role",
        "department",
        "job_title",
        "phone",
        "email",
        "location",
        "employment_status",
        "base_salary",
        "payroll_active",
        "photo_preview",
        "created_at",
    )
    list_filter = (
        "workforce_role",
        "department",
        "employment_status",
        "has_admin_access",
        "payroll_active",
        "location",
        "created_at",
    )
    search_fields = (
        "agent_id",
        "name",
        "phone",
        "email",
        "location",
        "department",
        "job_title",
        "ghana_card_number",
        "group_name",
    )
    readonly_fields = (
        "created_at",
        "photo_preview_large",
        "ghana_card_front_preview",
        "ghana_card_back_preview",
        "agent_summary",
    )
    fieldsets = (
        ("Workforce Information", {
            "fields": (
                "agent_id",
                "name",
                "workforce_role",
                "department",
                "job_title",
                "phone",
                "email",
                "location",
                "employment_type",
                "employment_status",
                "hire_date",
                "date_of_birth",
                "group_name",
                "supervisor",
                "has_admin_access",
                "payroll_active",
                "ghana_card_number",
                "created_at",
            )
        }),
        ("Payroll & Payment", {
            "fields": (
                "preferred_payment_method",
                "bank_name",
                "bank_account_name",
                "bank_account_number",
                "mobile_money_name",
                "mobile_money_number",
                "tax_number",
                "social_security_number",
                "base_salary",
                "housing_allowance",
                "transport_allowance",
                "meal_allowance",
                "communication_allowance",
                "other_allowance",
                "commission_rate",
            )
        }),
        ("Contact & HR", {
            "fields": (
                "residential_address",
                "emergency_contact_name",
                "emergency_contact_phone",
                "notes",
            )
        }),
        ("Photo & ID Documents", {
            "fields": (
                "photo",
                "photo_preview_large",
                "ghana_card_front",
                "ghana_card_front_preview",
                "ghana_card_back",
                "ghana_card_back_preview",
            )
        }),
        ("Summary", {
            "fields": ("agent_summary",)
        }),
    )
    ordering = ("name",)

    @admin.display(description="Photo")
    def photo_preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="width:42px;height:42px;object-fit:cover;'
                'border-radius:10px;border:1px solid #dbe5f1;" />',
                obj.photo.url
            )
        return "-"

    @admin.display(description="Agent Photo Preview")
    def photo_preview_large(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="max-width:180px;height:auto;object-fit:cover;'
                'border-radius:14px;border:1px solid #dbe5f1;box-shadow:0 8px 20px rgba(15,23,42,.08);" />',
                obj.photo.url
            )
        return "No photo uploaded."

    @admin.display(description="Ghana Card Front Preview")
    def ghana_card_front_preview(self, obj):
        if obj.ghana_card_front:
            return format_html(
                '<img src="{}" style="max-width:260px;height:auto;object-fit:cover;'
                'border-radius:14px;border:1px solid #dbe5f1;box-shadow:0 8px 20px rgba(15,23,42,.08);" />',
                obj.ghana_card_front.url
            )
        return "No front image uploaded."

    @admin.display(description="Ghana Card Back Preview")
    def ghana_card_back_preview(self, obj):
        if obj.ghana_card_back:
            return format_html(
                '<img src="{}" style="max-width:260px;height:auto;object-fit:cover;'
                'border-radius:14px;border:1px solid #dbe5f1;box-shadow:0 8px 20px rgba(15,23,42,.08);" />',
                obj.ghana_card_back.url
            )
        return "No back image uploaded."

    @admin.display(description="Agent Summary")
    def agent_summary(self, obj):
        loans_qs = obj.loans.all() if hasattr(obj, "loans") else []
        loans = list(loans_qs)

        total_loans = len(loans)
        active_loans = sum(1 for loan in loans if loan.status == "ACTIVE")
        closed_loans = sum(1 for loan in loans if loan.status == "CLOSED")
        default_loans = sum(1 for loan in loans if loan.status == "DEFAULT")

        total_disbursed = sum((loan.amount for loan in loans), 0)
        total_expected = sum((loan.total_expected_amount for loan in loans), 0)
        total_collected = sum((loan.total_paid_amount for loan in loans), 0)
        principal_outstanding = sum((loan.principal_outstanding for loan in loans), 0)
        roic_outstanding = sum((loan.roic_outstanding for loan in loans), 0)
        total_outstanding = sum((loan.balance_amount for loan in loans), 0)
        distinct_borrowers = len({loan.borrower_id for loan in loans if getattr(loan, "borrower_id", None)})

        return format_html(
            "<div>"
            "<strong>Role:</strong> {}<br>"
            "<strong>Department:</strong> {}<br>"
            "<strong>Total Loans:</strong> {}<br>"
            "<strong>Active Loans:</strong> {}<br>"
            "<strong>Closed Loans:</strong> {}<br>"
            "<strong>Default Loans:</strong> {}<br>"
            "<strong>Distinct Borrowers:</strong> {}<br>"
            "<strong>Base Salary:</strong> GHS {:,.2f}<br>"
            "<strong>Fixed Allowances:</strong> GHS {:,.2f}<br>"
            "<strong>Total Disbursed:</strong> GHS {:,.2f}<br>"
            "<strong>Total Expected:</strong> GHS {:,.2f}<br>"
            "<strong>Total Collected:</strong> GHS {:,.2f}<br>"
            "<strong>Principal Outstanding:</strong> GHS {:,.2f}<br>"
            "<strong>ROIC Outstanding:</strong> GHS {:,.2f}<br>"
            "<strong>Total Outstanding:</strong> GHS {:,.2f}"
            "</div>",
            obj.get_workforce_role_display(),
            obj.department or "-",
            total_loans,
            active_loans,
            closed_loans,
            default_loans,
            distinct_borrowers,
            obj.base_salary,
            obj.allowances_total,
            total_disbursed,
            total_expected,
            total_collected,
            principal_outstanding,
            roic_outstanding,
            total_outstanding,
        )


@admin.register(PayrollAdjustment)
class PayrollAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("employee", "adjustment_type", "category", "label", "amount", "is_recurring", "is_active", "effective_from", "effective_to")
    list_filter = ("adjustment_type", "category", "is_recurring", "is_active")
    search_fields = ("employee__name", "employee__agent_id", "label")


class PayrollLineInline(admin.TabularInline):
    model = PayrollLine
    extra = 0
    readonly_fields = (
        "employee",
        "payment_method",
        "base_salary",
        "fixed_allowances",
        "bonus_total",
        "commission_total",
        "overtime_total",
        "other_earnings",
        "statutory_deductions",
        "loan_recovery_deductions",
        "other_deductions",
        "gross_pay",
        "total_deductions",
        "net_pay",
    )
    can_delete = False


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ("title", "period_start", "period_end", "pay_date", "status", "created_by", "created_at")
    list_filter = ("status", "include_active_only", "include_commissions", "include_loan_recovery")
    search_fields = ("title",)
    readonly_fields = ("created_at", "updated_at", "approved_at", "paid_at")
    inlines = [PayrollLineInline]
