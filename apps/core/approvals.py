from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .audit import log_activity
from .models import ApprovalRequest


def _payload_safe(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _payload_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_payload_safe(item) for item in value]
    return value


def create_approval_request(
    *,
    workflow_type,
    title,
    submitted_by=None,
    description="",
    payload=None,
    metadata=None,
    source_path="",
    target_reference="",
    request=None,
):
    approval = ApprovalRequest.objects.create(
        workflow_type=workflow_type,
        title=title,
        submitted_by=submitted_by,
        description=description,
        payload=_payload_safe(payload or {}),
        metadata=_payload_safe(metadata or {}),
        source_path=source_path,
        target_reference=target_reference,
    )
    log_activity(
        category="APPROVAL",
        action="submitted",
        actor=submitted_by,
        object_type="ApprovalRequest",
        object_id=approval.pk,
        object_label=approval.title,
        message=f"Approval request submitted for {approval.get_workflow_type_display().lower()}.",
        metadata={"workflow_type": workflow_type, "status": approval.status},
        request=request,
    )
    return approval


def reject_approval_request(approval, reviewer, *, note="", request=None):
    if approval.status != "PENDING":
        raise ValueError("Only pending requests can be rejected.")
    if approval.submitted_by_id and reviewer and approval.submitted_by_id == reviewer.pk:
        raise ValueError("The submitting user cannot reject or approve their own request.")

    approval.status = "REJECTED"
    approval.reviewed_by = reviewer
    approval.reviewed_at = timezone.now()
    approval.review_note = (note or "").strip()
    approval.result_message = "Request rejected."
    approval.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "result_message", "updated_at"])

    log_activity(
        category="APPROVAL",
        action="rejected",
        actor=reviewer,
        object_type="ApprovalRequest",
        object_id=approval.pk,
        object_label=approval.title,
        message=f"Approval request rejected: {approval.title}.",
        metadata={"workflow_type": approval.workflow_type, "note": approval.review_note},
        request=request,
    )
    return approval


def approve_and_execute_request(approval, reviewer, *, note="", request=None):
    if approval.status != "PENDING":
        raise ValueError("Only pending requests can be approved.")
    if approval.submitted_by_id and reviewer and approval.submitted_by_id == reviewer.pk:
        raise ValueError("The submitting user cannot approve their own request.")

    if approval.workflow_type == "LOAN_CREATION":
        from apps.loans.cross_company import get_cross_company_debt_check
        from apps.loans.models import Borrower

        borrower = Borrower.objects.filter(pk=approval.payload.get("borrower_id")).first()
        if borrower is not None:
            latest_check = get_cross_company_debt_check(borrower=borrower)
            if latest_check["requires_review"] and not (note or "").strip():
                raise ValueError(
                    "Add an approval note after reviewing the customer's external debt exposure with other onboarded companies."
                )

    handler = {
        "LOAN_CREATION": _execute_loan_creation,
        "PAYROLL_RUN_APPROVAL": _execute_payroll_run_approval,
        "ACCOUNTING_JOURNAL": _execute_accounting_journal,
        "ASSET_DISPOSAL": _execute_asset_disposal,
    }.get(approval.workflow_type)

    if handler is None:
        raise ValueError("No handler is configured for this approval workflow.")

    with transaction.atomic():
        try:
            result = handler(approval, reviewer, note=note)
        except Exception as exc:
            approval.status = "FAILED"
            approval.reviewed_by = reviewer
            approval.reviewed_at = timezone.now()
            approval.review_note = (note or "").strip()
            approval.result_message = str(exc)
            approval.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "result_message", "updated_at"])
            log_activity(
                category="APPROVAL",
                action="failed",
                actor=reviewer,
                object_type="ApprovalRequest",
                object_id=approval.pk,
                object_label=approval.title,
                message=f"Approval execution failed for {approval.title}.",
                metadata={"workflow_type": approval.workflow_type, "error": str(exc)},
                request=request,
            )
            raise

        approval.status = "EXECUTED"
        approval.reviewed_by = reviewer
        approval.reviewed_at = timezone.now()
        approval.review_note = (note or "").strip()
        approval.result_message = result.get("message", "Request approved and executed.")
        if result.get("target_reference"):
            approval.target_reference = result["target_reference"]
        approval.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "result_message",
                "target_reference",
                "updated_at",
            ]
        )

    log_activity(
        category="APPROVAL",
        action="approved",
        actor=reviewer,
        object_type="ApprovalRequest",
        object_id=approval.pk,
        object_label=approval.title,
        message=f"Approval request executed: {approval.title}.",
        metadata={"workflow_type": approval.workflow_type, "result": result},
        request=request,
    )
    return approval, result


def _execute_loan_creation(approval, reviewer, *, note=""):
    from apps.loans.models import Borrower, Loan
    from apps.loans.cross_company import get_cross_company_debt_check
    from apps.loans.services import build_loan_statement
    from apps.loans.services_sms import safe_send_sms
    from apps.notifications.services import notify_user

    payload = approval.payload
    borrower = Borrower.objects.get(pk=payload["borrower_id"])
    latest_check = get_cross_company_debt_check(borrower=borrower)
    if latest_check["requires_review"] and not (note or "").strip():
        raise ValueError(
            "An approval note is required because this borrower has external debt exposure with another onboarded company."
        )

    def optional_date(name):
        value = payload.get(name)
        return date.fromisoformat(value) if value else None

    def optional_decimal(name):
        value = payload.get(name)
        return Decimal(str(value)) if value not in (None, "") else None

    loan = Loan.objects.create(
        borrower=borrower,
        agent_name_id=payload["agent_id"],
        amount=Decimal(str(payload["amount"])),
        duration_months=int(payload.get("duration_months") or 0),
        duration_weeks=int(payload["duration_weeks"]),
        repayment_frequency=payload.get("repayment_frequency") or "WEEKLY",
        sector=payload.get("sector") or "",
        sector_other=payload.get("sector_other") or "",
        loan_acquisition_date=optional_date("loan_acquisition_date"),
        start_date=date.fromisoformat(payload["start_date"]),
        weekly_payment=Decimal(str(payload["weekly_payment"])),
        borrower_declaration_accepted=bool(payload.get("borrower_declaration_accepted")),
        borrower_signature_name=payload.get("borrower_signature_name") or "",
        borrower_signed_date=optional_date("borrower_signed_date"),
        guarantor_name=payload.get("guarantor_name") or "",
        guarantor_id_number=payload.get("guarantor_id_number") or "",
        guarantor_signature_name=payload.get("guarantor_signature_name") or "",
        guarantor_signed_date=optional_date("guarantor_signed_date"),
        collateral_type=payload.get("collateral_type") or "",
        collateral_details=payload.get("collateral_details") or "",
        collateral_estimated_value=optional_decimal("collateral_estimated_value"),
        collateral_location=payload.get("collateral_location") or "",
        collateral_borrower_consent_accepted=bool(payload.get("collateral_borrower_consent_accepted")),
        collateral_borrower_signed_date=optional_date("collateral_borrower_signed_date"),
        collateral_guarantor_signature_name=payload.get("collateral_guarantor_signature_name") or "",
        collateral_guarantor_signed_date=optional_date("collateral_guarantor_signed_date"),
        application_received_by=payload.get("application_received_by") or "",
        application_received_date=optional_date("application_received_date"),
        approved_amount=optional_decimal("approved_amount"),
        approved_repayment_plan=payload.get("approved_repayment_plan") or "",
        loan_officer_signature_name=payload.get("loan_officer_signature_name") or "",
        approval_manager_signature_name=payload.get("approval_manager_signature_name") or "",
        approval_date=optional_date("approval_date"),
    )
    loan.borrower.refresh_status(save=True)

    from apps.loans.views import _build_new_loan_sms_messages

    borrower_phone = loan.borrower.phone
    agent_phone = loan.agent_name.phone if loan.agent_name else None
    borrower_msg, agent_msg = _build_new_loan_sms_messages(loan)
    if borrower_phone:
        safe_send_sms(borrower_phone, borrower_msg)
    if agent_phone:
        safe_send_sms(agent_phone, agent_msg)

    statement = build_loan_statement(loan)
    notify_user(reviewer, "STATEMENT", f"Loan Statement: Loan #{loan.id}", statement, send_email=True)

    log_activity(
        category="LOAN",
        action="created_from_approval",
        actor=reviewer,
        object_type="Loan",
        object_id=loan.pk,
        object_label=f"Loan #{loan.pk}",
        message=f"Loan #{loan.pk} was created after approval for {loan.borrower.full_name}.",
        metadata={"borrower_id": loan.borrower_id, "agent_id": loan.agent_name_id, "approval_id": approval.pk},
    )
    return {
        "message": f"Loan #{loan.pk} created successfully.",
        "target_reference": f"Loan #{loan.pk}",
    }


def _execute_payroll_run_approval(approval, reviewer, *, note=""):
    from apps.accounts.models import PayrollRun

    run = PayrollRun.objects.get(pk=approval.payload["run_id"])
    if run.status != "DRAFT":
        raise ValueError("Only draft payroll runs can be approved.")
    run.status = "APPROVED"
    run.approved_by = reviewer
    run.approved_at = timezone.now()
    run.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    log_activity(
        category="PAYROLL",
        action="approved",
        actor=reviewer,
        object_type="PayrollRun",
        object_id=run.pk,
        object_label=run.title,
        message=f"Payroll run '{run.title}' approved.",
        metadata={"approval_id": approval.pk},
    )
    return {
        "message": f"Payroll run '{run.title}' approved.",
        "target_reference": run.title,
    }


def _execute_accounting_journal(approval, reviewer, *, note=""):
    from apps.accounting.models import AccountingPeriod, create_journal_entry

    payload = approval.payload
    prepared_lines = []
    for line in payload.get("lines", []):
        from apps.accounting.models import LedgerAccount

        account = LedgerAccount.objects.get(pk=line["account_id"])
        prepared_lines.append(
            {
                "account": account,
                "description": line.get("description", ""),
                "debit": Decimal(str(line.get("debit") or "0.00")),
                "credit": Decimal(str(line.get("credit") or "0.00")),
            }
        )

    entry = create_journal_entry(
        entry_date=date.fromisoformat(payload["entry_date"]),
        memo=payload["memo"],
        reference=payload.get("reference", ""),
        lines=prepared_lines,
        created_by=reviewer,
    )
    if payload.get("period_id"):
        entry.period = AccountingPeriod.objects.get(pk=payload["period_id"])
        entry.save(update_fields=["period"])

    log_activity(
        category="ACCOUNTING",
        action="journal_posted",
        actor=reviewer,
        object_type="JournalEntry",
        object_id=entry.pk,
        object_label=entry.entry_no,
        message=f"Journal entry {entry.entry_no} posted from approval queue.",
        metadata={"approval_id": approval.pk},
    )
    return {
        "message": f"Journal entry {entry.entry_no} posted successfully.",
        "target_reference": entry.entry_no,
    }


def _execute_asset_disposal(approval, reviewer, *, note=""):
    from apps.assets.models import AssetDisposal
    from apps.assets.views import _post_disposal

    payload = approval.payload
    disposal = AssetDisposal.objects.create(
        asset_id=payload["asset_id"],
        disposal_date=date.fromisoformat(payload["disposal_date"]),
        disposal_type=payload["disposal_type"],
        proceeds=Decimal(str(payload.get("proceeds") or "0.00")),
        selling_cost=Decimal(str(payload.get("selling_cost") or "0.00")),
        settlement_account_id=payload.get("settlement_account_id") or None,
        gain_account_id=payload.get("gain_account_id") or None,
        loss_account_id=payload.get("loss_account_id") or None,
        notes=payload.get("notes", ""),
        created_by=reviewer,
    )
    _post_disposal(disposal, reviewer)

    log_activity(
        category="ASSET",
        action="disposed",
        actor=reviewer,
        object_type="AssetDisposal",
        object_id=disposal.pk,
        object_label=disposal.asset.asset_code,
        message=f"Asset {disposal.asset.asset_code} disposed from approval queue.",
        metadata={"approval_id": approval.pk},
    )
    return {
        "message": f"Asset {disposal.asset.asset_code} disposal posted successfully.",
        "target_reference": disposal.asset.asset_code,
    }
