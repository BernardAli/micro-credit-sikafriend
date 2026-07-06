from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    path("inbox/", views.inbox, name="inbox"),
]