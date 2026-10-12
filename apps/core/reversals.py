"""Administrator-approved corrections of recorded transactions.

Requests never move cash or call a payment provider. Execution retains source
evidence, offsets its active postings in the current open period, and updates
the operational balance in the same transaction.
"""
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .approvals import _payload_safe, create_approval_request
from .audit import log_activity
from .models import ApprovalRequest, REVERSAL_SOURCE_CHOICES, TransactionReversal
from .roles import get_user_role

SOURCE_MODELS = {
    "PAYMENT": ("loans", "Payment"), "DEPOSIT": ("loans", "SecurityDepositTransaction"),
    "TRANSFER": ("loans", "SecurityDepositTransfer"), "BANK": ("accounting", "BankTransaction"),
    "INVOICE": ("accounting", "Invoice"), "BILL": ("accounting", "Bill"),
    "PAYROLL": ("accounts", "PayrollRun"), "JOURNAL": ("accounting", "JournalEntry"),
    "DEPRECIATION": ("assets", "DepreciationRun"),
}
ZERO = Decimal("0.00")


def source_model(kind):
    if kind not in SOURCE_MODELS:
        raise ValueError("Select a supported transaction type.")
    return apps.get_model(*SOURCE_MODELS[kind])


def get_source(kind, source_id, *, lock=False):
    model = source_model(kind)
    source = model.objects.get(pk=source_id)
    if not lock:
        return source
    # Match the lock order used by collection, deposit approval and ledger sync.
    Loan = apps.get_model("loans", "Loan")
    Deposit = apps.get_model("loans", "SecurityDeposit")
    loans, deposits = {}, {}
    if kind == "PAYMENT":
        loan_ids = [source.loan_id]
    elif kind in {"DEPOSIT", "TRANSFER"}:
        deposit_ids = [source.deposit_id] if kind == "DEPOSIT" else [source.source_id, source.target_id]
        loan_ids = list(Deposit.objects.filter(pk__in=deposit_ids).values_list("loan_id", flat=True))
    else:
        loan_ids = []
    if loan_ids:
        loans = {row.pk: row for row in Loan.objects.select_for_update().filter(pk__in=loan_ids).order_by("pk")}
    if kind in {"DEPOSIT", "TRANSFER"}:
        deposits = {row.pk: row for row in Deposit.objects.select_for_update().filter(pk__in=deposit_ids).order_by("pk")}
        for row in deposits.values():
            row.loan = loans[row.loan_id]
    locked = model.objects.select_for_update().get(pk=source_id)
    if kind == "PAYMENT":
        if source.loan_id != locked.loan_id:
            raise ValueError("The source loan changed. Submit a new request.")
        locked.loan = loans[locked.loan_id]
    elif kind == "DEPOSIT":
        if source.deposit_id != locked.deposit_id:
            raise ValueError("The source deposit changed. Submit a new request.")
        locked.deposit = deposits[locked.deposit_id]
    elif kind == "TRANSFER":
        if (source.source_id, source.target_id) != (locked.source_id, locked.target_id):
            raise ValueError("The transfer accounts changed. Submit a new request.")
        locked.source, locked.target = deposits[locked.source_id], deposits[locked.target_id]
    elif kind in {"PAYROLL", "DEPRECIATION"}:
        list(locked.lines.select_for_update().order_by("pk"))
        if kind == "DEPRECIATION":
            Asset = apps.get_model("assets", "AssetItem")
            list(Asset.objects.select_for_update().filter(pk__in=locked.lines.values("asset_id")).order_by("pk"))
    return locked


def source_entries(kind, source, *, lock=False):
    Journal = apps.get_model("accounting", "JournalEntry")
    entries = Journal.objects.filter(status="POSTED", reversed_by__isnull=True)
    if lock:
        entries = entries.select_for_update()
    if kind == "PAYMENT":
        entries = entries.filter(source_type="LOAN_REPAYMENT", source_key=f"payment:{source.pk}:repayment")
    elif kind == "DEPOSIT":
        entries = entries.filter(Q(pk=source.accounting_entry_id) | Q(source_type="SECURITY_DEPOSIT", source_key=f"security-deposit:{source.pk}"))
    elif kind == "TRANSFER":
        entries = entries.none()  # Both accounts are the same deposit liability.
    elif kind == "PAYROLL":
        entries = entries.filter(source_type="PAYROLL", source_key=f"payroll:{source.pk}:paid")
    elif kind == "JOURNAL":
        entries = entries.filter(pk=source.pk)
    else:
        entries = entries.filter(pk=source.posted_entry_id)
    return list(entries.order_by("pk").prefetch_related("lines__account"))


def source_snapshot(kind, source, *, lock=False, entries=None):
    entries = source_entries(kind, source, lock=lock) if entries is None else entries
    fields = {field.attname: getattr(source, field.attname) for field in source._meta.concrete_fields
              if field.name not in {"reversal", "created_at", "updated_at"}}
    snapshot = {"kind": kind, "fields": fields,
        "journals": [{"id": entry.pk, "entry_no": entry.entry_no, "date": entry.entry_date,
            "lines": [{"account_id": line.account_id, "account": f"{line.account.code} · {line.account.name}",
                "debit": line.debit, "credit": line.credit} for line in entry.lines.all()]} for entry in entries]}
    if kind in {"PAYROLL", "DEPRECIATION"}:
        snapshot["lines"] = list(source.lines.order_by("pk").values())
    if kind in {"PAYMENT", "DEPOSIT", "TRANSFER"}:
        loans = [source.loan] if kind == "PAYMENT" else [source.deposit.loan] if kind == "DEPOSIT" else [source.source.loan, source.target.loan]
        snapshot["loan_terms"] = [{name: getattr(loan, name) for name in ("pk", "borrower_id", "agent_name_id", "portfolio_id", "amount", "weekly_payment", "duration_weeks", "duration_months", "repayment_frequency", "start_date")} for loan in loans]
    return _payload_safe(snapshot)


def validate_postings(kind, source, entries):
    if len(entries) > 1:
        raise ValueError("Multiple active source postings require reconciliation before reversal.")
    for entry in entries:
        lines = list(entry.lines.all())
        debits = sum((line.debit for line in lines), ZERO)
        credits = sum((line.credit for line in lines), ZERO)
        if not lines or debits <= ZERO or debits != credits or any(min(line.debit, line.credit) < ZERO or (line.debit and line.credit) for line in lines):
            raise ValueError("An invalid source journal requires reconciliation before reversal.")
        if kind in {"PAYMENT", "DEPOSIT", "BANK", "INVOICE", "BILL"} and debits != source.amount:
            raise ValueError("The source posting does not match the recorded amount. Reconcile it before reversal.")
        if kind == "DEPRECIATION" and debits != source.total_depreciation:
            raise ValueError("The source posting does not match the depreciation lines. Reconcile it before reversal.")


def validate_source(kind, source):
    if TransactionReversal.objects.filter(source_kind=kind, source_id=source.pk).exists() or getattr(source, "reversal_id", None):
        raise ValueError("This transaction has already been reversed. A reversal cannot be undone.")
    recorded_date = next((getattr(source, name, None) for name in ("payment_date", "transaction_date", "issue_date", "pay_date", "entry_date", "posting_date") if getattr(source, name, None)), None)
    if recorded_date and recorded_date > timezone.localdate():
        raise ValueError("Future-dated transactions require reconciliation before a reversal can be recorded.")
    if kind in {"PAYMENT", "DEPOSIT", "TRANSFER", "BANK", "INVOICE", "BILL"} and source.amount <= ZERO:
        raise ValueError("An invalid transaction amount requires reconciliation before reversal.")
    if kind == "PAYMENT":
        if source.is_void or source.is_pending:
            raise ValueError("Only settled receipts can be reversed. Use verification controls for pending submissions.")
        if source.amount != source.principal_paid + source.roic_paid + source.customer_credit or source.loan.total_expected_amount < source.loan.principal_amount:
            raise ValueError("Management must resolve this loan's terms and allocations before reversing a receipt.")
        if min(source.principal_paid, source.roic_paid, source.customer_credit) < ZERO:
            raise ValueError("Negative receipt allocations require reconciliation before reversal.")
    elif kind == "DEPOSIT":
        if source.action == "COLLECTION" and source.amount > source.deposit.held_amount:
            raise ValueError("These deposit funds have already been refunded, applied or transferred. Reverse the later movements first.")
        if source.action == "DEFAULT_APPLICATION" and source.amount > source.deposit.loan.security_deposit_applied_amount:
            raise ValueError("The recorded deposit application does not reconcile with the loan. Management must review it first.")
        if source.action not in {"COLLECTION", "REFUND", "DEFAULT_APPLICATION"}:
            raise ValueError("Unsupported deposit action.")
    elif kind == "TRANSFER":
        if source.amount > source.target.held_amount:
            raise ValueError("The receiving deposit has used these funds. Reverse its later movements first.")
        if source.source.borrower_id != source.target.borrower_id:
            raise ValueError("Management must review this transfer's customer ownership.")
    elif kind in {"INVOICE", "BILL"}:
        if source.status not in {"OPEN", "OVERDUE"} or not source.posted_entry_id:
            raise ValueError("Only posted, unsettled documents can be reversed. Settled or partially settled documents require reconciliation first.")
    elif kind == "PAYROLL":
        if source.status != "PAID":
            raise ValueError("Only paid payroll runs can be reversed. Unpaid runs use the normal cancellation process.")
    elif kind == "JOURNAL":
        if source.status != "POSTED" or source.reversed_by_id:
            raise ValueError("Only an active posted manual journal can be reversed.")
        if source.source_type != "GENERAL" or (source.source_key and not source.source_key.startswith("manual:")) or source.source_key.startswith("reversal:"):
            raise ValueError("Reverse an operational posting from its source transaction, so its balances stay consistent.")
        operational_relations = ("bank_transactions", "invoices", "bills", "security_deposit_transactions", "capitalized_assets", "asset_maintenance_entries", "asset_depreciation_runs", "asset_disposals")
        if any(getattr(source, name).exists() for name in operational_relations):
            raise ValueError("This journal belongs to an operational source transaction. Request its source reversal instead.")
        if apps.get_model("accounting", "JournalEntry").objects.filter(reversed_by_id=source.pk).exists():
            raise ValueError("A reversal entry cannot itself be reversed.")
    elif kind == "BANK":
        if not source.posted_entry_id:
            raise ValueError("This cashbook transaction has not been posted.")
    elif kind == "DEPRECIATION":
        if source.status != "POSTED" or not source.posted_entry_id:
            raise ValueError("Only posted depreciation runs can be reversed.")
        Line = apps.get_model("assets", "DepreciationLine")
        asset_ids = source.lines.values("asset_id")
        disposed = apps.get_model("assets", "AssetItem").objects.filter(pk__in=asset_ids, status__in=["DISPOSED", "WRITTEN_OFF"]).exists()
        disposal_recorded = apps.get_model("assets", "AssetDisposal").objects.filter(asset_id__in=asset_ids, posted_entry__isnull=False).exists()
        if disposed or disposal_recorded:
            raise ValueError("A depreciated asset has been disposed of. Management must reconcile the disposal first.")
        if Line.objects.filter(asset_id__in=asset_ids, run__status="POSTED").exclude(run=source).filter(Q(run__posting_date__gt=source.posting_date) | Q(run__posting_date=source.posting_date, run_id__gt=source.pk)).exists():
            raise ValueError("Later depreciation uses this run's balances. Reverse later runs first.")
    # Linked sources must have an active original posting, never a prior offset.
    linked_id = getattr(source, "posted_entry_id", None) or getattr(source, "accounting_entry_id", None)
    if linked_id and not apps.get_model("accounting", "JournalEntry").objects.filter(pk=linked_id, status="POSTED", reversed_by__isnull=True).exists():
        raise ValueError("The source journal is already void or reversed. Reconcile it before requesting a reversal.")


def describe_source(kind, source):
    """Human-readable preview shared by requests, reviewers and the register."""
    display = dict(REVERSAL_SOURCE_CHOICES)[kind]
    details = []
    if kind == "PAYMENT":
        label = f"Receipt #{source.pk} · Loan #{source.loan_id}"
        amount, tx_date, reference = source.amount, source.payment_date, source.reference
        details = [("Customer", source.loan.borrower.full_name), ("Customer number", source.loan.borrower.borrower_id), ("Method", source.get_payment_method_display()), ("Principal allocation", source.principal_paid),
            ("Interest allocation", source.roic_paid), ("Customer credit held", source.customer_credit)]
        impact = "Remove this receipt from collections and customer credit; restore its loan balance and recalculate loan and customer status."
        url = reverse("loans:loan_detail", args=[source.loan_id])
    elif kind == "DEPOSIT":
        label = f"{source.get_action_display()} #{source.pk} · Loan #{source.deposit.loan_id}"
        amount, tx_date, reference = source.amount, source.transaction_date, source.reference
        details = [("Customer", source.deposit.borrower.full_name), ("Customer number", source.deposit.borrower.borrower_id), ("Funds held at submission", source.deposit.held_amount), ("Method", source.get_payment_method_display())]
        impact = {"COLLECTION": "Reduce the security funds held. The recorded loan disbursement remains valid; any security shortfall is shown for follow-up.",
            "REFUND": "Restore the refunded amount to the customer's security funds held.",
            "DEFAULT_APPLICATION": "Restore held security funds and increase the outstanding loan principal."}[source.action]
        url = reverse("loans:security_deposit", args=[source.deposit.loan_id])
    elif kind == "TRANSFER":
        label = f"Deposit transfer #{source.pk} · Loan #{source.source.loan_id} → #{source.target.loan_id}"
        amount, tx_date, reference = source.amount, timezone.localtime(source.created_at).date(), source.reference
        details = [("Customer", source.source.borrower.full_name), ("Customer number", source.source.borrower.borrower_id)]
        impact = "Restore funds to the original deposit and reduce the receiving deposit. Combined customer security funds and the general ledger remain unchanged."
        url = reverse("loans:security_deposit", args=[source.target.loan_id])
    elif kind == "PAYROLL":
        label, amount, tx_date, reference = source.title, source.total_net, source.pay_date, f"Payroll #{source.pk}"
        details = [("Employees", source.lines.count()), ("Gross payroll", source.total_gross), ("Deductions", source.total_deductions)]
        impact = "Cancel this paid run, offset all its recorded payroll costs, deductions and payment, and retain every employee line and original payment timestamp."
        url = reverse("payroll_run_detail", args=[source.pk])
    elif kind == "JOURNAL":
        label, amount, tx_date, reference = source.entry_no, source.total_debits, source.entry_date, source.reference
        impact = "Post an equal debit/credit offset to the original accounts. Keep the original journal and its historical period intact."
        url = reverse("accounting:journal_detail", args=[source.pk])
    elif kind == "DEPRECIATION":
        label, amount, tx_date, reference = source.title, source.total_depreciation, source.posting_date, f"Depreciation #{source.pk}"
        impact = "Cancel the depreciation run, offset its expense and accumulated depreciation, and restore asset book values."
        url = reverse("assets:hub")
    elif kind == "BANK":
        label = f"{source.get_transaction_type_display()} #{source.pk} · {source.bank_account.name}"
        amount, tx_date, reference = source.amount, source.transaction_date, source.reference
        details = [("Source account", source.bank_account.name), ("Transaction type", source.get_transaction_type_display())]
        if source.target_bank_account_id:
            details.append(("Destination account", source.target_bank_account.name))
        impact = "Offset this cashbook posting, including both bank accounts for a transfer, and retain the original transaction."
        url = reverse("accounting:hub") + "?tab=cashbook"
    else:
        label = source.invoice_number if kind == "INVOICE" else source.bill_number
        amount, tx_date, reference = source.amount, source.issue_date, label
        details = [("Counterparty", source.counterparty.name), ("Due date", source.due_date), ("Document status", source.get_status_display())]
        impact = "Void this unsettled document and offset its original accrual. Remove it from outstanding balances and aging reports."
        url = reverse("accounting:hub") + ("?tab=receivables" if kind == "INVOICE" else "?tab=payables")
    details = [(label, f"GHS {value:,.2f}" if isinstance(value, Decimal) else value) for label, value in details]
    return {"kind": kind, "type": display, "source": source, "source_id": source.pk, "label": label,
        "amount": amount, "date": tx_date, "reference": reference, "details": details, "impact": impact, "url": url}


@transaction.atomic
def request_reversal(*, kind, source_id, user, reason, evidence_reference="", request=None):
    role = get_user_role(user)
    if not user or not user.is_active or role not in {"admin", "agent"}:
        raise PermissionDenied("Only active staff and assigned officers can request a reversal.")
    if role == "agent" and kind not in {"PAYMENT", "DEPOSIT", "TRANSFER"}:
        raise PermissionDenied("Only administrators can request accounting or payroll reversals.")
    source = get_source(kind, source_id, lock=True)
    check_source_access(kind, source, user)
    reason = (reason or "").strip()
    evidence_reference = (evidence_reference or "").strip()
    if len(reason) < 10 or len(reason) > 4000 or len(evidence_reference) > 180:
        raise ValueError("Give a clear reason of 10–4,000 characters and an evidence reference of at most 180 characters.")
    validate_source(kind, source)
    source_key = f"{kind}:{source.pk}"
    if ApprovalRequest.objects.filter(workflow_type="TRANSACTION_REVERSAL", status="PENDING", payload__source_key=source_key).exists():
        raise ValueError("A reversal request for this transaction is already awaiting approval.")
    info = describe_source(kind, source)
    entries = source_entries(kind, source, lock=True)
    snapshot = source_snapshot(kind, source, entries=entries)
    validate_postings(kind, source, entries)
    approval = create_approval_request(workflow_type="TRANSACTION_REVERSAL", submitted_by=user,
        title=f"Reverse {info['label']}"[:180], description=f"{reason}\n\nImpact: {info['impact']}",
        payload={"kind": kind, "source_id": source.pk, "source_key": source_key, "reason": reason,
            "evidence_reference": evidence_reference, "snapshot": snapshot},
        metadata={"amount": info["amount"], "date": info["date"], "label": info["label"], "details": info["details"], "impact": info["impact"], "source_url": info["url"]},
        target_reference=info["reference"] or info["label"][:180],
        source_path=request.path if request else info["url"], request=request)
    log_activity(category="REVERSAL", action="requested", actor=user, object_type=source._meta.label,
        object_id=source.pk, object_label=info["label"], message=f"Reversal requested for {info['label']}.",
        metadata={"approval_id": approval.pk, "amount": str(info["amount"]), "reason": reason}, request=request)
    return approval


def check_source_access(kind, source, user):
    role = get_user_role(user)
    if user.is_active and role == "admin":
        return
    if not user.is_active or role != "agent" or kind not in {"PAYMENT", "DEPOSIT", "TRANSFER"}:
        raise PermissionDenied("You cannot access this transaction reversal.")
    from apps.loans.portfolios import agent_can_access
    loans = [source.loan] if kind == "PAYMENT" else [source.deposit.loan] if kind == "DEPOSIT" else [source.source.loan, source.target.loan]
    if not all(agent_can_access(user.agent_profile, loan) for loan in loans):
        raise PermissionDenied("This transaction is outside your assigned portfolio.")


def execute_reversal(approval, reviewer, *, note=""):
    # Called inside approve_and_execute_request's locked transaction/savepoint.
    if not reviewer.is_active or not (reviewer.is_staff or reviewer.is_superuser):
        raise PermissionDenied("An active administrator must approve the reversal.")
    if reviewer.pk == approval.submitted_by_id:
        raise ValueError("A different administrator must review a transaction reversal, including requests from management and superusers.")
    if len((note or "").strip()) < 10:
        raise ValueError("Enter an administrator review note of at least 10 characters.")
    payload = approval.payload
    kind = payload["kind"]
    source = get_source(kind, payload["source_id"], lock=True)
    validate_source(kind, source)
    entries = source_entries(kind, source, lock=True)
    snapshot = source_snapshot(kind, source, entries=entries)
    if snapshot != payload["snapshot"]:
        raise ValueError("The transaction or its ledger posting changed after submission. Submit a new request after reviewing the updated record.")
    validate_postings(kind, source, entries)
    info = describe_source(kind, source)
    reversal = TransactionReversal.objects.create(approval=approval, source_kind=kind, source_id=source.pk,
        source_label=info["label"], amount=info["amount"], reason=payload["reason"],
        evidence_reference=payload.get("evidence_reference", ""), original_snapshot=snapshot,
        effective_date=timezone.localdate(), approved_by=reviewer)
    from apps.accounting.models import reverse_journal_entry
    for entry in entries:
        offset, created = reverse_journal_entry(entry, user=reviewer, reason=f"{reversal.reference} · {payload['reason']}")
        if not created:
            raise ValueError("The source entry is already reversed. Review the latest record.")
        reversal.journal_entries.add(offset)
    if kind != "JOURNAL":
        updates = {"reversal": reversal}
        if kind == "PAYMENT":
            updates["is_void"] = True  # Preserve original principal, interest and credit as evidence.
        elif kind in {"INVOICE", "BILL"}:
            updates["status"] = "VOID"
        elif kind in {"PAYROLL", "DEPRECIATION"}:
            updates["status"] = "CANCELLED"
        type(source).objects.filter(pk=source.pk).update(**updates)
    if kind == "PAYMENT":
        source.loan.refresh_status(save=True)
        source.loan.borrower.refresh_status(save=True)
        Collection = apps.get_model("loans", "RepaymentCollection")
        for collection in Collection.objects.select_for_update().filter(payment=source):
            collection.status = "CANCELLED"
            collection.reconciliation_notes = f"{collection.reconciliation_notes}\nApproved reversal {reversal.reference}: {payload['reason']}".strip()
            collection.save(update_fields=["status", "reconciliation_notes"])
    elif kind == "DEPOSIT":
        deposit = source.deposit
        if source.action == "DEFAULT_APPLICATION":
            loan = deposit.loan
            loan.security_deposit_applied_total -= source.amount
            loan.save(update_fields=["security_deposit_applied_total"])
            loan.refresh_status(save=True)
            loan.borrower.refresh_status(save=True)
        deposit.refresh_status(save=True)
    elif kind == "TRANSFER":
        source.source.refresh_status(save=True)
        source.target.refresh_status(save=True)
    log_activity(category="REVERSAL", action="executed", actor=reviewer, object_type="TransactionReversal",
        object_id=reversal.pk, object_label=reversal.reference,
        message=f"{reversal.reference}: approved reversal of {info['label']} for GHS {info['amount']:,.2f}.",
        metadata={"approval_id": approval.pk, "source_kind": kind, "source_id": source.pk, "reason": payload["reason"], "review_note": note})
    return {"message": f"{reversal.reference} completed. Original transaction retained and balances updated.", "target_reference": reversal.reference, "reversal_id": reversal.pk}
