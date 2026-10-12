from django.urls import path

from . import views
from . import reversal_views


app_name = "core"

urlpatterns = [
    path("reversals/", reversal_views.reversal_hub, name="reversals"),
    path("reversals/request/<str:kind>/<int:source_id>/", reversal_views.reversal_request, name="reversal_request"),
    path("reversals/requests/<int:pk>/", reversal_views.reversal_detail, name="reversal_detail"),
    path("loan-requests/", views.loan_request_hub, name="loan_requests"),
    path("approvals/", views.approval_hub, name="approvals"),
    path("audit/", views.audit_trail, name="audit_trail"),
]
