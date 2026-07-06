from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('company', '0003_website_multipage'),
    ]

    operations = [
        # Hero layout
        migrations.AddField(
            model_name='companyprofile',
            name='hero_layout',
            field=models.CharField(
                choices=[('split', 'Split — Text left, card right'), ('centered', 'Centered — Full-width headline'), ('fullscreen', 'Full Screen — Image fills viewport')],
                default='split', max_length=20,
                help_text='Visual layout of the homepage hero section.',
            ),
        ),
        # Business identity extras
        migrations.AddField(
            model_name='companyprofile',
            name='founded_year',
            field=models.PositiveSmallIntegerField(null=True, blank=True, help_text='Year the company was founded.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='license_number',
            field=models.CharField(max_length=80, blank=True, help_text='Regulatory licence number.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='registration_number',
            field=models.CharField(max_length=80, blank=True, help_text='Business registration number.'),
        ),
        # SEO
        migrations.AddField(
            model_name='companyprofile',
            name='meta_title',
            field=models.CharField(max_length=120, blank=True, help_text='Browser tab / SEO title.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='meta_description',
            field=models.TextField(blank=True, help_text='Meta description for search engines.'),
        ),
        # JSON content sections
        migrations.AddField(
            model_name='companyprofile',
            name='core_values',
            field=models.JSONField(default=list, blank=True, help_text='Company values JSON array.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='how_steps',
            field=models.JSONField(default=list, blank=True, help_text='How It Works steps JSON array.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='partners',
            field=models.JSONField(default=list, blank=True, help_text='Partners/sponsors JSON array.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='certifications',
            field=models.JSONField(default=list, blank=True, help_text='Certifications JSON array.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='awards',
            field=models.JSONField(default=list, blank=True, help_text='Awards JSON array.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='business_hours',
            field=models.JSONField(default=list, blank=True, help_text='Business hours JSON array.'),
        ),
        # Page headlines
        migrations.AddField(
            model_name='companyprofile',
            name='about_headline',
            field=models.CharField(max_length=160, blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='about_subheadline',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='services_headline',
            field=models.CharField(max_length=160, blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='services_subheadline',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='team_headline',
            field=models.CharField(max_length=160, blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='team_subheadline',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='contact_headline',
            field=models.CharField(max_length=160, blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='contact_subheadline',
            field=models.TextField(blank=True),
        ),
        # Homepage CTA
        migrations.AddField(
            model_name='companyprofile',
            name='cta_headline',
            field=models.CharField(max_length=180, blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='cta_body',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='cta_button_text',
            field=models.CharField(max_length=60, blank=True, default='Contact Us Today'),
        ),
        # Visibility toggles
        migrations.AddField(
            model_name='companyprofile',
            name='show_stats_band',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='show_how_section',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='show_partners_section',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='show_certifications_section',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='show_awards_section',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='show_gallery_section',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='show_agents_on_team',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='show_topbar',
            field=models.BooleanField(default=True),
        ),
    ]
