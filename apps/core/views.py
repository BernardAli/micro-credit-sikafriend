from django.contrib import messages
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.approvals import approve_and_execute_request, reject_approval_request
from apps.core.roles import admin_required

from .models import ActivityLog, ApprovalRequest


@admin_required
def approval_hub(request):
    status_filter = (request.GET.get("status") or "").strip().upper()
    workflow_filter = (request.GET.get("workflow") or "").strip().upper()

    approvals = ApprovalRequest.objects.select_related("submitted_by", "reviewed_by").order_by("-submitted_at")
    if status_filter:
        approvals = approvals.filter(status=status_filter)
    if workflow_filter:
        approvals = approvals.filter(workflow_type=workflow_filter)

    if request.method == "POST":
        approval = get_object_or_404(ApprovalRequest, pk=request.POST.get("approval_id"))
        action = request.POST.get("action")
        note = (request.POST.get("note") or "").strip()
        try:
            if action == "approve":
                approve_and_execute_request(approval, request.user, note=note, request=request)
                messages.success(request, f"Approval request '{approval.title}' executed successfully.")
            elif action == "reject":
                reject_approval_request(approval, request.user, note=note, request=request)
                messages.success(request, f"Approval request '{approval.title}' rejected.")
        except Exception as exc:
            messages.error(request, f"Approval action failed: {exc}")
        return redirect("core:approvals")

    pending_count = ApprovalRequest.objects.filter(status="PENDING").count()
    failed_count = ApprovalRequest.objects.filter(status="FAILED").count()
    recent_logs = ActivityLog.objects.select_related("actor").filter(category="APPROVAL")[:10]
    context = {
        "title": "Approval Controls",
        "approvals": approvals[:100],
        "pending_count": pending_count,
        "failed_count": failed_count,
        "executed_count": ApprovalRequest.objects.filter(status="EXECUTED").count(),
        "rejected_count": ApprovalRequest.objects.filter(status="REJECTED").count(),
        "recent_logs": recent_logs,
        "status_filter": status_filter,
        "workflow_filter": workflow_filter,
        "workflow_choices": ApprovalRequest._meta.get_field("workflow_type").choices,
        "status_choices": ApprovalRequest._meta.get_field("status").choices,
    }
    return render(request, "core/approvals.html", context)


@admin_required
def audit_trail(request):
    q = (request.GET.get("q") or "").strip()
    category_filter = (request.GET.get("category") or "").strip().upper()

    logs = ActivityLog.objects.select_related("actor").order_by("-created_at")
    if q:
        logs = logs.filter(
            models.Q(message__icontains=q)
            | models.Q(object_label__icontains=q)
            | models.Q(object_type__icontains=q)
            | models.Q(action__icontains=q)
        )
    if category_filter:
        logs = logs.filter(category=category_filter)

    context = {
        "title": "Audit Trail",
        "logs": logs[:200],
        "q": q,
        "category_filter": category_filter,
        "category_choices": ActivityLog._meta.get_field("category").choices,
        "total_logs": ActivityLog.objects.count(),
        "approval_logs": ActivityLog.objects.filter(category="APPROVAL").count(),
        "loan_logs": ActivityLog.objects.filter(category="LOAN").count(),
        "accounting_logs": ActivityLog.objects.filter(category="ACCOUNTING").count(),
        "asset_logs": ActivityLog.objects.filter(category="ASSET").count(),
    }
    return render(request, "core/audit_trail.html", context)
