from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounting", "0001_initial"),
        ("accounts", "0006_workforce_payroll"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=30, unique=True)),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("default_useful_life_months", models.PositiveIntegerField(default=36)),
                ("default_residual_value_rate", models.DecimalField(decimal_places=2, default=Decimal("5.00"), help_text="Residual value as a percentage of acquisition cost.", max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal("0.00")), django.core.validators.MaxValueValidator(Decimal("100.00"))])),
                ("default_depreciation_method", models.CharField(choices=[("STRAIGHT_LINE", "Straight Line"), ("REDUCING_BALANCE", "Reducing Balance")], default="STRAIGHT_LINE", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("accumulated_depreciation_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asset_categories_accumulated", to="accounting.ledgeraccount")),
                ("asset_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asset_categories_asset", to="accounting.ledgeraccount")),
                ("default_funding_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asset_categories_funding", to="accounting.ledgeraccount")),
                ("depreciation_expense_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asset_categories_depreciation_expense", to="accounting.ledgeraccount")),
                ("maintenance_expense_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asset_categories_maintenance_expense", to="accounting.ledgeraccount")),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="DepreciationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("posting_date", models.DateField(default=django.utils.timezone.localdate)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("POSTED", "Posted"), ("CANCELLED", "Cancelled")], default="POSTED", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_depreciation_runs_created", to=settings.AUTH_USER_MODEL)),
                ("posted_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_depreciation_runs", to="accounting.journalentry")),
            ],
            options={"ordering": ["-posting_date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="AssetItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("asset_code", models.CharField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=180)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("IN_MAINTENANCE", "In Maintenance"), ("DISPOSED", "Disposed"), ("WRITTEN_OFF", "Written Off")], default="ACTIVE", max_length=20)),
                ("condition", models.CharField(choices=[("EXCELLENT", "Excellent"), ("GOOD", "Good"), ("FAIR", "Fair"), ("POOR", "Poor"), ("CRITICAL", "Critical")], default="GOOD", max_length=20)),
                ("serial_number", models.CharField(blank=True, max_length=120)),
                ("manufacturer", models.CharField(blank=True, max_length=120)),
                ("model_name", models.CharField(blank=True, max_length=120)),
                ("location", models.CharField(blank=True, max_length=160)),
                ("branch_name", models.CharField(blank=True, max_length=160)),
                ("acquisition_date", models.DateField(default=django.utils.timezone.localdate)),
                ("in_service_date", models.DateField(default=django.utils.timezone.localdate)),
                ("warranty_expiry", models.DateField(blank=True, null=True)),
                ("purchase_cost", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("residual_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("useful_life_months", models.PositiveIntegerField(default=36)),
                ("depreciation_method", models.CharField(choices=[("STRAIGHT_LINE", "Straight Line"), ("REDUCING_BALANCE", "Reducing Balance")], default="STRAIGHT_LINE", max_length=20)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("accumulated_depreciation_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assets_accumulated_depreciation", to="accounting.ledgeraccount")),
                ("acquisition_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="capitalized_assets", to="accounting.journalentry")),
                ("asset_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assets_capitalized", to="accounting.ledgeraccount")),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assets", to="assets.assetcategory")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assets_created", to=settings.AUTH_USER_MODEL)),
                ("custodian", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_assets", to="accounts.agent")),
                ("depreciation_expense_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assets_depreciation_expense", to="accounting.ledgeraccount")),
                ("funding_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assets_funding_source", to="accounting.ledgeraccount")),
                ("maintenance_expense_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assets_maintenance_expense", to="accounting.ledgeraccount")),
                ("vendor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assets_supplied", to="accounting.counterparty")),
            ],
            options={"ordering": ["asset_code", "name"]},
        ),
        migrations.CreateModel(
            name="AssetDisposal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("disposal_date", models.DateField(default=django.utils.timezone.localdate)),
                ("disposal_type", models.CharField(choices=[("SALE", "Sale"), ("WRITE_OFF", "Write Off"), ("DONATION", "Donation"), ("LOSS", "Loss / Theft"), ("TRADE_IN", "Trade-In")], default="SALE", max_length=20)),
                ("proceeds", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("selling_cost", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("asset", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="disposal", to="assets.assetitem")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_disposals_created", to=settings.AUTH_USER_MODEL)),
                ("gain_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asset_disposal_gains", to="accounting.ledgeraccount")),
                ("loss_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asset_disposal_losses", to="accounting.ledgeraccount")),
                ("posted_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_disposals", to="accounting.journalentry")),
                ("settlement_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asset_disposal_settlements", to="accounting.ledgeraccount")),
            ],
            options={"ordering": ["-disposal_date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="AssetAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assigned_date", models.DateField(default=django.utils.timezone.localdate)),
                ("returned_date", models.DateField(blank=True, null=True)),
                ("location", models.CharField(blank=True, max_length=160)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="assets.assetitem")),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_assignments", to="accounts.agent")),
            ],
            options={"ordering": ["-assigned_date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="AssetMaintenance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("maintenance_type", models.CharField(choices=[("PREVENTIVE", "Preventive"), ("CORRECTIVE", "Corrective"), ("REPAIR", "Repair"), ("SERVICE", "Service"), ("UPGRADE", "Upgrade"), ("INSPECTION", "Inspection")], default="PREVENTIVE", max_length=20)),
                ("status", models.CharField(choices=[("SCHEDULED", "Scheduled"), ("IN_PROGRESS", "In Progress"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")], default="SCHEDULED", max_length=20)),
                ("requested_on", models.DateField(default=django.utils.timezone.localdate)),
                ("scheduled_for", models.DateField(blank=True, null=True)),
                ("completed_on", models.DateField(blank=True, null=True)),
                ("estimated_cost", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("actual_cost", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("description", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="maintenance_records", to="assets.assetitem")),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_maintenance_assignments", to="accounts.agent")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_maintenance_created", to=settings.AUTH_USER_MODEL)),
                ("expense_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asset_maintenance_expense_entries", to="accounting.ledgeraccount")),
                ("posted_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_maintenance_entries", to="accounting.journalentry")),
                ("settlement_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asset_maintenance_settlements", to="accounting.ledgeraccount")),
                ("vendor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_maintenance_jobs", to="accounting.counterparty")),
            ],
            options={"ordering": ["-requested_on", "-created_at"]},
        ),
        migrations.CreateModel(
            name="DepreciationLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("opening_cost", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("opening_accumulated_depreciation", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("depreciation_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("closing_accumulated_depreciation", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("closing_book_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="depreciation_lines", to="assets.assetitem")),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="assets.depreciationrun")),
            ],
            options={"ordering": ["asset__asset_code"], "unique_together": {("run", "asset")}},
        ),
    ]
