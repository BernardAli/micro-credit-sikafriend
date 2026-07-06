from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Agent
from apps.accounting.models import Counterparty, JournalEntry, LedgerAccount


ASSET_STATUS_CHOICES = [
    ("DRAFT", "Draft"),
    ("ACTIVE", "Active"),
    ("IN_MAINTENANCE", "In Maintenance"),
    ("DISPOSED", "Disposed"),
    ("WRITTEN_OFF", "Written Off"),
]

ASSET_CONDITION_CHOICES = [
    ("EXCELLENT", "Excellent"),
    ("GOOD", "Good"),
    ("FAIR", "Fair"),
    ("POOR", "Poor"),
    ("CRITICAL", "Critical"),
]

DEPRECIATION_METHOD_CHOICES = [
    ("STRAIGHT_LINE", "Straight Line"),
    ("REDUCING_BALANCE", "Reducing Balance"),
]

MAINTENANCE_TYPE_CHOICES = [
    ("PREVENTIVE", "Preventive"),
    ("CORRECTIVE", "Corrective"),
    ("REPAIR", "Repair"),
    ("SERVICE", "Service"),
    ("UPGRADE", "Upgrade"),
    ("INSPECTION", "Inspection"),
]

MAINTENANCE_STATUS_CHOICES = [
    ("SCHEDULED", "Scheduled"),
    ("IN_PROGRESS", "In Progress"),
    ("COMPLETED", "Completed"),
    ("CANCELLED", "Cancelled"),
]

DEPRECIATION_RUN_STATUS_CHOICES = [
    ("DRAFT", "Draft"),
    ("POSTED", "Posted"),
    ("CANCELLED", "Cancelled"),
]

DISPOSAL_TYPE_CHOICES = [
    ("SALE", "Sale"),
    ("WRITE_OFF", "Write Off"),
    ("DONATION", "Donation"),
    ("LOSS", "Loss / Theft"),
    ("TRADE_IN", "Trade-In"),
]


def _money(value):
    return Decimal(value or Decimal("0.00")).quantize(Decimal("0.01"))


def _months_between(start_date, end_date):
    if not start_date or not end_date or end_date < start_date:
        return 0
    return ((end_date.year - start_date.year) * 12) + (end_date.month - start_date.month) + 1


class AssetCategory(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    default_useful_life_months = models.PositiveIntegerField(default=36)
    default_residual_value_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Residual value as a percentage of acquisition cost.",
    )
    default_depreciation_method = models.CharField(
        max_length=20,
        choices=DEPRECIATION_METHOD_CHOICES,
        default="STRAIGHT_LINE",
    )
    asset_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_categories_asset",
    )
    accumulated_depreciation_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_categories_accumulated",
    )
    depreciation_expense_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_categories_depreciation_expense",
    )
    maintenance_expense_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_categories_maintenance_expense",
    )
    default_funding_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_categories_funding",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class AssetItem(models.Model):
    asset_code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=180)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name="assets")
    status = models.CharField(max_length=20, choices=ASSET_STATUS_CHOICES, default="ACTIVE")
    condition = models.CharField(max_length=20, choices=ASSET_CONDITION_CHOICES, default="GOOD")
    serial_number = models.CharField(max_length=120, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    location = models.CharField(max_length=160, blank=True)
    branch_name = models.CharField(max_length=160, blank=True)
    custodian = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_assets",
    )
    vendor = models.ForeignKey(
        Counterparty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets_supplied",
    )
    acquisition_date = models.DateField(default=timezone.localdate)
    in_service_date = models.DateField(default=timezone.localdate)
    warranty_expiry = models.DateField(null=True, blank=True)
    purchase_cost = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    residual_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    useful_life_months = models.PositiveIntegerField(default=36)
    depreciation_method = models.CharField(max_length=20, choices=DEPRECIATION_METHOD_CHOICES, default="STRAIGHT_LINE")
    asset_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="assets_capitalized",
    )
    accumulated_depreciation_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="assets_accumulated_depreciation",
    )
    depreciation_expense_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="assets_depreciation_expense",
    )
    maintenance_expense_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="assets_maintenance_expense",
    )
    funding_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="assets_funding_source",
        null=True,
        blank=True,
    )
    acquisition_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="capitalized_assets",
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["asset_code", "name"]

    def save(self, *args, **kwargs):
        if not self.useful_life_months:
            self.useful_life_months = self.category.default_useful_life_months
        if self.residual_value is None:
            self.residual_value = Decimal("0.00")
        super().save(*args, **kwargs)

    @property
    def depreciable_base(self):
        return max(_money(self.purchase_cost) - _money(self.residual_value), Decimal("0.00")).quantize(Decimal("0.01"))

    def theoretical_accumulated_depreciation_as_of(self, as_of_date=None):
        as_of_date = as_of_date or timezone.localdate()
        if not self.in_service_date or as_of_date < self.in_service_date or self.useful_life_months <= 0:
            return Decimal("0.00")

        elapsed_months = min(self.useful_life_months, _months_between(self.in_service_date, as_of_date))
        base = self.depreciable_base
        if base <= 0:
            return Decimal("0.00")

        if self.depreciation_method == "STRAIGHT_LINE":
            monthly = (base / Decimal(self.useful_life_months)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return min(base, monthly * elapsed_months).quantize(Decimal("0.01"))

        carrying_value = _money(self.purchase_cost)
        accumulated = Decimal("0.00")
        monthly_rate = Decimal("2.00") / Decimal(self.useful_life_months)
        for _ in range(elapsed_months):
            depreciation = (carrying_value * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            max_allowed = max(carrying_value - _money(self.residual_value), Decimal("0.00"))
            depreciation = min(depreciation, max_allowed)
            accumulated += depreciation
            carrying_value -= depreciation
            if carrying_value <= _money(self.residual_value):
                break
        return min(base, _money(accumulated))

    @property
    def posted_accumulated_depreciation(self):
        total = self.depreciation_lines.filter(run__status="POSTED").aggregate(total=Sum("depreciation_amount"))["total"] or Decimal("0.00")
        return _money(total)

    @property
    def depreciation_due(self):
        return max(self.theoretical_accumulated_depreciation_as_of() - self.posted_accumulated_depreciation, Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def net_book_value(self):
        return max(_money(self.purchase_cost) - self.posted_accumulated_depreciation, _money(self.residual_value)).quantize(Decimal("0.01"))

    @property
    def total_maintenance_cost(self):
        total = self.maintenance_records.filter(status="COMPLETED").aggregate(total=Sum("actual_cost"))["total"] or Decimal("0.00")
        return _money(total)

    @property
    def is_under_warranty(self):
        return bool(self.warranty_expiry and self.warranty_expiry >= timezone.localdate())

    def __str__(self):
        return f"{self.asset_code} - {self.name}"


class AssetAssignment(models.Model):
    asset = models.ForeignKey(AssetItem, on_delete=models.CASCADE, related_name="assignments")
    assigned_to = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_assignments",
    )
    assigned_date = models.DateField(default=timezone.localdate)
    returned_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-assigned_date", "-created_at"]

    def __str__(self):
        return f"{self.asset.asset_code} assignment"


class AssetMaintenance(models.Model):
    asset = models.ForeignKey(AssetItem, on_delete=models.CASCADE, related_name="maintenance_records")
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPE_CHOICES, default="PREVENTIVE")
    status = models.CharField(max_length=20, choices=MAINTENANCE_STATUS_CHOICES, default="SCHEDULED")
    requested_on = models.DateField(default=timezone.localdate)
    scheduled_for = models.DateField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_maintenance_assignments",
    )
    vendor = models.ForeignKey(
        Counterparty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_maintenance_jobs",
    )
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    actual_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    expense_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_maintenance_expense_entries",
        null=True,
        blank=True,
    )
    settlement_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_maintenance_settlements",
        null=True,
        blank=True,
    )
    posted_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_maintenance_entries",
    )
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_maintenance_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-requested_on", "-created_at"]

    def __str__(self):
        return f"{self.asset.asset_code} maintenance"


class DepreciationRun(models.Model):
    title = models.CharField(max_length=160)
    period_start = models.DateField()
    period_end = models.DateField()
    posting_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=12, choices=DEPRECIATION_RUN_STATUS_CHOICES, default="POSTED")
    notes = models.TextField(blank=True)
    posted_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_depreciation_runs",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_depreciation_runs_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-posting_date", "-created_at"]

    @property
    def total_depreciation(self):
        total = self.lines.aggregate(total=Sum("depreciation_amount"))["total"] or Decimal("0.00")
        return _money(total)

    def __str__(self):
        return self.title


class DepreciationLine(models.Model):
    run = models.ForeignKey(DepreciationRun, on_delete=models.CASCADE, related_name="lines")
    asset = models.ForeignKey(AssetItem, on_delete=models.CASCADE, related_name="depreciation_lines")
    opening_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    opening_accumulated_depreciation = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    depreciation_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    closing_accumulated_depreciation = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    closing_book_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["asset__asset_code"]
        unique_together = ("run", "asset")

    def __str__(self):
        return f"{self.run.title} - {self.asset.asset_code}"


class AssetDisposal(models.Model):
    asset = models.OneToOneField(AssetItem, on_delete=models.CASCADE, related_name="disposal")
    disposal_date = models.DateField(default=timezone.localdate)
    disposal_type = models.CharField(max_length=20, choices=DISPOSAL_TYPE_CHOICES, default="SALE")
    proceeds = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    selling_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    settlement_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_disposal_settlements",
        null=True,
        blank=True,
    )
    gain_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_disposal_gains",
        null=True,
        blank=True,
    )
    loss_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="asset_disposal_losses",
        null=True,
        blank=True,
    )
    posted_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_disposals",
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_disposals_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-disposal_date", "-created_at"]

    def __str__(self):
        return f"{self.asset.asset_code} disposal"
