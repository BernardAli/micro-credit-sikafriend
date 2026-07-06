from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('company', '0004_website_v2'),
    ]

    operations = [
        migrations.AddField(
            model_name='companyprofile',
            name='show_hero_carousel',
            field=models.BooleanField(default=False, help_text='Replace the static hero with an auto-advancing 3-slide carousel.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='hero_slides',
            field=models.JSONField(blank=True, default=list, help_text='Up to 3 slide objects: [{"headline":"...","subheadline":"...","cta_text":"Apply","cta_url":"","overlay":"0.65"}]'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='hero_slide_2_image',
            field=models.ImageField(blank=True, help_text='Background image for carousel slide 2.', upload_to='company/website/carousel/'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='hero_slide_3_image',
            field=models.ImageField(blank=True, help_text='Background image for carousel slide 3.', upload_to='company/website/carousel/'),
        ),
    ]
