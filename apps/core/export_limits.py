"""Shared per-account budgets for expensive document and report generation."""
from django.conf import settings
from django.http import HttpResponse
from apps.accounts.security import reserve_attempt


def export_limit_response(request):
    wait = reserve_attempt('document-export', str(request.user.pk), settings.EXPORTS_PER_MINUTE, window=60)
    if wait:
        response = HttpResponse('Too many exports. Please wait before generating another document.', status=429)
        response['Retry-After'] = str(wait)
        response['Cache-Control'] = 'private, no-store'
        return response
    return None
