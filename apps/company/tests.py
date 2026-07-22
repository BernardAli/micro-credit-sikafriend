import json
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.forms.models import model_to_dict
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.communication.models import WebsiteLead
from apps.company.models import CompanyProfile
from apps.company.request_cache import CompanyRequestCacheMiddleware


class ManagementTeamPhotoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="company-admin",
            password="password",
            email="admin@example.com",
        )
        self.profile = CompanyProfile.get_solo()

    def test_uploaded_photo_is_saved_on_matching_management_team_member(self):
        from apps.company.forms import CompanyProfileForm

        image_bytes = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(image_bytes, format="PNG")
        image = SimpleUploadedFile("director.png", image_bytes.getvalue(), content_type="image/png")
        data = model_to_dict(self.profile)
        data["management_team_text"] = '[{"name":"Ama Mensah","title":"CEO","initials":"AM","bio":"Founder"}]'
        data["payroll_tax_brackets_text"] = json.dumps(self.profile.payroll_tax_brackets)
        with patch("apps.company.forms.default_storage.save", return_value="company/management-team/director.png"), patch(
            "apps.company.forms.default_storage.url", return_value="/media/company/management-team/director.png"
        ):
            form = CompanyProfileForm(data, {"management_team_image_0": image}, instance=self.profile)
            self.assertTrue(form.is_valid(), form.errors)
            profile = form.save()

        self.assertEqual(profile.management_team[0]["image"], "/media/company/management-team/director.png")

    def test_management_photo_is_rendered_on_public_team_and_about_pages(self):
        image_url = "/media/company/management-team/director.png"
        self.profile.management_team = [{"name": "Ama Mensah", "title": "CEO", "image": image_url}]
        self.profile.save(update_fields=["management_team"])

        for route in ("company:team", "company:about"):
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, image_url)


class OurImpactTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("impact-admin", "impact@example.com", "password")
        self.profile = CompanyProfile.get_solo()

    def test_company_settings_contains_comprehensive_impact_editor(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("company:edit"))
        self.assertContains(response, "Our Impact — Corporate Social Responsibility")
        self.assertContains(response, "Headline Impact Metrics")
        self.assertContains(response, "CSR Initiatives &amp; Community Programmes")

    def test_public_impact_page_renders_metrics_initiatives_and_commitment(self):
        self.profile.impact_headline = "Opportunity that lasts"
        self.profile.impact_stats = [{"value": "500+", "label": "Women supported", "detail": "Through business training"}]
        self.profile.impact_initiatives = [{
            "title": "Market Women Growth Programme", "category": "Financial Inclusion",
            "summary": "Business skills and mentoring.", "outcome": "120 businesses strengthened",
            "location": "Accra", "year": "2026", "image": "/media/company/impact/market.jpg",
        }]
        self.profile.impact_commitment = "We will publish and improve our community outcomes every year."
        self.profile.save()

        response = self.client.get(reverse("company:impact"))
        self.assertEqual(response.status_code, 200)
        for content in ("Opportunity that lasts", "500+", "Market Women Growth Programme", "120 businesses strengthened", self.profile.impact_commitment):
            self.assertContains(response, content)

    def test_initiative_photo_upload_is_attached_to_matching_item(self):
        from apps.company.forms import CompanyProfileForm

        image_bytes = BytesIO()
        Image.new("RGB", (2, 2), "green").save(image_bytes, format="PNG")
        upload = SimpleUploadedFile("outreach.png", image_bytes.getvalue(), content_type="image/png")
        data = model_to_dict(self.profile)
        data["impact_initiatives_text"] = '[{"title":"School Support","category":"Education","summary":"Learning materials"}]'
        data["payroll_tax_brackets_text"] = json.dumps(self.profile.payroll_tax_brackets)
        with patch("apps.company.forms.default_storage.save", return_value="company/impact/initiatives/outreach.png"), patch(
            "apps.company.forms.default_storage.url", return_value="/media/company/impact/initiatives/outreach.png"
        ):
            form = CompanyProfileForm(data, {"impact_initiative_image_0": upload}, instance=self.profile)
            self.assertTrue(form.is_valid(), form.errors)
            profile = form.save()
        self.assertEqual(profile.impact_initiatives[0]["image"], "/media/company/impact/initiatives/outreach.png")


class CompanyProfileRequestCacheTests(TestCase):
    def test_singleton_is_queried_once_per_request(self):
        CompanyProfile.get_solo()

        def render_many_values(_request):
            profiles = [CompanyProfile.get_solo() for _ in range(25)]
            self.assertTrue(all(profile.pk == 1 for profile in profiles))

        middleware = CompanyRequestCacheMiddleware(render_many_values)
        with self.assertNumQueries(1):
            middleware(object())

    def test_cache_does_not_leak_between_requests(self):
        CompanyProfile.get_solo()
        middleware = CompanyRequestCacheMiddleware(lambda _request: CompanyProfile.get_solo())

        with self.assertNumQueries(2):
            middleware(object())
            middleware(object())


class WebsiteContactTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("company:contact")
        self.payload = {
            "name": "Ama Mensah",
            "email": "ama@example.com",
            "phone": "0200000000",
            "subject": "Loan enquiry",
            "message": "Please contact me about a business loan.",
            "website": "",
        }

    def test_valid_submission_is_saved_and_confirmed(self):
        response = self.client.post(self.url, self.payload, REMOTE_ADDR="192.0.2.1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your message has been received")
        self.assertEqual(WebsiteLead.objects.count(), 1)

    @patch("apps.communication.models.WebsiteLead.objects.create", side_effect=DatabaseError("offline"))
    def test_database_failure_is_reported_without_false_success(self, _create):
        response = self.client.post(self.url, self.payload, REMOTE_ADDR="192.0.2.2")
        self.assertContains(response, "could not receive your message")
        self.assertNotContains(response, "Your message has been received")

    def test_honeypot_submission_is_rejected(self):
        payload = {**self.payload, "website": "https://spam.example"}
        response = self.client.post(self.url, payload, REMOTE_ADDR="192.0.2.3")
        self.assertContains(response, "Unable to submit this message")
        self.assertFalse(WebsiteLead.objects.exists())

    def test_rate_limit_rejects_sixth_submission(self):
        for index in range(6):
            response = self.client.post(
                self.url,
                {**self.payload, "email": f"ama{index}@example.com"},
                REMOTE_ADDR="192.0.2.4",
            )
        self.assertContains(response, "Too many messages")
        self.assertEqual(WebsiteLead.objects.count(), 5)
