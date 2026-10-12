from django.contrib import admin
from apps.core.financial_admin import FinancialEvidenceAdmin

from .models import (
    AccountingPeriod,
    BankAccount,
    BankTransaction,
    Bill,
    Budget,
    BudgetLine,
    Counterparty,
    Invoice,
    JournalEntry,
    JournalLine,
    LedgerAccount,
)


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0


@admin.register(LedgerAccount)
class LedgerAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "account_type", "is_active", "is_system", "is_cash_account", "is_bank_account")
    list_filter = ("account_type", "is_active", "is_system", "is_cash_account", "is_bank_account")
    search_fields = ("code", "name")


@admin.register(AccountingPeriod)
class AccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "status")
    list_filter = ("status",)
    search_fields = ("name",)


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("entry_no", "entry_date", "memo", "source_type", "status", "total_debits", "total_credits")
    list_filter = ("status", "source_type", "entry_date")
    search_fields = ("entry_no", "memo", "reference", "source_key")
    inlines = [JournalLineInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Counterparty)
class CounterpartyAdmin(admin.ModelAdmin):
    list_display = ("name", "counterparty_type", "phone", "email", "is_active")
    list_filter = ("counterparty_type", "is_active")
    search_fields = ("name", "phone", "email")


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "linked_account", "opening_balance", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "institution", "account_number", "mobile_money_number")


@admin.register(BankTransaction)
class BankTransactionAdmin(FinancialEvidenceAdmin):
    list_display = ("bank_account", "transaction_date", "transaction_type", "amount", "reference")
    list_filter = ("transaction_type", "transaction_date")
    search_fields = ("reference", "description")


@admin.register(Invoice)
class InvoiceAdmin(FinancialEvidenceAdmin):
    list_display = ("invoice_number", "counterparty", "issue_date", "due_date", "amount", "status")
    list_filter = ("status", "issue_date")
    search_fields = ("invoice_number", "description", "counterparty__name")


@admin.register(Bill)
class BillAdmin(FinancialEvidenceAdmin):
    list_display = ("bill_number", "counterparty", "issue_date", "due_date", "amount", "status")
    list_filter = ("status", "issue_date")
    search_fields = ("bill_number", "description", "counterparty__name")


class BudgetLineInline(admin.TabularInline):
    model = BudgetLine
    extra = 0


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("name", "period", "status", "total_budget")
    list_filter = ("status", "period")
    search_fields = ("name",)
    inlines = [BudgetLineInline]

