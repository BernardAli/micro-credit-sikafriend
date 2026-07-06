from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from apps.core.pagination import paginate_items
from .models import Notification

@login_required
def inbox(request):
    qs = Notification.objects.filter(recipient=request.user).order_by("-created_at")
    unread_count = qs.filter(is_read=False).count()
    pagination = paginate_items(request, qs, per_page=12)

    return render(request, "notifications/inbox.html", {
        "items": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "title": "Notifications",
        "unread_count": unread_count,
    })
