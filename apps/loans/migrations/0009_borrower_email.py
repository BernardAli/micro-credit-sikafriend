from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0008_borrower_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="borrower",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
