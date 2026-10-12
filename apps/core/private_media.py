"""Private customer/workforce uploads, including authenticated legacy URLs."""
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages
from django.db.models import Q
from django.http import FileResponse, Http404
from django.utils.deconstruct import deconstructible

from .roles import get_agent_for_user, get_borrower_for_user, get_user_role


@deconstructible
class PrivateMediaStorage(FileSystemStorage):
    def __init__(self, **kwargs):
        kwargs.setdefault("location", settings.PRIVATE_MEDIA_ROOT)
        kwargs.setdefault("base_url", "/private-media/")
        kwargs.setdefault("file_permissions_mode", 0o600)
        kwargs.setdefault("directory_permissions_mode", 0o700)
        super().__init__(**kwargs)

    def _open(self, name, mode="rb"):
        try:
            return super()._open(name, mode)
        except FileNotFoundError:
            # Existing uploads remain readable while being moved out of public media.
            return FileSystemStorage(location=settings.MEDIA_ROOT).open(name, mode)

    def exists(self, name):
        return super().exists(name) or FileSystemStorage(location=settings.MEDIA_ROOT).exists(name)

    def size(self, name):
        try:
            return super().size(name)
        except FileNotFoundError:
            return FileSystemStorage(location=settings.MEDIA_ROOT).size(name)


def private_upload_storage():
    return storages["private"]


def media_file(request, path, *, public=False):
    parts = Path(path).parts
    if not parts or ".." in parts or path.startswith(("/", "\\")) or "\\" in path:
        raise Http404
    if public and parts[0] == "company":
        storage = storages["default"]
    else:
        role = get_user_role(request.user)
        if role not in {"admin", "agent", "borrower"}:
            raise Http404
        from apps.accounts.models import Agent
        from apps.loans.models import Borrower
        from apps.loans.portfolios import agent_portfolio_ids
        borrower_files = Borrower.objects.filter(Q(photo=path) | Q(ghana_card_front=path) | Q(ghana_card_back=path))
        officer_files = Agent.objects.filter(Q(photo=path) | Q(ghana_card_front=path) | Q(ghana_card_back=path))
        if role == "agent":
            officer = get_agent_for_user(request.user)
            borrower_files = borrower_files.filter(portfolio_id__in=agent_portfolio_ids(officer))
            officer_files = officer_files.filter(user=request.user)
        elif role == "borrower":
            borrower = get_borrower_for_user(request.user)
            borrower_files = borrower_files.filter(pk=borrower.pk)
            officer_files = officer_files.none()
        if not (borrower_files.exists() or officer_files.exists()):
            raise Http404
        storage = private_upload_storage()
    try:
        response = FileResponse(storage.open(path, "rb"))
    except (FileNotFoundError, OSError, ValueError):
        raise Http404
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    if response["Content-Type"].split(";", 1)[0] not in {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "application/pdf"}:
        response["Content-Type"] = "application/octet-stream"
        response["Content-Disposition"] = "attachment"
    return response
