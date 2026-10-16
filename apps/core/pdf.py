"""PDF resources are limited to embedded data and approved public local assets."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
from django.conf import settings
from weasyprint.urls import URLFetcher


class LocalPDFResources(URLFetcher):
    def __init__(self):
        super().__init__(allowed_protocols={"data", "file"}, allow_redirects=False)

    def fetch(self, url, headers=None):
        parsed = urlsplit(url)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path)).resolve()
            roots = [Path(settings.STATIC_ROOT).resolve(), (settings.BASE_DIR / "static").resolve(),
                     (Path(settings.MEDIA_ROOT) / "company").resolve()]
            if parsed.netloc not in ("", "localhost") or not any(path.is_relative_to(root) for root in roots):
                raise ValueError("PDF resource is outside approved public assets.")
        if len(url) > 32 * 1024 * 1024:
            raise ValueError("PDF resource exceeds the permitted size.")
        return super().fetch(url, headers)
