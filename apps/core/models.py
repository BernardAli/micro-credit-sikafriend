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
    ("SECURITY_DEPOSIT", "Security Deposit Control"),
    ("TRANSACTION_REVERSAL", "Transaction Reversal"),
]

AUDIT_CATEGORY_CHOICES = [
    ("APPROVAL", "Approval"),
    ("LOAN", "Loan"),
    ("PAYROLL", "Payroll"),
    ("ACCOUNTING", "Accounting"),
    ("ASSET", "Asset"),
    ("SECURITY_DEPOSIT", "Security Deposit"),
    ("IMPORT", "Import"),
    ("SYSTEM", "System"),
    ("REVERSAL", "Transaction Reversal"),
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


REVERSAL_SOURCE_CHOICES = [
    ("PAYMENT", "Loan repayment"),
    ("DEPOSIT", "Security deposit transaction"),
    ("TRANSFER", "Deposit carry-forward"),
    ("BANK", "Cashbook / bank transaction"),
    ("INVOICE", "Unsettled sales invoice"),
    ("BILL", "Unsettled supplier bill"),
    ("PAYROLL", "Paid payroll run"),
    ("JOURNAL", "Manual journal"),
    ("DEPRECIATION", "Asset depreciation run"),
]


class TransactionReversal(models.Model):
    """Permanent evidence of a completed, approved correction; never a cash refund."""
    approval = models.OneToOneField(ApprovalRequest, on_delete=models.PROTECT, related_name="reversal")
    source_kind = models.CharField(max_length=20, choices=REVERSAL_SOURCE_CHOICES)
    source_id = models.PositiveBigIntegerField()
    source_label = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    reason = models.TextField()
    evidence_reference = models.CharField(max_length=180, blank=True)
    original_snapshot = models.JSONField()
    effective_date = models.DateField()
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transaction_reversals_approved")
    journal_entries = models.ManyToManyField("accounting.JournalEntry", related_name="approved_reversals", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["source_kind", "source_id"], name="unique_completed_transaction_reversal")]

    @property
    def reference(self):
        return f"REV-{self.pk:06d}"

    def __str__(self):
        return f"{self.reference} · {self.source_label}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            from django.core.exceptions import ValidationError
            raise ValidationError("Completed reversal evidence cannot be changed.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Completed reversal evidence cannot be deleted.")


class ReversibleTransaction(models.Model):
    reversal = models.OneToOneField(TransactionReversal, null=True, blank=True, editable=False,
        on_delete=models.PROTECT, related_name="%(app_label)s_%(class)s")

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk, reversal__isnull=False).exists():
            from django.core.exceptions import ValidationError
            raise ValidationError("Reversed transaction evidence is read-only. Record a new transaction for any correction.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.reversal_id or getattr(self, "posted_entry_id", None) or getattr(self, "accounting_entry_id", None):
            from django.core.exceptions import ValidationError
            raise ValidationError("Financial evidence cannot be deleted. Request an approved transaction reversal.")
        return super().delete(*args, **kwargs)
