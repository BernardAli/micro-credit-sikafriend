import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CompanyProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company_name", models.CharField(default="SikaFriend", help_text="Your business / brand name.", max_length=120)),
                ("tagline", models.CharField(blank=True, default="Micro-Credit Enterprise", help_text="Short tagline shown below the brand name.", max_length=180)),
                ("description", models.TextField(blank=True, default="Premium operations environment for portfolio monitoring, borrower management, recovery tracking, and field execution.", help_text="One-paragraph description used on the dashboard hero.")),
                ("logo", models.ImageField(blank=True, help_text="Optional logo image (shown in topbar).", upload_to="company/logos/")),
                ("favicon", models.ImageField(blank=True, help_text="Optional favicon (.ico / .png, 32x32 recommended).", upload_to="company/favicons/")),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("website", models.URLField(blank=True)),
                ("currency_code", models.CharField(choices=[("GHS", "Ghana Cedi (GHS \u20b5)"), ("NGN", "Nigerian Naira (NGN \u20a6)"), ("KES", "Kenyan Shilling (KES)"), ("UGX", "Ugandan Shilling (UGX)"), ("ZAR", "South African Rand (ZAR R)"), ("XOF", "West African CFA (XOF)"), ("USD", "US Dollar (USD $)"), ("GBP", "British Pound (GBP \u00a3)"), ("EUR", "Euro (EUR \u20ac)"), ("TZS", "Tanzanian Shilling (TZS)"), ("RWF", "Rwandan Franc (RWF)"), ("ETB", "Ethiopian Birr (ETB)"), ("ZMW", "Zambian Kwacha (ZMW)"), ("MWK", "Malawian Kwacha (MWK)"), ("SLL", "Sierra Leonean Leone (SLL)")], default="GHS", help_text="Currency used across all monetary displays.", max_length=6)),
                ("currency_symbol", models.CharField(default="GHS", help_text="Symbol or prefix shown on amounts, e.g. '\u20b5', 'GHS', '$'.", max_length=6)),
                ("country", models.CharField(blank=True, default="Ghana", max_length=80)),
                ("timezone_name", models.CharField(blank=True, default="Africa/Accra", help_text="Django timezone string, e.g. 'Africa/Accra'.", max_length=60)),
                ("repayment_cycle", models.CharField(choices=[("weekly", "Weekly"), ("biweekly", "Bi-Weekly"), ("monthly", "Monthly")], default="weekly", help_text="Default repayment cadence for new loans.", max_length=12)),
                ("default_loan_duration", models.PositiveIntegerField(default=12, help_text="Default number of repayment periods for new loans.", validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(520)])),
                ("overdue_grace_periods", models.PositiveIntegerField(default=6, help_text="Number of missed repayment periods before a loan is marked DEFAULT and the borrower flagged as BAD.", validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(52)])),
                ("loan_tiers", models.JSONField(blank=True, default=list, help_text='JSON array of tier objects: [{"code":"BRONZE","label":"Bronze","min":0,"max":3000}, ...]')),
                ("borrower_languages", models.JSONField(blank=True, default=list, help_text='JSON array of language strings available on borrower records, e.g. ["Twi","Ewe","Ga","Hausa"]')),
                ("color_theme", models.CharField(choices=[("forest", "Forest Green & Gold  (default)"), ("ocean", "Ocean Blue & Silver"), ("royal", "Royal Purple & Amber"), ("ember", "Ember Red & Copper"), ("slate", "Slate Grey & Teal"), ("midnight", "Midnight Black & Gold")], default="forest", help_text="Pre-built colour theme applied across the interface.", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Company Profile",
                "verbose_name_plural": "Company Profile",
            },
        ),
    ]
