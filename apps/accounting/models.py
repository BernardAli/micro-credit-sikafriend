from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone
from apps.core.models import ReversibleTransaction


ACCOUNT_TYPE_CHOICES = [
    ("ASSET", "Asset"),
    ("LIABILITY", "Liability"),
    ("EQUITY", "Equity"),
    ("INCOME", "Income"),
    ("EXPENSE", "Expense"),
]

PERIOD_STATUS_CHOICES = [
    ("OPEN", "Open"),
    ("CLOSED", "Closed"),
    ("ARCHIVED", "Archived"),
]

ENTRY_STATUS_CHOICES = [
    ("DRAFT", "Draft"),
    ("POSTED", "Posted"),
    ("VOID", "Void"),
]

COUNTERPARTY_TYPE_CHOICES = [
    ("CUSTOMER", "Customer"),
    ("VENDOR", "Vendor"),
    ("EMPLOYEE", "Employee"),
    ("LENDER", "Lender"),
    ("PARTNER", "Partner"),
    ("OTHER", "Other"),
]

JOURNAL_SOURCE_CHOICES = [
    ("GENERAL", "General Journal"),
    ("LOAN_DISBURSEMENT", "Loan Disbursement"),
    ("LOAN_REPAYMENT", "Loan Repayment"),
    ("SECURITY_DEPOSIT", "Security Deposit"),
    ("PAYROLL", "Payroll"),
    ("BANK_TRANSACTION", "Bank Transaction"),
    ("INVOICE", "Invoice"),
    ("BILL", "Bill"),
    ("ADJUSTMENT", "Adjustment"),
]

DOCUMENT_STATUS_CHOICES = [
    ("DRAFT", "Draft"),
    ("OPEN", "Open"),
    ("PARTIAL", "Partially Settled"),
    ("PAID", "Paid"),
    ("OVERDUE", "Overdue"),
    ("VOID", "Void"),
]

BUDGET_STATUS_CHOICES = [
    ("DRAFT", "Draft"),
    ("ACTIVE", "Active"),
    ("CLOSED", "Closed"),
]

BANK_TRANSACTION_TYPE_CHOICES = [
    ("DEPOSIT", "Deposit"),
    ("WITHDRAWAL", "Withdrawal"),
    ("TRANSFER_OUT", "Transfer Out"),
    ("INTEREST", "Interest Received"),
    ("BANK_CHARGE", "Bank Charge"),
    ("ADJUSTMENT", "Adjustment"),
]

NORMAL_BALANCE_BY_TYPE = {
    "ASSET": "DEBIT",
    "EXPENSE": "DEBIT",
    "LIABILITY": "CREDIT",
    "EQUITY": "CREDIT",
    "INCOME": "CREDIT",
}

DEFAULT_LEDGER_ACCOUNTS = [
    {"code": "1000", "name": "Cash On Hand", "account_type": "ASSET", "is_cash_account": True},
    {"code": "1005", "name": "Mobile Money Wallet", "account_type": "ASSET", "is_cash_account": True},
    {"code": "1010", "name": "Bank Current Account", "account_type": "ASSET", "is_bank_account": True},
    {"code": "1090", "name": "Cash Clearing / Suspense", "account_type": "ASSET"},
    {"code": "1100", "name": "Accounts Receivable", "account_type": "ASSET", "is_receivable": True},
    {"code": "1200", "name": "Salary Advances Recoverable", "account_type": "ASSET"},
    {"code": "1300", "name": "Loan Portfolio Principal", "account_type": "ASSET"},
    {"code": "1500", "name": "Fixed Assets", "account_type": "ASSET"},
    {"code": "1590", "name": "Accumulated Depreciation - Fixed Assets", "account_type": "ASSET"},
    {"code": "2000", "name": "Accounts Payable", "account_type": "LIABILITY", "is_payable": True},
    {"code": "2050", "name": "Payroll Statutory Deductions Payable", "account_type": "LIABILITY"},
    {"code": "2051", "name": "PAYE Payable", "account_type": "LIABILITY"},
    {"code": "2052", "name": "Employee Pension Payable", "account_type": "LIABILITY"},
    {"code": "2053", "name": "Employer Pension Payable", "account_type": "LIABILITY"},
    {"code": "2054", "name": "Welfare Deductions Payable", "account_type": "LIABILITY"},
    {"code": "2060", "name": "Payroll Other Deductions Clearing", "account_type": "LIABILITY"},
    {"code": "2065", "name": "Customer Security Deposits Held", "account_type": "LIABILITY", "is_payable": True},
    {"code": "2066", "name": "Customer Repayment Credits Held", "account_type": "LIABILITY", "is_payable": True, "allow_manual_entries": False},
    {"code": "2100", "name": "Taxes Payable", "account_type": "LIABILITY"},
    {"code": "2200", "name": "Borrowings / External Funding", "account_type": "LIABILITY"},
    {"code": "3000", "name": "Owner Capital", "account_type": "EQUITY"},
    {"code": "3100", "name": "Retained Earnings", "account_type": "EQUITY", "allow_manual_entries": False},
    {"code": "4000", "name": "Loan ROIC / Interest Income", "account_type": "INCOME"},
    {"code": "4010", "name": "Processing & Service Fee Income", "account_type": "INCOME"},
    {"code": "4020", "name": "Penalty Income", "account_type": "INCOME"},
    {"code": "4090", "name": "Other Operating Income", "account_type": "INCOME"},
    {"code": "5000", "name": "Salary Expense", "account_type": "EXPENSE"},
    {"code": "5010", "name": "Staff Allowance Expense", "account_type": "EXPENSE"},
    {"code": "5020", "name": "Commission Expense", "account_type": "EXPENSE"},
    {"code": "5035", "name": "Employer Statutory Contribution Expense", "account_type": "EXPENSE"},
    {"code": "5030", "name": "Marketing Expense", "account_type": "EXPENSE"},
    {"code": "5040", "name": "Transport & Field Operations Expense", "account_type": "EXPENSE"},
    {"code": "5050", "name": "Utilities & Rent Expense", "account_type": "EXPENSE"},
    {"code": "5060", "name": "Office & Admin Expense", "account_type": "EXPENSE"},
    {"code": "5070", "name": "Professional Fees Expense", "account_type": "EXPENSE"},
    {"code": "5080", "name": "Bank Charges Expense", "account_type": "EXPENSE"},
    {"code": "5090", "name": "Bad Debt & Impairment Expense", "account_type": "EXPENSE"},
    {"code": "5091", "name": "Depreciation Expense", "account_type": "EXPENSE"},
    {"code": "5092", "name": "Asset Maintenance Expense", "account_type": "EXPENSE"},
    {"code": "5093", "name": "Loss On Asset Disposal", "account_type": "EXPENSE"},
    {"code": "4091", "name": "Gain On Asset Disposal", "account_type": "INCOME"},
]


class AccountingPeriod(models.Model):
    name = models.CharField(max_length=120, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=12, choices=PERIOD_STATUS_CHOICES, default="OPEN")
    notes = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    @property
    def is_open(self):
        return self.status == "OPEN"

    def contains(self, value):
        return self.start_date <= value <= self.end_date

    def __str__(self):
        return self.name


class LedgerAccount(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=160)
    account_type = models.CharField(max_length=12, choices=ACCOUNT_TYPE_CHOICES)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    is_cash_account = models.BooleanField(default=False)
    is_bank_account = models.BooleanField(default=False)
    is_receivable = models.BooleanField(default=False)
    is_payable = models.BooleanField(default=False)
    allow_manual_entries = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code", "name"]

    @property
    def normal_balance(self):
        return NORMAL_BALANCE_BY_TYPE.get(self.account_type, "DEBIT")

    @property
    def total_debits(self):
        total = self.lines.aggregate(total=Sum("debit"))["total"] or Decimal("0.00")
        return Decimal(total).quantize(Decimal("0.01"))

    @property
    def total_credits(self):
        total = self.lines.aggregate(total=Sum("credit"))["total"] or Decimal("0.00")
        return Decimal(total).quantize(Decimal("0.01"))

    @property
    def current_balance(self):
        debit = self.total_debits
        credit = self.total_credits
        if self.normal_balance == "DEBIT":
            return (debit - credit).quantize(Decimal("0.01"))
        return (credit - debit).quantize(Decimal("0.01"))

    def __str__(self):
        return f"{self.code} - {self.name}"


class Counterparty(models.Model):
    name = models.CharField(max_length=180)
    counterparty_type = models.CharField(max_length=12, choices=COUNTERPARTY_TYPE_CHOICES, default="OTHER")
    contact_person = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    location = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class JournalEntry(models.Model):
    reversed_by = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal_of", editable=False)
    entry_no = models.CharField(max_length=40, unique=True, blank=True)
    entry_date = models.DateField(default=timezone.localdate)
    source_date = models.DateField(null=True, blank=True, editable=False)
    memo = models.CharField(max_length=255)
    reference = models.CharField(max_length=120, blank=True)
    period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_entries",
    )
    source_type = models.CharField(max_length=24, choices=JOURNAL_SOURCE_CHOICES, default="GENERAL")
    source_key = models.CharField(max_length=120, blank=True)
    source_label = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=ENTRY_STATUS_CHOICES, default="POSTED")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_entries_created",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-entry_date", "-created_at"]

    @property
    def total_debits(self):
        total = self.lines.aggregate(total=Sum("debit"))["total"] or Decimal("0.00")
        return Decimal(total).quantize(Decimal("0.01"))

    @property
    def total_credits(self):
        total = self.lines.aggregate(total=Sum("credit"))["total"] or Decimal("0.00")
        return Decimal(total).quantize(Decimal("0.01"))

    @property
    def is_balanced(self):
        return self.total_debits == self.total_credits

    def save(self, *args, **kwargs):
        original = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        posting_changed = original is None or any(getattr(original, name) != getattr(self, name) for name in ("entry_date", "period_id", "status"))
        if not self.entry_no:
            stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
            self.entry_no = f"JE-{stamp}"
        if not self.period_id and self.entry_date:
            self.period = (
                AccountingPeriod.objects.filter(
                    start_date__lte=self.entry_date,
                    end_date__gte=self.entry_date,
                )
                .order_by("-start_date")
                .first()
            )
        if self.status == "POSTED" and not self.posted_at:
            self.posted_at = timezone.now()
        if posting_changed and self.period_id and not self.period.is_open:
            raise ValidationError("Journal entries cannot be posted or changed in a closed accounting period.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.entry_no or f"Journal #{self.pk}"


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="lines")
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.account} ({self.entry})"


class BankAccount(models.Model):
    name = models.CharField(max_length=160)
    institution = models.CharField(max_length=160)
    account_number = models.CharField(max_length=80, blank=True)
    mobile_money_number = models.CharField(max_length=30, blank=True)
    linked_account = models.OneToOneField(LedgerAccount, on_delete=models.PROTECT, related_name="bank_profile")
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    @property
    def book_balance(self):
        return (Decimal(self.opening_balance) + self.linked_account.current_balance).quantize(Decimal("0.01"))

    def __str__(self):
        return self.name


class BankTransaction(ReversibleTransaction):
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="transactions")
    transaction_date = models.DateField(default=timezone.localdate)
    transaction_type = models.CharField(max_length=16, choices=BANK_TRANSACTION_TYPE_CHOICES)
    reference = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    counterparty = models.ForeignKey(
        Counterparty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transactions",
    )
    target_bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_transfers",
    )
    offset_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_offset_transactions",
    )
    description = models.CharField(max_length=255, blank=True)
    posted_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transactions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transactions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transaction_date", "-created_at"]

    def __str__(self):
        return f"{self.bank_account.name} - {self.transaction_type} - {self.amount}"


class Invoice(ReversibleTransaction):
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT, related_name="invoices")
    invoice_number = models.CharField(max_length=60, unique=True)
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    income_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="sales_invoices",
    )
    receivable_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="receivable_invoices",
    )
    settlement_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="settled_invoices",
    )
    status = models.CharField(max_length=12, choices=DOCUMENT_STATUS_CHOICES, default="OPEN")
    posted_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issue_date", "-created_at"]

    @property
    def outstanding_amount(self):
        if self.status in {"PAID", "VOID"}:
            return Decimal("0.00")
        return Decimal(self.amount).quantize(Decimal("0.01"))

    def __str__(self):
        return self.invoice_number


class Bill(ReversibleTransaction):
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT, related_name="bills")
    bill_number = models.CharField(max_length=60, unique=True)
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    expense_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="expense_bills",
    )
    payable_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="payable_bills",
    )
    settlement_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="settled_bills",
    )
    status = models.CharField(max_length=12, choices=DOCUMENT_STATUS_CHOICES, default="OPEN")
    posted_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bills",
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bills_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issue_date", "-created_at"]

    @property
    def outstanding_amount(self):
        if self.status in {"PAID", "VOID"}:
            return Decimal("0.00")
        return Decimal(self.amount).quantize(Decimal("0.01"))

    def __str__(self):
        return self.bill_number


class Budget(models.Model):
    name = models.CharField(max_length=160)
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT, related_name="budgets")
    status = models.CharField(max_length=12, choices=BUDGET_STATUS_CHOICES, default="DRAFT")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def total_budget(self):
        total = self.lines.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return Decimal(total).quantize(Decimal("0.01"))

    def __str__(self):
        return self.name


class BudgetLine(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="budget_lines")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["account__code"]
        unique_together = ("budget", "account")

    def __str__(self):
        return f"{self.budget.name} - {self.account.code}"


def ensure_default_ledger_accounts():
    for item in DEFAULT_LEDGER_ACCOUNTS:
        code = item["code"]
        defaults = {
            "name": item["name"],
            "account_type": item["account_type"],
            "is_cash_account": item.get("is_cash_account", False),
            "is_bank_account": item.get("is_bank_account", False),
            "is_receivable": item.get("is_receivable", False),
            "is_payable": item.get("is_payable", False),
            "allow_manual_entries": item.get("allow_manual_entries", True),
            "is_system": True,
        }
        account, created = LedgerAccount.objects.get_or_create(code=code, defaults=defaults)
        if not created:
            changed = False
            for field, value in defaults.items():
                if getattr(account, field) != value:
                    setattr(account, field, value)
                    changed = True
            if changed:
                account.save()


def ensure_default_accounting_period():
    today = timezone.localdate()
    start = today.replace(month=1, day=1)
    end = today.replace(month=12, day=31)
    name = f"FY {today.year}"
    AccountingPeriod.objects.get_or_create(
        name=name,
        defaults={"start_date": start, "end_date": end, "status": "OPEN"},
    )


def get_ledger_account(code):
    return LedgerAccount.objects.filter(code=code).first()


def create_journal_entry(
    *,
    entry_date,
    memo,
    lines,
    created_by=None,
    reference="",
    source_type="GENERAL",
    source_key="",
    source_label="",
    source_date=None,
    status="POSTED",
):
    prepared_lines = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    quant = Decimal("0.01")

    for line in lines:
        account = line.get("account")
        debit = Decimal(line.get("debit") or Decimal("0.00")).quantize(quant)
        credit = Decimal(line.get("credit") or Decimal("0.00")).quantize(quant)
        description = (line.get("description") or "").strip()
        if debit < 0 or credit < 0 or (debit > 0 and credit > 0):
            raise ValueError("Journal lines need a nonnegative debit or credit, never both.")
        if not account or (debit == 0 and credit == 0):
            continue
        if not account.is_active:
            raise ValueError("Journal accounts must be active.")
        if source_type == "GENERAL" and not account.allow_manual_entries:
            raise ValueError("This account does not permit manual journal entries.")
        prepared_lines.append({
            "account": account,
            "debit": debit,
            "credit": credit,
            "description": description,
        })
        total_debit += debit
        total_credit += credit

    total_debit = total_debit.quantize(quant)
    total_credit = total_credit.quantize(quant)

    if len(prepared_lines) < 2:
        raise ValueError("A journal entry needs at least two populated lines.")
    if total_debit != total_credit:
        raise ValueError("Journal entry lines must balance before posting.")

    with transaction.atomic():
        period = AccountingPeriod.objects.select_for_update().filter(start_date__lte=entry_date, end_date__gte=entry_date).order_by("-start_date").first()
        if period and not period.is_open:
            raise ValueError("Journal entries cannot be posted in a closed accounting period.")
        entry = JournalEntry.objects.create(
            entry_date=entry_date,
            memo=memo,
            reference=reference,
            period=period,
            source_type=source_type,
            source_key=source_key,
            source_label=source_label,
            source_date=source_date,
            status=status,
            created_by=created_by,
        )
        for line in prepared_lines:
            JournalLine.objects.create(
                entry=entry,
                account=line["account"],
                description=line["description"],
                debit=line["debit"],
                credit=line["credit"],
            )
    return entry


@transaction.atomic
def reverse_journal_entry(entry, *, user=None, reason=""):
    """Retain the original posting and offset it in the current open period."""
    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.reversed_by_id:
        return entry.reversed_by, False
    if entry.status != "POSTED":
        return None, False
    reversal = create_journal_entry(
        entry_date=timezone.localdate(), memo=f"Reverse {entry.entry_no}: {reason}"[:255],
        lines=[{"account": line.account, "debit": line.credit, "credit": line.debit, "description": f"Reversal of {entry.entry_no}"} for line in entry.lines.select_related("account")],
        created_by=user, source_type="ADJUSTMENT", source_key=f"reversal:{entry.pk}",
        source_label=entry.source_label, reference=entry.reference,
        source_date=entry.source_date or entry.entry_date,
    )
    entry.reversed_by = reversal
    entry.save(update_fields=["reversed_by"])
    return reversal, True
