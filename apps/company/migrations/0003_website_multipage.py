from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0002_company_website_fields"),
    ]

    operations = [
        # Gallery images
        *[
            migrations.AddField(
                model_name="companyprofile",
                name=f"gallery_image_{i}",
                field=models.ImageField(blank=True, upload_to="company/gallery/",
                                        help_text=f"Gallery image {i}"),
            )
            for i in range(1, 11)
        ],
        *[
            migrations.AddField(
                model_name="companyprofile",
                name=f"gallery_caption_{i}",
                field=models.CharField(blank=True, max_length=120),
            )
            for i in range(1, 11)
        ],
        # About extras
        migrations.AddField(model_name="companyprofile", name="goals",
            field=models.JSONField(blank=True, default=list, help_text="Goals JSON array")),
        migrations.AddField(model_name="companyprofile", name="management_team",
            field=models.JSONField(blank=True, default=list, help_text="Management team JSON array")),
        migrations.AddField(model_name="companyprofile", name="about_image_2",
            field=models.ImageField(blank=True, upload_to="company/website/")),
        migrations.AddField(model_name="companyprofile", name="about_image_3",
            field=models.ImageField(blank=True, upload_to="company/website/")),
        # Branches
        migrations.AddField(model_name="companyprofile", name="branches",
            field=models.JSONField(blank=True, default=list,
                                   help_text="Branches/locations JSON array")),
        # Site branding
        migrations.AddField(model_name="companyprofile", name="site_primary_color",
            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="companyprofile", name="site_secondary_color",
            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="companyprofile", name="site_bg_color",
            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="companyprofile", name="site_text_color",
            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="companyprofile", name="site_nav_bg",
            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="companyprofile", name="site_footer_bg",
            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="companyprofile", name="site_section_alt_bg",
            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="companyprofile", name="hero_overlay_opacity",
            field=models.FloatField(blank=True, default=0.0)),
        migrations.AddField(model_name="companyprofile", name="site_font",
            field=models.CharField(
                choices=[("dm_sans","DM Sans + DM Serif Display"),("inter","Inter + Playfair Display"),
                         ("poppins","Poppins + Cormorant Garamond"),("nunito","Nunito + Libre Baskerville"),
                         ("raleway","Raleway + Lora")],
                default="dm_sans", max_length=30)),
        # Page hero images
        migrations.AddField(model_name="companyprofile", name="about_hero_image",
            field=models.ImageField(blank=True, upload_to="company/website/")),
        migrations.AddField(model_name="companyprofile", name="services_hero_image",
            field=models.ImageField(blank=True, upload_to="company/website/")),
        migrations.AddField(model_name="companyprofile", name="team_hero_image",
            field=models.ImageField(blank=True, upload_to="company/website/")),
        migrations.AddField(model_name="companyprofile", name="contact_hero_image",
            field=models.ImageField(blank=True, upload_to="company/website/")),
        # Contact page
        migrations.AddField(model_name="companyprofile", name="contact_intro",
            field=models.TextField(blank=True)),
        migrations.AddField(model_name="companyprofile", name="maps_embed_url",
            field=models.URLField(blank=True, max_length=1000)),
    ]
