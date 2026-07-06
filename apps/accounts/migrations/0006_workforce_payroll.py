from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_agent_email"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="agent",
            name="bank_account_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="agent",
            name="bank_account_number",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="agent",
            name="bank_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="agent",
            name="base_salary",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="agent",
            name="commission_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Commission rate as a percentage of collections for payroll calculation.", max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal("0.00")), django.core.validators.MaxValueValidator(Decimal("100.00"))]),
        ),
        migrations.AddField(
            model_name="agent",
            name="communication_allowance",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="agent",
            name="date_of_birth",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agent",
            name="department",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="agent",
            name="emergency_contact_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="agent",
            name="emergency_contact_phone",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="agent",
            name="employment_status",
            field=models.CharField(choices=[("ACTIVE", "Active"), ("ONBOARDING", "Onboarding"), ("ON_LEAVE", "On Leave"), ("SUSPENDED", "Suspended"), ("EXITED", "Exited")], default="ACTIVE", max_length=20),
        ),
        migrations.AddField(
            model_name="agent",
            name="employment_type",
            field=models.CharField(choices=[("FULL_TIME", "Full Time"), ("PART_TIME", "Part Time"), ("CONTRACT", "Contract"), ("CONSULTANT", "Consultant")], default="FULL_TIME", max_length=20),
        ),
        migrations.AddField(
            model_name="agent",
            name="has_admin_access",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="agent",
            name="hire_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agent",
            name="housing_allowance",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="agent",
            name="job_title",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="agent",
            name="meal_allowance",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="agent",
            name="mobile_money_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="agent",
            name="mobile_money_number",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="agent",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="agent",
            name="other_allowance",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="agent",
            name="payroll_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="agent",
            name="preferred_payment_method",
            field=models.CharField(choices=[("BANK", "Bank Transfer"), ("MOMO", "Mobile Money"), ("CASH", "Cash"), ("MIXED", "Mixed")], default="BANK", max_length=10),
        ),
        migrations.AddField(
            model_name="agent",
            name="residential_address",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="agent",
            name="social_security_number",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="agent",
            name="tax_number",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="agent",
            name="transport_allowance",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="agent",
            name="workforce_role",
            field=models.CharField(choices=[("AGENT", "Field Agent"), ("HR", "Human Resources"), ("STAFF", "General Staff"), ("FINANCE", "Finance"), ("OPERATIONS", "Operations"), ("RECOVERY", "Recovery"), ("MANAGEMENT", "Management")], default="AGENT", max_length=20),
        ),
        migrations.AlterField(
            model_name="agent",
            name="ghana_card_back",
            field=models.ImageField(blank=True, null=True, upload_to="agents/ghana_cards/back/"),
        ),
        migrations.AlterField(
            model_name="agent",
            name="ghana_card_front",
            field=models.ImageField(blank=True, null=True, upload_to="agents/ghana_cards/front/"),
        ),
        migrations.AlterField(
            model_name="agent",
            name="ghana_card_number",
            field=models.CharField(blank=True, max_length=30, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="agent",
            name="group_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AlterField(
            model_name="agent",
            name="photo",
            field=models.ImageField(blank=True, null=True, upload_to="agents/photos/"),
        ),
        migrations.AddField(
            model_name="agent",
            name="supervisor",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="team_members", to="accounts.agent"),
        ),
        migrations.CreateModel(
            name="PayrollAdjustment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("adjustment_type", models.CharField(choices=[("EARNING", "Earning"), ("DEDUCTION", "Deduction")], max_length=12)),
                ("category", models.CharField(choices=[("BONUS", "Bonus"), ("ALLOWANCE", "Allowance"), ("OVERTIME", "Overtime"), ("COMMISSION", "Commission"), ("TAX", "Tax"), ("PENSION", "Pension"), ("WELFARE", "Welfare"), ("ADVANCE_RECOVERY", "Advance Recovery"), ("LOAN_RECOVERY", "Loan Recovery"), ("PENALTY", "Penalty"), ("OTHER", "Other")], default="OTHER", max_length=24)),
                ("label", models.CharField(max_length=160)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("is_recurring", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payroll_adjustments", to="accounts.agent")),
            ],
            options={"ordering": ["-effective_from", "-created_at"]},
        ),
        migrations.CreateModel(
            name="PayrollRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("pay_date", models.DateField()),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("APPROVED", "Approved"), ("PAID", "Paid"), ("CANCELLED", "Cancelled")], default="DRAFT", max_length=12)),
                ("include_active_only", models.BooleanField(default=True)),
                ("include_commissions", models.BooleanField(default=True)),
                ("include_loan_recovery", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payroll_runs_approved", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payroll_runs_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-period_end", "-created_at"]},
        ),
        migrations.CreateModel(
            name="PayrollLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payment_method", models.CharField(choices=[("BANK", "Bank Transfer"), ("MOMO", "Mobile Money"), ("CASH", "Cash"), ("MIXED", "Mixed")], default="BANK", max_length=10)),
                ("base_salary", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("fixed_allowances", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("bonus_total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("commission_total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("overtime_total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("other_earnings", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("statutory_deductions", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("loan_recovery_deductions", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("other_deductions", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("gross_pay", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("total_deductions", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("net_pay", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("collections_tracked", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("disbursements_tracked", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payroll_lines", to="accounts.agent")),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="accounts.payrollrun")),
            ],
            options={"ordering": ["employee__name"], "unique_together": {("run", "employee")}},
        ),
    ]
