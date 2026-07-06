from django.contrib import admin

from .models import ActivityLog, ApprovalRequest


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "workflow_type", "status", "submitted_by", "reviewed_by", "submitted_at", "reviewed_at")
    list_filter = ("workflow_type", "status", "submitted_at", "reviewed_at")
    search_fields = ("title", "description", "target_reference", "review_note", "result_message")
    readonly_fields = ("submitted_at", "reviewed_at", "created_at", "updated_at")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "category", "action", "actor", "object_type", "object_label")
    list_filter = ("category", "action", "created_at")
    search_fields = ("message", "object_label", "object_type", "object_id")
    readonly_fields = ("created_at",)
