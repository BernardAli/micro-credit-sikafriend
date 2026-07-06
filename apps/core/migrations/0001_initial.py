from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ActivityLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("APPROVAL", "Approval"), ("LOAN", "Loan"), ("PAYROLL", "Payroll"), ("ACCOUNTING", "Accounting"), ("ASSET", "Asset"), ("IMPORT", "Import"), ("SYSTEM", "System")], default="SYSTEM", max_length=20)),
                ("action", models.CharField(max_length=100)),
                ("object_type", models.CharField(blank=True, max_length=80)),
                ("object_id", models.CharField(blank=True, max_length=80)),
                ("object_label", models.CharField(blank=True, max_length=180)),
                ("message", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activity_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ApprovalRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("workflow_type", models.CharField(choices=[("LOAN_CREATION", "Loan Creation"), ("PAYROLL_RUN_APPROVAL", "Payroll Run Approval"), ("ACCOUNTING_JOURNAL", "Accounting Journal"), ("ASSET_DISPOSAL", "Asset Disposal")], max_length=40)),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("EXECUTED", "Executed"), ("REJECTED", "Rejected"), ("FAILED", "Failed"), ("CANCELLED", "Cancelled")], default="PENDING", max_length=12)),
                ("source_path", models.CharField(blank=True, max_length=255)),
                ("target_reference", models.CharField(blank=True, max_length=180)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("review_note", models.TextField(blank=True)),
                ("result_message", models.TextField(blank=True)),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approval_requests_reviewed", to=settings.AUTH_USER_MODEL)),
                ("submitted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approval_requests_submitted", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-submitted_at", "-created_at"]},
        ),
    ]
