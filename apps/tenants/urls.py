"""Stub tenants URLs — single-tenant standalone project."""
from django.urls import path
from django.views.generic import RedirectView

app_name = "tenants"

urlpatterns = [
    path("onboarding/", RedirectView.as_view(url="/", permanent=False), name="onboarding"),
]
