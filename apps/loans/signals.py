from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from apps.notifications.services import notify_user

from .models import Borrower, Loan, Payment

User = get_user_model()


def _build_new_loan_alert(loan: Loan) -> str:
    b = loan.borrower
    return (
        "New Loan Alert!\n\n"
        f"Name: {b.full_name}\n"
        f"ID: {b.national_id}\n"
        f"Amount: GHS {loan.amount}\n"
        f"Duration: {loan.duration_weeks} weeks\n"
        f"Start date: {loan.start_date:%d/%m/%Y}\n"
        f"Weekly Payment: GHS {loan.weekly_payment}\n"
        f"Location: {b.location}\n"
        f"Agent: {loan.agent_name}\n"
    )

@receiver(post_save, sender=Loan)
def on_loan_created(sender, instance: Loan, created, raw=False, **kwargs):
    # Django passes raw=True while loading fixtures. Related records may not be
    # available yet, and historical imports must not resend notifications.
    if raw or not created:
        return
    if getattr(instance, "_skip_new_loan_notifications", False):
        return

    # simple approach: notify all staff users (managers)
    staff_users = User.objects.filter(is_staff=True, is_active=True)
    msg = _build_new_loan_alert(instance)
    for u in staff_users:
        notify_user(u, "NEW_LOAN", "New Loan Alert!", msg, send_email=True)

@receiver(post_save, sender=Payment)
def on_payment_received(sender, instance: Payment, created, raw=False, **kwargs):
    if raw or not created or instance.is_void or instance.is_pending:
        return

    loan = instance.loan
    staff_users = User.objects.filter(is_staff=True, is_active=True)
    msg = (
        "Payment Received!\n\n"
        f"Borrower: {loan.borrower.full_name} ({loan.borrower.national_id})\n"
        f"Loan ID: {loan.id}\n"
        f"Amount Paid: GHS {instance.amount}\n"
        f"Date: {instance.payment_date:%d/%m/%Y}\n"
        f"Balance: GHS {loan.balance_amount}\n"
        f"Outstanding payments: {loan.outstanding_payments_count}\n"
    )
    for u in staff_users:
        notify_user(u, "PAYMENT", f"Payment: Loan #{loan.id}", msg, send_email=True)
