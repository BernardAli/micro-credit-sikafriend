from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.notifications.services import notify_user

from .models import Payment, RepaymentCollection

AUTO_COLLECTION_METHODS = {"MOBILE_MONEY", "BANK", "CARD"}
SUCCESS_PROVIDER_STATES = {"success", "successful", "paid", "completed"}
FAILED_PROVIDER_STATES = {"failed", "error", "cancelled", "rejected"}


def company_currency_code() -> str:
    try:
        from apps.company.models import CompanyProfile

        return CompanyProfile.get_solo().currency_code or "GHS"
    except Exception:
        return "GHS"


def build_collection_reference() -> str:
    return f"RC-{uuid4().hex[:10].upper()}"


def build_provider_reference() -> str:
    return f"INT-{uuid4().hex[:12].upper()}"


def initiate_repayment_collection(
    *,
    loan,
    amount: Decimal,
    payment_method: str,
    submitted_by=None,
    payer_phone: str = "",
    payer_name: str = "",
    submitted_reference: str = "",
    note: str = "",
) -> RepaymentCollection:
    collection = RepaymentCollection.objects.create(
        loan=loan,
        borrower=loan.borrower,
        submitted_by=submitted_by,
        amount=Decimal(amount).quantize(Decimal("0.01")),
        currency_code=company_currency_code(),
        payment_method=payment_method,
        provider="INTERNAL",
        status="PENDING",
        client_reference=build_collection_reference(),
        provider_reference=build_provider_reference(),
        submitted_reference=submitted_reference,
        payer_phone=payer_phone,
        payer_name=payer_name,
        note=note,
        gateway_payload={
            "provider": "INTERNAL",
            "instructions": "Await provider callback or internal settlement confirmation.",
        },
    )
    return collection


def review_reason_for_collection(collection: RepaymentCollection) -> str:
    if collection.payment_id:
        return "This collection has already been reconciled to a payment."

    if collection.amount <= Decimal("0.00"):
        return "Collection amount must be greater than zero."

    if collection.loan.balance_amount <= Decimal("0.00"):
        return "The related loan is already fully settled."

    if collection.amount > collection.loan.balance_amount:
        return "Received amount exceeds the outstanding loan balance."

    if (
        collection.provider_reference
        and RepaymentCollection.objects.filter(
            provider=collection.provider,
            provider_reference=collection.provider_reference,
        )
        .exclude(pk=collection.pk)
        .exclude(status__in=["FAILED", "CANCELLED"])
        .exists()
    ):
        return "Another collection already exists with this provider reference."

    if (
        collection.submitted_reference
        and Payment.objects.filter(
            loan=collection.loan,
            reference__iexact=collection.submitted_reference,
            is_void=False,
            is_pending=False,
        )
        .exists()
    ):
        return "A posted payment already uses this submitted reference."

    return ""


@transaction.atomic
def reconcile_collection(
    collection: RepaymentCollection,
    *,
    reviewer=None,
    force: bool = False,
    notes: str = "",
):
    collection = RepaymentCollection.objects.select_related("loan", "borrower", "submitted_by").get(pk=collection.pk)

    if collection.payment_id:
        if collection.status != "RECONCILED":
            collection.status = "RECONCILED"
            collection.reconciled_at = timezone.now()
            if notes:
                collection.reconciliation_notes = notes
            collection.save(update_fields=["status", "reconciled_at", "reconciliation_notes"])
        return collection.payment, False

    reason = review_reason_for_collection(collection)
    if reason and not force:
        collection.status = "MANUAL_REVIEW"
        collection.failure_reason = reason
        if notes:
            collection.reconciliation_notes = notes
        collection.save(update_fields=["status", "failure_reason", "reconciliation_notes"])
        return None, False

    reference = collection.provider_reference or collection.submitted_reference or collection.client_reference
    note_parts = [part for part in [collection.note, f"Collection ref: {collection.client_reference}"] if part]
    if collection.provider_reference:
        note_parts.append(f"Provider ref: {collection.provider_reference}")
    if force and reason:
        note_parts.append(f"Forced reconciliation: {reason}")
    payment = Payment.objects.create(
        loan=collection.loan,
        payment_date=timezone.localdate(),
        amount=collection.amount,
        payment_method=collection.payment_method,
        reference=reference,
        note=" | ".join(note_parts)[:255],
        is_pending=False,
        submitted_by=collection.submitted_by,
    )

    collection.payment = payment
    collection.status = "RECONCILED"
    collection.reconciled_at = timezone.now()
    collection.failure_reason = ""
    if notes:
        collection.reconciliation_notes = notes
    collection.save(
        update_fields=[
            "payment",
            "status",
            "reconciled_at",
            "failure_reason",
            "reconciliation_notes",
        ]
    )

    if collection.submitted_by:
        try:
            notify_user(
                collection.submitted_by,
                "PAYMENT",
                "Payment Confirmed",
                f"Your {collection.get_payment_method_display()} repayment of "
                f"{collection.currency_code} {collection.amount:,.2f} for Loan #{collection.loan_id} "
                f"has been confirmed.",
                send_email=False,
            )
        except Exception:
            pass

    return payment, True


@transaction.atomic
def process_collection_callback(
    collection: RepaymentCollection,
    *,
    provider_status: str,
    payload: dict | None = None,
):
    payload = payload or {}
    status_key = (provider_status or "").strip().lower()

    collection = RepaymentCollection.objects.select_related("loan", "borrower", "submitted_by").get(pk=collection.pk)
    update_fields = ["callback_payload"]
    collection.callback_payload = payload

    provider_reference = payload.get("provider_reference") or payload.get("transaction_reference")
    if provider_reference:
        collection.provider_reference = str(provider_reference).strip()
        update_fields.append("provider_reference")

    if status_key in SUCCESS_PROVIDER_STATES:
        collection.status = "SUCCEEDED"
        collection.provider_confirmed_at = timezone.now()
        collection.failure_reason = ""
        update_fields.extend(["status", "provider_confirmed_at", "failure_reason"])
        collection.save(update_fields=update_fields)

        payment, created = reconcile_collection(collection)
        collection.refresh_from_db()
        if payment is None and collection.submitted_by:
            try:
                notify_user(
                    collection.submitted_by,
                    "PAYMENT",
                    "Payment Needs Review",
                    f"Your repayment for Loan #{collection.loan_id} was received but needs manual review by our team.",
                    send_email=False,
                )
            except Exception:
                pass
        return collection, payment, created

    if status_key in FAILED_PROVIDER_STATES:
        collection.status = "FAILED"
        collection.failed_at = timezone.now()
        collection.failure_reason = (payload.get("reason") or payload.get("message") or "Provider marked the collection as failed.")[:255]
        update_fields.extend(["status", "failed_at", "failure_reason"])
        collection.save(update_fields=update_fields)

        if collection.submitted_by:
            try:
                notify_user(
                    collection.submitted_by,
                    "PAYMENT",
                    "Payment Failed",
                    f"Your repayment request for Loan #{collection.loan_id} could not be completed. "
                    f"Reason: {collection.failure_reason}",
                    send_email=False,
                )
            except Exception:
                pass
        return collection, None, False

    collection.status = "PROCESSING"
    update_fields.append("status")
    collection.save(update_fields=update_fields)
    return collection, None, False


def process_collection_webhook(*, provider: str, payload: dict):
    client_reference = (payload.get("client_reference") or payload.get("reference") or "").strip()
    provider_reference = (payload.get("provider_reference") or payload.get("transaction_reference") or "").strip()

    qs = RepaymentCollection.objects.filter(provider__iexact=provider)
    if client_reference:
        collection = qs.get(client_reference=client_reference)
    elif provider_reference:
        collection = qs.get(provider_reference=provider_reference)
    else:
        raise RepaymentCollection.DoesNotExist("No collection reference provided.")

    status = payload.get("status") or payload.get("event") or payload.get("state") or ""
    return process_collection_callback(collection, provider_status=status, payload=payload)
