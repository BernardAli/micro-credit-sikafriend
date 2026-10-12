from django.urls import path
from . import views
from apps.loans import statement_views

urlpatterns = [
    # ── Agent list & management (admin only) ──────────────────
    path("",                              views.agent_list,                  name="agent_list"),
    path("agents/analytics/",            views.agents_analytics,            name="agents_analytics"),
    path("agents/analysis/range/",       views.agents_monthly_range_analysis, name="agents_monthly_range_analysis"),
    path("agents/new/",                  views.agent_create,                name="agent_create"),
    path("agents/import/",               views.agent_bulk_import,           name="agent_bulk_import"),
    path("agents/import/sample/<str:file_type>/", views.agent_bulk_import_sample, name="agent_bulk_import_sample"),
    path("agents/register/",             views.agent_register,              name="agent_register"),
    path("payroll/",                     views.payroll_hub,                 name="payroll_hub"),
    path("payroll/<int:pk>/",            views.payroll_run_detail,          name="payroll_run_detail"),

    # ── Individual agent ──────────────────────────────────────
    path("agents/<int:pk>/",             views.agent_detail,                name="agent_detail"),
    path("agents/<int:pk>/statement/", statement_views.agent_statement, name="agent_statement"),
    path("agents/<int:pk>/statement/pdf/", statement_views.agent_statement_pdf, name="agent_statement_pdf"),
    path("agents/<int:pk>/delete/",      views.agent_delete,                name="agent_delete"),
    path("agents/<int:pk>/analysis/",    views.agent_comprehensive_analysis, name="agent_comprehensive_analysis"),
    path("agents/<int:pk>/analysis/range/", views.agent_monthly_range_analysis, name="agent_monthly_range_analysis"),
    path("agents/<int:pk>/reset-password/", views.agent_reset_password,    name="agent_reset_password"),

    # ── Borrower login management (admin only) ────────────────
    path("borrowers/<int:pk>/create-login/", views.borrower_create_login,   name="borrower_create_login"),
    path("borrowers/<int:pk>/reset-login/",  views.borrower_reset_login,    name="borrower_reset_login"),
]
