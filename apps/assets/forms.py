from django import forms

from apps.accounts.models import Agent
from apps.accounting.models import Counterparty, LedgerAccount

from .models import (
    AssetAssignment,
    AssetCategory,
    AssetDisposal,
    AssetItem,
    AssetMaintenance,
    DepreciationRun,
)


class DateInput(forms.DateInput):
    input_type = "date"


class AssetCategoryForm(forms.ModelForm):
    class Meta:
        model = AssetCategory
        fields = [
            "code",
            "name",
            "description",
            "default_useful_life_months",
            "default_residual_value_rate",
            "default_depreciation_method",
            "asset_account",
            "accumulated_depreciation_account",
            "depreciation_expense_account",
            "maintenance_expense_account",
            "default_funding_account",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset_account"].queryset = LedgerAccount.objects.filter(account_type="ASSET", is_active=True).order_by("code")
        self.fields["accumulated_depreciation_account"].queryset = LedgerAccount.objects.filter(account_type="ASSET", is_active=True).order_by("code")
        self.fields["depreciation_expense_account"].queryset = LedgerAccount.objects.filter(account_type="EXPENSE", is_active=True).order_by("code")
        self.fields["maintenance_expense_account"].queryset = LedgerAccount.objects.filter(account_type="EXPENSE", is_active=True).order_by("code")
        self.fields["default_funding_account"].queryset = LedgerAccount.objects.filter(is_active=True).order_by("code")


class AssetItemForm(forms.ModelForm):
    post_acquisition = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Post the acquisition into accounting immediately after saving.",
    )

    class Meta:
        model = AssetItem
        fields = [
            "asset_code",
            "name",
            "category",
            "status",
            "condition",
            "serial_number",
            "manufacturer",
            "model_name",
            "location",
            "branch_name",
            "custodian",
            "vendor",
            "acquisition_date",
            "in_service_date",
            "warranty_expiry",
            "purchase_cost",
            "residual_value",
            "useful_life_months",
            "depreciation_method",
            "asset_account",
            "accumulated_depreciation_account",
            "depreciation_expense_account",
            "maintenance_expense_account",
            "funding_account",
            "notes",
        ]
        widgets = {
            "acquisition_date": DateInput(),
            "in_service_date": DateInput(),
            "warranty_expiry": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = AssetCategory.objects.order_by("name")
        self.fields["custodian"].queryset = Agent.objects.order_by("name")
        self.fields["vendor"].queryset = Counterparty.objects.filter(is_active=True).order_by("name")
        asset_accounts = LedgerAccount.objects.filter(account_type="ASSET", is_active=True).order_by("code")
        expense_accounts = LedgerAccount.objects.filter(account_type="EXPENSE", is_active=True).order_by("code")
        all_accounts = LedgerAccount.objects.filter(is_active=True).order_by("code")
        self.fields["asset_account"].queryset = asset_accounts
        self.fields["accumulated_depreciation_account"].queryset = asset_accounts
        self.fields["depreciation_expense_account"].queryset = expense_accounts
        self.fields["maintenance_expense_account"].queryset = expense_accounts
        self.fields["funding_account"].queryset = all_accounts

        if not self.instance.pk and self.initial.get("category"):
            self._seed_from_category(self.initial["category"])

        category_field = self.data.get(self.add_prefix("category")) or getattr(self.instance, "category_id", None)
        if category_field and not self.instance.pk:
            try:
                category = AssetCategory.objects.get(pk=category_field)
                self._seed_from_category(category)
            except (AssetCategory.DoesNotExist, ValueError, TypeError):
                pass

    def _seed_from_category(self, category):
        if isinstance(category, AssetCategory):
            self.fields["asset_account"].initial = category.asset_account_id
            self.fields["accumulated_depreciation_account"].initial = category.accumulated_depreciation_account_id
            self.fields["depreciation_expense_account"].initial = category.depreciation_expense_account_id
            self.fields["maintenance_expense_account"].initial = category.maintenance_expense_account_id
            self.fields["funding_account"].initial = category.default_funding_account_id
            self.fields["useful_life_months"].initial = category.default_useful_life_months
            self.fields["depreciation_method"].initial = category.default_depreciation_method

    def clean(self):
        cleaned = super().clean()
        purchase_cost = cleaned.get("purchase_cost")
        residual_value = cleaned.get("residual_value") or 0
        if purchase_cost is not None and residual_value > purchase_cost:
            self.add_error("residual_value", "Residual value cannot exceed acquisition cost.")
        return cleaned


class AssetAssignmentForm(forms.ModelForm):
    class Meta:
        model = AssetAssignment
        fields = ["asset", "assigned_to", "assigned_date", "returned_date", "location", "notes"]
        widgets = {
            "assigned_date": DateInput(),
            "returned_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = AssetItem.objects.exclude(status__in=["DISPOSED", "WRITTEN_OFF"]).order_by("asset_code")
        self.fields["assigned_to"].queryset = Agent.objects.order_by("name")


class AssetMaintenanceForm(forms.ModelForm):
    post_maintenance = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Post completed maintenance cost to accounting immediately.",
    )

    class Meta:
        model = AssetMaintenance
        fields = [
            "asset",
            "maintenance_type",
            "status",
            "requested_on",
            "scheduled_for",
            "completed_on",
            "assigned_to",
            "vendor",
            "estimated_cost",
            "actual_cost",
            "expense_account",
            "settlement_account",
            "description",
            "notes",
        ]
        widgets = {
            "requested_on": DateInput(),
            "scheduled_for": DateInput(),
            "completed_on": DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = AssetItem.objects.exclude(status__in=["DISPOSED", "WRITTEN_OFF"]).order_by("asset_code")
        self.fields["assigned_to"].queryset = Agent.objects.order_by("name")
        self.fields["vendor"].queryset = Counterparty.objects.filter(is_active=True).order_by("name")
        self.fields["expense_account"].queryset = LedgerAccount.objects.filter(account_type="EXPENSE", is_active=True).order_by("code")
        self.fields["settlement_account"].queryset = LedgerAccount.objects.filter(is_active=True).order_by("code")


class DepreciationRunForm(forms.ModelForm):
    class Meta:
        model = DepreciationRun
        fields = ["title", "period_start", "period_end", "posting_date", "notes"]
        widgets = {
            "period_start": DateInput(),
            "period_end": DateInput(),
            "posting_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("period_start")
        end = cleaned.get("period_end")
        if start and end and start > end:
            self.add_error("period_end", "Period end must be on or after the period start.")
        return cleaned


class AssetDisposalForm(forms.ModelForm):
    class Meta:
        model = AssetDisposal
        fields = [
            "asset",
            "disposal_date",
            "disposal_type",
            "proceeds",
            "selling_cost",
            "settlement_account",
            "gain_account",
            "loss_account",
            "notes",
        ]
        widgets = {
            "disposal_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = AssetItem.objects.exclude(status__in=["DISPOSED", "WRITTEN_OFF"]).order_by("asset_code")
        asset_accounts = LedgerAccount.objects.filter(is_active=True).order_by("code")
        self.fields["settlement_account"].queryset = asset_accounts
        self.fields["gain_account"].queryset = LedgerAccount.objects.filter(account_type="INCOME", is_active=True).order_by("code")
        self.fields["loss_account"].queryset = LedgerAccount.objects.filter(account_type="EXPENSE", is_active=True).order_by("code")


class AssetBulkImportForm(forms.Form):
    FILE_TYPE_CHOICES = [
        ("auto", "Auto-detect from file name"),
        ("csv", "CSV (.csv)"),
        ("excel", "Excel (.xlsx)"),
        ("json", "JSON (.json)"),
        ("xml", "XML (.xml)"),
    ]

    IMPORT_MODE_CHOICES = [
        ("create_only", "Create new assets only"),
        ("upsert", "Create new assets or update matching asset codes"),
    ]

    data_file = forms.FileField(
        label="Asset import file",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".csv,.xlsx,.json,.xml",
            }
        ),
    )
    file_type = forms.ChoiceField(
        choices=FILE_TYPE_CHOICES,
        initial="auto",
        help_text="Choose a format explicitly or let the system infer it from the uploaded file name.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    import_mode = forms.ChoiceField(
        choices=IMPORT_MODE_CHOICES,
        initial="create_only",
        help_text="Use update mode when matching asset codes should be refreshed instead of rejected.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    post_acquisitions = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Automatically post acquisition journals for imported assets that do not already have one.",
    )
