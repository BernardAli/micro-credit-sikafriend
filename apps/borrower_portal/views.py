from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from apps.core.roles import get_borrower_for_user, get_user_role
from apps.loans.payment_gateway import (
    AUTO_COLLECTION_METHODS,
    initiate_repayment_collection,
    process_collection_callback,
)


def borrower_required(view_func):
    """Allow only users who have a borrower_profile."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        borrower = get_borrower_for_user(request.user)
        if borrower is None:
            # Admins/agents who hit a borrower URL → redirect to their home
            role = get_user_role(request.user)
            if role == "admin":
                return redirect("loans:dashboard")
            if role == "agent":
                from apps.core.roles import get_agent_for_user
                agent = get_agent_for_user(request.user)
                if agent:
                    return redirect("agent_detail", pk=agent.pk)
            messages.error(request, "No borrower account found.")
            return redirect("login")
        return view_func(request, *args, **kwargs)
    return wrapper


@borrower_required
def portal_home(request):
    """Borrower's main portal — summary of all their loans."""
    borrower = get_borrower_for_user(request.user)
    from apps.loans.models import Loan, Payment

    loans = (
        Loan.objects
        .filter(borrower=borrower)
        .prefetch_related("payments")
        .select_related("agent_name")
        .order_by("-created_at")
    )

    # Aggregate totals
    total_disbursed        = sum((l.amount for l in loans), Decimal("0.00"))
    total_expected         = sum((l.total_expected_amount for l in loans), Decimal("0.00"))
    total_paid             = sum((l.total_paid_amount for l in loans), Decimal("0.00"))
    total_outstanding      = sum((l.balance_amount for l in loans), Decimal("0.00"))
    total_principal_paid   = sum((l.total_principal_paid for l in loans), Decimal("0.00"))
    total_roic_paid        = sum((l.total_roic_paid for l in loans), Decimal("0.00"))

    collection_rate = (
        (total_paid / total_expected * Decimal("100")).quantize(Decimal("0.01"))
        if total_expected > 0 else Decimal("0.00")
    )

    active_loans  = [l for l in loans if l.status == "ACTIVE"]
    closed_loans  = [l for l in loans if l.status == "CLOSED"]
    default_loans = [l for l in loans if l.status == "DEFAULT"]

    # 5 most recent payments across all loans
    recent_payments = (
        Payment.objects
        .filter(Q(is_void=False) | Q(reversal__isnull=False), loan__borrower=borrower)
        .select_related("loan", "loan__agent_name", "reversal")
        .order_by("-payment_date", "-created_at")[:8]
    )

    context = {
        "title":               "My Loan Account",
        "borrower":            borrower,
        "loans":               loans,
        "active_loans":        active_loans,
        "closed_loans":        closed_loans,
        "default_loans":       default_loans,
        "total_disbursed":     total_disbursed.quantize(Decimal("0.01")),
        "total_expected":      total_expected.quantize(Decimal("0.01")),
        "total_paid":          total_paid.quantize(Decimal("0.01")),
        "customer_credit":     sum((l.total_customer_credit for l in loans), Decimal("0.00")),
        "total_outstanding":   total_outstanding.quantize(Decimal("0.01")),
        "total_principal_paid":total_principal_paid.quantize(Decimal("0.01")),
        "total_roic_paid":     total_roic_paid.quantize(Decimal("0.01")),
        "collection_rate":     collection_rate,
        "recent_payments":     recent_payments,
    }
    return render(request, "borrower_portal/portal_home.html", context)


@borrower_required
def portal_loan_detail(request, loan_id):
    """Borrower views a single loan's full detail and payment history."""
    from apps.loans.models import Loan, Payment
    from django.shortcuts import get_object_or_404

    borrower = get_borrower_for_user(request.user)
    loan = get_object_or_404(Loan, pk=loan_id, borrower=borrower)

    payments = (
        loan.payments
        .filter(Q(is_void=False) | Q(reversal__isnull=False))
        .select_related("reversal")
        .order_by("payment_date", "id")
    )

    context = {
        "title":    f"Loan #{loan.id}",
        "borrower": borrower,
        "loan":     loan,
        "payments": payments,
    }
    return render(request, "borrower_portal/portal_loan_detail.html", context)


@borrower_required
def portal_change_password(request):
    """Borrower changes their own password."""
    from django.contrib.auth import update_session_auth_hash
    from django import forms as _forms

    class ChangePasswordForm(_forms.Form):
        current_password = _forms.CharField(widget=_forms.PasswordInput, label="Current password")
        new_password     = _forms.CharField(widget=_forms.PasswordInput, label="New password",
                                             help_text="At least 8 characters.")
        new_password2    = _forms.CharField(widget=_forms.PasswordInput, label="Confirm new password")

        def clean(self):
            cleaned = super().clean()
            p1 = cleaned.get("new_password", "")
            p2 = cleaned.get("new_password2", "")
            if p1 and p2 and p1 != p2:
                self.add_error("new_password2", "Passwords do not match.")
            if p1 and len(p1) < 8:
                self.add_error("new_password", "Password must be at least 8 characters.")
            return cleaned

    form = ChangePasswordForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        user = request.user
        if not user.check_password(form.cleaned_data["current_password"]):
            form.add_error("current_password", "Current password is incorrect.")
        else:
            user.set_password(form.cleaned_data["new_password"])
            user.save()
            update_session_auth_hash(request, user)   # keep logged in
            messages.success(request, "Password changed successfully.")
            return redirect("borrower:portal")

    return render(request, "borrower_portal/change_password.html", {
        "title": "Change Password",
        "form": form,
    })


@borrower_required
def portal_make_payment(request, loan_id):
    """Borrower submits an online payment for staff to confirm."""
    from django.shortcuts import get_object_or_404
    from apps.loans.models import Loan, Payment, RepaymentCollection

    borrower = get_borrower_for_user(request.user)
    loan = get_object_or_404(Loan, pk=loan_id, borrower=borrower)

    if loan.status not in ("ACTIVE", "DEFAULT"):
        messages.error(request, "This loan is already closed.")
        return redirect("borrower:loan_detail", loan_id=loan.pk)

    if not loan.is_ready_for_disbursement:
        messages.error(request, "Repayments are available after the required security deposit is approved.")
        return redirect("borrower:loan_detail", loan_id=loan.pk)

    error = None
    if request.method == "POST":
        raw_amount = request.POST.get("amount", "").strip()
        method     = request.POST.get("payment_method", "MOBILE_MONEY").strip()
        reference  = request.POST.get("reference", "").strip()
        note       = request.POST.get("note", "").strip()
        payer_phone = request.POST.get("payer_phone", "").strip()
        payer_name  = request.POST.get("payer_name", "").strip()

        try:
            amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01")).clean(raw_amount)
        except ValidationError:
            error = "Please enter a valid payment amount."
        else:
            if amount > loan.balance_amount:
                error = (
                    f"Payment amount cannot be more than your outstanding balance of "
                    f"GHS {loan.balance_amount:,.2f}."
                )

            if method not in dict(Payment.PAYMENT_METHOD_CHOICES):
                method = "MOBILE_MONEY"
            if not error and method in AUTO_COLLECTION_METHODS:
                collection = initiate_repayment_collection(
                    loan=loan,
                    amount=amount,
                    payment_method=method,
                    submitted_by=request.user,
                    payer_phone=payer_phone,
                    payer_name=payer_name,
                    submitted_reference=reference,
                    note=note,
                )
                messages.success(
                    request,
                    f"Payment details submitted. Reference: {collection.client_reference}. "
                    "Our team will verify receipt of the funds before crediting your loan.",
                )
                return redirect("borrower:make_payment", loan_id=loan.pk)

            if not error:
                try:
                    Payment.objects.create(
                        loan=loan,
                        amount=amount,
                        payment_method=method,
                        reference=reference,
                        note=note,
                        is_pending=True,
                        submitted_by=request.user,
                    )
                except ValidationError as exc:
                    messages.error(request, "; ".join(exc.messages))
                    return redirect("borrower:make_payment", loan_id=loan.pk)

                # Notify all staff
                try:
                    from apps.notifications.services import notify_user
                    from django.contrib.auth.models import User

                    admins = User.objects.filter(is_staff=True)
                    for admin in admins:
                        notify_user(
                            admin,
                            "PAYMENT",
                            f"Payment submission from {borrower.full_name}",
                            f"{borrower.full_name} submitted a {method.replace('_', ' ')} "
                            f"payment of GHS {amount:,.2f} for Loan #{loan.id}. "
                            f"Reference: {reference or 'N/A'}. Awaiting confirmation.",
                            send_email=False,
                        )
                except Exception:
                    pass

                messages.success(
                    request,
                    "Your payment has been submitted and is awaiting confirmation by our team. "
                    "You will be notified once it is processed.",
                )
                return redirect("borrower:loan_detail", loan_id=loan.pk)

    pending_payments = loan.payments.filter(is_pending=True, is_void=False)
    collections = loan.repayment_collections.exclude(status="CANCELLED").order_by("-initiated_at")[:8]

    return render(request, "borrower_portal/make_payment.html", {
        "title":            f"Make Payment — Loan #{loan.id}",
        "loan":             loan,
        "borrower":         borrower,
        "error":            error,
        "pending_payments": pending_payments,
        "collections":      collections,
        "payment_methods":  Payment.PAYMENT_METHOD_CHOICES,
        "auto_collection_methods": AUTO_COLLECTION_METHODS,
    })
