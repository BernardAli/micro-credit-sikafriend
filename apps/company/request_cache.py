from contextvars import ContextVar


_request_cache = ContextVar("company_request_cache", default=None)


def get_cached_value(key):
    cache = _request_cache.get()
    if cache is None:
        return None
    return cache.get(key)


def set_cached_value(key, value):
    cache = _request_cache.get()
    if cache is not None:
        cache[key] = value


class CompanyRequestCacheMiddleware:
    """Keep company-wide singleton lookups local to one request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request_cache.set({})
        try:
            return self.get_response(request)
        finally:
            _request_cache.reset(token)
