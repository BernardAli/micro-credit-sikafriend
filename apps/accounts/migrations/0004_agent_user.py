import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_agent_agent_id_agent_ghana_card_back_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="agent",
            name="user",
            field=models.OneToOneField(
                blank=True,
                help_text="Login account for this agent.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="agent_profile",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
