from django.conf import settings
from django.db import connection, DatabaseError
from django.http import Http404, JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def health(request):
    expected = settings.HEALTHCHECK_TOKEN
    supplied = request.headers.get("Authorization", "")
    if not expected or not constant_time_compare(supplied, f"Bearer {expected}"):
        raise Http404
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
