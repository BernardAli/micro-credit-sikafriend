"""Stub middleware — no-op for single-tenant standalone project."""


class TenantSubscriptionEnforcementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)
