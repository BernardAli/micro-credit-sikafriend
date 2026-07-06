from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountingPeriod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("CLOSED", "Closed"), ("ARCHIVED", "Archived")], default="OPEN", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-start_date"]},
        ),
        migrations.CreateModel(
            name="Counterparty",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("counterparty_type", models.CharField(choices=[("CUSTOMER", "Customer"), ("VENDOR", "Vendor"), ("EMPLOYEE", "Employee"), ("LENDER", "Lender"), ("PARTNER", "Partner"), ("OTHER", "Other")], default="OTHER", max_length=12)),
                ("contact_person", models.CharField(blank=True, max_length=160)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("location", models.CharField(blank=True, max_length=160)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="JournalEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entry_no", models.CharField(blank=True, max_length=40, unique=True)),
                ("entry_date", models.DateField()),
                ("memo", models.CharField(max_length=255)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("source_type", models.CharField(choices=[("GENERAL", "General Journal"), ("LOAN_DISBURSEMENT", "Loan Disbursement"), ("LOAN_REPAYMENT", "Loan Repayment"), ("PAYROLL", "Payroll"), ("BANK_TRANSACTION", "Bank Transaction"), ("INVOICE", "Invoice"), ("BILL", "Bill"), ("ADJUSTMENT", "Adjustment")], default="GENERAL", max_length=24)),
                ("source_key", models.CharField(blank=True, max_length=120)),
                ("source_label", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("POSTED", "Posted"), ("VOID", "Void")], default="POSTED", max_length=12)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="journal_entries_created", to=settings.AUTH_USER_MODEL)),
                ("period", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="journal_entries", to="accounting.accountingperiod")),
            ],
            options={"ordering": ["-entry_date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="LedgerAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=160)),
                ("account_type", models.CharField(choices=[("ASSET", "Asset"), ("LIABILITY", "Liability"), ("EQUITY", "Equity"), ("INCOME", "Income"), ("EXPENSE", "Expense")], max_length=12)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("is_system", models.BooleanField(default=False)),
                ("is_cash_account", models.BooleanField(default=False)),
                ("is_bank_account", models.BooleanField(default=False)),
                ("is_receivable", models.BooleanField(default=False)),
                ("is_payable", models.BooleanField(default=False)),
                ("allow_manual_entries", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="children", to="accounting.ledgeraccount")),
            ],
            options={"ordering": ["code", "name"]},
        ),
        migrations.CreateModel(
            name="Budget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("CLOSED", "Closed")], default="DRAFT", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("period", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="budgets", to="accounting.accountingperiod")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="JournalLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("description", models.CharField(blank=True, max_length=255)),
                ("debit", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("credit", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="accounting.ledgeraccount")),
                ("entry", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="accounting.journalentry")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="BankAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("institution", models.CharField(max_length=160)),
                ("account_number", models.CharField(blank=True, max_length=80)),
                ("mobile_money_number", models.CharField(blank=True, max_length=30)),
                ("opening_balance", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("linked_account", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="bank_profile", to="accounting.ledgeraccount")),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="BudgetLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal("0.00"))])),
                ("notes", models.CharField(blank=True, max_length=255)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="budget_lines", to="accounting.ledgeraccount")),
                ("budget", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="accounting.budget")),
            ],
            options={"ordering": ["account__code"], "unique_together": {("budget", "account")}},
        ),
        migrations.CreateModel(
            name="Invoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("invoice_number", models.CharField(max_length=60, unique=True)),
                ("issue_date", models.DateField()),
                ("due_date", models.DateField()),
                ("description", models.CharField(max_length=255)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("OPEN", "Open"), ("PARTIAL", "Partially Settled"), ("PAID", "Paid"), ("OVERDUE", "Overdue"), ("VOID", "Void")], default="OPEN", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("counterparty", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="invoices", to="accounting.counterparty")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="invoices_created", to=settings.AUTH_USER_MODEL)),
                ("income_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales_invoices", to="accounting.ledgeraccount")),
                ("posted_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="invoices", to="accounting.journalentry")),
                ("receivable_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receivable_invoices", to="accounting.ledgeraccount")),
                ("settlement_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="settled_invoices", to="accounting.ledgeraccount")),
            ],
            options={"ordering": ["-issue_date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="Bill",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bill_number", models.CharField(max_length=60, unique=True)),
                ("issue_date", models.DateField()),
                ("due_date", models.DateField()),
                ("description", models.CharField(max_length=255)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("OPEN", "Open"), ("PARTIAL", "Partially Settled"), ("PAID", "Paid"), ("OVERDUE", "Overdue"), ("VOID", "Void")], default="OPEN", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("counterparty", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bills", to="accounting.counterparty")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bills_created", to=settings.AUTH_USER_MODEL)),
                ("expense_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expense_bills", to="accounting.ledgeraccount")),
                ("payable_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payable_bills", to="accounting.ledgeraccount")),
                ("posted_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bills", to="accounting.journalentry")),
                ("settlement_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="settled_bills", to="accounting.ledgeraccount")),
            ],
            options={"ordering": ["-issue_date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="BankTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transaction_date", models.DateField()),
                ("transaction_type", models.CharField(choices=[("DEPOSIT", "Deposit"), ("WITHDRAWAL", "Withdrawal"), ("TRANSFER_OUT", "Transfer Out"), ("INTEREST", "Interest Received"), ("BANK_CHARGE", "Bank Charge"), ("ADJUSTMENT", "Adjustment")], max_length=16)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("description", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("bank_account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transactions", to="accounting.bankaccount")),
                ("counterparty", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bank_transactions", to="accounting.counterparty")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bank_transactions_created", to=settings.AUTH_USER_MODEL)),
                ("offset_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bank_offset_transactions", to="accounting.ledgeraccount")),
                ("posted_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bank_transactions", to="accounting.journalentry")),
                ("target_bank_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incoming_transfers", to="accounting.bankaccount")),
            ],
            options={"ordering": ["-transaction_date", "-created_at"]},
        ),
    ]
