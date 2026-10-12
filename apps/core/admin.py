from django.contrib import admin

from .models import ActivityLog, ApprovalRequest, TransactionReversal
from .financial_admin import FinancialEvidenceAdmin


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(FinancialEvidenceAdmin):
    list_display = ("title", "workflow_type", "status", "submitted_by", "reviewed_by", "submitted_at", "reviewed_at")
    list_filter = ("workflow_type", "status", "submitted_at", "reviewed_at")
    search_fields = ("title", "description", "target_reference", "review_note", "result_message")
    readonly_fields = ("submitted_at", "reviewed_at", "created_at", "updated_at")


@admin.register(ActivityLog)
class ActivityLogAdmin(FinancialEvidenceAdmin):
    list_display = ("created_at", "category", "action", "actor", "object_type", "object_label")
    list_filter = ("category", "action", "created_at")
    search_fields = ("message", "object_label", "object_type", "object_id")
    readonly_fields = ("created_at",)


@admin.register(TransactionReversal)
class TransactionReversalAdmin(FinancialEvidenceAdmin):
    list_display = ("reference", "source_label", "source_kind", "amount", "effective_date", "approved_by")
    list_filter = ("source_kind", "effective_date")
    search_fields = ("source_label", "reason", "evidence_reference")
