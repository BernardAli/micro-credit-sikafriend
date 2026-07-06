from django.urls import path
from . import views

app_name = "loans"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("reports/", views.reports_center, name="reports_center"),
    path("reports/business-state/pdf/", views.business_state_pdf_report, name="business_state_pdf_report"),
    path("loans/new/", views.loan_create, name="loan_create"),
    path("loans/cross-company-check/", views.borrower_cross_company_check, name="borrower_cross_company_check"),
    path("loans/import/", views.loan_bulk_import, name="loan_bulk_import"),
    path("loans/import/sample/<str:file_type>/", views.loan_bulk_import_sample, name="loan_bulk_import_sample"),
    path("loans/<int:loan_id>/", views.loan_detail, name="loan_detail"),
    path("loans/<int:loan_id>/statement/pdf/", views.loan_statement_pdf, name="loan_statement_pdf"),
    path("loans/<int:loan_id>/statement/", views.loan_statement, name="loan_statement"),
    path("loans/active/", views.active_loans_list, name="active_loans_list"),

    path("borrowers/", views.borrower_list, name="borrower_list"),
    path("borrowers/analytics/", views.borrower_analytics, name="borrower_analytics"),
    path("borrowers/status-analytics/", views.borrower_status_analytics, name="borrower_status_analytics"),
    path("borrowers/new/", views.borrower_create, name="borrower_create"),
    path("borrowers/import/", views.borrower_bulk_import, name="borrower_bulk_import"),
    path("borrowers/import/sample/<str:file_type>/", views.borrower_bulk_import_sample, name="borrower_bulk_import_sample"),
    path("borrowers/<int:pk>/", views.borrower_detail, name="borrower_detail"),
    path("borrowers/<int:pk>/edit/", views.borrower_update, name="borrower_update"),
    path("borrowers/<int:pk>/delete/", views.borrower_delete, name="borrower_delete"),
    path("loans/<int:loan_id>/payments/new/", views.loan_payment_create,  name="loan_payment_create"),
    path("payments/pending/",                 views.pending_payments_list, name="pending_payments"),
    path("payments/<int:payment_id>/confirm/",views.payment_confirm,       name="payment_confirm"),
    path("payments/<int:payment_id>/reject/", views.payment_reject,        name="payment_reject"),
    path("payments/reconciliation/",          views.payment_reconciliation_queue, name="payment_reconciliation"),
    path("payments/collections/<int:collection_id>/mark-success/", views.payment_collection_mark_success, name="payment_collection_mark_success"),
    path("payments/collections/<int:collection_id>/force-reconcile/", views.payment_collection_force_reconcile, name="payment_collection_force_reconcile"),
    path("payments/collections/<int:collection_id>/mark-failed/", views.payment_collection_mark_failed, name="payment_collection_mark_failed"),
    path("payments/collections/webhook/<str:provider>/", views.payment_collection_webhook, name="payment_collection_webhook"),
    path("loans/list/", views.loans_list, name="loans_list"),
    path("loans/analytics/", views.loan_analytics, name="loan_analytics"),
    path("loans/monthly-analytics/", views.loan_monthly_analytics, name="loan_monthly_analytics"),
]
