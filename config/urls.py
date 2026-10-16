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
    mfa_setup, mfa_verify, mfa_recovery, account_security,
)
from apps.core.roles import role_redirect_view
from apps.core.private_media import media_file
from apps.core.health import health

urlpatterns = [
    path("health/", health, name="health"),
    path("private-media/<path:path>", media_file, name="private_media"),
    path("media/<path:path>", media_file, {"public": True}, name="legacy_media"),
    path("admin/", admin.site.urls),

    # Authentication
    path("login/", TenantLoginPageView.as_view(template_name="registration/tenant_login.html"), name="login"),
    path("account-security/", account_security, name="account_security"),
    path("account-security/setup/", mfa_setup, name="mfa_setup"),
    path("account-security/verify/", mfa_verify, name="mfa_verify"),
    path("account-security/recovery/", mfa_recovery, name="mfa_recovery"),
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

if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
