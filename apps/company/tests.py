from unittest.mock import patch

from django.core.cache import cache
from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse

from apps.communication.models import WebsiteLead
from apps.company.models import CompanyProfile
from apps.company.request_cache import CompanyRequestCacheMiddleware


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
