from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('company', '0005_hero_carousel'),
    ]

    operations = [
        migrations.AddField(
            model_name='companyprofile',
            name='show_trust_strip',
            field=models.BooleanField(default=True, help_text='Show the 4-item trust-signals bar below the hero section.'),
        ),
    ]
