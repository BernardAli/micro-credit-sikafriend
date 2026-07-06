from apps.company.messaging import send_company_email
from .models import Notification


def notify_user(user, notif_type: str, title: str, message: str, send_email: bool = True):
    Notification.objects.create(
        recipient=user,
        notif_type=notif_type,
        title=title,
        message=message,
    )

    if send_email and user.email:
        send_company_email(
            subject=title,
            message=message,
            recipient_list=[user.email],
            fail_silently=True,
        )

def send_sms_stub(phone: str, message: str):
    """
    Replace with your SMS provider integration (Hubtel, Twilio, etc.)
    """
    # print(f"[SMS to {phone}] {message}")
    return
