from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0007_alter_companyprofile_about_headline_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="hero_slide_1_feature_image",
            field=models.ImageField(
                blank=True,
                help_text="Foreground image shown beside the text on carousel slide 1.",
                upload_to="company/website/carousel/feature/",
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="hero_slide_2_feature_image",
            field=models.ImageField(
                blank=True,
                help_text="Foreground image shown beside the text on carousel slide 2.",
                upload_to="company/website/carousel/feature/",
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="hero_slide_3_feature_image",
            field=models.ImageField(
                blank=True,
                help_text="Foreground image shown beside the text on carousel slide 3.",
                upload_to="company/website/carousel/feature/",
            ),
        ),
    ]
