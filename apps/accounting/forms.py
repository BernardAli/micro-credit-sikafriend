from django import forms
from django.forms import formset_factory

from .models import (
    AccountingPeriod,
    BankAccount,
    BankTransaction,
    Bill,
    Budget,
    BudgetLine,
    Counterparty,
    Invoice,
    LedgerAccount,
)


class DateInput(forms.DateInput):
    input_type = "date"


class AccountingPeriodForm(forms.ModelForm):
    class Meta:
        model = AccountingPeriod
        fields = ["name", "start_date", "end_date", "status", "notes"]
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class LedgerAccountForm(forms.ModelForm):
    class Meta:
        model = LedgerAccount
        fields = [
            "code",
            "name",
            "account_type",
            "parent",
            "description",
            "is_cash_account",
            "is_bank_account",
            "is_receivable",
            "is_payable",
            "allow_manual_entries",
            "is_active",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class CounterpartyForm(forms.ModelForm):
    class Meta:
        model = Counterparty
        fields = [
            "name",
            "counterparty_type",
            "contact_person",
            "phone",
            "email",
            "location",
            "notes",
            "is_active",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = [
            "name",
            "institution",
            "account_number",
            "mobile_money_number",
            "linked_account",
            "opening_balance",
            "notes",
            "is_active",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["linked_account"].queryset = LedgerAccount.objects.filter(account_type="ASSET", is_active=True).order_by("code")


class BankTransactionForm(forms.ModelForm):
    class Meta:
        model = BankTransaction
        fields = [
            "bank_account",
            "transaction_date",
            "transaction_type",
            "amount",
            "reference",
            "counterparty",
            "target_bank_account",
            "offset_account",
            "description",
        ]
        widgets = {
            "transaction_date": DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        asset_accounts = LedgerAccount.objects.filter(account_type="ASSET", is_active=True).order_by("code")
        self.fields["offset_account"].queryset = LedgerAccount.objects.filter(is_active=True).order_by("code")
        self.fields["target_bank_account"].queryset = BankAccount.objects.filter(is_active=True).order_by("name")
        self.fields["bank_account"].queryset = BankAccount.objects.filter(is_active=True).order_by("name")
        self.fields["counterparty"].queryset = Counterparty.objects.filter(is_active=True).order_by("name")
        self.fields["offset_account"].help_text = "Required for deposits, withdrawals, adjustments, and bank charges. Transfers use the target bank."
        self.fields["bank_account"].help_text = "Choose the cashbook or bank ledger receiving or paying the funds."
        _ = asset_accounts

    def clean(self):
        cleaned = super().clean()
        tx_type = cleaned.get("transaction_type")
        target_bank = cleaned.get("target_bank_account")
        offset_account = cleaned.get("offset_account")
        bank_account = cleaned.get("bank_account")

        if tx_type == "TRANSFER_OUT":
            if not target_bank:
                self.add_error("target_bank_account", "Select the destination bank or wallet for a transfer.")
            if target_bank and bank_account and target_bank.pk == bank_account.pk:
                self.add_error("target_bank_account", "Transfer source and destination cannot be the same account.")
        elif not offset_account:
            self.add_error("offset_account", "Select the balancing ledger account for this transaction.")

        return cleaned


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "counterparty",
            "invoice_number",
            "issue_date",
            "due_date",
            "description",
            "amount",
            "income_account",
            "receivable_account",
            "settlement_account",
            "status",
            "notes",
        ]
        widgets = {
            "issue_date": DateInput(),
            "due_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["counterparty"].queryset = Counterparty.objects.filter(is_active=True).order_by("name")
        self.fields["income_account"].queryset = LedgerAccount.objects.filter(account_type="INCOME", is_active=True).order_by("code")
        self.fields["receivable_account"].queryset = LedgerAccount.objects.filter(is_receivable=True, is_active=True).order_by("code")
        self.fields["settlement_account"].queryset = LedgerAccount.objects.filter(account_type="ASSET", is_active=True).order_by("code")


class BillForm(forms.ModelForm):
    class Meta:
        model = Bill
        fields = [
            "counterparty",
            "bill_number",
            "issue_date",
            "due_date",
            "description",
            "amount",
            "expense_account",
            "payable_account",
            "settlement_account",
            "status",
            "notes",
        ]
        widgets = {
            "issue_date": DateInput(),
            "due_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["counterparty"].queryset = Counterparty.objects.filter(is_active=True).order_by("name")
        self.fields["expense_account"].queryset = LedgerAccount.objects.filter(account_type="EXPENSE", is_active=True).order_by("code")
        self.fields["payable_account"].queryset = LedgerAccount.objects.filter(is_payable=True, is_active=True).order_by("code")
        self.fields["settlement_account"].queryset = LedgerAccount.objects.filter(account_type="ASSET", is_active=True).order_by("code")


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ["name", "period", "status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class BudgetLineForm(forms.ModelForm):
    class Meta:
        model = BudgetLine
        fields = ["budget", "account", "amount", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = LedgerAccount.objects.filter(
            account_type__in=["EXPENSE", "INCOME"],
            is_active=True,
        ).order_by("code")


class JournalEntryHeaderForm(forms.Form):
    entry_date = forms.DateField(widget=DateInput())
    memo = forms.CharField(max_length=255)
    reference = forms.CharField(max_length=120, required=False)
    period = forms.ModelChoiceField(queryset=AccountingPeriod.objects.order_by("-start_date"), required=False)


class JournalLineDraftForm(forms.Form):
    account = forms.ModelChoiceField(queryset=LedgerAccount.objects.none(), required=False)
    description = forms.CharField(max_length=255, required=False)
    debit = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=14)
    credit = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=14)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = LedgerAccount.objects.filter(is_active=True).order_by("code")

    def clean(self):
        cleaned = super().clean()
        account = cleaned.get("account")
        debit = cleaned.get("debit")
        credit = cleaned.get("credit")
        has_amount = (debit or 0) > 0 or (credit or 0) > 0

        if has_amount and not account:
            self.add_error("account", "Select an account for this line.")
        if (debit or 0) > 0 and (credit or 0) > 0:
            self.add_error("credit", "Enter either a debit or a credit, not both.")
        return cleaned


JournalLineFormSet = formset_factory(JournalLineDraftForm, extra=4)

