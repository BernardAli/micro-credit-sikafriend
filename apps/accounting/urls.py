from django.urls import path

from . import views


app_name = "accounting"

urlpatterns = [
    path("", views.accounting_hub, name="hub"),
    path("journals/<int:entry_id>/", views.journal_entry_detail, name="journal_detail"),
]

