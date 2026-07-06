from django.conf import settings
from django.db import models



APPROVAL_STATUS_CHOICES = [
    ("PENDING", "Pending"),
    ("EXECUTED", "Executed"),
    ("REJECTED", "Rejected"),
    ("FAILED", "Failed"),
    ("CANCELLED", "Cancelled"),
]

APPROVAL_WORKFLOW_CHOICES = [
    ("LOAN_CREATION", "Loan Creation"),
    ("PAYROLL_RUN_APPROVAL", "Payroll Run Approval"),
    ("ACCOUNTING_JOURNAL", "Accounting Journal"),
    ("ASSET_DISPOSAL", "Asset Disposal"),
]

AUDIT_CATEGORY_CHOICES = [
    ("APPROVAL", "Approval"),
    ("LOAN", "Loan"),
    ("PAYROLL", "Payroll"),
    ("ACCOUNTING", "Accounting"),
    ("ASSET", "Asset"),
    ("IMPORT", "Import"),
    ("SYSTEM", "System"),
]


class ApprovalRequest(models.Model):
    workflow_type = models.CharField(max_length=40, choices=APPROVAL_WORKFLOW_CHOICES)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=APPROVAL_STATUS_CHOICES, default="PENDING")
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests_submitted",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests_reviewed",
    )
    source_path = models.CharField(max_length=255, blank=True)
    target_reference = models.CharField(max_length=180, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    review_note = models.TextField(blank=True)
    result_message = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at", "-created_at"]

    def __str__(self):
        return f"{self.get_workflow_type_display()} - {self.title}"


class ActivityLog(models.Model):
    category = models.CharField(max_length=20, choices=AUDIT_CATEGORY_CHOICES, default="SYSTEM")
    action = models.CharField(max_length=100)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=80, blank=True)
    object_label = models.CharField(max_length=180, blank=True)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.category} - {self.action} - {self.object_label or self.object_type}"
