from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models

import apps.company.statutory


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0007_alter_companyprofile_about_headline_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="corporate_income_tax_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("25.00"), help_text="Reference corporate income tax rate for management reporting.", max_digits=5, validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="employee_pension_payable_account_code",
            field=models.CharField(default="2052", help_text="Ledger code used for employee pension liabilities.", max_length=20),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="employer_pension_payable_account_code",
            field=models.CharField(default="2053", help_text="Ledger code used for employer pension liabilities.", max_length=20),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="employer_statutory_expense_account_code",
            field=models.CharField(default="5035", help_text="Expense ledger used for employer statutory contributions.", max_length=20),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="getfund_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("2.50"), help_text="GETFund levy rate.", max_digits=5, validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="nhil_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("2.50"), help_text="National Health Insurance Levy rate.", max_digits=5, validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="paye_payable_account_code",
            field=models.CharField(default="2051", help_text="Ledger code used for PAYE liabilities.", max_length=20),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_employee_pension_enabled",
            field=models.BooleanField(default=True, help_text="Deduct employee pension contributions from payroll automatically."),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_employee_pension_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("5.50"), help_text="Employee pension deduction as a percentage of basic salary.", max_digits=5, validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_employer_pension_enabled",
            field=models.BooleanField(default=True, help_text="Accrue employer pension contributions as an additional payroll cost."),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_employer_pension_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("13.00"), help_text="Employer pension contribution as a percentage of basic salary.", max_digits=5, validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_personal_relief_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Monthly relief deducted before PAYE is calculated.", max_digits=10, validators=[MinValueValidator(Decimal("0.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_tax_brackets",
            field=models.JSONField(blank=True, default=apps.company.statutory.default_payroll_tax_brackets, help_text='JSON array of tax bands: [{"up_to":"490.00","rate":"0.00","label":"First 490"}, ...]'),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_tax_enabled",
            field=models.BooleanField(default=True, help_text="Automatically calculate employee PAYE during payroll generation."),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_welfare_deduction_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Optional staff welfare deduction as a percentage of gross pay.", max_digits=5, validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_welfare_enabled",
            field=models.BooleanField(default=False, help_text="Apply staff welfare deductions automatically during payroll runs."),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="payroll_welfare_fixed_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Optional flat welfare deduction applied to each payroll line.", max_digits=10, validators=[MinValueValidator(Decimal("0.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="vat_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("15.00"), help_text="Standard VAT rate used by the business.", max_digits=5, validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="welfare_payable_account_code",
            field=models.CharField(default="2054", help_text="Ledger code used for staff welfare or union deductions.", max_length=20),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="withholding_tax_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("5.00"), help_text="Default withholding tax rate for supplier or contractor payments.", max_digits=5, validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))]),
        ),
    ]
