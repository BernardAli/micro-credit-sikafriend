from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_agent_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="agent",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
