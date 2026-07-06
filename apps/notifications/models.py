from django.conf import settings
from django.db import models

class Notification(models.Model):
    TYPE_CHOICES = [
        ("NEW_LOAN", "New Loan Alert"),
        ("PAYMENT", "Payment Received"),
        ("STATEMENT", "Loan Statement"),
        ("REMINDER", "Payment Reminder"),
    ]

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notif_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_notif_type_display()} -> {self.recipient}"