from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views

from apps.accounts.auth_views import (
    PasswordResetCompletePageView,
    PasswordResetConfirmPageView,
    PasswordResetDonePageView,
    PasswordResetRequestView,
    TenantLoginPageView,
)
from apps.core.roles import role_redirect_view

urlpatterns = [
    path("admin/", admin.site.urls),

    # Authentication
    path("login/", TenantLoginPageView.as_view(template_name="registration/tenant_login.html"), name="login"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password_reset"),
    path("password-reset/done/", PasswordResetDonePageView.as_view(), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", PasswordResetConfirmPageView.as_view(), name="password_reset_confirm"),
    path("reset/done/", PasswordResetCompletePageView.as_view(), name="password_reset_complete"),
    path("redirect/", role_redirect_view, name="role_redirect"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),

    # App modules
    path("", include("apps.company.urls")),
    path("", include("apps.loans.urls")),
    path("agents/", include("apps.accounts.urls")),
    path("accounting/", include("apps.accounting.urls")),
    path("assets/", include("apps.assets.urls")),
    path("", include("apps.core.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("communication/", include("apps.communication.urls")),
    path("", include("apps.borrower_portal.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
