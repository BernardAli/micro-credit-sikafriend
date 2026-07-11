from django.urls import path

from . import views


app_name = "core"

urlpatterns = [
    path("loan-requests/", views.loan_request_hub, name="loan_requests"),
    path("approvals/", views.approval_hub, name="approvals"),
    path("audit/", views.audit_trail, name="audit_trail"),
]
