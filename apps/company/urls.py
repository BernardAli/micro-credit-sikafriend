from django.urls import path
from . import views

app_name = "company"

urlpatterns = [
    # Admin
    path("setup/",    views.company_setup,    name="setup"),
    path("settings/", views.company_edit,     name="edit"),
    path("settings/database-backup/", views.database_backup_hub, name="backup"),
    path("settings/database-backup/<str:fmt>/", views.database_backup_download, name="backup_download"),

    # Public website — multi-page
    path("",                views.website_home,     name="website"),
    path("about/",          views.website_about,    name="about"),
    path("services/",       views.website_services, name="services"),
    path("services/<slug:service_slug>/", views.website_service_detail, name="service_detail"),
    path("team/",           views.website_team,     name="team"),
    path("our-impact/",     views.website_impact,   name="impact"),
    path("documents/",      views.website_documents, name="documents"),
    path("contact/",        views.website_contact,  name="contact"),
    path("privacy-policy/", views.website_privacy,  name="privacy"),
]
