from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0011_alter_payment_payment_method_repaymentcollection"),
    ]

    operations = [
        migrations.AddField(
            model_name="borrower",
            name="alternative_phone",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="borrower",
            name="borrower_type",
            field=models.CharField(choices=[("NEW", "New Borrower"), ("EXISTING", "Existing Borrower (New Loan)")], default="NEW", max_length=12),
        ),
        migrations.AddField(
            model_name="borrower",
            name="date_of_birth",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="borrower",
            name="digital_address",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="borrower",
            name="gender",
            field=models.CharField(blank=True, choices=[("MALE", "Male"), ("FEMALE", "Female")], max_length=10),
        ),
        migrations.AddField(
            model_name="borrower",
            name="nearest_landmark",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="borrower",
            name="residence_directions",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="borrower",
            name="residence_status",
            field=models.CharField(blank=True, choices=[("OWNED", "Owned"), ("RENTED", "Rented"), ("FAMILY_HOUSE", "Family House"), ("OTHER", "Other")], max_length=20),
        ),
        migrations.AddField(
            model_name="borrower",
            name="residence_status_other",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="borrower",
            name="years_at_residence",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="loan",
            name="application_received_by",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="loan",
            name="application_received_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="approval_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="approval_manager_signature_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="loan",
            name="approved_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="approved_repayment_plan",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="loan",
            name="borrower_declaration_accepted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="loan",
            name="borrower_signed_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="borrower_signature_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="loan",
            name="collateral_borrower_consent_accepted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="loan",
            name="collateral_borrower_signed_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="collateral_details",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="loan",
            name="collateral_estimated_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="collateral_guarantor_signature_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="loan",
            name="collateral_guarantor_signed_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="collateral_location",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name="loan",
            name="collateral_type",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="loan",
            name="duration_months",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="loan",
            name="duration_weeks",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="loan",
            name="guarantor_id_number",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="loan",
            name="guarantor_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="loan",
            name="guarantor_signature_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="loan",
            name="guarantor_signed_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="loan_acquisition_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loan",
            name="loan_officer_signature_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="loan",
            name="repayment_frequency",
            field=models.CharField(choices=[("DAILY", "Daily"), ("WEEKLY", "Weekly")], default="WEEKLY", max_length=10),
        ),
        migrations.AddField(
            model_name="loan",
            name="sector",
            field=models.CharField(blank=True, choices=[("AGRIC_FISHING_FORESTRY", "Agric / Fishing / Forestry"), ("EDUCATION", "Education"), ("SERVICES", "Services"), ("MANUFACTURING_AGRO_PROCESSING", "Manufacturing / Agro-processing"), ("RELIGIOUS_ENTERPRISE", "Church / Religious Enterprise"), ("CONSTRUCTION", "Construction"), ("COMMERCE_TRADING", "Commerce / Trading"), ("TRANSPORT_COMMUNICATION", "Transport / Communication"), ("HOUSEHOLD_CONSUMPTION", "Household Consumption"), ("MORTGAGE_HOUSING_HOME_IMPROVEMENT", "Mortgage / Housing / Home Improvement"), ("OTHER", "Other")], max_length=50),
        ),
        migrations.AddField(
            model_name="loan",
            name="sector_other",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
