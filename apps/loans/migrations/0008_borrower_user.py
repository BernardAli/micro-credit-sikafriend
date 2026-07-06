import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0007_loan_loan_category"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="borrower",
            name="user",
            field=models.OneToOneField(
                blank=True,
                help_text="Login account for this borrower.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="borrower_profile",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
