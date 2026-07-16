import csv
import json
from collections import defaultdict
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from weasyprint import HTML

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.db.models import Sum, Count, F, DecimalField, ExpressionWrapper, Q, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils.crypto import constant_time_compare
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font

from .forms import (
    LoanForm,
    PaymentForm,
    BorrowerForm,
    BorrowerBulkImportForm,
    LoanBulkImportForm,
    PaymentCreateForm,
    LoanCreateForBorrowerForm,
)
from .borrower_imports import (
    build_borrower_import_sample,
    get_borrower_import_column_help,
    get_borrower_import_formats,
    import_borrower_rows,
    infer_borrower_import_format,
    parse_borrower_import,
)
from .loan_imports import (
    build_loan_import_sample,
    get_loan_import_column_help,
    get_loan_import_formats,
    import_loan_rows,
    infer_loan_import_format,
    parse_loan_import,
)
from .cross_company import (
    empty_cross_company_debt_check,
    format_cross_company_debt_summary,
    get_cross_company_debt_check,
    serialize_cross_company_debt_check,
)
from .models import Loan, Borrower, Payment, RepaymentCollection
from .payment_gateway import process_collection_callback, process_collection_webhook, reconcile_collection
from .reports import (
    EXPORT_FORMATS,
    HALF_YEAR_CHOICES,
    MONTH_CHOICES,
    PERIOD_CHOICES,
    QUARTER_CHOICES,
    available_years,
    build_report,
    export_report_csv,
    export_report_excel,
    export_report_json,
    get_report_definition,
    report_catalog_groups,
    resolve_report_period,
)
from .services import build_loan_statement
from .services_sms import safe_send_sms
from apps.accounts.models import Agent
from apps.accounts.usernames import build_portal_username, visible_portal_username
from apps.core.approvals import create_approval_request
from apps.core.audit import log_activity
from apps.core.pagination import paginate_items
from apps.core.roles import admin_required
from apps.notifications.services import notify_user
from apps.core.limits import can_create_borrower



# ─── Role-scoping helpers (inserted by setup) ────────────────────────────────

def _get_request_role(request):
    """Return (role, agent_or_none) for the logged-in user."""
    from apps.core.roles import get_user_role, get_agent_for_user
    role  = get_user_role(request.user)
    agent = get_agent_for_user(request.user) if role == "agent" else None
    return role, agent


def _payment_webhook_authorized(request) -> bool:
    expected = (getattr(settings, "PAYMENT_WEBHOOK_SECRET", "") or "").strip()
    if not expected:
        return bool(
            getattr(settings, "DEBUG", False)
            and getattr(settings, "ALLOW_INSECURE_PAYMENT_WEBHOOKS", False)
        )

    auth_header = (request.headers.get("Authorization", "") or "").strip()
    if auth_header.lower().startswith("bearer "):
        auth_header = auth_header[7:].strip()

    candidates = [
        request.headers.get("X-Webhook-Secret", ""),
        request.headers.get("X-Webhook-Token", ""),
        request.headers.get("X-Payment-Webhook-Secret", ""),
        auth_header,
    ]
    return any(
        candidate and constant_time_compare(candidate.strip(), expected)
        for candidate in candidates
    )



def _generate_temp_password(length=10):
    """Generate a readable temporary password: 4 letters + 2 digits + 4 letters."""
    import random, string
    chars = string.ascii_letters + string.digits
    # Always include at least 2 digits and start with a letter
    letters = string.ascii_lowercase
    digits  = string.digits
    upper   = string.ascii_uppercase
    pwd = (
        random.choice(upper) +
        "".join(random.choices(letters, k=3)) +
        "".join(random.choices(digits, k=2)) +
        "".join(random.choices(letters, k=3)) +
        random.choice(upper)
    )
    return pwd


@admin_required
def reports_center(request):
    report_key = (request.GET.get("report") or "executive_summary").strip()
    report_key = get_report_definition(report_key)["key"]
    period = resolve_report_period(request.GET)
    report = build_report(report_key, period)
    export_format = (request.GET.get("format") or "").strip().lower()

    if export_format == "csv":
        return export_report_csv(report)
    if export_format == "excel":
        return export_report_excel(report, period=period)
    if export_format == "json":
        return export_report_json(report)
    if export_format == "pdf":
        html = render_to_string("loans/reports_pdf.html", {"report": report})
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{slugify(report["title"]) or "report"}-'
            f'{period["start"]:%Y%m%d}-{period["end"]:%Y%m%d}.pdf"'
        )
        return response

    context = {
        "report": report,
        "report_key": report_key,
        "report_groups": report_catalog_groups(),
        "period": period,
        "period_choices": PERIOD_CHOICES,
        "month_choices": MONTH_CHOICES,
        "quarter_choices": QUARTER_CHOICES,
        "half_year_choices": HALF_YEAR_CHOICES,
        "year_choices": available_years(),
        "export_formats": EXPORT_FORMATS,
    }
    return render(request, "loans/reports_center.html", context)


def _company_name():
    """Return current company name for use in messages and reports."""
    try:
        from apps.company.models import CompanyProfile
        return CompanyProfile.get_solo().company_name
    except Exception:
        return "MicroCredit"


def quantize_amount(value):
    return Decimal(value or Decimal("0.00")).quantize(Decimal("0.01"))


def build_category_summary_from_loans(loans):
    summary = []
    try:
        from apps.company.models import CompanyProfile
        tiers = CompanyProfile.get_solo().tiers_for_template
        choices = [(t["code"], t["label"]) for t in tiers]
    except Exception:
        choices = Loan.LOAN_CATEGORY_CHOICES
    for code, label in choices:
        category_loans = [loan for loan in loans if loan.loan_category == code]
        disbursed = sum((Decimal(loan.amount) for loan in category_loans), Decimal("0.00"))
        expected = sum((loan.total_expected_amount for loan in category_loans), Decimal("0.00"))
        roic = sum((loan.roic_amount for loan in category_loans), Decimal("0.00"))
        collected = sum((loan.total_paid_amount for loan in category_loans), Decimal("0.00"))
        balance = sum((loan.balance_amount for loan in category_loans), Decimal("0.00"))

        summary.append({
            "code": code,
            "label": label,
            "count": len(category_loans),
            "disbursed": quantize_amount(disbursed),
            "expected": quantize_amount(expected),
            "roic": quantize_amount(roic),
            "collected": quantize_amount(collected),
            "balance": quantize_amount(balance),
        })
    return summary

def _q(value):
    return Decimal(value or Decimal("0.00")).quantize(Decimal("0.01"))


def _ghs(value):
    value = _q(value)
    return f"GHS {value:,.2f}"


def _sms_amount(value):
    amount = _q(value)
    formatted = f"{amount:,.2f}"
    if formatted.endswith(".00"):
        return formatted[:-3]
    return formatted


def _first_name(full_name):
    parts = (full_name or "").strip().split()
    return parts[0] if parts else "Customer"


def _loan_duration_label(duration_weeks, duration_months=0, repayment_frequency="WEEKLY"):
    months = int(duration_months or 0)
    weeks = int(duration_weeks or 0)
    parts = []
    if months:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    if weeks:
        parts.append(f"{weeks} week{'s' if weeks != 1 else ''}")
    if not parts:
        parts.append("0 weeks")
    frequency = "daily" if repayment_frequency == "DAILY" else "weekly"
    return f"{', '.join(parts)} ({frequency})"


LOAN_APPROVAL_EXTRA_FIELDS = (
    "duration_months",
    "repayment_frequency",
    "sector",
    "sector_other",
    "loan_acquisition_date",
    "borrower_declaration_accepted",
    "borrower_signature_name",
    "borrower_signed_date",
    "guarantor_name",
    "guarantor_id_number",
    "guarantor_signature_name",
    "guarantor_signed_date",
    "collateral_type",
    "collateral_details",
    "collateral_estimated_value",
    "collateral_location",
    "collateral_borrower_consent_accepted",
    "collateral_borrower_signed_date",
    "collateral_guarantor_signature_name",
    "collateral_guarantor_signed_date",
    "application_received_by",
    "application_received_date",
    "approved_amount",
    "approved_repayment_plan",
    "loan_officer_signature_name",
    "approval_manager_signature_name",
    "approval_date",
)


def _loan_approval_payload(loan, *, borrower=None):
    borrower_obj = borrower or loan.borrower
    payload = {
        "borrower_id": borrower_obj.pk,
        "agent_id": loan.agent_name_id,
        "amount": str(loan.amount),
        "duration_months": int(loan.duration_months or 0),
        "duration_weeks": int(loan.duration_weeks),
        "start_date": loan.start_date.isoformat(),
        "weekly_payment": str(loan.weekly_payment),
    }
    for field in LOAN_APPROVAL_EXTRA_FIELDS:
        value = getattr(loan, field, None)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = str(value)
        payload[field] = value
    return payload


def _loan_external_debt_check_for_borrower(borrower, request):
    if borrower is None:
        return empty_cross_company_debt_check()
    return get_cross_company_debt_check(borrower=borrower)


def _external_debt_acknowledged(request) -> bool:
    return request.POST.get("confirm_external_debt_review") == "on"


def _build_new_loan_sms_messages(loan):
    borrower_name = _first_name(loan.borrower.full_name)
    agent_name = _first_name(loan.agent_name.name if loan.agent_name else "")
    amount = _sms_amount(loan.amount)
    weekly_payment = _sms_amount(loan.weekly_payment)
    duration = _loan_duration_label(loan.duration_weeks, loan.duration_months, loan.repayment_frequency)
    repayment_label = "Daily Payment" if loan.repayment_frequency == "DAILY" else "Weekly Payment"
    repayment_short = "Daily" if loan.repayment_frequency == "DAILY" else "Weekly"
    company_name = _company_name()

    borrower_msg = (
        f"{company_name} New Loan Alert!\n"
        f"Hello {borrower_name},\n"
        f"Your GHS {amount} loan is approved & disbursed.\n"
        f"{repayment_label}: GHS {weekly_payment}\n"
        f"Duration: {duration}\n"
        "Thank you."
    )
    agent_msg = (
        f"{company_name} Loan Alert!\n"
        f"Hello {agent_name},\n"
        f"GHS {amount} loan disbursed to {borrower_name}.\n"
        f"{repayment_short}: GHS {weekly_payment} | {duration}\n"
        "Kindly ensure repayment follow-up"
    )
    return borrower_msg, agent_msg


def _build_payment_create_sms_messages(loan, payment):
    borrower_name = _first_name(loan.borrower.full_name)
    agent_name = _first_name(loan.agent_name.name if loan.agent_name else "")
    payment_amount = _sms_amount(payment.amount)
    loan_amount = _sms_amount(loan.amount)
    weekly_payment = _sms_amount(loan.weekly_payment)
    weeks_paid = loan.actual_payments_count
    weeks_remaining = loan.outstanding_payments_count
    company_name = _company_name()

    borrower_msg = (
        f"{company_name} Payment Alert!\n"
        f"Hello {borrower_name},\n"
        f"Your payment of GHS {payment_amount} has been received successfully.\n"
        f"Loan: GHS {loan_amount} | Weekly: GHS {weekly_payment}\n"
        f"Weeks Paid: {weeks_paid} | Remaining: {weeks_remaining}\n"
        "Thank you."
    )
    agent_msg = (
        f"{company_name} Agent Alert!\n"
        f"Hello {agent_name},\n"
        f"Payment of GHS {payment_amount} received from {borrower_name}.\n"
        f"Loan: GHS {loan_amount} | Weekly: GHS {weekly_payment}\n"
        f"Weeks Paid: {weeks_paid} | Remaining: {weeks_remaining}\n"
        "Please update records. Thank you."
    )
    return borrower_msg, agent_msg

@staff_member_required
def business_state_pdf_report(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    last_30_days = today - timezone.timedelta(days=30)
    last_7_days = today - timezone.timedelta(days=7)

    loans_qs = Loan.objects.select_related("borrower", "agent_name").prefetch_related("payments")
    active_loans_qs = loans_qs.filter(status="ACTIVE")
    closed_loans_qs = loans_qs.filter(status="CLOSED")
    default_loans_qs = loans_qs.filter(status="DEFAULT")

    borrowers_qs = Borrower.objects.prefetch_related("loans")
    agents_qs = Agent.objects.all()
    payments_qs = Payment.objects.filter(is_void=False).select_related("loan", "loan__borrower", "loan__agent_name")

    total_loans = loans_qs.count()
    active_loans = active_loans_qs.count()
    closed_loans = closed_loans_qs.count()
    default_loans = default_loans_qs.count()

    total_borrowers = borrowers_qs.count()
    active_borrowers = borrowers_qs.filter(status="ACTIVE").count()
    closed_borrowers = borrowers_qs.filter(status="CLOSED").count()
    bad_borrowers = borrowers_qs.filter(status="BAD").count()

    total_agents = agents_qs.count()
    agents_with_loans = agents_qs.filter(loans__isnull=False).distinct().count()

    total_disbursed = _q(loans_qs.aggregate(s=Sum("amount"))["s"])
    active_disbursed = _q(active_loans_qs.aggregate(s=Sum("amount"))["s"])

    total_expected = sum((loan.total_expected_amount for loan in loans_qs), Decimal("0.00"))
    active_expected = sum((loan.total_expected_amount for loan in active_loans_qs), Decimal("0.00"))
    total_roic = sum((loan.roic_amount for loan in loans_qs), Decimal("0.00"))
    active_roic = sum((loan.roic_amount for loan in active_loans_qs), Decimal("0.00"))

    total_collected = _q(payments_qs.aggregate(s=Sum("amount"))["s"])
    total_principal_collected = _q(payments_qs.aggregate(s=Sum("principal_paid"))["s"])
    total_roic_collected = _q(payments_qs.aggregate(s=Sum("roic_paid"))["s"])

    today_collected = _q(payments_qs.filter(payment_date=today).aggregate(s=Sum("amount"))["s"])
    week_collected = _q(payments_qs.filter(payment_date__gte=last_7_days, payment_date__lte=today).aggregate(s=Sum("amount"))["s"])
    month_collected = _q(payments_qs.filter(payment_date__gte=month_start, payment_date__lte=today).aggregate(s=Sum("amount"))["s"])

    month_disbursed = _q(loans_qs.filter(created_at__date__gte=month_start, created_at__date__lte=today).aggregate(s=Sum("amount"))["s"])
    loans_last_30_days = loans_qs.filter(created_at__date__gte=last_30_days, created_at__date__lte=today).count()

    total_expected = _q(total_expected)
    active_expected = _q(active_expected)
    total_roic = _q(total_roic)
    active_roic = _q(active_roic)

    total_outstanding = _q(total_expected - total_collected)
    active_outstanding = _q(active_expected - _q(payments_qs.filter(loan__status="ACTIVE").aggregate(s=Sum("amount"))["s"]))
    principal_outstanding = _q(total_disbursed - total_principal_collected)
    roic_outstanding = _q(total_roic - total_roic_collected)

    collection_rate = _q((total_collected / total_expected * Decimal("100")) if total_expected > 0 else Decimal("0.00"))
    avg_loan_size = _q((total_disbursed / Decimal(total_loans)) if total_loans > 0 else Decimal("0.00"))

    # PAR proxy
    seasoned_cutoff = today - timezone.timedelta(weeks=4)
    par_amount = Decimal("0.00")
    par_count = 0
    for loan in active_loans_qs:
        if loan.balance_amount > 0 and loan.start_date and loan.start_date <= seasoned_cutoff:
            par_amount += loan.balance_amount
            par_count += 1
    par_amount = _q(par_amount)
    par_rate = _q((par_amount / active_expected * Decimal("100")) if active_expected > 0 else Decimal("0.00"))

    # Loan category breakdown
    category_summary = []
    try:
        from apps.company.models import CompanyProfile
        _tiers = CompanyProfile.get_solo().tiers_for_template
        _cat_choices = [(t["code"], t["label"]) for t in _tiers]
    except Exception:
        _cat_choices = Loan.LOAN_CATEGORY_CHOICES
    if _cat_choices:
        for value, label in _cat_choices:
            cat_loans = loans_qs.filter(loan_category=value)
            cat_count = cat_loans.count()
            cat_disbursed = _q(cat_loans.aggregate(s=Sum("amount"))["s"])
            cat_expected = _q(sum((loan.total_expected_amount for loan in cat_loans), Decimal("0.00")))
            cat_collected = _q(sum((loan.total_paid_amount for loan in cat_loans), Decimal("0.00")))
            cat_balance = _q(sum((loan.balance_amount for loan in cat_loans), Decimal("0.00")))
            category_summary.append({
                "label": label,
                "count": cat_count,
                "disbursed": cat_disbursed,
                "expected": cat_expected,
                "collected": cat_collected,
                "balance": cat_balance,
            })

    # Agent leaderboard
    agent_rows = []
    for agent in agents_qs.order_by("name"):
        agent_loans = loans_qs.filter(agent_name=agent)
        if not agent_loans.exists():
            continue

        disbursed = _q(agent_loans.aggregate(s=Sum("amount"))["s"])
        expected = _q(sum((loan.total_expected_amount for loan in agent_loans), Decimal("0.00")))
        collected = _q(sum((loan.total_paid_amount for loan in agent_loans), Decimal("0.00")))
        balance = _q(sum((loan.balance_amount for loan in agent_loans), Decimal("0.00")))
        principal_out = _q(sum((loan.principal_outstanding for loan in agent_loans), Decimal("0.00")))
        roic_out = _q(sum((loan.roic_outstanding for loan in agent_loans), Decimal("0.00")))
        rate = _q((collected / expected * Decimal("100")) if expected > 0 else Decimal("0.00"))

        agent_rows.append({
            "name": agent.name,
            "loans": agent_loans.count(),
            "borrowers": agent_loans.values("borrower_id").distinct().count(),
            "disbursed": disbursed,
            "expected": expected,
            "collected": collected,
            "balance": balance,
            "principal_out": principal_out,
            "roic_out": roic_out,
            "rate": rate,
        })

    agent_rows = sorted(agent_rows, key=lambda x: x["balance"], reverse=True)[:12]

    # Top risky loans
    top_risky_loans = []
    for loan in loans_qs:
        top_risky_loans.append({
            "id": loan.id,
            "borrower": loan.borrower.full_name,
            "agent": loan.agent_name.name if loan.agent_name else "-",
            "category": loan.get_loan_category_display() if hasattr(loan, "get_loan_category_display") else "-",
            "status": loan.status,
            "borrower_status": loan.borrower.status,
            "principal": _q(loan.amount),
            "expected": _q(loan.total_expected_amount),
            "collected": _q(loan.total_paid_amount),
            "balance": _q(loan.balance_amount),
            "overdue_weeks": loan.overdue_weeks,
        })
    top_risky_loans = sorted(
        top_risky_loans,
        key=lambda x: (x["status"] != "DEFAULT", -x["overdue_weeks"], -x["balance"])
    )[:15]

    # Top borrowers by exposure
    borrower_rows = []
    for borrower in borrowers_qs:
        borrower_loans = borrower.loans.all()
        if not borrower_loans:
            continue
        borrower_rows.append({
            "name": borrower.full_name,
            "status": borrower.status,
            "loans": len(borrower_loans),
            "disbursed": _q(sum((loan.amount for loan in borrower_loans), Decimal("0.00"))),
            "expected": _q(sum((loan.total_expected_amount for loan in borrower_loans), Decimal("0.00"))),
            "collected": _q(sum((loan.total_paid_amount for loan in borrower_loans), Decimal("0.00"))),
            "balance": _q(sum((loan.balance_amount for loan in borrower_loans), Decimal("0.00"))),
        })
    borrower_rows = sorted(borrower_rows, key=lambda x: x["balance"], reverse=True)[:15]

    generated_at = timezone.now()

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        @page {{
          size: A4;
          margin: 18mm 14mm 18mm 14mm;
        }}
        body {{
          font-family: Arial, Helvetica, sans-serif;
          color: #0f172a;
          font-size: 11px;
          line-height: 1.45;
        }}
        .cover {{
          padding: 28px;
          border-radius: 20px;
          color: white;
          background:
            radial-gradient(circle at top right, rgba(14,165,233,.25), transparent 30%),
            radial-gradient(circle at left center, rgba(37,99,235,.18), transparent 28%),
            linear-gradient(135deg, #0f172a 0%, #1e3a8a 52%, #0ea5e9 100%);
          margin-bottom: 18px;
        }}
        h1 {{
          font-size: 28px;
          margin: 0 0 8px 0;
        }}
        .sub {{
          font-size: 13px;
          opacity: .95;
        }}
        .meta {{
          margin-top: 14px;
          font-size: 12px;
          opacity: .95;
        }}
        h2 {{
          font-size: 16px;
          margin: 20px 0 8px 0;
          color: #0f172a;
          padding-bottom: 6px;
          border-bottom: 1px solid #dbe5f1;
        }}
        .kpi-grid {{
          display: table;
          width: 100%;
          border-spacing: 8px;
          margin: 6px 0 10px 0;
        }}
        .kpi-row {{
          display: table-row;
        }}
        .kpi {{
          display: table-cell;
          width: 25%;
          vertical-align: top;
          background: #f8fbff;
          border: 1px solid #dbe5f1;
          border-radius: 12px;
          padding: 12px;
        }}
        .kpi-label {{
          font-size: 10px;
          color: #64748b;
          text-transform: uppercase;
          font-weight: bold;
        }}
        .kpi-value {{
          margin-top: 6px;
          font-size: 18px;
          font-weight: bold;
          color: #0f172a;
        }}
        .kpi-sub {{
          margin-top: 5px;
          color: #64748b;
          font-size: 10px;
        }}
        table {{
          width: 100%;
          border-collapse: collapse;
          margin-top: 10px;
        }}
        th {{
          background: #eff6ff;
          color: #1e3a8a;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: .2px;
          border: 1px solid #dbe5f1;
          padding: 8px;
          text-align: left;
        }}
        td {{
          border: 1px solid #e2e8f0;
          padding: 8px;
          vertical-align: top;
        }}
        .right {{
          text-align: right;
        }}
        .center {{
          text-align: center;
        }}
        .badge {{
          display: inline-block;
          padding: 3px 8px;
          border-radius: 999px;
          font-size: 10px;
          font-weight: bold;
        }}
        .green {{ background: #dcfce7; color: #166534; }}
        .amber {{ background: #fef3c7; color: #92400e; }}
        .red {{ background: #fee2e2; color: #991b1b; }}
        .blue {{ background: #dbeafe; color: #1d4ed8; }}
        .note {{
          background: #f8fafc;
          border: 1px solid #e2e8f0;
          border-left: 4px solid #2563eb;
          padding: 12px 14px;
          border-radius: 10px;
          margin-top: 10px;
        }}
        .small {{
          font-size: 10px;
          color: #64748b;
        }}
        .page-break {{
          page-break-before: always;
        }}
      </style>
    </head>
    <body>

      <div class="cover">
        <h1>{_company_name()} Business State Report</h1>
        <div class="sub">
          Comprehensive executive report on the current operating state of the micro-credit business,
          including portfolio health, collections, risk exposure, borrower quality, agent productivity,
          and category concentration.
        </div>
        <div class="meta">
          Report Date: {today.strftime("%d %B %Y")}<br>
          Generated At: {generated_at.strftime("%d %B %Y %H:%M")}<br>
          Prepared For: Management / Executive Decision-Making
        </div>
      </div>

      <h2>1. Executive Snapshot</h2>
      <div class="kpi-grid">
        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-label">Total Disbursed</div>
            <div class="kpi-value">{_ghs(total_disbursed)}</div>
            <div class="kpi-sub">Average loan size {_ghs(avg_loan_size)}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Total Expected</div>
            <div class="kpi-value">{_ghs(total_expected)}</div>
            <div class="kpi-sub">Principal + ROIC due</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Total Collected</div>
            <div class="kpi-value">{_ghs(total_collected)}</div>
            <div class="kpi-sub">Collection rate {collection_rate}%</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Total Outstanding</div>
            <div class="kpi-value">{_ghs(total_outstanding)}</div>
            <div class="kpi-sub">Current total exposure</div>
          </div>
        </div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-label">Loans</div>
            <div class="kpi-value">{total_loans}</div>
            <div class="kpi-sub">Active {active_loans} · Closed {closed_loans} · Default {default_loans}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Borrowers</div>
            <div class="kpi-value">{total_borrowers}</div>
            <div class="kpi-sub">Active {active_borrowers} · Closed {closed_borrowers} · Bad {bad_borrowers}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Agents</div>
            <div class="kpi-value">{total_agents}</div>
            <div class="kpi-sub">Agents with loans {agents_with_loans}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">PAR Proxy</div>
            <div class="kpi-value">{par_rate}%</div>
            <div class="kpi-sub">PAR amount {_ghs(par_amount)} · PAR count {par_count}</div>
          </div>
        </div>
      </div>

      <div class="note">
        <strong>Management Interpretation:</strong>
        The portfolio currently holds <strong>{_ghs(total_outstanding)}</strong> in total outstanding exposure against
        <strong>{_ghs(total_disbursed)}</strong> disbursed principal. The current recovery rate is
        <strong>{collection_rate}%</strong>. Default exposure stands at <strong>{default_loans}</strong> loans, while
        borrower-quality risk is reflected by <strong>{bad_borrowers}</strong> bad-status borrowers.
      </div>

      <h2>2. Recovery & Liquidity Position</h2>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th class="right">Amount</th>
            <th>Interpretation</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Total Principal Collected</td><td class="right">{_ghs(total_principal_collected)}</td><td>Recovered against principal disbursed</td></tr>
          <tr><td>Total ROIC Collected</td><td class="right">{_ghs(total_roic_collected)}</td><td>Recovered interest / return component</td></tr>
          <tr><td>Principal Outstanding</td><td class="right">{_ghs(principal_outstanding)}</td><td>Remaining unrecovered principal</td></tr>
          <tr><td>ROIC Outstanding</td><td class="right">{_ghs(roic_outstanding)}</td><td>Remaining unrecovered ROIC</td></tr>
          <tr><td>Active Portfolio Outstanding</td><td class="right">{_ghs(active_outstanding)}</td><td>Exposure still open on active loans</td></tr>
          <tr><td>Collected Today</td><td class="right">{_ghs(today_collected)}</td><td>Same-day inflow snapshot</td></tr>
          <tr><td>Collected Last 7 Days</td><td class="right">{_ghs(week_collected)}</td><td>Short-term cash recovery trend</td></tr>
          <tr><td>Collected This Month</td><td class="right">{_ghs(month_collected)}</td><td>Month-to-date collections</td></tr>
          <tr><td>Disbursed This Month</td><td class="right">{_ghs(month_disbursed)}</td><td>Month-to-date loan creation volume</td></tr>
        </tbody>
      </table>

      <h2>3. Portfolio Structure</h2>
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th class="center">Count</th>
            <th class="right">Principal / Exposure View</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><span class="badge amber">ACTIVE</span></td>
            <td class="center">{active_loans}</td>
            <td class="right">{_ghs(active_disbursed)} disbursed · {_ghs(active_expected)} expected · {_ghs(active_roic)} ROIC</td>
          </tr>
          <tr>
            <td><span class="badge green">CLOSED</span></td>
            <td class="center">{closed_loans}</td>
            <td class="right">Fully repaid or no remaining balance</td>
          </tr>
          <tr>
            <td><span class="badge red">DEFAULT</span></td>
            <td class="center">{default_loans}</td>
            <td class="right">Highest recovery attention required</td>
          </tr>
        </tbody>
      </table>

      <h2>4. Loan Category Concentration</h2>
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th class="center">Loans</th>
            <th class="right">Disbursed</th>
            <th class="right">Expected</th>
            <th class="right">Collected</th>
            <th class="right">Balance</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
              f"<tr><td>{c['label']}</td><td class='center'>{c['count']}</td><td class='right'>{_ghs(c['disbursed'])}</td><td class='right'>{_ghs(c['expected'])}</td><td class='right'>{_ghs(c['collected'])}</td><td class='right'>{_ghs(c['balance'])}</td></tr>"
              for c in category_summary
          ) or "<tr><td colspan='6'>No category data found.</td></tr>"}
        </tbody>
      </table>

      <div class="page-break"></div>

      <h2>5. Agent Performance & Exposure</h2>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th class="center">Loans</th>
            <th class="center">Borrowers</th>
            <th class="right">Disbursed</th>
            <th class="right">Expected</th>
            <th class="right">Collected</th>
            <th class="right">Balance</th>
            <th class="right">Rate</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
              f"<tr><td>{a['name']}</td><td class='center'>{a['loans']}</td><td class='center'>{a['borrowers']}</td><td class='right'>{_ghs(a['disbursed'])}</td><td class='right'>{_ghs(a['expected'])}</td><td class='right'>{_ghs(a['collected'])}</td><td class='right'>{_ghs(a['balance'])}</td><td class='right'>{a['rate']}%</td></tr>"
              for a in agent_rows
          ) or "<tr><td colspan='8'>No agent data found.</td></tr>"}
        </tbody>
      </table>

      <h2>6. Highest Risk / Highest Priority Loans</h2>
      <table>
        <thead>
          <tr>
            <th>Loan</th>
            <th>Borrower</th>
            <th>Agent</th>
            <th>Category</th>
            <th>Status</th>
            <th>Borrower Status</th>
            <th class="right">Balance</th>
            <th class="center">Overdue Weeks</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
              f"<tr><td>#{r['id']}</td><td>{r['borrower']}</td><td>{r['agent']}</td><td>{r['category']}</td><td>{r['status']}</td><td>{r['borrower_status']}</td><td class='right'>{_ghs(r['balance'])}</td><td class='center'>{r['overdue_weeks']}</td></tr>"
              for r in top_risky_loans
          ) or "<tr><td colspan='8'>No risky loan data found.</td></tr>"}
        </tbody>
      </table>

      <h2>7. Largest Borrower Exposures</h2>
      <table>
        <thead>
          <tr>
            <th>Borrower</th>
            <th>Status</th>
            <th class="center">Loans</th>
            <th class="right">Disbursed</th>
            <th class="right">Expected</th>
            <th class="right">Collected</th>
            <th class="right">Balance</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
              f"<tr><td>{b['name']}</td><td>{b['status']}</td><td class='center'>{b['loans']}</td><td class='right'>{_ghs(b['disbursed'])}</td><td class='right'>{_ghs(b['expected'])}</td><td class='right'>{_ghs(b['collected'])}</td><td class='right'>{_ghs(b['balance'])}</td></tr>"
              for b in borrower_rows
          ) or "<tr><td colspan='7'>No borrower exposure data found.</td></tr>"}
        </tbody>
      </table>

      <h2>8. Executive Decision Notes</h2>
      <div class="note">
        <strong>Suggested management actions based on current data:</strong>
        <br><br>
        1. Intensify collections and follow-up on default loans and high-overdue accounts immediately.
        <br>
        2. Review agents with high balance exposure but weaker recovery rates.
        <br>
        3. Evaluate whether higher-value categories are producing acceptable recovery quality relative to exposure.
        <br>
        4. Review top borrower exposures for restructuring, escalation, or focused monitoring.
        <br>
        5. Compare new monthly disbursement volume against monthly collections to manage liquidity discipline.
      </div>

      <div class="small" style="margin-top:20px;">
        This document is system-generated from the live {_company_name()} portfolio as of {generated_at.strftime("%d %B %Y %H:%M")}.
      </div>

    </body>
    </html>
    """

    pdf_file = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()

    filename = f"{_company_name().lower().replace(' ', '_')}_business_state_report_{today.strftime('%Y%m%d')}.pdf"
    response = HttpResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response

@login_required
def dashboard(request):
    # Agents → redirect to their own detail page
    _role, _agent = _get_request_role(request)
    if _role == "agent" and _agent:
        return redirect("agent_detail", pk=_agent.pk)
    if _role == "borrower":
        return redirect("borrower:portal")

    today = timezone.localdate()

    loans_qs = Loan.objects.select_related("borrower", "agent_name").prefetch_related("payments")
    borrowers_qs = Borrower.objects.all()
    payments_qs = (
        Payment.objects
        .filter(is_void=False)
        .select_related("loan", "loan__borrower", "loan__agent_name")
        .order_by("-created_at")
    )

    loans_list_all = list(loans_qs)
    borrowers_list = list(borrowers_qs)
    payments_list = list(payments_qs)

    active_loans_list = [loan for loan in loans_list_all if loan.status == "ACTIVE"]
    closed_loans_list = [loan for loan in loans_list_all if loan.status == "CLOSED"]
    default_loans_list = [loan for loan in loans_list_all if loan.status == "DEFAULT"]

    borrowers_count = len(borrowers_list)
    borrower_active_count = sum(1 for borrower in borrowers_list if borrower.status == "ACTIVE")
    borrower_closed_count = sum(1 for borrower in borrowers_list if borrower.status == "CLOSED")
    borrower_bad_count = sum(1 for borrower in borrowers_list if borrower.status == "BAD")

    agents_count = Agent.objects.count()

    total_loans = len(loans_list_all)
    active_count = len(active_loans_list)
    closed_count = len(closed_loans_list)
    default_count = len(default_loans_list)

    total_disbursed = quantize_amount(sum((loan.amount for loan in loans_list_all), Decimal("0.00")))
    active_disbursed = quantize_amount(sum((loan.amount for loan in active_loans_list), Decimal("0.00")))
    total_expected = quantize_amount(sum((loan.total_expected_amount for loan in loans_list_all), Decimal("0.00")))
    active_expected = quantize_amount(sum((loan.total_expected_amount for loan in active_loans_list), Decimal("0.00")))
    total_roic = quantize_amount(sum((loan.roic_amount for loan in loans_list_all), Decimal("0.00")))
    active_roic = quantize_amount(sum((loan.roic_amount for loan in active_loans_list), Decimal("0.00")))

    total_collected = quantize_amount(sum((payment.amount for payment in payments_list), Decimal("0.00")))
    total_principal_collected = quantize_amount(sum((payment.principal_paid for payment in payments_list), Decimal("0.00")))
    total_roic_collected = quantize_amount(sum((payment.roic_paid for payment in payments_list), Decimal("0.00")))
    total_payments_count = len(payments_list)

    default_payments_list = [payment for payment in payments_list if payment.loan.status == "DEFAULT"]
    default_collected = quantize_amount(sum((payment.amount for payment in default_payments_list), Decimal("0.00")))
    default_roic_collected = quantize_amount(sum((payment.roic_paid for payment in default_payments_list), Decimal("0.00")))

    last7 = today - timezone.timedelta(days=7)
    last_30_days = today - timezone.timedelta(days=30)
    last_90_days = today - timezone.timedelta(days=90)
    month_start = today.replace(day=1)

    today_collected = quantize_amount(sum((payment.amount for payment in payments_list if payment.payment_date == today), Decimal("0.00")))
    week_collected = quantize_amount(sum((payment.amount for payment in payments_list if last7 <= payment.payment_date <= today), Decimal("0.00")))
    month_collected = quantize_amount(sum((payment.amount for payment in payments_list if month_start <= payment.payment_date <= today), Decimal("0.00")))
    last_30_collected = quantize_amount(sum((payment.amount for payment in payments_list if last_30_days <= payment.payment_date <= today), Decimal("0.00")))

    month_disbursed = quantize_amount(sum((loan.amount for loan in loans_list_all if month_start <= loan.created_at.date() <= today), Decimal("0.00")))
    last_30_disbursed = quantize_amount(sum((loan.amount for loan in loans_list_all if last_30_days <= loan.created_at.date() <= today), Decimal("0.00")))
    month_new_loans = sum(1 for loan in loans_list_all if month_start <= loan.created_at.date() <= today)
    last_30_new_loans = sum(1 for loan in loans_list_all if last_30_days <= loan.created_at.date() <= today)
    month_new_borrowers = sum(1 for borrower in borrowers_list if month_start <= borrower.created_at.date() <= today)
    last_30_new_borrowers = sum(1 for borrower in borrowers_list if last_30_days <= borrower.created_at.date() <= today)

    active_payments_list = [payment for payment in payments_list if payment.loan.status == "ACTIVE"]
    active_collected = quantize_amount(sum((payment.amount for payment in active_payments_list), Decimal("0.00")))
    active_principal_collected = quantize_amount(sum((payment.principal_paid for payment in active_payments_list), Decimal("0.00")))
    active_roic_collected = quantize_amount(sum((payment.roic_paid for payment in active_payments_list), Decimal("0.00")))

    total_outstanding_active = quantize_amount(active_expected - active_collected)
    if total_outstanding_active < 0:
        total_outstanding_active = Decimal("0.00")

    active_principal_outstanding = quantize_amount(active_disbursed - active_principal_collected)
    if active_principal_outstanding < 0:
        active_principal_outstanding = Decimal("0.00")

    active_roic_outstanding = quantize_amount(active_roic - active_roic_collected)
    if active_roic_outstanding < 0:
        active_roic_outstanding = Decimal("0.00")

    total_equity_outstanding = quantize_amount(total_disbursed - total_collected)
    if total_equity_outstanding < 0:
        total_equity_outstanding = Decimal("0.00")

    total_principal_outstanding = quantize_amount(total_disbursed - total_collected + total_roic_collected)
    if total_principal_outstanding < 0:
        total_principal_outstanding = Decimal("0.00")

    total_roic_outstanding = quantize_amount(total_roic - total_roic_collected)
    if total_roic_outstanding < 0:
        total_roic_outstanding = Decimal("0.00")

    default_disbursed = quantize_amount(sum((loan.amount for loan in default_loans_list), Decimal("0.00")))
    default_expected = quantize_amount(sum((loan.total_expected_amount for loan in default_loans_list), Decimal("0.00")))
    default_roic_expected = quantize_amount(sum((loan.roic_amount for loan in default_loans_list), Decimal("0.00")))

    total_default = quantize_amount(default_expected - default_collected)
    if total_default < 0:
        total_default = Decimal("0.00")

    principal_default = quantize_amount(default_disbursed - default_collected + default_roic_collected)
    if principal_default < 0:
        principal_default = Decimal("0.00")

    equity_default = quantize_amount(default_disbursed - default_collected)
    if equity_default < 0:
        equity_default = Decimal("0.00")

    collections_rate = (
        (total_collected / total_expected * Decimal("100")).quantize(Decimal("0.01"))
        if total_expected > 0 else Decimal("0.00")
    )
    active_collection_rate = (
        (active_collected / active_expected * Decimal("100")).quantize(Decimal("0.01"))
        if active_expected > 0 else Decimal("0.00")
    )
    avg_loan_size = (
        (total_disbursed / Decimal(total_loans)).quantize(Decimal("0.01"))
        if total_loans > 0 else Decimal("0.00")
    )

    default_rate_count = (
        (Decimal(default_count) / Decimal(total_loans) * Decimal("100")).quantize(Decimal("0.01"))
        if total_loans > 0 else Decimal("0.00")
    )
    default_rate_balance = (
        (total_default / total_expected * Decimal("100")).quantize(Decimal("0.01"))
        if total_expected > 0 else Decimal("0.00")
    )

    seasoned_cutoff = today - timezone.timedelta(weeks=4)
    par_amount = Decimal("0.00")
    par_count = 0
    overdue_watch_count = 0
    overdue_total_amount = Decimal("0.00")
    critical_overdue_count = 0
    for loan in active_loans_list:
        if loan.overdue_weeks > 0:
            overdue_watch_count += 1
            overdue_total_amount += loan.balance_amount
        if loan.is_overdue_more_than_6_weeks:
            critical_overdue_count += 1
        if loan.balance_amount > 0 and loan.start_date and loan.start_date <= seasoned_cutoff:
            par_amount += loan.balance_amount
            par_count += 1

    par_amount = quantize_amount(par_amount)
    overdue_total_amount = quantize_amount(overdue_total_amount)
    par_rate = (
        (par_amount / active_expected * Decimal("100")).quantize(Decimal("0.01"))
        if active_expected > 0 else Decimal("0.00")
    )

    recent_loans = loans_list_all[:12]
    recent_payments = payments_list[:12]

    agent_map = {}
    borrower_map = {}
    location_map = {}
    group_map = {}

    for loan in loans_list_all:
        agent = loan.agent_name
        borrower = loan.borrower
        agent_key = agent.pk if agent else 0
        borrower_key = borrower.pk if borrower else 0
        location_key = (borrower.location or "Unknown").strip() if borrower else "Unknown"
        group_key = (borrower.group_name or "Ungrouped").strip() if borrower else "Ungrouped"

        agent_entry = agent_map.setdefault(agent_key, {
            "agent": agent,
            "borrower_ids": set(),
            "loans_count": 0,
            "active_loans": 0,
            "closed_loans": 0,
            "default_loans": 0,
            "disbursed": Decimal("0.00"),
            "expected": Decimal("0.00"),
            "roic_expected": Decimal("0.00"),
            "principal_outstanding": Decimal("0.00"),
            "roic_outstanding": Decimal("0.00"),
            "total_outstanding": Decimal("0.00"),
            "collected": Decimal("0.00"),
            "principal_collected": Decimal("0.00"),
            "roic_collected": Decimal("0.00"),
            "payment_count": 0,
            "latest_payment": None,
        })
        agent_entry["borrower_ids"].add(borrower_key)
        agent_entry["loans_count"] += 1
        if loan.status == "ACTIVE":
            agent_entry["active_loans"] += 1
        elif loan.status == "CLOSED":
            agent_entry["closed_loans"] += 1
        elif loan.status == "DEFAULT":
            agent_entry["default_loans"] += 1
        agent_entry["disbursed"] += loan.amount
        agent_entry["expected"] += loan.total_expected_amount
        agent_entry["roic_expected"] += loan.roic_amount
        agent_entry["principal_outstanding"] += loan.principal_outstanding
        agent_entry["roic_outstanding"] += loan.roic_outstanding
        agent_entry["total_outstanding"] += loan.balance_amount

        borrower_entry = borrower_map.setdefault(borrower_key, {
            "borrower": borrower,
            "agent_ids": set(),
            "total_loans": 0,
            "active_loans": 0,
            "closed_loans": 0,
            "default_loans": 0,
            "disbursed": Decimal("0.00"),
            "expected": Decimal("0.00"),
            "collected": Decimal("0.00"),
            "principal_outstanding": Decimal("0.00"),
            "roic_outstanding": Decimal("0.00"),
            "total_outstanding": Decimal("0.00"),
            "max_overdue_weeks": 0,
            "latest_loan": None,
            "latest_payment": None,
        })
        borrower_entry["agent_ids"].add(agent_key)
        borrower_entry["total_loans"] += 1
        if loan.status == "ACTIVE":
            borrower_entry["active_loans"] += 1
        elif loan.status == "CLOSED":
            borrower_entry["closed_loans"] += 1
        elif loan.status == "DEFAULT":
            borrower_entry["default_loans"] += 1
        borrower_entry["disbursed"] += loan.amount
        borrower_entry["expected"] += loan.total_expected_amount
        borrower_entry["collected"] += loan.total_paid_amount
        borrower_entry["principal_outstanding"] += loan.principal_outstanding
        borrower_entry["roic_outstanding"] += loan.roic_outstanding
        borrower_entry["total_outstanding"] += loan.balance_amount
        borrower_entry["max_overdue_weeks"] = max(borrower_entry["max_overdue_weeks"], loan.overdue_weeks)
        if borrower_entry["latest_loan"] is None or loan.created_at > borrower_entry["latest_loan"]:
            borrower_entry["latest_loan"] = loan.created_at

        location_entry = location_map.setdefault(location_key, {
            "name": location_key,
            "borrower_ids": set(),
            "loan_count": 0,
            "default_loans": 0,
            "disbursed": Decimal("0.00"),
            "expected": Decimal("0.00"),
            "collected": Decimal("0.00"),
            "total_outstanding": Decimal("0.00"),
        })
        location_entry["borrower_ids"].add(borrower_key)
        location_entry["loan_count"] += 1
        if loan.status == "DEFAULT":
            location_entry["default_loans"] += 1
        location_entry["disbursed"] += loan.amount
        location_entry["expected"] += loan.total_expected_amount
        location_entry["collected"] += loan.total_paid_amount
        location_entry["total_outstanding"] += loan.balance_amount

        group_entry = group_map.setdefault(group_key, {
            "name": group_key,
            "borrower_ids": set(),
            "loan_count": 0,
            "default_loans": 0,
            "disbursed": Decimal("0.00"),
            "expected": Decimal("0.00"),
            "collected": Decimal("0.00"),
            "total_outstanding": Decimal("0.00"),
        })
        group_entry["borrower_ids"].add(borrower_key)
        group_entry["loan_count"] += 1
        if loan.status == "DEFAULT":
            group_entry["default_loans"] += 1
        group_entry["disbursed"] += loan.amount
        group_entry["expected"] += loan.total_expected_amount
        group_entry["collected"] += loan.total_paid_amount
        group_entry["total_outstanding"] += loan.balance_amount

    for payment in payments_list:
        agent = payment.loan.agent_name
        borrower = payment.loan.borrower
        agent_key = agent.pk if agent else 0
        borrower_key = borrower.pk if borrower else 0

        if agent_key in agent_map:
            agent_entry = agent_map[agent_key]
            agent_entry["collected"] += payment.amount
            agent_entry["principal_collected"] += payment.principal_paid
            agent_entry["roic_collected"] += payment.roic_paid
            agent_entry["payment_count"] += 1
            if agent_entry["latest_payment"] is None or payment.created_at > agent_entry["latest_payment"]:
                agent_entry["latest_payment"] = payment.created_at

        if borrower_key in borrower_map:
            borrower_entry = borrower_map[borrower_key]
            if borrower_entry["latest_payment"] is None or payment.created_at > borrower_entry["latest_payment"]:
                borrower_entry["latest_payment"] = payment.created_at

    agent_board = []
    for entry in agent_map.values():
        rate = (
            (entry["collected"] / entry["expected"] * Decimal("100")).quantize(Decimal("0.01"))
            if entry["expected"] > 0 else Decimal("0.00")
        )
        avg_agent_loan = (
            (entry["disbursed"] / Decimal(entry["loans_count"])).quantize(Decimal("0.01"))
            if entry["loans_count"] > 0 else Decimal("0.00")
        )
        agent_board.append({
            "agent": entry["agent"],
            "agent_id": entry["agent"].pk if entry["agent"] else None,
            "agent_name": entry["agent"].name if entry["agent"] else "Unknown Agent",
            "borrowers_count": len(entry["borrower_ids"]),
            "loans_count": entry["loans_count"],
            "active_loans": entry["active_loans"],
            "closed_loans": entry["closed_loans"],
            "default_loans": entry["default_loans"],
            "disbursed": quantize_amount(entry["disbursed"]),
            "expected": quantize_amount(entry["expected"]),
            "roic_expected": quantize_amount(entry["roic_expected"]),
            "collected": quantize_amount(entry["collected"]),
            "principal_collected": quantize_amount(entry["principal_collected"]),
            "roic_collected": quantize_amount(entry["roic_collected"]),
            "principal_outstanding": quantize_amount(entry["principal_outstanding"]),
            "roic_outstanding": quantize_amount(entry["roic_outstanding"]),
            "total_outstanding": quantize_amount(entry["total_outstanding"]),
            "payment_count": entry["payment_count"],
            "latest_payment": entry["latest_payment"],
            "avg_loan_size": avg_agent_loan,
            "collection_rate": rate,
        })
    agent_board.sort(key=lambda row: (-row["total_outstanding"], -row["disbursed"], row["agent_name"].lower()))
    top_collecting_agents = sorted(
        [row for row in agent_board if row["expected"] > 0],
        key=lambda row: (-row["collection_rate"], -row["collected"], row["agent_name"].lower())
    )[:6]
    weak_agents = sorted(
        [row for row in agent_board if row["expected"] > 0 and row["total_outstanding"] > 0],
        key=lambda row: (row["collection_rate"], -row["default_loans"], -row["total_outstanding"], row["agent_name"].lower())
    )[:6]
    agent_board = agent_board[:12]

    borrower_exposure_board = []
    for borrower in borrowers_list:
        entry = borrower_map.get(borrower.pk, {
            "borrower": borrower,
            "agent_ids": set(),
            "total_loans": 0,
            "active_loans": 0,
            "closed_loans": 0,
            "default_loans": 0,
            "disbursed": Decimal("0.00"),
            "expected": Decimal("0.00"),
            "collected": Decimal("0.00"),
            "principal_outstanding": Decimal("0.00"),
            "roic_outstanding": Decimal("0.00"),
            "total_outstanding": Decimal("0.00"),
            "max_overdue_weeks": 0,
            "latest_loan": None,
            "latest_payment": None,
        })
        rate = (
            (entry["collected"] / entry["expected"] * Decimal("100")).quantize(Decimal("0.01"))
            if entry["expected"] > 0 else Decimal("0.00")
        )
        borrower_exposure_board.append({
            "borrower": borrower,
            "agent_count": len(entry["agent_ids"]),
            "total_loans": entry["total_loans"],
            "active_loans": entry["active_loans"],
            "closed_loans": entry["closed_loans"],
            "default_loans": entry["default_loans"],
            "disbursed": quantize_amount(entry["disbursed"]),
            "expected": quantize_amount(entry["expected"]),
            "collected": quantize_amount(entry["collected"]),
            "principal_outstanding": quantize_amount(entry["principal_outstanding"]),
            "roic_outstanding": quantize_amount(entry["roic_outstanding"]),
            "total_outstanding": quantize_amount(entry["total_outstanding"]),
            "max_overdue_weeks": entry["max_overdue_weeks"],
            "latest_loan": entry["latest_loan"],
            "latest_payment": entry["latest_payment"],
            "collection_rate": rate,
        })
    borrower_exposure_board.sort(
        key=lambda row: (-row["total_outstanding"], -row["default_loans"], row["borrower"].full_name.lower())
    )
    top_borrowers_outstanding = borrower_exposure_board[:12]
    top_bad_borrowers = [
        row for row in borrower_exposure_board
        if row["borrower"].status == "BAD" or row["default_loans"] > 0 or row["max_overdue_weeks"] > 6
    ][:10]

    location_board = []
    for entry in location_map.values():
        rate = (
            (entry["collected"] / entry["expected"] * Decimal("100")).quantize(Decimal("0.01"))
            if entry["expected"] > 0 else Decimal("0.00")
        )
        location_board.append({
            "name": entry["name"],
            "borrowers_count": len(entry["borrower_ids"]),
            "loan_count": entry["loan_count"],
            "default_loans": entry["default_loans"],
            "disbursed": quantize_amount(entry["disbursed"]),
            "expected": quantize_amount(entry["expected"]),
            "collected": quantize_amount(entry["collected"]),
            "total_outstanding": quantize_amount(entry["total_outstanding"]),
            "collection_rate": rate,
        })
    location_board.sort(key=lambda row: (-row["total_outstanding"], -row["borrowers_count"], row["name"].lower()))
    location_board = location_board[:10]

    group_board = []
    for entry in group_map.values():
        rate = (
            (entry["collected"] / entry["expected"] * Decimal("100")).quantize(Decimal("0.01"))
            if entry["expected"] > 0 else Decimal("0.00")
        )
        group_board.append({
            "name": entry["name"],
            "borrowers_count": len(entry["borrower_ids"]),
            "loan_count": entry["loan_count"],
            "default_loans": entry["default_loans"],
            "disbursed": quantize_amount(entry["disbursed"]),
            "expected": quantize_amount(entry["expected"]),
            "collected": quantize_amount(entry["collected"]),
            "total_outstanding": quantize_amount(entry["total_outstanding"]),
            "collection_rate": rate,
        })
    group_board.sort(key=lambda row: (-row["total_outstanding"], -row["borrowers_count"], row["name"].lower()))
    group_board = group_board[:10]

    category_board = build_category_summary_from_loans(loans_list_all)

    loan_status_board = []
    for status_code, status_label in Loan.STATUS_CHOICES:
        status_loans = [loan for loan in loans_list_all if loan.status == status_code]
        count = len(status_loans)
        disbursed = quantize_amount(sum((loan.amount for loan in status_loans), Decimal("0.00")))
        expected = quantize_amount(sum((loan.total_expected_amount for loan in status_loans), Decimal("0.00")))
        collected = quantize_amount(sum((loan.total_paid_amount for loan in status_loans), Decimal("0.00")))
        balance = quantize_amount(sum((loan.balance_amount for loan in status_loans), Decimal("0.00")))
        share = (
            (Decimal(count) / Decimal(total_loans) * Decimal("100")).quantize(Decimal("0.01"))
            if total_loans > 0 else Decimal("0.00")
        )
        loan_status_board.append({
            "code": status_code,
            "label": status_label,
            "count": count,
            "disbursed": disbursed,
            "expected": expected,
            "collected": collected,
            "balance": balance,
            "share": share,
        })

    borrower_status_board = []
    for status_code, status_label in Borrower.STATUS_CHOICES:
        status_rows = [row for row in borrower_exposure_board if row["borrower"].status == status_code]
        count = sum(1 for borrower in borrowers_list if borrower.status == status_code)
        loan_count = sum(row["total_loans"] for row in status_rows)
        disbursed = quantize_amount(sum((row["disbursed"] for row in status_rows), Decimal("0.00")))
        expected = quantize_amount(sum((row["expected"] for row in status_rows), Decimal("0.00")))
        collected = quantize_amount(sum((row["collected"] for row in status_rows), Decimal("0.00")))
        balance = quantize_amount(sum((row["total_outstanding"] for row in status_rows), Decimal("0.00")))
        share = (
            (Decimal(count) / Decimal(borrowers_count) * Decimal("100")).quantize(Decimal("0.01"))
            if borrowers_count > 0 else Decimal("0.00")
        )
        borrower_status_board.append({
            "code": status_code,
            "label": status_label,
            "count": count,
            "loan_count": loan_count,
            "disbursed": disbursed,
            "expected": expected,
            "collected": collected,
            "balance": balance,
            "share": share,
        })

    age_bands = [
        ("0-4 Weeks", lambda weeks: weeks <= 4),
        ("5-8 Weeks", lambda weeks: 5 <= weeks <= 8),
        ("9-12 Weeks", lambda weeks: 9 <= weeks <= 12),
        ("13+ Weeks", lambda weeks: weeks >= 13),
    ]
    age_band_board = []
    for label, matcher in age_bands:
        band_loans = [loan for loan in loans_list_all if matcher(loan.weeks_since_start)]
        age_band_board.append({
            "label": label,
            "count": len(band_loans),
            "default_count": sum(1 for loan in band_loans if loan.status == "DEFAULT"),
            "disbursed": quantize_amount(sum((loan.amount for loan in band_loans), Decimal("0.00"))),
            "balance": quantize_amount(sum((loan.balance_amount for loan in band_loans), Decimal("0.00"))),
        })

    watchlist_loans = []
    for loan in loans_list_all:
        if loan.balance_amount <= Decimal("0.00"):
            continue
        severity = "Healthy"
        if loan.status == "DEFAULT" or loan.is_overdue_more_than_6_weeks:
            severity = "Critical"
        elif loan.overdue_weeks > 0 or loan.balance_amount >= Decimal("10000.00"):
            severity = "Warning"

        watchlist_loans.append({
            "loan": loan,
            "severity": severity,
            "overdue_weeks": loan.overdue_weeks,
            "balance": quantize_amount(loan.balance_amount),
            "principal_outstanding": quantize_amount(loan.principal_outstanding),
            "roic_outstanding": quantize_amount(loan.roic_outstanding),
        })
    watchlist_loans.sort(
        key=lambda row: (
            0 if row["severity"] == "Critical" else 1 if row["severity"] == "Warning" else 2,
            -row["overdue_weeks"],
            -row["balance"],
        )
    )
    watchlist_loans = watchlist_loans[:15]

    recovery_windows = []
    for label, start_date in (
        ("Today", today),
        ("Last 7 Days", last7),
        ("Month to Date", month_start),
        ("Last 30 Days", last_30_days),
        ("Last 90 Days", last_90_days),
    ):
        window_loans = [loan for loan in loans_list_all if start_date <= loan.created_at.date() <= today]
        window_payments = [payment for payment in payments_list if start_date <= payment.payment_date <= today]
        recovery_windows.append({
            "label": label,
            "loan_count": len(window_loans),
            "payment_count": len(window_payments),
            "disbursed": quantize_amount(sum((loan.amount for loan in window_loans), Decimal("0.00"))),
            "collected": quantize_amount(sum((payment.amount for payment in window_payments), Decimal("0.00"))),
            "principal_collected": quantize_amount(sum((payment.principal_paid for payment in window_payments), Decimal("0.00"))),
            "roic_collected": quantize_amount(sum((payment.roic_paid for payment in window_payments), Decimal("0.00"))),
        })

    month_markers = []
    cursor = today.replace(day=1)
    for _ in range(6):
        month_markers.append(cursor)
        cursor = (cursor - timezone.timedelta(days=1)).replace(day=1)
    month_markers.reverse()
    month_disbursed_map = {marker: Decimal("0.00") for marker in month_markers}
    month_collected_map = {marker: Decimal("0.00") for marker in month_markers}
    month_loan_count_map = {marker: 0 for marker in month_markers}
    month_payment_count_map = {marker: 0 for marker in month_markers}

    for loan in loans_list_all:
        marker = loan.created_at.date().replace(day=1)
        if marker in month_disbursed_map:
            month_disbursed_map[marker] += loan.amount
            month_loan_count_map[marker] += 1
    for payment in payments_list:
        marker = payment.payment_date.replace(day=1)
        if marker in month_collected_map:
            month_collected_map[marker] += payment.amount
            month_payment_count_map[marker] += 1

    daily_markers = [today - timezone.timedelta(days=offset) for offset in range(29, -1, -1)]
    daily_disbursed_map = {marker: Decimal("0.00") for marker in daily_markers}
    daily_collected_map = {marker: Decimal("0.00") for marker in daily_markers}
    for loan in loans_list_all:
        created_day = loan.created_at.date()
        if created_day in daily_disbursed_map:
            daily_disbursed_map[created_day] += loan.amount
    for payment in payments_list:
        if payment.payment_date in daily_collected_map:
            daily_collected_map[payment.payment_date] += payment.amount

    chart_month_labels = [marker.strftime("%b %Y") for marker in month_markers]
    chart_month_disbursed = [float(quantize_amount(month_disbursed_map[marker])) for marker in month_markers]
    chart_month_collected = [float(quantize_amount(month_collected_map[marker])) for marker in month_markers]
    chart_month_loan_counts = [month_loan_count_map[marker] for marker in month_markers]
    chart_month_payment_counts = [month_payment_count_map[marker] for marker in month_markers]

    chart_daily_labels = [marker.strftime("%d %b") for marker in daily_markers]
    chart_daily_disbursed = [float(quantize_amount(daily_disbursed_map[marker])) for marker in daily_markers]
    chart_daily_collected = [float(quantize_amount(daily_collected_map[marker])) for marker in daily_markers]

    chart_loan_status_labels = [row["label"] for row in loan_status_board]
    chart_loan_status_counts = [row["count"] for row in loan_status_board]
    chart_loan_status_balances = [float(row["balance"]) for row in loan_status_board]

    chart_borrower_status_labels = [row["label"] for row in borrower_status_board]
    chart_borrower_status_counts = [row["count"] for row in borrower_status_board]
    chart_borrower_status_balances = [float(row["balance"]) for row in borrower_status_board]

    chart_category_labels = [row["label"] for row in category_board]
    chart_category_counts = [row["count"] for row in category_board]
    chart_category_disbursed = [float(row["disbursed"]) for row in category_board]
    chart_category_balance = [float(row["balance"]) for row in category_board]

    chart_agent_labels = [row["agent_name"] for row in agent_board]
    chart_agent_outstanding = [float(row["total_outstanding"]) for row in agent_board]
    chart_agent_collection_rates = [float(row["collection_rate"]) for row in agent_board]

    chart_location_labels = [row["name"] for row in location_board]
    chart_location_balances = [float(row["total_outstanding"]) for row in location_board]

    chart_group_labels = [row["name"] for row in group_board]
    chart_group_balances = [float(row["total_outstanding"]) for row in group_board]

    chart_borrower_labels = [row["borrower"].full_name for row in top_borrowers_outstanding[:10]]
    chart_borrower_balances = [float(row["total_outstanding"]) for row in top_borrowers_outstanding[:10]]

    chart_age_band_labels = [row["label"] for row in age_band_board]
    chart_age_band_counts = [row["count"] for row in age_band_board]
    chart_age_band_balances = [float(row["balance"]) for row in age_band_board]

    chart_payment_mix_labels = ["Principal Collected", "ROIC Collected"]
    chart_payment_mix_values = [float(total_principal_collected), float(total_roic_collected)]
    chart_outstanding_mix_labels = ["Principal Outstanding", "ROIC Outstanding"]
    chart_outstanding_mix_values = [float(total_principal_outstanding), float(total_roic_outstanding)]

    generated_at = timezone.now()

    context = {
        "title": f"{_company_name()} Dashboard",
        "generated_at": generated_at,
        "hero_total_disbursed": total_disbursed,
        "hero_total_amount_collected": total_collected,
        "hero_roic_collected": total_roic_collected,
        "hero_principal_outstanding": total_principal_outstanding,
        "borrowers_count": borrowers_count,
        "borrower_active_count": borrower_active_count,
        "borrower_closed_count": borrower_closed_count,
        "borrower_bad_count": borrower_bad_count,
        "agents_count": agents_count,
        "total_loans": total_loans,
        "active_count": active_count,
        "closed_count": closed_count,
        "default_count": default_count,
        "month_new_loans": month_new_loans,
        "last_30_new_loans": last_30_new_loans,
        "month_new_borrowers": month_new_borrowers,
        "last_30_new_borrowers": last_30_new_borrowers,
        "total_disbursed": total_disbursed,
        "active_disbursed": active_disbursed,
        "month_disbursed": month_disbursed,
        "last_30_disbursed": last_30_disbursed,
        "total_expected": total_expected,
        "active_expected": active_expected,
        "total_roic": total_roic,
        "active_roic": active_roic,
        "total_collected": total_collected,
        "total_principal_collected": total_principal_collected,
        "total_roic_collected": total_roic_collected,
        "month_collected": month_collected,
        "last_30_collected": last_30_collected,
        "total_principal_outstanding": total_principal_outstanding,
        "total_equity_outstanding": total_equity_outstanding,
        "total_roic_outstanding": total_roic_outstanding,
        "default_expected": default_expected,
        "default_roic_expected": default_roic_expected,
        "total_default": total_default,
        "principal_default": principal_default,
        "equity_default": equity_default,
        "total_outstanding_active": total_outstanding_active,
        "active_principal_outstanding": active_principal_outstanding,
        "active_roic_outstanding": active_roic_outstanding,
        "collections_rate": collections_rate,
        "active_collection_rate": active_collection_rate,
        "default_rate_count": default_rate_count,
        "default_rate_balance": default_rate_balance,
        "today_collected": today_collected,
        "week_collected": week_collected,
        "par_amount": par_amount,
        "par_rate": par_rate,
        "par_count": par_count,
        "avg_loan_size": avg_loan_size,
        "total_payments_count": total_payments_count,
        "overdue_watch_count": overdue_watch_count,
        "overdue_total_amount": overdue_total_amount,
        "critical_overdue_count": critical_overdue_count,
        "recent_loans": recent_loans,
        "recent_payments": recent_payments,
        "agent_board": agent_board,
        "top_collecting_agents": top_collecting_agents,
        "weak_agents": weak_agents,
        "category_board": category_board,
        "loan_status_board": loan_status_board,
        "borrower_status_board": borrower_status_board,
        "top_borrowers_outstanding": top_borrowers_outstanding,
        "top_bad_borrowers": top_bad_borrowers,
        "location_board": location_board,
        "group_board": group_board,
        "age_band_board": age_band_board,
        "watchlist_loans": watchlist_loans,
        "recovery_windows": recovery_windows,
        "chart_month_labels": chart_month_labels,
        "chart_month_disbursed": chart_month_disbursed,
        "chart_month_collected": chart_month_collected,
        "chart_month_loan_counts": chart_month_loan_counts,
        "chart_month_payment_counts": chart_month_payment_counts,
        "chart_daily_labels": chart_daily_labels,
        "chart_daily_disbursed": chart_daily_disbursed,
        "chart_daily_collected": chart_daily_collected,
        "chart_loan_status_labels": chart_loan_status_labels,
        "chart_loan_status_counts": chart_loan_status_counts,
        "chart_loan_status_balances": chart_loan_status_balances,
        "chart_borrower_status_labels": chart_borrower_status_labels,
        "chart_borrower_status_counts": chart_borrower_status_counts,
        "chart_borrower_status_balances": chart_borrower_status_balances,
        "chart_category_labels": chart_category_labels,
        "chart_category_counts": chart_category_counts,
        "chart_category_disbursed": chart_category_disbursed,
        "chart_category_balance": chart_category_balance,
        "chart_agent_labels": chart_agent_labels,
        "chart_agent_outstanding": chart_agent_outstanding,
        "chart_agent_collection_rates": chart_agent_collection_rates,
        "chart_location_labels": chart_location_labels,
        "chart_location_balances": chart_location_balances,
        "chart_group_labels": chart_group_labels,
        "chart_group_balances": chart_group_balances,
        "chart_borrower_labels": chart_borrower_labels,
        "chart_borrower_balances": chart_borrower_balances,
        "chart_age_band_labels": chart_age_band_labels,
        "chart_age_band_counts": chart_age_band_counts,
        "chart_age_band_balances": chart_age_band_balances,
        "chart_payment_mix_labels": chart_payment_mix_labels,
        "chart_payment_mix_values": chart_payment_mix_values,
        "chart_outstanding_mix_labels": chart_outstanding_mix_labels,
        "chart_outstanding_mix_values": chart_outstanding_mix_values,
        "loans": loans_list_all[:50],
    }

    return render(request, "loans/dashboard.html", context)


@login_required
def loan_create(request):
    _role, _agent = _get_request_role(request)
    if _role not in ("admin", "agent"):
        from django.contrib import messages as _m
        _m.error(request, "You do not have permission to create loans.")
        return redirect("loans:dashboard")

    form = LoanForm(request.POST or None, agent_override=_agent)
    selected_external_debt_check = empty_cross_company_debt_check()
    selected_borrower = None

    borrower_id = request.POST.get("borrower") if request.method == "POST" else request.GET.get("borrower")
    if borrower_id:
        selected_borrower = Borrower.objects.filter(pk=borrower_id).first()
        if selected_borrower is not None:
            selected_external_debt_check = _loan_external_debt_check_for_borrower(selected_borrower, request)

    if request.method == "POST" and form.is_valid():
        loan = form.save(commit=False)
        external_debt_check = _loan_external_debt_check_for_borrower(loan.borrower, request)
        if external_debt_check["requires_review"] and not _external_debt_acknowledged(request):
            form.add_error(
                None,
                "This customer has open debt with another onboarded company. Review the external debt summary and confirm before submitting the loan for approval."
            )
            selected_external_debt_check = external_debt_check
            selected_borrower = loan.borrower
        else:
            # Agents always own the loans they create
            if _role == "agent" and _agent:
                loan.agent_name = _agent
            approval_description = (
                f"Loan creation request for borrower {loan.borrower.full_name} "
                f"with principal GHS {loan.amount} over {loan.duration_weeks} weeks."
            )
            if external_debt_check["requires_review"]:
                approval_description = (
                    f"{approval_description}\n\nExternal debt check: {format_cross_company_debt_summary(external_debt_check)}"
                )
            approval = create_approval_request(
                workflow_type="LOAN_CREATION",
                title=f"New loan for {loan.borrower.full_name}",
                description=approval_description,
                submitted_by=request.user,
                payload=_loan_approval_payload(loan),
                metadata={
                    "borrower_id": loan.borrower_id,
                    "borrower_name": loan.borrower.full_name,
                    "agent_id": loan.agent_name_id,
                    "agent_name": loan.agent_name.name if loan.agent_name else "",
                    "category_preview": loan.get_loan_category_display(),
                    "external_debt_check": serialize_cross_company_debt_check(external_debt_check),
                    "external_debt_review_acknowledged": _external_debt_acknowledged(request),
                },
                source_path=request.path,
                target_reference=loan.borrower.full_name,
                request=request,
            )
            log_activity(
                category="LOAN",
                action="approval_requested",
                actor=request.user,
                object_type="ApprovalRequest",
                object_id=approval.pk,
                object_label=approval.title,
                message=f"Loan creation request submitted for {loan.borrower.full_name}.",
                metadata={
                    "approval_id": approval.pk,
                    "borrower_id": loan.borrower_id,
                    "external_debt_check": serialize_cross_company_debt_check(external_debt_check),
                },
                request=request,
            )
            messages.success(
                request,
                f"Loan approval request submitted for {loan.borrower.full_name}. "
                "A different admin must approve it before the loan is issued."
            )
            if _role == "agent" and _agent:
                return redirect("agent_detail", pk=_agent.pk)
            return redirect("core:loan_requests")

    return render(request, "loans/loan_create.html", {
        "form": form,
        "title": "Create Loan",
        "is_agent": _role == "agent",
        "selected_borrower": selected_borrower,
        "selected_external_debt_check": selected_external_debt_check,
        "selected_external_debt_check_json": json.dumps(serialize_cross_company_debt_check(selected_external_debt_check)),
    })


@login_required
def borrower_cross_company_check(request):
    _role, _agent = _get_request_role(request)
    if _role not in ("admin", "agent"):
        return JsonResponse({"detail": "You do not have permission to run cross-company debt checks."}, status=403)

    borrower = None
    borrower_id = (request.GET.get("borrower_id") or "").strip()
    if borrower_id:
        borrower = Borrower.objects.filter(pk=borrower_id).first()

    if borrower is None:
        summary = get_cross_company_debt_check(
            national_id=request.GET.get("national_id", ""),
            ghana_card_number=request.GET.get("ghana_card_number", ""),
        )
    else:
        summary = _loan_external_debt_check_for_borrower(borrower, request)

    return JsonResponse(serialize_cross_company_debt_check(summary))


@login_required
def loan_detail(request, loan_id: int):
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    loan = get_object_or_404(
        Loan.objects.select_related("borrower", "agent_name").prefetch_related("payments"),
        id=loan_id
    )
    # Agents may only view loans assigned to them
    if _role == "agent" and _agent and loan.agent_name_id != _agent.pk:
        from django.contrib import messages as _m
        _m.error(request, "You can only view loans assigned to you.")
        return redirect("agent_detail", pk=_agent.pk)

    loan.refresh_status(save=True)
    loan.borrower.refresh_status(save=True)

    # Use PaymentCreateForm here because the loan is already known from the URL
    payment_form = PaymentCreateForm(request.POST or None)

    if request.method == "POST" and payment_form.is_valid():
        p = payment_form.save(commit=False)
        p.loan = loan
        p.save()

        # refresh from DB after payment save
        loan = Loan.objects.select_related("borrower", "agent_name").prefetch_related("payments").get(id=loan_id)
        loan.refresh_status(save=True)
        loan.borrower.refresh_status(save=True)

        statement = build_loan_statement(loan)
        notify_user(
            request.user,
            "STATEMENT",
            f"Updated Statement: Loan #{loan.id}",
            statement,
            send_email=True
        )

        borrower_phone = loan.borrower.phone
        agent_phone = loan.agent_name.phone if loan.agent_name and loan.agent_name.phone else None

        borrower_msg = (
            f"{_company_name()}: Payment received for Loan #{loan.id} "
            f"({loan.get_loan_category_display()}). "
            f"GHS {p.amount} on {p.payment_date:%d/%m/%Y}. "
            f"Principal: GHS {p.principal_paid}. ROIC: GHS {p.roic_paid}. "
            f"Principal outstanding: GHS {loan.principal_outstanding}. "
            f"ROIC outstanding: GHS {loan.roic_outstanding}. "
            f"Balance: GHS {loan.balance_amount}. "
            f"Borrower status: {loan.borrower.status}."
        )

        agent_msg = (
            f"{_company_name()}: Payment recorded. Borrower: {loan.borrower.full_name}. "
            f"Loan #{loan.id} ({loan.get_loan_category_display()}). "
            f"GHS {p.amount} on {p.payment_date:%d/%m/%Y}. "
            f"Principal: GHS {p.principal_paid}. ROIC: GHS {p.roic_paid}. "
            f"Balance: GHS {loan.balance_amount}. "
            f"Borrower status: {loan.borrower.status}."
        )

        if borrower_phone:
            safe_send_sms(borrower_phone, borrower_msg)
        if agent_phone:
            safe_send_sms(agent_phone, agent_msg)

        log_activity(
            category="LOAN",
            action="payment_recorded",
            actor=request.user,
            object_type="Payment",
            object_id=p.pk,
            object_label=f"Loan #{loan.id} payment",
            message=f"Payment of GHS {p.amount:,.2f} recorded for Loan #{loan.id}.",
            metadata={"loan_id": loan.id, "payment_id": p.pk, "borrower_id": loan.borrower_id},
            request=request,
        )
        messages.success(request, f"Payment recorded successfully for Loan #{loan.id}.")
        return redirect("loans:loan_detail", loan_id=loan.id)

    payments = list(loan.payments.filter(is_void=False).order_by("payment_date", "id"))

    payment_dates = [p.payment_date.strftime("%d/%m/%Y") for p in payments]
    payment_amounts = [float(p.amount) for p in payments]
    principal_paid_series = [float(p.principal_paid) for p in payments]
    roic_paid_series = [float(p.roic_paid) for p in payments]

    cumulative_total = []
    cumulative_principal = []
    cumulative_roic = []

    total_running = Decimal("0.00")
    principal_running = Decimal("0.00")
    roic_running = Decimal("0.00")

    for p in payments:
        total_running += Decimal(p.amount)
        principal_running += Decimal(p.principal_paid)
        roic_running += Decimal(p.roic_paid)

        cumulative_total.append(float(total_running))
        cumulative_principal.append(float(principal_running))
        cumulative_roic.append(float(roic_running))

    allocation_breakdown = [
        {"value": float(loan.total_principal_paid), "name": "Principal Paid"},
        {"value": float(loan.total_roic_paid), "name": "ROIC Paid"},
    ]

    outstanding_breakdown = [
        {"value": float(loan.principal_outstanding), "name": "Principal Outstanding"},
        {"value": float(loan.roic_outstanding), "name": "ROIC Outstanding"},
    ]

    context = {
        "loan": loan,
        "loan_category_label": loan.get_loan_category_display(),
        "payments": payments,
        "payment_form": payment_form,
        "title": f"Loan #{loan.id}",
        "chart_payment_dates": json.dumps(payment_dates),
        "chart_payment_amounts": json.dumps(payment_amounts),
        "chart_principal_paid_series": json.dumps(principal_paid_series),
        "chart_roic_paid_series": json.dumps(roic_paid_series),
        "chart_cumulative_total": json.dumps(cumulative_total),
        "chart_cumulative_principal": json.dumps(cumulative_principal),
        "chart_cumulative_roic": json.dumps(cumulative_roic),
        "chart_allocation_breakdown": json.dumps(allocation_breakdown),
        "chart_outstanding_breakdown": json.dumps(outstanding_breakdown),
    }
    return render(request, "loans/loan_detail.html", context)


@login_required
def loan_statement(request, loan_id: int):
    loan = get_object_or_404(Loan, id=loan_id)
    statement = build_loan_statement(loan)
    return render(request, "loans/statement.html", {
        "loan": loan,
        "statement": statement,
        "title": f"Statement - Loan #{loan.id}",
    })


@login_required
def loan_statement_pdf(request, loan_id: int):
    loan = get_object_or_404(
        Loan.objects.select_related("borrower", "agent_name").prefetch_related("payments"),
        id=loan_id,
    )
    payments = loan.payments.filter(is_void=False).order_by("payment_date", "id")
    statement = build_loan_statement(loan)
    generated_at = timezone.localtime()

    try:
        from apps.company.models import CompanyProfile
        company = CompanyProfile.get_solo()
        company_name = company.company_name
        company_address = company.address
        company_phone = company.phone
        company_email = company.email
    except Exception:
        company_name = _company_name()
        company_address = ""
        company_phone = ""
        company_email = ""

    html = render_to_string(
        "loans/statement_pdf.html",
        {
            "loan": loan,
            "payments": payments,
            "statement": statement,
            "title": f"Statement - Loan #{loan.id}",
            "generated_at": generated_at,
            "company_name": company_name,
            "company_address": company_address,
            "company_phone": company_phone,
            "company_email": company_email,
        },
        request=request,
    )

    pdf_file = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    borrower_slug = slugify(loan.borrower.full_name) or f"borrower-{loan.borrower_id}"
    filename = f"loan-statement-{loan.id}-{borrower_slug}.pdf"
    response = HttpResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@login_required
def active_loans_list(request):
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    q = (request.GET.get("q") or "").strip()
    agent_id = (request.GET.get("agent") or "").strip()
    location = (request.GET.get("location") or "").strip()
    borrower_status = (request.GET.get("borrower_status") or "").strip()
    loan_category = (request.GET.get("loan_category") or "").strip()
    sort = (request.GET.get("sort") or "newest").strip()

    loans_qs = (
        Loan.objects.select_related("borrower", "agent_name")
        .filter(status="ACTIVE")
        .order_by("-created_at")
    )
    # Agents see only their own loans
    if _role == "agent" and _agent:
        loans_qs = loans_qs.filter(agent_name=_agent)

    if q:
        loans_qs = loans_qs.filter(
            Q(borrower__full_name__icontains=q) |
            Q(borrower__national_id__icontains=q) |
            Q(borrower__borrower_id__icontains=q) |
            Q(borrower__phone__icontains=q) |
            Q(borrower__email__icontains=q) |
            Q(borrower__ghana_card_number__icontains=q) |
            Q(agent_name__name__icontains=q)
        )

    if agent_id:
        loans_qs = loans_qs.filter(agent_name_id=agent_id)

    if location:
        loans_qs = loans_qs.filter(borrower__location__icontains=location)

    if borrower_status:
        loans_qs = loans_qs.filter(borrower__status=borrower_status)

    if loan_category:
        loans_qs = loans_qs.filter(loan_category=loan_category)

    loans = list(loans_qs)
    loan_rows = []

    total_active_loans = len(loans)
    total_principal = Decimal("0.00")
    total_roic = Decimal("0.00")
    total_expected = Decimal("0.00")
    total_paid = Decimal("0.00")
    total_principal_paid = Decimal("0.00")
    total_roic_paid = Decimal("0.00")
    total_principal_outstanding = Decimal("0.00")
    total_roic_outstanding = Decimal("0.00")
    total_balance = Decimal("0.00")

    overdue_loans_count = 0
    overdue_over_6_count = 0
    total_overdue_amount = Decimal("0.00")

    for loan in loans:
        principal = loan.amount
        roic = loan.roic_amount
        expected = loan.total_expected_amount
        paid = loan.total_paid_amount
        principal_paid = loan.total_principal_paid
        roic_paid = loan.total_roic_paid
        principal_outstanding = loan.principal_outstanding
        roic_outstanding = loan.roic_outstanding
        balance = loan.balance_amount
        overdue_weeks = loan.overdue_weeks
        is_critical = loan.is_overdue_more_than_6_weeks

        if overdue_weeks > 0:
            overdue_loans_count += 1
            total_overdue_amount += balance

        if is_critical:
            overdue_over_6_count += 1

        row = {
            "loan": loan,
            "principal": quantize_amount(principal),
            "roic": quantize_amount(roic),
            "expected": quantize_amount(expected),
            "paid": quantize_amount(paid),
            "principal_paid": quantize_amount(principal_paid),
            "roic_paid": quantize_amount(roic_paid),
            "principal_outstanding": quantize_amount(principal_outstanding),
            "roic_outstanding": quantize_amount(roic_outstanding),
            "balance": quantize_amount(balance),
            "overdue_weeks": overdue_weeks,
            "is_critical": is_critical,
        }
        loan_rows.append(row)

        total_principal += principal
        total_roic += roic
        total_expected += expected
        total_paid += paid
        total_principal_paid += principal_paid
        total_roic_paid += roic_paid
        total_principal_outstanding += principal_outstanding
        total_roic_outstanding += roic_outstanding
        total_balance += balance

    if sort == "balance_desc":
        loan_rows.sort(key=lambda x: x["balance"], reverse=True)
    elif sort == "balance_asc":
        loan_rows.sort(key=lambda x: x["balance"])
    elif sort == "oldest":
        loan_rows.sort(key=lambda x: x["loan"].created_at)
    elif sort == "start_oldest":
        loan_rows.sort(key=lambda x: x["loan"].start_date)
    elif sort == "start_newest":
        loan_rows.sort(key=lambda x: x["loan"].start_date, reverse=True)
    elif sort == "overdue_desc":
        loan_rows.sort(key=lambda x: (x["overdue_weeks"], x["balance"]), reverse=True)
    else:
        loan_rows.sort(key=lambda x: x["loan"].created_at, reverse=True)

    collection_rate = (
        (total_paid / total_expected) * Decimal("100")
    ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")

    avg_loan_size = (
        total_principal / Decimal(total_active_loans)
    ).quantize(Decimal("0.01")) if total_active_loans > 0 else Decimal("0.00")

    agents = Agent.objects.all().order_by("name")
    category_summary = build_category_summary_from_loans(loans)
    pagination = paginate_items(request, loan_rows, per_page=12)

    context = {
        "title": "Active Loans",
        "loans": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "q": q,
        "agent_id": agent_id,
        "location": location,
        "borrower_status": borrower_status,
        "loan_category": loan_category,
        "sort": sort,
        "agents": agents,
        "loan_category_choices": [(t["code"], t["label"]) for t in __import__("apps.company.models", fromlist=["CompanyProfile"]).CompanyProfile.get_solo().tiers_for_template] if True else Loan.LOAN_CATEGORY_CHOICES,
        "category_summary": category_summary,
        "borrower_status_choices": [
            ("ACTIVE", "Active"),
            ("CLOSED", "Closed"),
            ("BAD", "Bad"),
        ],
        "sort_choices": [
            ("newest", "Newest Created"),
            ("oldest", "Oldest Created"),
            ("start_newest", "Latest Start Date"),
            ("start_oldest", "Earliest Start Date"),
            ("balance_desc", "Highest Balance"),
            ("balance_asc", "Lowest Balance"),
            ("overdue_desc", "Most Overdue"),
        ],
        "total_active_loans": total_active_loans,
        "total_principal": quantize_amount(total_principal),
        "total_roic": quantize_amount(total_roic),
        "total_expected": quantize_amount(total_expected),
        "total_paid": quantize_amount(total_paid),
        "total_principal_paid": quantize_amount(total_principal_paid),
        "total_roic_paid": quantize_amount(total_roic_paid),
        "total_principal_outstanding": quantize_amount(total_principal_outstanding),
        "total_roic_outstanding": quantize_amount(total_roic_outstanding),
        "total_balance": quantize_amount(total_balance),
        "collection_rate": collection_rate,
        "avg_loan_size": avg_loan_size,
        "overdue_loans_count": overdue_loans_count,
        "overdue_over_6_count": overdue_over_6_count,
        "total_overdue_amount": quantize_amount(total_overdue_amount),
    }

    return render(request, "loans/active_loans_list.html", context)


@login_required
def borrower_create(request):
    _role2, _creator_agent = _get_request_role(request)
    # Both admins and agents may create borrowers
    if _role2 not in ("admin", "agent"):
        from django.contrib import messages as _m
        _m.error(request, "You do not have permission to add borrowers.")
        return redirect("loans:dashboard")

    borrower_limit = can_create_borrower()
    if not borrower_limit.allowed:
        messages.error(request, borrower_limit.reason)
        return redirect("loans:borrower_list")

    form = BorrowerForm(
        request.POST or None,
        request.FILES or None,
        creating=True,
    )

    if request.method == "POST" and form.is_valid():
        from django.contrib.auth.models import User as _User

        borrower = form.save(commit=False)

        # ── Create portal login account ───────────────────────
        username = form.cleaned_data["portal_username"]
        stored_username = build_portal_username(username)
        temp_password = _generate_temp_password()

        portal_user = _User.objects.create_user(
            username=stored_username,
            email=(borrower.email or "").strip().lower(),
            password=temp_password,
        )
        borrower.user = portal_user
        borrower.save()
        borrower.refresh_status(save=True)

        # ── Send temp password via SMS ────────────────────────
        company = _company_name()
        borrower_phone = borrower.phone

        borrower_sms = (
            f"{company}: Your portal account has been created. "
            f"Username: {username}  Temp Password: {temp_password}  "
            f"Login at /login/ and change your password immediately."
        )

        # If created by an agent, also notify the agent
        agent_phone = None
        if _creator_agent:
            agent_phone = _creator_agent.phone
            agent_sms = (
                f"{company}: Borrower '{borrower.full_name}' has been registered. "
                f"Portal login created — Username: {username}  Temp Password: {temp_password}  "
                f"Please share these credentials securely with the borrower."
            )
            safe_send_sms(agent_phone, agent_sms)

        safe_send_sms(borrower_phone, borrower_sms)

        # ── Show credentials on-screen so the creator can note them ──
        messages.success(
            request,
            f"Borrower '{borrower.full_name}' registered. "
            f"Portal login created — Username: {username} | Temp Password: {temp_password}. "
            f"SMS sent to {borrower_phone}. "
            f"Advise the borrower to change their password after first login."
        )
        return redirect("loans:borrower_detail", pk=borrower.pk)

    return render(request, "loans/borrowers/borrower_create.html", {
        "form": form,
        "title": "Add New Borrower",
    })


@admin_required
def borrower_bulk_import(request):
    form = BorrowerBulkImportForm(request.POST or None, request.FILES or None)
    import_result = None

    if request.method == "POST" and form.is_valid():
        uploaded_file = form.cleaned_data["data_file"]
        selected_type = form.cleaned_data["file_type"]
        import_mode = form.cleaned_data["import_mode"]

        file_type = selected_type
        if selected_type == "auto":
            file_type = infer_borrower_import_format(uploaded_file.name)
            if not file_type:
                form.add_error(
                    "data_file",
                    "Could not infer the file type. Choose CSV, Excel, JSON, or XML explicitly.",
                )

        if file_type and not form.errors:
            try:
                rows = parse_borrower_import(uploaded_file, file_type)
                import_result = import_borrower_rows(rows, import_mode=import_mode)
                if import_result["errors"]:
                    messages.warning(
                        request,
                        f"Bulk import completed: {import_result['created']} created, "
                        f"{import_result['updated']} updated, {len(import_result['errors'])} failed.",
                    )
                else:
                    messages.success(
                        request,
                        f"Bulk import completed successfully: {import_result['created']} created"
                        + (f", {import_result['updated']} updated." if import_result["updated"] else ".")
                    )
            except Exception as exc:
                form.add_error("data_file", str(exc))

    return render(
        request,
        "loans/borrowers/borrower_bulk_import.html",
        {
            "title": "Bulk Import Borrowers",
            "form": form,
            "format_options": get_borrower_import_formats(),
            "column_help": get_borrower_import_column_help(),
            "import_result": import_result,
        },
    )


@admin_required
def borrower_bulk_import_sample(request, file_type):
    supported = {item["slug"] for item in get_borrower_import_formats()}
    if file_type not in supported:
        raise Http404("Unsupported sample file type.")

    filename, content_type, payload = build_borrower_import_sample(file_type)
    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@admin_required
def loan_bulk_import(request):
    form = LoanBulkImportForm(request.POST or None, request.FILES or None)
    import_result = None

    if request.method == "POST" and form.is_valid():
        uploaded_file = form.cleaned_data["data_file"]
        selected_type = form.cleaned_data["file_type"]
        import_mode = form.cleaned_data["import_mode"]

        file_type = selected_type
        if selected_type == "auto":
            file_type = infer_loan_import_format(uploaded_file.name)
            if not file_type:
                form.add_error(
                    "data_file",
                    "Could not infer the file type. Choose CSV, Excel, JSON, or XML explicitly.",
                )

        if file_type and not form.errors:
            try:
                rows = parse_loan_import(uploaded_file, file_type)
                import_result = import_loan_rows(rows, import_mode=import_mode)
                if import_result["errors"]:
                    messages.warning(
                        request,
                        f"Bulk import completed: {import_result['created']} created, "
                        f"{import_result['updated']} updated, {len(import_result['errors'])} failed.",
                    )
                else:
                    messages.success(
                        request,
                        f"Bulk import completed successfully: {import_result['created']} created"
                        + (f", {import_result['updated']} updated." if import_result["updated"] else ".")
                    )
            except Exception as exc:
                form.add_error("data_file", str(exc))

    return render(
        request,
        "loans/loan_bulk_import.html",
        {
            "title": "Bulk Import Loans",
            "form": form,
            "format_options": get_loan_import_formats(),
            "column_help": get_loan_import_column_help(),
            "import_result": import_result,
        },
    )


@admin_required
def loan_bulk_import_sample(request, file_type):
    supported = {item["slug"] for item in get_loan_import_formats()}
    if file_type not in supported:
        raise Http404("Unsupported sample file type.")

    filename, content_type, payload = build_loan_import_sample(file_type)
    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def borrower_list(request):
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    borrowers = Borrower.objects.all().order_by("-created_at").prefetch_related(
        Prefetch("loans", queryset=Loan.objects.prefetch_related("payments").select_related("agent_name"))
    )
    # Agents see only borrowers who have at least one loan under them
    if _role == "agent" and _agent:
        borrowers = borrowers.filter(loans__agent_name=_agent).distinct()

    q = (request.GET.get("q") or "").strip()
    location = (request.GET.get("location") or "").strip()
    group_name = (request.GET.get("group_name") or "").strip()
    preferred_language = (request.GET.get("preferred_language") or "").strip()
    risk = (request.GET.get("risk") or "").strip()
    borrower_status = (request.GET.get("borrower_status") or "").strip()
    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")

    if q:
        borrowers = borrowers.filter(
            Q(full_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(email__icontains=q) |
            Q(national_id__icontains=q) |
            Q(borrower_id__icontains=q) |
            Q(ghana_card_number__icontains=q)
        )

    if location:
        borrowers = borrowers.filter(location__icontains=location)

    if group_name:
        borrowers = borrowers.filter(group_name__icontains=group_name)

    if preferred_language:
        borrowers = borrowers.filter(preferred_language=preferred_language)

    if borrower_status:
        borrowers = borrowers.filter(status=borrower_status)

    if from_date:
        parsed_from = parse_date(from_date)
        if parsed_from:
            borrowers = borrowers.filter(created_at__date__gte=parsed_from)

    if to_date:
        parsed_to = parse_date(to_date)
        if parsed_to:
            borrowers = borrowers.filter(created_at__date__lte=parsed_to)

    borrower_rows = []

    total_borrowers = borrowers.count()
    borrowers_active_count = borrowers.filter(status="ACTIVE").count()
    borrowers_closed_count = borrowers.filter(status="CLOSED").count()
    borrowers_bad_count = borrowers.filter(status="BAD").count()

    portfolio_principal = Decimal("0.00")
    portfolio_expected = Decimal("0.00")
    portfolio_collected = Decimal("0.00")
    portfolio_principal_outstanding = Decimal("0.00")
    portfolio_roic_outstanding = Decimal("0.00")
    portfolio_total_outstanding = Decimal("0.00")

    for borrower in borrowers:
        borrower.refresh_status(save=True)
        loans = list(borrower.loans.all())

        total_loans = len(loans)
        active_loans = sum(1 for l in loans if l.status == "ACTIVE")
        closed_loans = sum(1 for l in loans if l.status == "CLOSED")
        default_loans = sum(1 for l in loans if l.status == "DEFAULT")

        total_disbursed = sum((l.amount for l in loans), Decimal("0.00"))
        total_expected = sum((l.total_expected_amount for l in loans), Decimal("0.00"))
        total_collected = sum((l.total_paid_amount for l in loans), Decimal("0.00"))
        principal_outstanding = sum((l.principal_outstanding for l in loans), Decimal("0.00"))
        roic_outstanding = sum((l.roic_outstanding for l in loans), Decimal("0.00"))
        total_outstanding = sum((l.balance_amount for l in loans), Decimal("0.00"))
        latest_loan = max((l.created_at for l in loans), default=None)

        category_mix = defaultdict(int)
        for l in loans:
            category_mix[l.get_loan_category_display()] += 1

        risk_label = "Low"
        if borrower.status == "BAD" or default_loans > 0:
            risk_label = "High"
        elif borrower.status == "ACTIVE" and total_outstanding > Decimal("0.00"):
            risk_label = "Medium"

        row = {
            "borrower": borrower,
            "borrower_status": borrower.status,
            "total_loans": total_loans,
            "active_loans": active_loans,
            "closed_loans": closed_loans,
            "default_loans": default_loans,
            "total_disbursed": quantize_amount(total_disbursed),
            "total_expected": quantize_amount(total_expected),
            "total_collected": quantize_amount(total_collected),
            "principal_outstanding": quantize_amount(principal_outstanding),
            "roic_outstanding": quantize_amount(roic_outstanding),
            "total_outstanding": quantize_amount(total_outstanding),
            "latest_loan": latest_loan,
            "risk_label": risk_label,
            "category_mix": dict(category_mix),
        }
        borrower_rows.append(row)

        portfolio_principal += total_disbursed
        portfolio_expected += total_expected
        portfolio_collected += total_collected
        portfolio_principal_outstanding += principal_outstanding
        portfolio_roic_outstanding += roic_outstanding
        portfolio_total_outstanding += total_outstanding

    if risk:
        borrower_rows = [r for r in borrower_rows if r["risk_label"] == risk]

    borrower_rows.sort(
        key=lambda x: (
            -x["total_outstanding"],
            -x["active_loans"],
            x["borrower"].full_name.lower()
        )
    )
    pagination = paginate_items(request, borrower_rows, per_page=12)

    context = {
        "borrowers": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "title": "Borrowers",
        "total_borrowers": total_borrowers,
        "borrowers_active_count": borrowers_active_count,
        "borrowers_closed_count": borrowers_closed_count,
        "borrowers_bad_count": borrowers_bad_count,
        "portfolio_principal": quantize_amount(portfolio_principal),
        "portfolio_expected": quantize_amount(portfolio_expected),
        "portfolio_collected": quantize_amount(portfolio_collected),
        "portfolio_principal_outstanding": quantize_amount(portfolio_principal_outstanding),
        "portfolio_roic_outstanding": quantize_amount(portfolio_roic_outstanding),
        "portfolio_total_outstanding": quantize_amount(portfolio_total_outstanding),
        "risk": risk,
        "borrower_status": borrower_status,
        "preferred_language": preferred_language,
        "group_name": group_name,
        "q": q,
        "location": location,
        "from_date": from_date,
        "to_date": to_date,
        "language_choices": Borrower.LANGUAGE_CHOICES,
        "borrower_status_choices": Borrower.STATUS_CHOICES,
        "risk_choices": [("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
    }

    return render(request, "loans/borrowers/borrower_list.html", context)


@login_required
def borrower_analytics(request):
    _role6, _agent6 = _get_request_role(request)
    if _role6 == "borrower":
        return redirect("borrower:portal")
    if _role6 == "agent" and _agent6:
        return redirect("agent_comprehensive_analysis", pk=_agent6.pk)
    borrowers = Borrower.objects.all().prefetch_related(
        Prefetch("loans", queryset=Loan.objects.prefetch_related("payments").select_related("agent_name"))
    ).order_by("full_name")

    q = (request.GET.get("q") or "").strip()
    location = (request.GET.get("location") or "").strip()
    group_name = (request.GET.get("group_name") or "").strip()
    preferred_language = (request.GET.get("preferred_language") or "").strip()
    risk = (request.GET.get("risk") or "").strip()
    borrower_status = (request.GET.get("borrower_status") or "").strip()
    export = (request.GET.get("export") or "").strip().lower()
    printable = (request.GET.get("print") or "").strip()

    if q:
        borrowers = borrowers.filter(
            Q(full_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(email__icontains=q) |
            Q(national_id__icontains=q) |
            Q(borrower_id__icontains=q) |
            Q(ghana_card_number__icontains=q)
        )

    if location:
        borrowers = borrowers.filter(location__icontains=location)

    if group_name:
        borrowers = borrowers.filter(group_name__icontains=group_name)

    if preferred_language:
        borrowers = borrowers.filter(preferred_language=preferred_language)

    if borrower_status:
        borrowers = borrowers.filter(status=borrower_status)

    borrower_rows = []

    total_borrowers = borrowers.count()
    borrowers_with_loans = 0
    borrowers_without_loans = 0
    borrowers_with_active_loans = 0
    borrowers_with_default_loans = 0
    borrowers_fully_paid = 0

    total_loans = 0
    total_active_loans = 0
    total_closed_loans = 0
    total_default_loans = 0

    portfolio_principal = Decimal("0.00")
    portfolio_roic = Decimal("0.00")
    portfolio_expected = Decimal("0.00")
    portfolio_collected = Decimal("0.00")
    portfolio_principal_collected = Decimal("0.00")
    portfolio_roic_collected = Decimal("0.00")
    portfolio_principal_outstanding = Decimal("0.00")
    portfolio_roic_outstanding = Decimal("0.00")
    portfolio_total_outstanding = Decimal("0.00")

    location_map = {}
    group_map = {}
    language_map = {}
    risk_map = {"Low": 0, "Medium": 0, "High": 0}
    status_map = {"No Loan": 0, "Active": 0, "Closed": 0, "Bad": 0}

    for borrower in borrowers:
        borrower.refresh_status(save=True)
        loans = list(borrower.loans.all())

        total_loans_b = len(loans)
        active_loans = sum(1 for l in loans if l.status == "ACTIVE")
        closed_loans = sum(1 for l in loans if l.status == "CLOSED")
        default_loans = sum(1 for l in loans if l.status == "DEFAULT")

        total_disbursed = sum((l.amount for l in loans), Decimal("0.00"))
        total_roic = sum((l.roic_amount for l in loans), Decimal("0.00"))
        total_expected = sum((l.total_expected_amount for l in loans), Decimal("0.00"))
        total_collected = sum((l.total_paid_amount for l in loans), Decimal("0.00"))
        total_principal_collected = sum((l.total_principal_paid for l in loans), Decimal("0.00"))
        total_roic_collected = sum((l.total_roic_paid for l in loans), Decimal("0.00"))
        principal_outstanding = sum((l.principal_outstanding for l in loans), Decimal("0.00"))
        roic_outstanding = sum((l.roic_outstanding for l in loans), Decimal("0.00"))
        total_outstanding = sum((l.balance_amount for l in loans), Decimal("0.00"))

        avg_loan_size = (
            (total_disbursed / total_loans_b).quantize(Decimal("0.01"))
            if total_loans_b > 0 else Decimal("0.00")
        )
        collection_rate = (
            (total_collected / total_expected) * Decimal("100")
        ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")

        latest_loan = max((l.created_at for l in loans), default=None)
        latest_payment = None
        payment_dates = []
        category_mix = defaultdict(int)

        for l in loans:
            category_mix[l.get_loan_category_display()] += 1
            for p in l.payments.filter(is_void=False):
                payment_dates.append(p.payment_date)

        if payment_dates:
            latest_payment = max(payment_dates)

        if total_loans_b == 0:
            borrowers_without_loans += 1
            borrower_status_label = "No Loan"
        else:
            borrowers_with_loans += 1
            if borrower.status == "BAD":
                borrower_status_label = "Bad"
            elif borrower.status == "ACTIVE":
                borrower_status_label = "Active"
            else:
                borrower_status_label = "Closed"

        if borrower.status == "ACTIVE":
            borrowers_with_active_loans += 1
        if borrower.status == "BAD":
            borrowers_with_default_loans += 1
        if borrower.status == "CLOSED" and total_loans_b > 0:
            borrowers_fully_paid += 1

        risk_label = "Low"
        if borrower.status == "BAD" or total_outstanding >= Decimal("10000.00"):
            risk_label = "High"
        elif borrower.status == "ACTIVE" and total_outstanding > Decimal("0.00"):
            risk_label = "Medium"

        row = {
            "borrower": borrower,
            "borrower_status": borrower.status,
            "total_loans": total_loans_b,
            "active_loans": active_loans,
            "closed_loans": closed_loans,
            "default_loans": default_loans,
            "total_disbursed": quantize_amount(total_disbursed),
            "total_roic": quantize_amount(total_roic),
            "total_expected": quantize_amount(total_expected),
            "total_collected": quantize_amount(total_collected),
            "total_principal_collected": quantize_amount(total_principal_collected),
            "total_roic_collected": quantize_amount(total_roic_collected),
            "principal_outstanding": quantize_amount(principal_outstanding),
            "roic_outstanding": quantize_amount(roic_outstanding),
            "total_outstanding": quantize_amount(total_outstanding),
            "avg_loan_size": avg_loan_size,
            "collection_rate": collection_rate,
            "latest_loan": latest_loan,
            "latest_payment": latest_payment,
            "risk_label": risk_label,
            "status_label": borrower_status_label,
            "category_mix": dict(category_mix),
        }
        borrower_rows.append(row)

        total_loans += total_loans_b
        total_active_loans += active_loans
        total_closed_loans += closed_loans
        total_default_loans += default_loans

        portfolio_principal += total_disbursed
        portfolio_roic += total_roic
        portfolio_expected += total_expected
        portfolio_collected += total_collected
        portfolio_principal_collected += total_principal_collected
        portfolio_roic_collected += total_roic_collected
        portfolio_principal_outstanding += principal_outstanding
        portfolio_roic_outstanding += roic_outstanding
        portfolio_total_outstanding += total_outstanding

        location_key = borrower.location or "Unknown"
        location_map.setdefault(location_key, Decimal("0.00"))
        location_map[location_key] += total_outstanding

        group_key = borrower.group_name or "Unknown"
        group_map.setdefault(group_key, Decimal("0.00"))
        group_map[group_key] += total_outstanding

        lang_key = borrower.preferred_language or "Unknown"
        language_map.setdefault(lang_key, 0)
        language_map[lang_key] += 1

        risk_map[risk_label] += 1
        status_map[borrower_status_label] += 1

    if risk:
        borrower_rows = [r for r in borrower_rows if r["risk_label"] == risk]

    avg_collection_rate = (
        (portfolio_collected / portfolio_expected) * Decimal("100")
    ).quantize(Decimal("0.01")) if portfolio_expected > 0 else Decimal("0.00")

    avg_loan_size_portfolio = (
        (portfolio_principal / total_loans).quantize(Decimal("0.01"))
        if total_loans > 0 else Decimal("0.00")
    )

    top_10_outstanding = sorted(
        borrower_rows,
        key=lambda x: (-x["total_outstanding"], -x["active_loans"], x["borrower"].full_name.lower())
    )[:10]

    chart_location_labels = list(location_map.keys())
    chart_location_values = [float(v) for v in location_map.values()]
    chart_group_labels = list(group_map.keys())
    chart_group_values = [float(v) for v in group_map.values()]
    chart_language_labels = list(language_map.keys())
    chart_language_values = list(language_map.values())
    chart_risk_labels = list(risk_map.keys())
    chart_risk_values = list(risk_map.values())
    chart_status_labels = list(status_map.keys())
    chart_status_values = list(status_map.values())
    top_borrower_labels = [r["borrower"].full_name for r in top_10_outstanding]
    top_borrower_outstanding = [float(r["total_outstanding"]) for r in top_10_outstanding]
    top_borrower_principal_outstanding = [float(r["principal_outstanding"]) for r in top_10_outstanding]
    top_borrower_roic_outstanding = [float(r["roic_outstanding"]) for r in top_10_outstanding]

    if export == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="borrower_analytics.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Borrower ID", "Full Name", "National ID", "Phone", "Location", "Group", "Language",
            "Borrower Status", "Loan Categories",
            "Total Loans", "Active Loans", "Closed Loans", "Default Loans",
            "Disbursed", "ROIC", "Expected", "Collected",
            "Principal Collected", "ROIC Collected",
            "Principal Outstanding", "ROIC Outstanding", "Total Outstanding",
            "Collection Rate", "Risk", "Status"
        ])

        for row in borrower_rows:
            b = row["borrower"]
            category_text = ", ".join([f"{k}: {v}" for k, v in row["category_mix"].items()]) if row["category_mix"] else ""
            writer.writerow([
                b.borrower_id,
                b.full_name,
                b.national_id,
                b.phone,
                b.location,
                b.group_name,
                b.preferred_language,
                b.status,
                category_text,
                row["total_loans"],
                row["active_loans"],
                row["closed_loans"],
                row["default_loans"],
                row["total_disbursed"],
                row["total_roic"],
                row["total_expected"],
                row["total_collected"],
                row["total_principal_collected"],
                row["total_roic_collected"],
                row["principal_outstanding"],
                row["roic_outstanding"],
                row["total_outstanding"],
                row["collection_rate"],
                row["risk_label"],
                row["status_label"],
            ])
        return response

    if export == "excel":
        wb = Workbook()
        ws = wb.active
        ws.title = "Borrower Analytics"

        headers = [
            "Borrower ID", "Full Name", "National ID", "Phone", "Location", "Group", "Language",
            "Borrower Status", "Loan Categories",
            "Total Loans", "Active Loans", "Closed Loans", "Default Loans",
            "Disbursed", "ROIC", "Expected", "Collected",
            "Principal Collected", "ROIC Collected",
            "Principal Outstanding", "ROIC Outstanding", "Total Outstanding",
            "Collection Rate", "Risk", "Status"
        ]
        ws.append(headers)

        header_fill = PatternFill("solid", fgColor="1E3A8A")
        header_font = Font(color="FFFFFF", bold=True)

        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font

        for row in borrower_rows:
            b = row["borrower"]
            category_text = ", ".join([f"{k}: {v}" for k, v in row["category_mix"].items()]) if row["category_mix"] else ""
            ws.append([
                b.borrower_id,
                b.full_name,
                b.national_id,
                b.phone,
                b.location,
                b.group_name,
                b.preferred_language,
                b.status,
                category_text,
                row["total_loans"],
                row["active_loans"],
                row["closed_loans"],
                row["default_loans"],
                float(row["total_disbursed"]),
                float(row["total_roic"]),
                float(row["total_expected"]),
                float(row["total_collected"]),
                float(row["total_principal_collected"]),
                float(row["total_roic_collected"]),
                float(row["principal_outstanding"]),
                float(row["roic_outstanding"]),
                float(row["total_outstanding"]),
                float(row["collection_rate"]),
                row["risk_label"],
                row["status_label"],
            ])

        for col in ws.columns:
            max_length = 0
            col_letter = col[0].column_letter
            for cell in col:
                value = str(cell.value) if cell.value is not None else ""
                if len(value) > max_length:
                    max_length = len(value)
            ws.column_dimensions[col_letter].width = min(max_length + 2, 24)

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="borrower_analytics.xlsx"'
        return response

    pagination = paginate_items(request, borrower_rows, per_page=20)

    context = {
        "title": "Borrower Analytics",
        "borrowers": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "printable": printable,
        "total_borrowers": total_borrowers,
        "borrowers_with_loans": borrowers_with_loans,
        "borrowers_without_loans": borrowers_without_loans,
        "borrowers_with_active_loans": borrowers_with_active_loans,
        "borrowers_with_default_loans": borrowers_with_default_loans,
        "borrowers_fully_paid": borrowers_fully_paid,
        "total_loans": total_loans,
        "total_active_loans": total_active_loans,
        "total_closed_loans": total_closed_loans,
        "total_default_loans": total_default_loans,
        "portfolio_principal": quantize_amount(portfolio_principal),
        "portfolio_roic": quantize_amount(portfolio_roic),
        "portfolio_expected": quantize_amount(portfolio_expected),
        "portfolio_collected": quantize_amount(portfolio_collected),
        "portfolio_principal_collected": quantize_amount(portfolio_principal_collected),
        "portfolio_roic_collected": quantize_amount(portfolio_roic_collected),
        "portfolio_principal_outstanding": quantize_amount(portfolio_principal_outstanding),
        "portfolio_roic_outstanding": quantize_amount(portfolio_roic_outstanding),
        "portfolio_total_outstanding": quantize_amount(portfolio_total_outstanding),
        "avg_collection_rate": avg_collection_rate,
        "avg_loan_size_portfolio": avg_loan_size_portfolio,
        "q": q,
        "location": location,
        "group_name": group_name,
        "preferred_language": preferred_language,
        "risk": risk,
        "borrower_status": borrower_status,
        "from_date": request.GET.get("from_date", ""),
        "to_date": request.GET.get("to_date", ""),
        "language_choices": Borrower.LANGUAGE_CHOICES,
        "borrower_status_choices": Borrower.STATUS_CHOICES,
        "risk_choices": [("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
        "chart_location_labels": chart_location_labels,
        "chart_location_values": chart_location_values,
        "chart_group_labels": chart_group_labels,
        "chart_group_values": chart_group_values,
        "chart_language_labels": chart_language_labels,
        "chart_language_values": chart_language_values,
        "chart_risk_labels": chart_risk_labels,
        "chart_risk_values": chart_risk_values,
        "chart_status_labels": chart_status_labels,
        "chart_status_values": chart_status_values,
        "top_borrower_labels": top_borrower_labels,
        "top_borrower_outstanding": top_borrower_outstanding,
        "top_borrower_principal_outstanding": top_borrower_principal_outstanding,
        "top_borrower_roic_outstanding": top_borrower_roic_outstanding,
    }

    return render(request, "loans/borrowers/borrower_analytics.html", context)


@login_required
def borrower_status_analytics(request):
    borrowers = Borrower.objects.all().prefetch_related(
        Prefetch("loans", queryset=Loan.objects.select_related("agent_name").prefetch_related("payments"))
    ).order_by("full_name")

    q = (request.GET.get("q") or "").strip()
    location = (request.GET.get("location") or "").strip()
    group_name = (request.GET.get("group_name") or "").strip()
    preferred_language = (request.GET.get("preferred_language") or "").strip()
    borrower_status = (request.GET.get("borrower_status") or "").strip()

    if q:
        borrowers = borrowers.filter(
            Q(full_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(email__icontains=q) |
            Q(national_id__icontains=q) |
            Q(borrower_id__icontains=q) |
            Q(ghana_card_number__icontains=q)
        )

    if location:
        borrowers = borrowers.filter(location__icontains=location)

    if group_name:
        borrowers = borrowers.filter(group_name__icontains=group_name)

    if preferred_language:
        borrowers = borrowers.filter(preferred_language=preferred_language)

    if borrower_status:
        borrowers = borrowers.filter(status=borrower_status)

    rows = []

    summary = {
        "ACTIVE": {
            "count": 0,
            "loans": 0,
            "disbursed": Decimal("0.00"),
            "expected": Decimal("0.00"),
            "collected": Decimal("0.00"),
            "principal_outstanding": Decimal("0.00"),
            "roic_outstanding": Decimal("0.00"),
            "total_outstanding": Decimal("0.00"),
        },
        "CLOSED": {
            "count": 0,
            "loans": 0,
            "disbursed": Decimal("0.00"),
            "expected": Decimal("0.00"),
            "collected": Decimal("0.00"),
            "principal_outstanding": Decimal("0.00"),
            "roic_outstanding": Decimal("0.00"),
            "total_outstanding": Decimal("0.00"),
        },
        "BAD": {
            "count": 0,
            "loans": 0,
            "disbursed": Decimal("0.00"),
            "expected": Decimal("0.00"),
            "collected": Decimal("0.00"),
            "principal_outstanding": Decimal("0.00"),
            "roic_outstanding": Decimal("0.00"),
            "total_outstanding": Decimal("0.00"),
        },
    }

    location_status_map = defaultdict(lambda: {"ACTIVE": Decimal("0.00"), "CLOSED": Decimal("0.00"), "BAD": Decimal("0.00")})
    group_status_map = defaultdict(lambda: {"ACTIVE": Decimal("0.00"), "CLOSED": Decimal("0.00"), "BAD": Decimal("0.00")})
    language_status_map = defaultdict(lambda: {"ACTIVE": 0, "CLOSED": 0, "BAD": 0})

    for borrower in borrowers:
        borrower.refresh_status(save=True)
        loans = list(borrower.loans.all())
        b_status = borrower.status or "CLOSED"

        total_loans = len(loans)
        active_loans = sum(1 for l in loans if l.status == "ACTIVE")
        closed_loans = sum(1 for l in loans if l.status == "CLOSED")
        default_loans = sum(1 for l in loans if l.status == "DEFAULT")

        total_disbursed = sum((Decimal(l.amount) for l in loans), Decimal("0.00"))
        total_expected = sum((l.total_expected_amount for l in loans), Decimal("0.00"))
        total_collected = sum((l.total_paid_amount for l in loans), Decimal("0.00"))
        total_principal_collected = sum((l.total_principal_paid for l in loans), Decimal("0.00"))
        total_roic_collected = sum((l.total_roic_paid for l in loans), Decimal("0.00"))
        principal_outstanding = sum((l.principal_outstanding for l in loans), Decimal("0.00"))
        roic_outstanding = sum((l.roic_outstanding for l in loans), Decimal("0.00"))
        total_outstanding = sum((l.balance_amount for l in loans), Decimal("0.00"))
        total_roic = sum((l.roic_amount for l in loans), Decimal("0.00"))

        collection_rate = (
            (total_collected / total_expected) * Decimal("100")
        ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")

        avg_loan_size = (
            (total_disbursed / Decimal(total_loans)).quantize(Decimal("0.01"))
            if total_loans > 0 else Decimal("0.00")
        )

        latest_loan = max((l.created_at for l in loans), default=None)
        category_mix = defaultdict(int)
        for l in loans:
            category_mix[l.get_loan_category_display()] += 1

        row = {
            "borrower": borrower,
            "borrower_status": b_status,
            "total_loans": total_loans,
            "active_loans": active_loans,
            "closed_loans": closed_loans,
            "default_loans": default_loans,
            "total_disbursed": quantize_amount(total_disbursed),
            "total_roic": quantize_amount(total_roic),
            "total_expected": quantize_amount(total_expected),
            "total_collected": quantize_amount(total_collected),
            "total_principal_collected": quantize_amount(total_principal_collected),
            "total_roic_collected": quantize_amount(total_roic_collected),
            "principal_outstanding": quantize_amount(principal_outstanding),
            "roic_outstanding": quantize_amount(roic_outstanding),
            "total_outstanding": quantize_amount(total_outstanding),
            "collection_rate": collection_rate,
            "avg_loan_size": avg_loan_size,
            "latest_loan": latest_loan,
            "category_mix": dict(category_mix),
        }
        rows.append(row)

        summary[b_status]["count"] += 1
        summary[b_status]["loans"] += total_loans
        summary[b_status]["disbursed"] += total_disbursed
        summary[b_status]["expected"] += total_expected
        summary[b_status]["collected"] += total_collected
        summary[b_status]["principal_outstanding"] += principal_outstanding
        summary[b_status]["roic_outstanding"] += roic_outstanding
        summary[b_status]["total_outstanding"] += total_outstanding

        location_status_map[borrower.location or "Unknown"][b_status] += total_outstanding
        group_status_map[borrower.group_name or "Unknown"][b_status] += total_outstanding
        language_status_map[borrower.preferred_language or "Unknown"][b_status] += 1

    active_summary = summary["ACTIVE"]
    closed_summary = summary["CLOSED"]
    bad_summary = summary["BAD"]

    overall_borrowers = len(rows)
    overall_loans = sum(r["total_loans"] for r in rows)
    overall_disbursed = sum((r["total_disbursed"] for r in rows), Decimal("0.00"))
    overall_expected = sum((r["total_expected"] for r in rows), Decimal("0.00"))
    overall_collected = sum((r["total_collected"] for r in rows), Decimal("0.00"))
    overall_principal_outstanding = sum((r["principal_outstanding"] for r in rows), Decimal("0.00"))
    overall_roic_outstanding = sum((r["roic_outstanding"] for r in rows), Decimal("0.00"))
    overall_total_outstanding = sum((r["total_outstanding"] for r in rows), Decimal("0.00"))

    overall_collection_rate = (
        (overall_collected / overall_expected) * Decimal("100")
    ).quantize(Decimal("0.01")) if overall_expected > 0 else Decimal("0.00")

    bad_borrowers = sorted(
        [r for r in rows if r["borrower_status"] == "BAD"],
        key=lambda x: (-x["total_outstanding"], x["borrower"].full_name.lower())
    )[:10]

    active_exposure = sorted(
        [r for r in rows if r["borrower_status"] == "ACTIVE"],
        key=lambda x: (-x["total_outstanding"], x["borrower"].full_name.lower())
    )[:10]

    rows_sorted = sorted(
        rows,
        key=lambda x: (
            {"BAD": 0, "ACTIVE": 1, "CLOSED": 2}.get(x["borrower_status"], 3),
            -x["total_outstanding"],
            x["borrower"].full_name.lower(),
        )
    )
    pagination = paginate_items(request, rows_sorted, per_page=20)

    chart_status_labels = ["ACTIVE", "CLOSED", "BAD"]
    chart_status_values = [
        summary["ACTIVE"]["count"],
        summary["CLOSED"]["count"],
        summary["BAD"]["count"],
    ]

    chart_outstanding_status_values = [
        float(summary["ACTIVE"]["total_outstanding"]),
        float(summary["CLOSED"]["total_outstanding"]),
        float(summary["BAD"]["total_outstanding"]),
    ]

    chart_collection_status_values = [
        float(summary["ACTIVE"]["collected"]),
        float(summary["CLOSED"]["collected"]),
        float(summary["BAD"]["collected"]),
    ]

    chart_location_labels = list(location_status_map.keys())
    chart_location_active = [float(location_status_map[k]["ACTIVE"]) for k in chart_location_labels]
    chart_location_closed = [float(location_status_map[k]["CLOSED"]) for k in chart_location_labels]
    chart_location_bad = [float(location_status_map[k]["BAD"]) for k in chart_location_labels]

    chart_group_labels = list(group_status_map.keys())
    chart_group_active = [float(group_status_map[k]["ACTIVE"]) for k in chart_group_labels]
    chart_group_closed = [float(group_status_map[k]["CLOSED"]) for k in chart_group_labels]
    chart_group_bad = [float(group_status_map[k]["BAD"]) for k in chart_group_labels]

    chart_language_labels = list(language_status_map.keys())
    chart_language_active = [language_status_map[k]["ACTIVE"] for k in chart_language_labels]
    chart_language_closed = [language_status_map[k]["CLOSED"] for k in chart_language_labels]
    chart_language_bad = [language_status_map[k]["BAD"] for k in chart_language_labels]

    chart_bad_labels = [r["borrower"].full_name for r in bad_borrowers]
    chart_bad_outstanding = [float(r["total_outstanding"]) for r in bad_borrowers]

    chart_active_labels = [r["borrower"].full_name for r in active_exposure]
    chart_active_outstanding = [float(r["total_outstanding"]) for r in active_exposure]

    context = {
        "title": "Borrower Status Analytics",
        "borrowers": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "q": q,
        "location": location,
        "group_name": group_name,
        "preferred_language": preferred_language,
        "borrower_status": borrower_status,
        "language_choices": Borrower.LANGUAGE_CHOICES,
        "borrower_status_choices": Borrower.STATUS_CHOICES,
        "overall_borrowers": overall_borrowers,
        "overall_loans": overall_loans,
        "overall_disbursed": quantize_amount(overall_disbursed),
        "overall_expected": quantize_amount(overall_expected),
        "overall_collected": quantize_amount(overall_collected),
        "overall_principal_outstanding": quantize_amount(overall_principal_outstanding),
        "overall_roic_outstanding": quantize_amount(overall_roic_outstanding),
        "overall_total_outstanding": quantize_amount(overall_total_outstanding),
        "overall_collection_rate": overall_collection_rate,
        "active_summary": {k: (quantize_amount(v) if isinstance(v, Decimal) else v) for k, v in active_summary.items()},
        "closed_summary": {k: (quantize_amount(v) if isinstance(v, Decimal) else v) for k, v in closed_summary.items()},
        "bad_summary": {k: (quantize_amount(v) if isinstance(v, Decimal) else v) for k, v in bad_summary.items()},
        "chart_status_labels": chart_status_labels,
        "chart_status_values": chart_status_values,
        "chart_outstanding_status_values": chart_outstanding_status_values,
        "chart_collection_status_values": chart_collection_status_values,
        "chart_location_labels": chart_location_labels,
        "chart_location_active": chart_location_active,
        "chart_location_closed": chart_location_closed,
        "chart_location_bad": chart_location_bad,
        "chart_group_labels": chart_group_labels,
        "chart_group_active": chart_group_active,
        "chart_group_closed": chart_group_closed,
        "chart_group_bad": chart_group_bad,
        "chart_language_labels": chart_language_labels,
        "chart_language_active": chart_language_active,
        "chart_language_closed": chart_language_closed,
        "chart_language_bad": chart_language_bad,
        "chart_bad_labels": chart_bad_labels,
        "chart_bad_outstanding": chart_bad_outstanding,
        "chart_active_labels": chart_active_labels,
        "chart_active_outstanding": chart_active_outstanding,
    }

    return render(request, "loans/borrowers/borrower_status_analytics.html", context)


@login_required
def borrower_update(request, pk):
    _role3, _ = _get_request_role(request)
    if _role3 not in ("admin",):
        from django.contrib import messages as _m
        _m.error(request, "Only admins can edit borrowers.")
        return redirect("loans:dashboard")
    borrower = get_object_or_404(Borrower, pk=pk)
    form = BorrowerForm(request.POST or None, request.FILES or None, instance=borrower, creating=False)

    if request.method == "POST" and form.is_valid():
        borrower = form.save()
        borrower.refresh_status(save=True)
        messages.success(request, f"Borrower '{borrower.full_name}' updated successfully.")
        return redirect("loans:borrower_detail", pk=borrower.pk)

    return render(request, "loans/borrowers/borrower_update.html", {
        "form": form,
        "borrower": borrower,
        "title": f"Update Borrower - {borrower.full_name}",
    })


@login_required
def borrower_delete(request, pk):
    _role4, _ = _get_request_role(request)
    if _role4 not in ("admin",):
        from django.contrib import messages as _m
        _m.error(request, "Only admins can delete borrowers.")
        return redirect("loans:dashboard")
    borrower = get_object_or_404(Borrower, pk=pk)

    if request.method == "POST":
        name = borrower.full_name
        borrower.delete()
        messages.warning(request, f"Borrower '{name}' deleted.")
        return redirect("loans:borrower_list")

    return render(request, "loans/borrowers/borrower_confirm_delete.html", {
        "borrower": borrower,
        "title": "Delete Borrower",
    })


@login_required
def borrower_detail(request, pk):
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    borrower = get_object_or_404(Borrower, pk=pk)

    # Agents may only view borrowers assigned to them OR borrowers with no loans yet
    # (so they can issue the first loan). Once a loan exists under another agent,
    # access is denied.
    if _role == "agent" and _agent:
        has_own_loans   = borrower.loans.filter(agent_name=_agent).exists()
        has_other_loans = borrower.loans.exclude(agent_name=_agent).exists()
        has_any_loans   = borrower.loans.exists()
        if has_any_loans and not has_own_loans:
            from django.contrib import messages as _m
            _m.error(request, "This borrower is assigned to a different agent.")
            return redirect("agent_detail", pk=_agent.pk)

    borrower.refresh_status(save=True)
    external_debt_check = _loan_external_debt_check_for_borrower(borrower, request)

    loan_form = LoanCreateForBorrowerForm(
        request.POST or None,
        prefix="loan",
        agent_override=_agent if _role == "agent" else None,
    )
    payment_form = PaymentCreateForm(prefix="pay")

    if request.method == "POST":
        if "loan-submit" in request.POST and loan_form.is_valid():
            loan = loan_form.save(commit=False)
            loan.borrower = borrower
            external_debt_check = _loan_external_debt_check_for_borrower(borrower, request)
            if external_debt_check["requires_review"] and not _external_debt_acknowledged(request):
                loan_form.add_error(
                    None,
                    "This borrower has open debt with another onboarded company. Review the external debt summary and confirm before submitting the loan for approval."
                )
            else:
                # Agents always own the loans they issue
                if _role == "agent" and _agent:
                    loan.agent_name = _agent
                approval_description = (
                    f"Loan issuance request from borrower profile for {borrower.full_name} "
                    f"with principal GHS {loan.amount} over {loan.duration_weeks} weeks."
                )
                if external_debt_check["requires_review"]:
                    approval_description = (
                        f"{approval_description}\n\nExternal debt check: {format_cross_company_debt_summary(external_debt_check)}"
                    )
                approval = create_approval_request(
                    workflow_type="LOAN_CREATION",
                    title=f"Borrower loan request for {borrower.full_name}",
                    description=approval_description,
                    submitted_by=request.user,
                    payload=_loan_approval_payload(loan, borrower=borrower),
                    metadata={
                        "borrower_id": borrower.pk,
                        "borrower_name": borrower.full_name,
                        "agent_id": loan.agent_name_id,
                        "agent_name": loan.agent_name.name if loan.agent_name else "",
                        "category_preview": loan.get_loan_category_display(),
                        "external_debt_check": serialize_cross_company_debt_check(external_debt_check),
                        "external_debt_review_acknowledged": _external_debt_acknowledged(request),
                    },
                    source_path=request.path,
                    target_reference=borrower.full_name,
                    request=request,
                )
                log_activity(
                    category="LOAN",
                    action="approval_requested",
                    actor=request.user,
                    object_type="ApprovalRequest",
                    object_id=approval.pk,
                    object_label=approval.title,
                    message=f"Borrower detail loan request submitted for {borrower.full_name}.",
                    metadata={
                        "approval_id": approval.pk,
                        "borrower_id": borrower.pk,
                        "external_debt_check": serialize_cross_company_debt_check(external_debt_check),
                    },
                    request=request,
                )
                messages.success(
                    request,
                    f"Loan approval request submitted for {borrower.full_name}. "
                    "A different admin must approve it before the loan is issued."
                )
                return redirect("loans:borrower_detail", pk=borrower.pk)

    loans = borrower.loans.all().order_by("-created_at").prefetch_related("payments")
    statements = {loan.id: build_loan_statement(loan) for loan in loans}

    category_summary = defaultdict(int)
    for loan in loans:
        category_summary[loan.get_loan_category_display()] += 1

    return render(request, "loans/borrowers/borrower_detail.html", {
        "borrower": borrower,
        "borrower_login_username": visible_portal_username(
            getattr(getattr(borrower, "user", None), "username", ""),
        ),
        "loans": loans,
        "loan_form": loan_form,
        "payment_form": payment_form,
        "statements": statements,
        "category_summary": dict(category_summary),
        "borrower_category_mix": dict(category_summary),
        "external_debt_check": external_debt_check,
        "title": f"Borrower: {borrower.full_name}",
    })


@login_required
def loan_payment_create(request, loan_id):
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    loan = get_object_or_404(Loan.objects.select_related("borrower", "agent_name"), pk=loan_id)

    # Agents may only post payments on their own loans
    if _role == "agent" and _agent and loan.agent_name_id != _agent.pk:
        from django.contrib import messages as _m
        _m.error(request, "You can only record payments on loans assigned to you.")
        return redirect("agent_detail", pk=_agent.pk)

    borrower_id = loan.borrower_id

    form = PaymentCreateForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.loan = loan
        payment.save()
        loan.borrower.refresh_status(save=True)

        borrower_phone = loan.borrower.phone
        agent_phone = loan.agent_name.phone
        borrower_msg, agent_msg = _build_payment_create_sms_messages(loan, payment)

        safe_send_sms(borrower_phone, borrower_msg)
        safe_send_sms(agent_phone, agent_msg)

        messages.success(request, f"Payment recorded successfully for Loan #{loan.id}.")
        return redirect("loans:borrower_detail", pk=borrower_id)

    return render(request, "loans/payments/payment_create.html", {
        "loan": loan,
        "form": form,
        "title": f"Add Payment - Loan #{loan.id}",
    })


@login_required
def pending_payments_list(request):
    """Staff view: list all borrower-submitted pending payments."""
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    from .models import Payment
    from django.db.models import Sum as _Sum
    pending = (
        Payment.objects
        .filter(is_pending=True, is_void=False)
        .select_related("loan", "loan__borrower", "loan__agent_name", "submitted_by")
        .order_by("-created_at")
    )
    if _role == "agent" and _agent:
        pending = pending.filter(loan__agent_name=_agent)

    pending_list = list(pending)
    total_pending_amount = sum((p.amount for p in pending_list), Decimal("0.00"))
    unique_borrowers     = len({p.loan.borrower_id for p in pending_list})

    return render(request, "loans/payments/pending_payments.html", {
        "title":                "Pending Payment Confirmations",
        "pending":              pending_list,
        "total_pending_amount": total_pending_amount,
        "unique_borrowers":     unique_borrowers,
    })


@login_required
def payment_confirm(request, payment_id):
    """Staff confirms a borrower-submitted pending payment."""
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    from .models import Payment
    payment = get_object_or_404(Payment, pk=payment_id, is_pending=True, is_void=False)

    if _role == "agent" and _agent and payment.loan.agent_name_id != _agent.pk:
        messages.error(request, "You can only confirm payments on your own loans.")
        return redirect("loans:pending_payments")

    payment.is_pending = False
    payment.save()
    log_activity(
        category="LOAN",
        action="payment_confirmed",
        actor=request.user,
        object_type="Payment",
        object_id=payment.pk,
        object_label=f"Loan #{payment.loan_id} payment",
        message=f"Pending payment confirmed for Loan #{payment.loan_id}.",
        metadata={"loan_id": payment.loan_id, "payment_id": payment.pk},
        request=request,
    )

    if payment.submitted_by:
        try:
            from apps.notifications.services import notify_user
            notify_user(
                payment.submitted_by, "PAYMENT",
                "Payment Confirmed",
                f"Your payment of GHS {payment.amount:,.2f} for Loan #{payment.loan_id} "
                f"(Ref: {payment.reference or 'N/A'}) has been confirmed. Thank you!",
                send_email=False,
            )
        except Exception:
            pass

    messages.success(request, f"Payment of GHS {payment.amount:,.2f} confirmed for Loan #{payment.loan_id}.")
    return redirect("loans:pending_payments")


@login_required
def payment_reject(request, payment_id):
    """Staff rejects (voids) a borrower-submitted pending payment."""
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    from .models import Payment
    payment = get_object_or_404(Payment, pk=payment_id, is_pending=True, is_void=False)

    if _role == "agent" and _agent and payment.loan.agent_name_id != _agent.pk:
        messages.error(request, "You can only reject payments on your own loans.")
        return redirect("loans:pending_payments")

    payment.is_pending = False
    payment.is_void = True
    payment.save()
    log_activity(
        category="LOAN",
        action="payment_rejected",
        actor=request.user,
        object_type="Payment",
        object_id=payment.pk,
        object_label=f"Loan #{payment.loan_id} payment",
        message=f"Pending payment rejected for Loan #{payment.loan_id}.",
        metadata={"loan_id": payment.loan_id, "payment_id": payment.pk},
        request=request,
    )

    if payment.submitted_by:
        try:
            from apps.notifications.services import notify_user
            notify_user(
                payment.submitted_by, "PAYMENT",
                "Payment Not Confirmed",
                f"Your payment submission of GHS {payment.amount:,.2f} for Loan #{payment.loan_id} "
                f"could not be confirmed. Please contact your loan officer for assistance.",
                send_email=False,
            )
        except Exception:
            pass

    messages.warning(request, f"Payment of GHS {payment.amount:,.2f} rejected for Loan #{payment.loan_id}.")
    return redirect("loans:pending_payments")


@login_required
def payment_reconciliation_queue(request):
    """Staff queue for gateway collections that need review or reconciliation."""
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    collections = (
        RepaymentCollection.objects
        .select_related("loan", "borrower", "payment", "submitted_by", "loan__agent_name")
        .order_by("-initiated_at")
    )
    if _role == "agent" and _agent:
        collections = collections.filter(loan__agent_name=_agent)

    inflight = list(collections.filter(status__in=["PENDING", "PROCESSING", "SUCCEEDED"], payment__isnull=True)[:25])
    review_queue = list(collections.filter(status__in=["MANUAL_REVIEW", "FAILED"], payment__isnull=True)[:25])
    recent_reconciled = list(collections.filter(status="RECONCILED")[:12])

    total_value = sum((c.amount for c in inflight + review_queue), Decimal("0.00"))

    return render(request, "loans/payments/reconciliation_queue.html", {
        "title": "Repayment Reconciliation Queue",
        "inflight": inflight,
        "review_queue": review_queue,
        "recent_reconciled": recent_reconciled,
        "inflight_count": len(inflight),
        "review_count": len(review_queue),
        "total_open_value": total_value,
    })


@login_required
def payment_collection_mark_success(request, collection_id):
    if request.method != "POST":
        return redirect("loans:payment_reconciliation")

    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    collection = get_object_or_404(
        RepaymentCollection.objects.select_related("loan", "borrower", "loan__agent_name"),
        pk=collection_id,
    )
    if _role == "agent" and _agent and collection.loan.agent_name_id != _agent.pk:
        messages.error(request, "You can only reconcile collections on your own loans.")
        return redirect("loans:payment_reconciliation")

    payload = {
        "client_reference": collection.client_reference,
        "provider_reference": collection.provider_reference or collection.client_reference,
        "status": "success",
        "message": "Marked successful from reconciliation queue.",
    }
    collection, payment, _created = process_collection_callback(
        collection,
        provider_status="success",
        payload=payload,
    )

    if payment is not None:
        messages.success(request, f"Collection {collection.client_reference} was reconciled and posted.")
    else:
        messages.warning(request, f"Collection {collection.client_reference} still needs manual review.")
    return redirect("loans:payment_reconciliation")


@login_required
def payment_collection_force_reconcile(request, collection_id):
    if request.method != "POST":
        return redirect("loans:payment_reconciliation")

    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    collection = get_object_or_404(
        RepaymentCollection.objects.select_related("loan", "borrower", "loan__agent_name"),
        pk=collection_id,
    )
    if _role == "agent" and _agent and collection.loan.agent_name_id != _agent.pk:
        messages.error(request, "You can only reconcile collections on your own loans.")
        return redirect("loans:payment_reconciliation")

    payment, created = reconcile_collection(
        collection,
        reviewer=request.user,
        force=True,
        notes=f"Forced by {request.user.get_username()} on {timezone.localtime().strftime('%Y-%m-%d %H:%M')}.",
    )
    if payment is None:
        messages.error(request, "The collection could not be reconciled.")
    elif created:
        messages.success(request, f"Collection {collection.client_reference} was force-reconciled successfully.")
    else:
        messages.info(request, f"Collection {collection.client_reference} was already reconciled.")
    return redirect("loans:payment_reconciliation")


@login_required
def payment_collection_mark_failed(request, collection_id):
    if request.method != "POST":
        return redirect("loans:payment_reconciliation")

    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")

    collection = get_object_or_404(
        RepaymentCollection.objects.select_related("loan", "borrower", "loan__agent_name"),
        pk=collection_id,
    )
    if _role == "agent" and _agent and collection.loan.agent_name_id != _agent.pk:
        messages.error(request, "You can only update collections on your own loans.")
        return redirect("loans:payment_reconciliation")

    payload = {
        "client_reference": collection.client_reference,
        "provider_reference": collection.provider_reference or collection.client_reference,
        "status": "failed",
        "reason": "Marked failed from reconciliation queue.",
    }
    process_collection_callback(collection, provider_status="failed", payload=payload)
    messages.warning(request, f"Collection {collection.client_reference} marked as failed.")
    return redirect("loans:payment_reconciliation")


@csrf_exempt
def payment_collection_webhook(request, provider):
    """Webhook endpoint for payment gateway callbacks."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Only POST is allowed."}, status=405)

    if not _payment_webhook_authorized(request):
        return JsonResponse({"ok": False, "error": "Webhook authentication failed."}, status=403)

    try:
        if request.body:
            payload = json.loads(request.body.decode("utf-8"))
        else:
            payload = request.POST.dict()
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

    try:
        collection, payment, _created = process_collection_webhook(
            provider=provider.upper(),
            payload=payload,
        )
    except RepaymentCollection.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Collection not found."}, status=404)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse({
        "ok": True,
        "collection_reference": collection.client_reference,
        "status": collection.status,
        "payment_id": payment.pk if payment else None,
    })


@login_required
def loans_list(request):
    _role, _agent = _get_request_role(request)
    if _role == "borrower":
        return redirect("borrower:portal")
    loans = (
        Loan.objects.select_related("borrower", "agent_name")
        .prefetch_related("payments")
        .order_by("-created_at")
    )
    if _role == "agent" and _agent:
        loans = loans.filter(agent_name=_agent)

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    borrower_status = (request.GET.get("borrower_status") or "").strip()
    agent_id = (request.GET.get("agent_id") or "").strip()
    location = (request.GET.get("location") or "").strip()
    risk = (request.GET.get("risk") or "").strip()
    loan_category = (request.GET.get("loan_category") or "").strip()
    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")

    if q:
        loans = loans.filter(
            Q(id__icontains=q) |
            Q(borrower__full_name__icontains=q) |
            Q(borrower__borrower_id__icontains=q) |
            Q(borrower__national_id__icontains=q) |
            Q(borrower__phone__icontains=q) |
            Q(borrower__email__icontains=q) |
            Q(agent_name__name__icontains=q)
        )

    if status:
        loans = loans.filter(status=status)

    if borrower_status:
        loans = loans.filter(borrower__status=borrower_status)

    if agent_id:
        loans = loans.filter(agent_name_id=agent_id)

    if location:
        loans = loans.filter(borrower__location__icontains=location)

    if loan_category:
        loans = loans.filter(loan_category=loan_category)

    if from_date:
        parsed_from = parse_date(from_date)
        if parsed_from:
            loans = loans.filter(created_at__date__gte=parsed_from)

    if to_date:
        parsed_to = parse_date(to_date)
        if parsed_to:
            loans = loans.filter(created_at__date__lte=parsed_to)

    loan_rows = []

    total_loans = loans.count()
    active_loans = 0
    closed_loans = 0
    default_loans = 0

    total_disbursed = Decimal("0.00")
    total_expected = Decimal("0.00")
    total_roic = Decimal("0.00")
    total_collected = Decimal("0.00")
    total_principal_collected = Decimal("0.00")
    total_roic_collected = Decimal("0.00")
    total_principal_outstanding = Decimal("0.00")
    total_roic_outstanding = Decimal("0.00")
    total_balance = Decimal("0.00")

    for loan in loans:
        if loan.status == "ACTIVE":
            active_loans += 1
        elif loan.status == "CLOSED":
            closed_loans += 1
        elif loan.status == "DEFAULT":
            default_loans += 1

        risk_label = "Low"
        if loan.status == "DEFAULT" or loan.borrower.status == "BAD":
            risk_label = "High"
        elif loan.status == "ACTIVE" and loan.balance_amount > Decimal("0.00"):
            risk_label = "Medium"

        row = {
            "loan": loan,
            "risk_label": risk_label,
        }
        loan_rows.append(row)

        total_disbursed += loan.amount
        total_expected += loan.total_expected_amount
        total_roic += loan.roic_amount
        total_collected += loan.total_paid_amount
        total_principal_collected += loan.total_principal_paid
        total_roic_collected += loan.total_roic_paid
        total_principal_outstanding += loan.principal_outstanding
        total_roic_outstanding += loan.roic_outstanding
        total_balance += loan.balance_amount

    if risk:
        loan_rows = [r for r in loan_rows if r["risk_label"] == risk]

    loan_rows.sort(
        key=lambda x: (
            {"DEFAULT": 0, "ACTIVE": 1, "CLOSED": 2}.get(x["loan"].status, 3),
            -x["loan"].balance_amount,
            -x["loan"].created_at.timestamp(),
        )
    )
    pagination = paginate_items(request, loan_rows, per_page=12)

    avg_loan_size = (
        (total_disbursed / Decimal(total_loans)).quantize(Decimal("0.01"))
        if total_loans > 0 else Decimal("0.00")
    )
    collection_rate = (
        (total_collected / total_expected) * Decimal("100")
    ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")

    context = {
        "title": "Loans List",
        "loans": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "metrics_total_disbursed": quantize_amount(total_disbursed),
        "metrics_total_amount_collected": quantize_amount(total_collected),
        "metrics_roic_collected": quantize_amount(total_roic_collected),
        "metrics_principal_outstanding": quantize_amount(total_principal_outstanding),
        "total_loans": total_loans,
        "active_loans": active_loans,
        "closed_loans": closed_loans,
        "default_loans": default_loans,
        "total_disbursed": quantize_amount(total_disbursed),
        "total_expected": quantize_amount(total_expected),
        "total_roic": quantize_amount(total_roic),
        "total_collected": quantize_amount(total_collected),
        "total_principal_collected": quantize_amount(total_principal_collected),
        "total_roic_collected": quantize_amount(total_roic_collected),
        "total_principal_outstanding": quantize_amount(total_principal_outstanding),
        "total_roic_outstanding": quantize_amount(total_roic_outstanding),
        "total_balance": quantize_amount(total_balance),
        "avg_loan_size": avg_loan_size,
        "collection_rate": collection_rate,
        "q": q,
        "status": status,
        "borrower_status": borrower_status,
        "agent_id": agent_id,
        "location": location,
        "risk": risk,
        "loan_category": loan_category,
        "from_date": from_date,
        "to_date": to_date,
        "status_choices": Loan.STATUS_CHOICES,
        "loan_category_choices": [(t["code"], t["label"]) for t in __import__("apps.company.models", fromlist=["CompanyProfile"]).CompanyProfile.get_solo().tiers_for_template] if True else Loan.LOAN_CATEGORY_CHOICES,
        "borrower_status_choices": Borrower.STATUS_CHOICES,
        "risk_choices": [("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
        "agents": Agent.objects.all().order_by("name"),
    }
    return render(request, "loans/loans_list.html", context)


@login_required
def loan_analytics(request):
    _role5, _agent5 = _get_request_role(request)
    if _role5 == "borrower":
        return redirect("borrower:portal")
    if _role5 == "agent" and _agent5:
        return redirect("agent_comprehensive_analysis", pk=_agent5.pk)
    loans = (
        Loan.objects.select_related("borrower", "agent_name")
        .prefetch_related("payments")
        .order_by("-created_at")
    )

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    borrower_status = (request.GET.get("borrower_status") or "").strip()
    agent_id = (request.GET.get("agent_id") or "").strip()
    location = (request.GET.get("location") or "").strip()
    risk = (request.GET.get("risk") or "").strip()
    loan_category = (request.GET.get("loan_category") or "").strip()
    export = (request.GET.get("export") or "").strip().lower()

    if q:
        loans = loans.filter(
            Q(id__icontains=q) |
            Q(borrower__full_name__icontains=q) |
            Q(borrower__borrower_id__icontains=q) |
            Q(borrower__national_id__icontains=q) |
            Q(agent_name__name__icontains=q)
        )

    if status:
        loans = loans.filter(status=status)

    if borrower_status:
        loans = loans.filter(borrower__status=borrower_status)

    if agent_id:
        loans = loans.filter(agent_name_id=agent_id)

    if location:
        loans = loans.filter(borrower__location__icontains=location)

    if loan_category:
        loans = loans.filter(loan_category=loan_category)

    rows = []

    total_loans = loans.count()
    active_loans = 0
    closed_loans = 0
    default_loans = 0

    total_disbursed = Decimal("0.00")
    total_expected = Decimal("0.00")
    total_roic = Decimal("0.00")
    total_collected = Decimal("0.00")
    total_principal_collected = Decimal("0.00")
    total_roic_collected = Decimal("0.00")
    total_principal_outstanding = Decimal("0.00")
    total_roic_outstanding = Decimal("0.00")
    total_balance = Decimal("0.00")

    agent_map = defaultdict(lambda: Decimal("0.00"))
    borrower_status_map = {"ACTIVE": 0, "CLOSED": 0, "BAD": 0}
    loan_status_map = {"ACTIVE": 0, "CLOSED": 0, "DEFAULT": 0}
    risk_map = {"Low": 0, "Medium": 0, "High": 0}
    location_map = defaultdict(lambda: Decimal("0.00"))
    category_count_map = {label: 0 for _, label in Loan.LOAN_CATEGORY_CHOICES}
    category_balance_map = {label: 0.0 for _, label in Loan.LOAN_CATEGORY_CHOICES}

    for loan in loans:
        borrower_obj = loan.borrower
        agent_obj = loan.agent_name

        safe_borrower_status = borrower_obj.status if borrower_obj and borrower_obj.status in {"ACTIVE", "CLOSED", "BAD"} else "CLOSED"
        safe_loan_status = loan.status if loan.status in {"ACTIVE", "CLOSED", "DEFAULT"} else "ACTIVE"
        safe_agent_name = agent_obj.name if agent_obj and getattr(agent_obj, "name", "") else "Unknown Agent"
        safe_location = borrower_obj.location if borrower_obj and borrower_obj.location else "Unknown"
        safe_category_label = loan.get_loan_category_display() if getattr(loan, "loan_category", "") else "Uncategorized"

        if safe_loan_status == "ACTIVE":
            active_loans += 1
        elif safe_loan_status == "CLOSED":
            closed_loans += 1
        elif safe_loan_status == "DEFAULT":
            default_loans += 1

        risk_label = "Low"
        if safe_loan_status == "DEFAULT" or safe_borrower_status == "BAD":
            risk_label = "High"
        elif safe_loan_status == "ACTIVE" and loan.balance_amount > Decimal("0.00"):
            risk_label = "Medium"

        row = {
            "loan": loan,
            "risk_label": risk_label,
        }
        rows.append(row)

        total_disbursed += loan.amount
        total_expected += loan.total_expected_amount
        total_roic += loan.roic_amount
        total_collected += loan.total_paid_amount
        total_principal_collected += loan.total_principal_paid
        total_roic_collected += loan.total_roic_paid
        total_principal_outstanding += loan.principal_outstanding
        total_roic_outstanding += loan.roic_outstanding
        total_balance += loan.balance_amount

        agent_map[safe_agent_name] += loan.balance_amount
        borrower_status_map[safe_borrower_status] = borrower_status_map.get(safe_borrower_status, 0) + 1
        loan_status_map[safe_loan_status] = loan_status_map.get(safe_loan_status, 0) + 1
        risk_map[risk_label] = risk_map.get(risk_label, 0) + 1
        location_map[safe_location] += loan.balance_amount

        if safe_category_label not in category_count_map:
            category_count_map[safe_category_label] = 0
        if safe_category_label not in category_balance_map:
            category_balance_map[safe_category_label] = 0.0

        category_count_map[safe_category_label] += 1
        category_balance_map[safe_category_label] += float(loan.balance_amount)

    if risk:
        rows = [r for r in rows if r["risk_label"] == risk]

    rows.sort(
        key=lambda x: (
            -x["loan"].balance_amount,
            (x["loan"].borrower.full_name.lower() if x["loan"].borrower and x["loan"].borrower.full_name else "")
        )
    )

    avg_loan_size = (
        (total_disbursed / Decimal(total_loans)).quantize(Decimal("0.01"))
        if total_loans > 0 else Decimal("0.00")
    )
    collection_rate = (
        (total_collected / total_expected * Decimal("100")).quantize(Decimal("0.01"))
        if total_expected > 0 else Decimal("0.00")
    )

    top_outstanding = rows[:10]

    chart_agent_labels = list(agent_map.keys())
    chart_agent_values = [float(v) for v in agent_map.values()]
    chart_borrower_status_labels = list(borrower_status_map.keys())
    chart_borrower_status_values = list(borrower_status_map.values())
    chart_loan_status_labels = list(loan_status_map.keys())
    chart_loan_status_values = list(loan_status_map.values())
    chart_risk_labels = list(risk_map.keys())
    chart_risk_values = list(risk_map.values())
    chart_location_labels = list(location_map.keys())
    chart_location_values = [float(v) for v in location_map.values()]
    chart_category_labels = list(category_count_map.keys())
    chart_category_counts = list(category_count_map.values())
    chart_category_balances = list(category_balance_map.values())

    top_outstanding_labels = [f"Loan #{r['loan'].id}" for r in top_outstanding]
    top_outstanding_values = [float(r["loan"].balance_amount) for r in top_outstanding]
    top_principal_values = [float(r["loan"].principal_outstanding) for r in top_outstanding]
    top_roic_values = [float(r["loan"].roic_outstanding) for r in top_outstanding]

    if export == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="loan_analytics.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "Loan ID", "Borrower", "Borrower Status", "Agent", "Loan Status", "Loan Category",
            "Principal", "ROIC", "Expected", "Collected",
            "Principal Collected", "ROIC Collected",
            "Principal Outstanding", "ROIC Outstanding", "Balance", "Risk"
        ])
        for row in rows:
            l = row["loan"]
            writer.writerow([
                l.id,
                l.borrower.full_name if l.borrower else "",
                l.borrower.status if l.borrower and l.borrower.status else "CLOSED",
                l.agent_name.name if l.agent_name and l.agent_name.name else "Unknown Agent",
                l.status or "ACTIVE",
                l.get_loan_category_display() if getattr(l, "loan_category", "") else "Uncategorized",
                l.amount,
                l.roic_amount,
                l.total_expected_amount,
                l.total_paid_amount,
                l.total_principal_paid,
                l.total_roic_paid,
                l.principal_outstanding,
                l.roic_outstanding,
                l.balance_amount,
                row["risk_label"],
            ])
        return response

    if export == "excel":
        wb = Workbook()
        ws = wb.active
        ws.title = "Loan Analytics"

        headers = [
            "Loan ID", "Borrower", "Borrower Status", "Agent", "Loan Status", "Loan Category",
            "Principal", "ROIC", "Expected", "Collected",
            "Principal Collected", "ROIC Collected",
            "Principal Outstanding", "ROIC Outstanding", "Balance", "Risk"
        ]
        ws.append(headers)

        header_fill = PatternFill("solid", fgColor="1E3A8A")
        header_font = Font(color="FFFFFF", bold=True)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font

        for row in rows:
            l = row["loan"]
            ws.append([
                l.id,
                l.borrower.full_name if l.borrower else "",
                l.borrower.status if l.borrower and l.borrower.status else "CLOSED",
                l.agent_name.name if l.agent_name and l.agent_name.name else "Unknown Agent",
                l.status or "ACTIVE",
                l.get_loan_category_display() if getattr(l, "loan_category", "") else "Uncategorized",
                float(l.amount),
                float(l.roic_amount),
                float(l.total_expected_amount),
                float(l.total_paid_amount),
                float(l.total_principal_paid),
                float(l.total_roic_paid),
                float(l.principal_outstanding),
                float(l.roic_outstanding),
                float(l.balance_amount),
                row["risk_label"],
            ])

        for col in ws.columns:
            col_letter = col[0].column_letter
            max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
            ws.column_dimensions[col_letter].width = min(max_length + 2, 24)

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="loan_analytics.xlsx"'
        return response

    pagination = paginate_items(request, rows, per_page=20)

    context = {
        "title": "Loan Analytics",
        "loans": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "total_loans": total_loans,
        "active_loans": active_loans,
        "closed_loans": closed_loans,
        "default_loans": default_loans,
        "total_disbursed": quantize_amount(total_disbursed),
        "total_expected": quantize_amount(total_expected),
        "total_roic": quantize_amount(total_roic),
        "total_collected": quantize_amount(total_collected),
        "total_principal_collected": quantize_amount(total_principal_collected),
        "total_roic_collected": quantize_amount(total_roic_collected),
        "total_principal_outstanding": quantize_amount(total_principal_outstanding),
        "total_roic_outstanding": quantize_amount(total_roic_outstanding),
        "total_balance": quantize_amount(total_balance),
        "avg_loan_size": avg_loan_size,
        "collection_rate": collection_rate,
        "q": q,
        "status": status,
        "borrower_status": borrower_status,
        "agent_id": agent_id,
        "location": location,
        "risk": risk,
        "loan_category": loan_category,
        "status_choices": Loan.STATUS_CHOICES,
        "loan_category_choices": [(t["code"], t["label"]) for t in __import__("apps.company.models", fromlist=["CompanyProfile"]).CompanyProfile.get_solo().tiers_for_template] if True else Loan.LOAN_CATEGORY_CHOICES,
        "borrower_status_choices": Borrower.STATUS_CHOICES,
        "risk_choices": [("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
        "agents": Agent.objects.all().order_by("name"),
        "chart_agent_labels": chart_agent_labels,
        "chart_agent_values": chart_agent_values,
        "chart_borrower_status_labels": chart_borrower_status_labels,
        "chart_borrower_status_values": chart_borrower_status_values,
        "chart_loan_status_labels": chart_loan_status_labels,
        "chart_loan_status_values": chart_loan_status_values,
        "chart_risk_labels": chart_risk_labels,
        "chart_risk_values": chart_risk_values,
        "chart_location_labels": chart_location_labels,
        "chart_location_values": chart_location_values,
        "chart_category_labels": chart_category_labels,
        "chart_category_counts": chart_category_counts,
        "chart_category_balances": chart_category_balances,
        "top_outstanding_labels": top_outstanding_labels,
        "top_outstanding_values": top_outstanding_values,
        "top_principal_values": top_principal_values,
        "top_roic_values": top_roic_values,
    }
    return render(request, "loans/loan_analytics.html", context)


@login_required
def loan_monthly_analytics(request):
    loans = (
        Loan.objects.select_related("borrower", "agent_name")
        .prefetch_related("payments")
        .order_by("-created_at")
    )

    start_date = parse_date(request.GET.get("start_date") or "")
    end_date = parse_date(request.GET.get("end_date") or "")
    agent_id = (request.GET.get("agent_id") or "").strip()
    status = (request.GET.get("status") or "").strip()
    loan_category = (request.GET.get("loan_category") or "").strip()
    export = (request.GET.get("export") or "").strip().lower()

    today = timezone.localdate()
    if not start_date:
        start_date = today.replace(day=1)
    if not end_date:
        end_date = today

    loans = loans.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)

    if agent_id:
        loans = loans.filter(agent_name_id=agent_id)

    if status:
        loans = loans.filter(status=status)

    if loan_category:
        loans = loans.filter(loan_category=loan_category)

    rows = []

    total_loans = loans.count()
    active_loans = 0
    closed_loans = 0
    default_loans = 0

    total_disbursed = Decimal("0.00")
    total_expected = Decimal("0.00")
    total_roic = Decimal("0.00")
    total_collected = Decimal("0.00")
    total_principal_collected = Decimal("0.00")
    total_roic_collected = Decimal("0.00")
    total_principal_outstanding = Decimal("0.00")
    total_roic_outstanding = Decimal("0.00")
    total_balance = Decimal("0.00")

    daily_disbursed_map = defaultdict(lambda: Decimal("0.00"))
    daily_collected_map = defaultdict(lambda: Decimal("0.00"))
    status_map = {"ACTIVE": 0, "CLOSED": 0, "DEFAULT": 0}
    agent_map = defaultdict(lambda: Decimal("0.00"))
    category_map = defaultdict(lambda: Decimal("0.00"))

    for loan in loans:
        if loan.status == "ACTIVE":
            active_loans += 1
        elif loan.status == "CLOSED":
            closed_loans += 1
        elif loan.status == "DEFAULT":
            default_loans += 1

        total_disbursed += loan.amount
        total_expected += loan.total_expected_amount
        total_roic += loan.roic_amount
        total_collected += loan.total_paid_amount
        total_principal_collected += loan.total_principal_paid
        total_roic_collected += loan.total_roic_paid
        total_principal_outstanding += loan.principal_outstanding
        total_roic_outstanding += loan.roic_outstanding
        total_balance += loan.balance_amount

        loan_day = loan.created_at.date().isoformat()
        daily_disbursed_map[loan_day] += loan.amount
        agent_map[loan.agent_name.name] += loan.balance_amount
        status_map[loan.status] += 1
        category_map[loan.get_loan_category_display()] += loan.amount

        rows.append({"loan": loan})

    payments = Payment.objects.filter(
        is_void=False,
        loan__in=loans,
        payment_date__gte=start_date,
        payment_date__lte=end_date
    )
    for payment in payments:
        daily_collected_map[payment.payment_date.isoformat()] += payment.amount

    rows.sort(key=lambda x: (-x["loan"].balance_amount, x["loan"].borrower.full_name.lower()))

    avg_loan_size = (
        (total_disbursed / Decimal(total_loans)).quantize(Decimal("0.01"))
        if total_loans > 0 else Decimal("0.00")
    )
    collection_rate = (
        (total_collected / total_expected * Decimal("100")).quantize(Decimal("0.01"))
        if total_expected > 0 else Decimal("0.00")
    )

    all_days = sorted(set(list(daily_disbursed_map.keys()) + list(daily_collected_map.keys())))
    chart_day_labels = all_days
    chart_day_disbursed = [float(daily_disbursed_map[d]) for d in all_days]
    chart_day_collected = [float(daily_collected_map[d]) for d in all_days]

    chart_status_labels = list(status_map.keys())
    chart_status_values = list(status_map.values())

    chart_agent_labels = list(agent_map.keys())
    chart_agent_values = [float(v) for v in agent_map.values()]

    chart_category_labels = list(category_map.keys())
    chart_category_values = [float(v) for v in category_map.values()]

    if export == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="loan_monthly_analytics.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "Loan ID", "Borrower", "Agent", "Status", "Loan Category",
            "Principal", "ROIC", "Expected", "Collected",
            "Principal Outstanding", "ROIC Outstanding", "Balance", "Created At"
        ])
        for row in rows:
            l = row["loan"]
            writer.writerow([
                l.id, l.borrower.full_name, l.agent_name.name, l.status, l.get_loan_category_display(),
                l.amount, l.roic_amount, l.total_expected_amount, l.total_paid_amount,
                l.principal_outstanding, l.roic_outstanding, l.balance_amount,
                l.created_at.strftime("%Y-%m-%d %H:%M"),
            ])
        return response

    if export == "excel":
        wb = Workbook()
        ws = wb.active
        ws.title = "Loan Monthly Analytics"
        headers = [
            "Loan ID", "Borrower", "Agent", "Status", "Loan Category",
            "Principal", "ROIC", "Expected", "Collected",
            "Principal Outstanding", "ROIC Outstanding", "Balance", "Created At"
        ]
        ws.append(headers)
        header_fill = PatternFill("solid", fgColor="1E3A8A")
        header_font = Font(color="FFFFFF", bold=True)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font

        for row in rows:
            l = row["loan"]
            ws.append([
                l.id, l.borrower.full_name, l.agent_name.name, l.status, l.get_loan_category_display(),
                float(l.amount), float(l.roic_amount), float(l.total_expected_amount), float(l.total_paid_amount),
                float(l.principal_outstanding), float(l.roic_outstanding), float(l.balance_amount),
                l.created_at.strftime("%Y-%m-%d %H:%M"),
            ])

        for col in ws.columns:
            col_letter = col[0].column_letter
            max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
            ws.column_dimensions[col_letter].width = min(max_length + 2, 24)

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="loan_monthly_analytics.xlsx"'
        return response

    pagination = paginate_items(request, rows, per_page=20)

    context = {
        "title": "Loan Monthly Analytics",
        "loans": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "start_date": start_date,
        "end_date": end_date,
        "agent_id": agent_id,
        "status": status,
        "loan_category": loan_category,
        "total_loans": total_loans,
        "active_loans": active_loans,
        "closed_loans": closed_loans,
        "default_loans": default_loans,
        "total_disbursed": quantize_amount(total_disbursed),
        "total_expected": quantize_amount(total_expected),
        "total_roic": quantize_amount(total_roic),
        "total_collected": quantize_amount(total_collected),
        "total_principal_collected": quantize_amount(total_principal_collected),
        "total_roic_collected": quantize_amount(total_roic_collected),
        "total_principal_outstanding": quantize_amount(total_principal_outstanding),
        "total_roic_outstanding": quantize_amount(total_roic_outstanding),
        "total_balance": quantize_amount(total_balance),
        "avg_loan_size": avg_loan_size,
        "collection_rate": collection_rate,
        "chart_day_labels": chart_day_labels,
        "chart_day_disbursed": chart_day_disbursed,
        "chart_day_collected": chart_day_collected,
        "chart_status_labels": chart_status_labels,
        "chart_status_values": chart_status_values,
        "chart_agent_labels": chart_agent_labels,
        "chart_agent_values": chart_agent_values,
        "chart_category_labels": chart_category_labels,
        "chart_category_values": chart_category_values,
        "status_choices": Loan.STATUS_CHOICES,
        "loan_category_choices": [(t["code"], t["label"]) for t in __import__("apps.company.models", fromlist=["CompanyProfile"]).CompanyProfile.get_solo().tiers_for_template] if True else Loan.LOAN_CATEGORY_CHOICES,
        "agents": Agent.objects.all().order_by("name"),
    }
    return render(request, "loans/loan_monthly_analytics.html", context)
