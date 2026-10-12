from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .approvals import approve_and_execute_request, reject_approval_request
from .audit import log_activity
from .models import ApprovalRequest, REVERSAL_SOURCE_CHOICES, TransactionReversal
from .reversals import check_source_access, describe_source, get_source, request_reversal, source_model, source_snapshot, validate_source
from .roles import get_user_role


class ReversalRequestForm(forms.Form):
    reason = forms.CharField(min_length=10, max_length=4000, widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Explain the error, what happened to the funds, and the correction needed."}))
    evidence_reference = forms.CharField(required=False, max_length=180, label="Supporting reference", help_text="Receipt, bank reconciliation, incident or management reference.")
    verified = forms.BooleanField(label="I have checked the source transaction and supporting cash evidence.")


def _staff(request):
    role = get_user_role(request.user)
    if not request.user.is_active or role not in {"admin", "agent"}:
        raise PermissionDenied("Only staff and assigned officers can access transaction reversals.")
    return role


def _get_source(kind, pk):
    if pk > 9223372036854775807:
        raise Http404("Transaction not found.")
    try:
        return get_source(kind, pk)
    except ValueError as exc:
        raise Http404(str(exc)) from exc
    except source_model(kind).DoesNotExist as exc:
        raise Http404("Transaction not found.") from exc


@login_required
@require_http_methods(["GET", "POST"])
def reversal_request(request, kind, source_id):
    _staff(request)
    kind = kind.upper()
    source = _get_source(kind, source_id)
    check_source_access(kind, source, request.user)
    info = describe_source(kind, source)
    form = ReversalRequestForm(request.POST if request.method == "POST" else None)
    unavailable = ""
    try:
        validate_source(kind, source)
    except ValueError as exc:
        unavailable = str(exc)
    pending = ApprovalRequest.objects.filter(workflow_type="TRANSACTION_REVERSAL", status="PENDING", payload__source_key=f"{kind}:{source.pk}").first()
    if request.method == "POST" and form.is_valid() and not unavailable:
        try:
            approval = request_reversal(kind=kind, source_id=source_id, user=request.user,
                reason=form.cleaned_data["reason"], evidence_reference=form.cleaned_data["evidence_reference"], request=request)
            messages.success(request, "Reversal submitted. Balances change only after a different administrator approves and executes it.")
            return redirect("core:reversal_detail", pk=approval.pk)
        except ValueError as exc:
            form.add_error(None, str(exc))
    snapshot = source_snapshot(kind, source)
    return render(request, "core/reversal_request.html", {"title": "Request Transaction Reversal", "info": info,
        "form": form, "snapshot": snapshot, "unavailable": unavailable, "pending": pending, "today": timezone.localdate()})


@login_required
@require_http_methods(["GET", "POST"])
def reversal_detail(request, pk):
    role = _staff(request)
    approval = get_object_or_404(ApprovalRequest.objects.select_related("submitted_by", "reviewed_by"), pk=pk, workflow_type="TRANSACTION_REVERSAL")
    if role != "admin":
        source = _get_source(approval.payload["kind"], approval.payload["source_id"])
        check_source_access(approval.payload["kind"], source, request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        note = (request.POST.get("note") or "").strip()
        try:
            if action == "cancel":
                with transaction.atomic():
                    locked = ApprovalRequest.objects.select_for_update().get(pk=pk)
                    if locked.submitted_by_id != request.user.pk or locked.status != "PENDING":
                        raise PermissionDenied("Only the requester can withdraw a pending reversal request.")
                    locked.status = "CANCELLED"
                    locked.result_message = "Withdrawn by the requester; no balances changed."
                    locked.save(update_fields=["status", "result_message", "updated_at"])
                    log_activity(category="REVERSAL", action="withdrawn", actor=request.user,
                        object_type="ApprovalRequest", object_id=pk, object_label=locked.title,
                        message=locked.result_message, request=request)
                messages.success(request, "Pending reversal request withdrawn.")
            elif action in {"approve", "reject"}:
                if role != "admin":
                    raise PermissionDenied("Only an administrator can review a reversal request.")
                if action == "approve":
                    approve_and_execute_request(approval, request.user, note=note, request=request)
                    messages.success(request, "Approved reversal executed and balances updated.")
                else:
                    reject_approval_request(approval, request.user, note=note, request=request)
                    messages.success(request, "Reversal rejected; original balances retained.")
            else:
                raise ValueError("Select a valid review action.")
        except ValueError as exc:
            messages.error(request, str(exc))
        except PermissionDenied:
            raise
        except Exception as exc:
            messages.error(request, f"Reversal could not execute: {exc}")
        return redirect("core:reversal_detail", pk=pk)
    reversal = TransactionReversal.objects.filter(approval=approval).select_related("approved_by").prefetch_related("journal_entries").first()
    return render(request, "core/reversal_detail.html", {"title": "Transaction Reversal Review", "approval": approval,
        "snapshot": approval.payload.get("snapshot", {}), "reversal": reversal,
        "can_review": role == "admin" and request.user.pk != approval.submitted_by_id,
        "can_cancel": request.user.pk == approval.submitted_by_id, "today": timezone.localdate()})


@login_required
@require_http_methods(["GET"])
def reversal_hub(request):
    role = _staff(request)
    choices = REVERSAL_SOURCE_CHOICES if role == "admin" else REVERSAL_SOURCE_CHOICES[:3]
    kind = (request.GET.get("type") or "PAYMENT").upper()
    if kind not in dict(choices):
        raise PermissionDenied("This transaction type is restricted to administrators.")
    rows = source_model(kind).objects.all()
    query = (request.GET.get("q") or "").strip()[:180]
    state = request.GET.get("state") or "active"
    if kind == "PAYMENT":
        rows = rows.select_related("loan__borrower", "reversal").filter(is_pending=False)
        if state == "active":
            rows = rows.filter(is_void=False)
        if query:
            rows = rows.filter(Q(reference__icontains=query) | Q(loan__borrower__full_name__icontains=query) | Q(loan__borrower__borrower_id__icontains=query) | (Q(pk=int(query)) | Q(loan_id=int(query)) if query.isdecimal() and len(query) < 19 else Q()))
    elif kind == "DEPOSIT":
        rows = rows.select_related("deposit__loan", "deposit__borrower", "reversal")
    elif kind == "TRANSFER":
        rows = rows.select_related("source__borrower", "source__loan", "target__loan", "reversal")
    elif kind == "BANK":
        rows = rows.select_related("bank_account", "reversal").filter(posted_entry__isnull=False)
    elif kind in {"INVOICE", "BILL"}:
        rows = rows.select_related("counterparty", "reversal").filter(Q(status__in=["OPEN", "OVERDUE"]) | Q(reversal__isnull=False))
    elif kind in {"PAYROLL", "DEPRECIATION"}:
        rows = rows.select_related("reversal").filter(Q(status="PAID" if kind == "PAYROLL" else "POSTED") | Q(reversal__isnull=False))
        from django.db.models import Sum, DecimalField, Value
        from django.db.models.functions import Coalesce
        field = "net_pay" if kind == "PAYROLL" else "depreciation_amount"
        rows = rows.annotate(register_amount=Coalesce(Sum(f"lines__{field}"), Value(0), output_field=DecimalField(max_digits=20, decimal_places=2)))
    elif kind == "JOURNAL":
        rows = rows.filter(source_type="GENERAL", status="POSTED").exclude(source_key__startswith="reversal:")
        from django.db.models import Sum
        rows = rows.annotate(register_amount=Sum("lines__debit"))
    if kind != "PAYMENT":
        if state == "active":
            rows = rows.filter(reversed_by__isnull=True) if kind == "JOURNAL" else rows.filter(reversal__isnull=True)
        if query:
            conditions = Q(pk=int(query)) if query.isdecimal() and len(query) < 19 else Q(pk__in=[])
            for name in ("reference", "title", "invoice_number", "bill_number", "memo"):
                if any(field.name == name for field in rows.model._meta.fields):
                    conditions |= Q(**{f"{name}__icontains": query})
            rows = rows.filter(conditions)
    if role == "agent":
        from apps.loans.portfolios import agent_portfolio_ids
        portfolio_ids = agent_portfolio_ids(request.user.agent_profile)
        path = {"PAYMENT": "loan__portfolio_id__in", "DEPOSIT": "deposit__loan__portfolio_id__in", "TRANSFER": "target__loan__portfolio_id__in"}[kind]
        rows = rows.filter(**{path: portfolio_ids})
        if kind == "TRANSFER":
            rows = rows.filter(source__loan__portfolio_id__in=portfolio_ids)
    page = Paginator(rows.order_by("-pk"), 30).get_page(request.GET.get("page"))
    if kind == "JOURNAL":
        records = {row.source_id: row for row in TransactionReversal.objects.filter(source_kind=kind, source_id__in=[entry.pk for entry in page]).only("source_id", "approval_id")}
        for entry in page:
            entry.reversal = records.get(entry.pk)
            entry.reversal_id = entry.reversal.pk if entry.reversal else None
    approvals = ApprovalRequest.objects.filter(workflow_type="TRANSACTION_REVERSAL").select_related("submitted_by", "reviewed_by", "reversal")
    if role != "admin":
        approvals = approvals.filter(submitted_by=request.user)
    return render(request, "core/reversal_hub.html", {"title": "Transaction Reversals", "page": page, "kind": kind,
        "choices": choices, "q": query, "state": state, "cases": approvals[:30],
        "pending_count": approvals.filter(status="PENDING").count(), "completed_count": approvals.filter(status="EXECUTED").count()})
