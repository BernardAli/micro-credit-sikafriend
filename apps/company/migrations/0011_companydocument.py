from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0010_companyprofile_tenant_channel_integrations"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("file", models.FileField(upload_to="company/documents/")),
                ("is_public", models.BooleanField(default=True, help_text="Show this document on the public website downloads page.")),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["sort_order", "title", "id"],
            },
        ),
    ]
