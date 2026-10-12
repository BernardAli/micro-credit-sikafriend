from django.contrib import admin
from apps.core.financial_admin import FinancialEvidenceAdmin, FinancialEvidenceInline

from .models import (
    AssetAssignment,
    AssetCategory,
    AssetDisposal,
    AssetItem,
    AssetMaintenance,
    DepreciationLine,
    DepreciationRun,
)


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "default_useful_life_months", "default_depreciation_method")
    search_fields = ("code", "name")


class AssetAssignmentInline(admin.TabularInline):
    model = AssetAssignment
    extra = 0


class AssetMaintenanceInline(admin.TabularInline):
    model = AssetMaintenance
    extra = 0


@admin.register(AssetItem)
class AssetItemAdmin(admin.ModelAdmin):
    list_display = ("asset_code", "name", "category", "status", "location", "purchase_cost", "net_book_value")
    list_filter = ("status", "category", "depreciation_method", "condition")
    search_fields = ("asset_code", "name", "serial_number", "location")
    inlines = [AssetAssignmentInline, AssetMaintenanceInline]


@admin.register(AssetMaintenance)
class AssetMaintenanceAdmin(admin.ModelAdmin):
    list_display = ("asset", "maintenance_type", "status", "requested_on", "scheduled_for", "actual_cost")
    list_filter = ("maintenance_type", "status")
    search_fields = ("asset__asset_code", "asset__name", "description")


class DepreciationLineInline(FinancialEvidenceInline):
    model = DepreciationLine
    extra = 0


@admin.register(DepreciationRun)
class DepreciationRunAdmin(FinancialEvidenceAdmin):
    list_display = ("title", "period_start", "period_end", "posting_date", "status", "total_depreciation")
    list_filter = ("status", "posting_date")
    search_fields = ("title",)
    inlines = [DepreciationLineInline]


@admin.register(AssetDisposal)
class AssetDisposalAdmin(admin.ModelAdmin):
    list_display = ("asset", "disposal_date", "disposal_type", "proceeds", "selling_cost")
    list_filter = ("disposal_type", "disposal_date")
    search_fields = ("asset__asset_code", "asset__name")
