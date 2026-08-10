from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html

from .models import Borrower, Loan, Payment, RepaymentCollection, SecurityDeposit, SecurityDepositTransaction


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = (
        "payment_date",
        "amount",
        "principal_paid",
        "roic_paid",
        "reference",
        "note",
        "is_void",
        "created_at",
    )
    readonly_fields = (
        "principal_paid",
        "roic_paid",
        "created_at",
    )
    ordering = ("-payment_date", "-id")
    show_change_link = True


@admin.register(Borrower)
class BorrowerAdmin(admin.ModelAdmin):
    list_display = (
        "borrower_id",
        "full_name",
        "phone",
        "email",
        "location",
        "digital_address",
        "group_name",
        "preferred_language",
        "status_badge",
        "loans_count",
        "active_loans_count",
        "default_loans_count",
        "total_outstanding_display",
        "created_at",
    )
    list_filter = (
        "status",
        "preferred_language",
        "borrower_type",
        "gender",
        "residence_status",
        "location",
        "group_name",
        "created_at",
    )
    search_fields = (
        "borrower_id",
        "full_name",
        "national_id",
        "phone",
        "email",
        "location",
        "digital_address",
        "nearest_landmark",
        "ghana_card_number",
        "group_name",
    )
    readonly_fields = (
        "status",
        "created_at",
        "borrower_summary",
    )
    fieldsets = (
        ("Borrower Information", {
            "fields": (
                "borrower_id",
                "full_name",
                "national_id",
                "gender",
                "date_of_birth",
                "borrower_type",
                "phone",
                "alternative_phone",
                "email",
                "location",
                "group_name",
                "preferred_language",
                "status",
                "created_at",
            )
        }),
        ("Residential Information", {
            "fields": (
                "digital_address",
                "nearest_landmark",
                "residence_directions",
                "years_at_residence",
                "residence_status",
                "residence_status_other",
            )
        }),
        ("KYC / Identity", {
            "fields": (
                "ghana_card_number",
                "photo",
                "ghana_card_front",
                "ghana_card_back",
            )
        }),
        ("Portfolio Summary", {
            "fields": ("borrower_summary",)
        }),
    )
    ordering = ("full_name",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("loans__payments")

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "ACTIVE": "#b45309",
            "CLOSED": "#15803d",
            "BAD": "#b91c1c",
        }
        bg = {
            "ACTIVE": "#fef3c7",
            "CLOSED": "#dcfce7",
            "BAD": "#fee2e2",
        }
        return format_html(
            '<span style="padding:4px 10px;border-radius:999px;'
            'font-weight:700;color:{};background:{};">{}</span>',
            colors.get(obj.status, "#334155"),
            bg.get(obj.status, "#e2e8f0"),
            obj.get_status_display(),
        )

    @admin.display(description="Loans")
    def loans_count(self, obj):
        return obj.loans.count()

    @admin.display(description="Active Loans")
    def active_loans_count(self, obj):
        return obj.loans.filter(status="ACTIVE").count()

    @admin.display(description="Default Loans")
    def default_loans_count(self, obj):
        return obj.loans.filter(status="DEFAULT").count()

    @admin.display(description="Total Outstanding")
    def total_outstanding_display(self, obj):
        total = sum((loan.balance_amount for loan in obj.loans.all()), 0)
        return f"GHS {total:,.2f}"

    @admin.display(description="Borrower Summary")
    def borrower_summary(self, obj):
        loans = list(obj.loans.all())
        total_loans = len(loans)
        total_disbursed = sum((loan.amount for loan in loans), 0)
        total_expected = sum((loan.total_expected_amount for loan in loans), 0)
        total_paid = sum((loan.total_paid_amount for loan in loans), 0)
        total_balance = sum((loan.balance_amount for loan in loans), 0)
        return format_html(
            "<div>"
            "<strong>Total Loans:</strong> {}<br>"
            "<strong>Total Disbursed:</strong> GHS {:,.2f}<br>"
            "<strong>Total Expected:</strong> GHS {:,.2f}<br>"
            "<strong>Total Paid:</strong> GHS {:,.2f}<br>"
            "<strong>Total Outstanding:</strong> GHS {:,.2f}"
            "</div>",
            total_loans,
            total_disbursed,
            total_expected,
            total_paid,
            total_balance,
        )


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "borrower",
        "loan_category_badge",
        "status_badge",
        "amount",
        "duration_weeks",
        "weekly_payment",
        "roic_amount_display",
        "total_expected_amount_display",
        "total_paid_amount_display",
        "balance_amount_display",
        "overdue_weeks",
        "start_date",
        "created_at",
    )
    list_filter = (
        "status",
        "loan_category",
        "repayment_frequency",
        "sector",
        "start_date",
        "created_at",
    )
    search_fields = (
        "id",
        "borrower__full_name",
        "borrower__borrower_id",
        "borrower__national_id",
        "borrower__phone",
        "agent_name__name",
    )
    readonly_fields = (
        "loan_category",
        "status",
        "created_at",
        "loan_metrics",
    )
    fieldsets = (
        ("Loan Information", {
            "fields": (
                "borrower",
                "amount",
                "loan_category",
                "loan_acquisition_date",
                "repayment_frequency",
                "duration_months",
                "duration_weeks",
                "start_date",
                "weekly_payment",
                "sector",
                "sector_other",
                "status",
                "created_at",
            )
        }),
        ("Declaration & Guarantor", {
            "fields": (
                "borrower_declaration_accepted",
                "borrower_signature_name",
                "borrower_signed_date",
                "guarantor_name",
                "guarantor_id_number",
                "guarantor_signature_name",
                "guarantor_signed_date",
            )
        }),
        ("Collateral", {
            "fields": (
                "collateral_type",
                "collateral_details",
                "collateral_estimated_value",
                "collateral_location",
                "collateral_borrower_consent_accepted",
                "collateral_borrower_signed_date",
                "collateral_guarantor_signature_name",
                "collateral_guarantor_signed_date",
            )
        }),
        ("Office Use Only", {
            "fields": (
                "application_received_by",
                "application_received_date",
                "approved_amount",
                "approved_repayment_plan",
                "loan_officer_signature_name",
                "approval_manager_signature_name",
                "approval_date",
            )
        }),
        ("Computed Metrics", {
            "fields": ("loan_metrics",)
        }),
    )
    inlines = [PaymentInline]
    ordering = ("-created_at",)
    autocomplete_fields = ("borrower", )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("borrower", ).prefetch_related("payments")

    @admin.display(description="Category")
    def loan_category_badge(self, obj):
        colors = {
            "BRONZE": ("#92400e", "#fef3c7"),
            "SILVER": ("#475569", "#e2e8f0"),
            "GOLD": ("#a16207", "#fef9c3"),
            "PLATINUM": ("#1d4ed8", "#dbeafe"),
            "DIAMOND": ("#0f766e", "#ccfbf1"),
            "EXECUTIVE": ("#6d28d9", "#ede9fe"),
        }
        fg, bg = colors.get(obj.loan_category, ("#334155", "#e2e8f0"))
        return format_html(
            '<span style="padding:4px 10px;border-radius:999px;'
            'font-weight:700;color:{};background:{};">{}</span>',
            fg,
            bg,
            obj.get_loan_category_display(),
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "ACTIVE": ("#b45309", "#fef3c7"),
            "CLOSED": ("#15803d", "#dcfce7"),
            "DEFAULT": ("#b91c1c", "#fee2e2"),
        }
        fg, bg = colors.get(obj.status, ("#334155", "#e2e8f0"))
        return format_html(
            '<span style="padding:4px 10px;border-radius:999px;'
            'font-weight:700;color:{};background:{};">{}</span>',
            fg,
            bg,
            obj.get_status_display(),
        )

    @admin.display(description="ROIC")
    def roic_amount_display(self, obj):
        return f"GHS {obj.roic_amount:,.2f}"

    @admin.display(description="Expected Total")
    def total_expected_amount_display(self, obj):
        return f"GHS {obj.total_expected_amount:,.2f}"

    @admin.display(description="Total Paid")
    def total_paid_amount_display(self, obj):
        return f"GHS {obj.total_paid_amount:,.2f}"

    @admin.display(description="Balance")
    def balance_amount_display(self, obj):
        return f"GHS {obj.balance_amount:,.2f}"

    @admin.display(description="Loan Metrics")
    def loan_metrics(self, obj):
        return format_html(
            "<div>"
            "<strong>Principal:</strong> GHS {:,.2f}<br>"
            "<strong>ROIC:</strong> GHS {:,.2f}<br>"
            "<strong>Total Expected:</strong> GHS {:,.2f}<br>"
            "<strong>Total Paid:</strong> GHS {:,.2f}<br>"
            "<strong>Principal Paid:</strong> GHS {:,.2f}<br>"
            "<strong>ROIC Paid:</strong> GHS {:,.2f}<br>"
            "<strong>Principal Outstanding:</strong> GHS {:,.2f}<br>"
            "<strong>ROIC Outstanding:</strong> GHS {:,.2f}<br>"
            "<strong>Balance:</strong> GHS {:,.2f}<br>"
            "<strong>Expected Payments:</strong> {}<br>"
            "<strong>Actual Payments:</strong> {}<br>"
            "<strong>Outstanding Payments:</strong> {}<br>"
            "<strong>Weeks Since Start:</strong> {}<br>"
            "<strong>Expected Due By Now:</strong> {}<br>"
            "<strong>Overdue Weeks:</strong> {}<br>"
            "<strong>Overdue &gt; 6 Weeks:</strong> {}"
            "</div>",
            obj.principal_amount,
            obj.roic_amount,
            obj.total_expected_amount,
            obj.total_paid_amount,
            obj.total_principal_paid,
            obj.total_roic_paid,
            obj.principal_outstanding,
            obj.roic_outstanding,
            obj.balance_amount,
            obj.expected_payments_count,
            obj.actual_payments_count,
            obj.outstanding_payments_count,
            obj.weeks_since_start,
            obj.expected_payments_due_by_now,
            obj.overdue_weeks,
            "Yes" if obj.is_overdue_more_than_6_weeks else "No",
        )

    actions = ["refresh_selected_loan_statuses"]

    @admin.action(description="Refresh status for selected loans")
    def refresh_selected_loan_statuses(self, request, queryset):
        updated = 0
        for loan in queryset:
            old_status = loan.status
            loan.refresh_status(save=True)
            if loan.status != old_status:
                updated += 1
        self.message_user(request, f"Refreshed selected loans. {updated} loan(s) changed status.")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "loan_link",
        "borrower_name",
        "agent_name_display",
        "payment_date",
        "payment_method",
        "amount",
        "principal_paid",
        "roic_paid",
        "is_pending",
        "is_void",
        "reference",
        "created_at",
    )
    list_filter = (
        "is_void",
        "payment_date",
        "created_at",
        "loan__status",
        "loan__loan_category",
    )
    search_fields = (
        "id",
        "loan__id",
        "loan__borrower__full_name",
        "loan__borrower__borrower_id",
        "loan__borrower__phone",
        "loan__agent_name__name",
        "reference",
        "note",
    )
    readonly_fields = (
        "principal_paid",
        "roic_paid",
        "created_at",
        "payment_summary",
    )
    fieldsets = (
        ("Payment Information", {
            "fields": (
                "loan",
                "payment_date",
                "amount",
                "payment_method",
                "principal_paid",
                "roic_paid",
                "reference",
                "note",
                "is_pending",
                "is_void",
                "created_at",
            )
        }),
        ("Summary", {
            "fields": ("payment_summary",)
        }),
    )
    autocomplete_fields = ("loan",)
    ordering = ("-payment_date", "-id")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("loan", "loan__borrower", "loan__agent_name")

    @admin.display(description="Loan")
    def loan_link(self, obj):
        return f"Loan #{obj.loan_id}"

    @admin.display(description="Borrower")
    def borrower_name(self, obj):
        return obj.loan.borrower.full_name if obj.loan_id else "-"

    @admin.display(description="Agent")
    def agent_name_display(self, obj):
        return obj.loan.agent_name.name if obj.loan_id and obj.loan.agent_name_id else "-"

    @admin.display(description="Payment Summary")
    def payment_summary(self, obj):
        if not obj.loan_id:
            return "-"
        loan = obj.loan
        return format_html(
            "<div>"
            "<strong>Borrower:</strong> {}<br>"
            "<strong>Agent:</strong> {}<br>"
            "<strong>Loan Category:</strong> {}<br>"
            "<strong>Loan Status:</strong> {}<br>"
            "<strong>Payment Amount:</strong> GHS {:,.2f}<br>"
            "<strong>Principal Allocation:</strong> GHS {:,.2f}<br>"
            "<strong>ROIC Allocation:</strong> GHS {:,.2f}<br>"
            "<strong>Loan Balance After Payment:</strong> GHS {:,.2f}"
            "</div>",
            loan.borrower.full_name,
            loan.agent_name.name if loan.agent_name_id else "-",
            loan.get_loan_category_display(),
            loan.get_status_display(),
            obj.amount,
            obj.principal_paid,
            obj.roic_paid,
            loan.balance_amount,
        )

    actions = ["mark_selected_as_void", "mark_selected_as_active"]

    @admin.action(description="Mark selected payments as void")
    def mark_selected_as_void(self, request, queryset):
        count = 0
        for payment in queryset:
            if not payment.is_void:
                payment.is_void = True
                payment.save()
                count += 1
        self.message_user(request, f"{count} payment(s) marked as void.")

    @admin.action(description="Mark selected payments as not void")
    def mark_selected_as_active(self, request, queryset):
        count = 0
        for payment in queryset:
            if payment.is_void:
                payment.is_void = False
                payment.save()
                count += 1
        self.message_user(request, f"{count} payment(s) restored.")


@admin.register(RepaymentCollection)
class RepaymentCollectionAdmin(admin.ModelAdmin):
    list_display = (
        "client_reference",
        "loan_id",
        "borrower",
        "amount",
        "payment_method",
        "provider",
        "status",
        "provider_reference",
        "initiated_at",
        "reconciled_at",
    )
    list_filter = ("status", "provider", "payment_method", "initiated_at", "reconciled_at")
    search_fields = (
        "client_reference",
        "provider_reference",
        "submitted_reference",
        "loan__borrower__full_name",
        "loan__borrower__borrower_id",
        "payer_phone",
        "payer_name",
    )
    readonly_fields = (
        "initiated_at",
        "provider_confirmed_at",
        "reconciled_at",
        "failed_at",
    )
    autocomplete_fields = ("loan", "borrower", "payment", "submitted_by")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("loan", "borrower", "payment", "submitted_by")


class SecurityDepositTransactionInline(admin.TabularInline):
    model = SecurityDepositTransaction
    extra = 0
    readonly_fields = ("approved_by", "approval_request", "accounting_entry", "created_at")


@admin.register(SecurityDeposit)
class SecurityDepositAdmin(admin.ModelAdmin):
    list_display = ("loan", "borrower", "required_amount", "held_amount", "amount_due", "status")
    list_filter = ("status",)
    search_fields = ("loan__id", "borrower__full_name", "borrower__borrower_id")
    inlines = [SecurityDepositTransactionInline]
