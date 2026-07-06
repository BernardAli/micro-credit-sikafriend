"""Stub context processor — single-tenant standalone project."""


def tenant_context(request):
    return {
        "current_tenant": None,
        "tenant_plan": None,
        "is_public_tenant": False,
        "tenant_has_accounting": True,
        "tenant_has_assets": True,
        "tenant_has_marketing": True,
        "tenant_has_payroll": True,
        "tenant_has_api": True,
        "tenant_trial_expired": False,
        "tenant_is_trial": False,
    }
