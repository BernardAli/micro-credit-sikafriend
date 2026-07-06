from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0009_merge_20260523_0001"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_email_from_address",
            field=models.EmailField(
                blank=True,
                help_text="Tenant-specific sender address for operational emails. Falls back to the platform default when blank.",
                max_length=254,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_email_host",
            field=models.CharField(
                blank=True,
                help_text="SMTP host for this tenant's outbound email.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_email_host_password",
            field=models.CharField(
                blank=True,
                help_text="SMTP password or API secret for this tenant's outbound email.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_email_host_user",
            field=models.CharField(
                blank=True,
                help_text="SMTP username for this tenant's outbound email.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_email_port",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="SMTP port for this tenant's outbound email.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_email_use_ssl",
            field=models.BooleanField(
                blank=True,
                help_text="Use SSL for this tenant's outbound email. Leave blank to inherit the platform default.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_email_use_tls",
            field=models.BooleanField(
                blank=True,
                help_text="Use TLS for this tenant's outbound email. Leave blank to inherit the platform default.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_sms_api_key",
            field=models.CharField(
                blank=True,
                help_text="Tenant-specific SMS API key.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_sms_base_url",
            field=models.URLField(
                blank=True,
                help_text="Tenant-specific SMS API base URL.",
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_sms_provider",
            field=models.CharField(
                blank=True,
                default="",
                help_text="SMS provider for this tenant. Arkesel is currently supported in-app.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_sms_sender_id",
            field=models.CharField(
                blank=True,
                help_text="Tenant-specific SMS sender ID.",
                max_length=60,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_ussd_api_key",
            field=models.CharField(
                blank=True,
                help_text="Tenant-specific USSD API key.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_ussd_callback_token",
            field=models.CharField(
                blank=True,
                help_text="Optional token used to validate inbound USSD callbacks for this tenant.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_ussd_provider",
            field=models.CharField(
                blank=True,
                default="",
                help_text="USSD provider for this tenant, e.g. Hubtel or Arkesel.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_ussd_shortcode",
            field=models.CharField(
                blank=True,
                help_text="Tenant-specific USSD shortcode or service code.",
                max_length=60,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="tenant_ussd_username",
            field=models.CharField(
                blank=True,
                help_text="Tenant-specific USSD account username or client ID.",
                max_length=120,
            ),
        ),
    ]
