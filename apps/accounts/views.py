import csv
from collections import defaultdict
from io import BytesIO
from datetime import date

from django.contrib import messages
from django.http import HttpResponse
from django.http import Http404
from django.utils.text import slugify
from django.shortcuts import redirect
from django.utils.dateparse import parse_date
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter

from .agent_imports import (
    build_agent_import_sample,
    get_agent_import_column_help,
    get_agent_import_formats,
    import_agent_rows,
    infer_agent_import_format,
    parse_agent_import,
)
from .forms import (
    AgentBulkImportForm,
    AgentForm,
    AgentRegisterForm,
    AgentResetPasswordForm,
    PayrollAdjustmentForm,
    PayrollRunForm,
)
from apps.core.approvals import create_approval_request
from apps.core.audit import log_activity
from apps.core.pagination import paginate_items
from apps.core.roles import admin_required, agent_or_admin_required, get_user_role, get_agent_for_user
from apps.company.models import CompanyProfile
from apps.company.statutory import calculate_progressive_tax
from apps.accounts.tenant_usernames import build_tenant_scoped_username, current_schema_name, visible_portal_username
from apps.tenants.enforcement import can_create_agent

from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Prefetch, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.models import Agent, PayrollAdjustment, PayrollLine, PayrollRun
from apps.loans.models import Loan, Payment


ROLE_KPIS = [
    ("AGENT", "Field Agents"),
    ("HR", "HR Team"),
    ("STAFF", "General Staff"),
    ("FINANCE", "Finance"),
    ("OPERATIONS", "Operations"),
    ("RECOVERY", "Recovery"),
    ("MANAGEMENT", "Management"),
]


def _money(value):
    return Decimal(value or "0.00").quantize(Decimal("0.01"))


def _payroll_policy(company_profile=None):
    profile = company_profile or CompanyProfile.get_solo()
    return {
        "profile": profile,
        "tax_enabled": profile.payroll_tax_enabled,
        "employee_pension_enabled": profile.payroll_employee_pension_enabled,
        "employer_pension_enabled": profile.payroll_employer_pension_enabled,
        "welfare_enabled": profile.payroll_welfare_enabled,
        "personal_relief": _money(profile.payroll_personal_relief_amount),
        "employee_pension_rate": Decimal(profile.payroll_employee_pension_rate or Decimal("0.00")),
        "employer_pension_rate": Decimal(profile.payroll_employer_pension_rate or Decimal("0.00")),
        "welfare_rate": Decimal(profile.payroll_welfare_deduction_rate or Decimal("0.00")),
        "welfare_fixed_amount": _money(profile.payroll_welfare_fixed_amount),
        "tax_brackets": profile.payroll_tax_brackets_for_template,
    }


def _payroll_adjustments_for_period(employee, period_start, period_end):
    adjustments = employee.payroll_adjustments.filter(is_active=True)
    results = []
    for adjustment in adjustments:
        if adjustment.is_recurring:
            if adjustment.effective_from > period_end:
                continue
            if adjustment.effective_to and adjustment.effective_to < period_start:
                continue
        else:
            if not (period_start <= adjustment.effective_from <= period_end):
                continue
        results.append(adjustment)
    return results


def _employee_period_metrics(employee, period_start, period_end):
    if not employee.is_field_agent:
        return {
            "collections": Decimal("0.00"),
            "disbursements": Decimal("0.00"),
            "payments_count": 0,
            "loans_count": 0,
            "active_loans": 0,
        }

    loans = Loan.objects.filter(
        agent_name=employee,
        created_at__date__gte=period_start,
        created_at__date__lte=period_end,
    )
    payments = Payment.objects.filter(
        is_void=False,
        loan__agent_name=employee,
        payment_date__gte=period_start,
        payment_date__lte=period_end,
    )
    return {
        "collections": _money(payments.aggregate(total=Sum("amount"))["total"]),
        "disbursements": _money(loans.aggregate(total=Sum("amount"))["total"]),
        "payments_count": payments.count(),
        "loans_count": loans.count(),
        "active_loans": Loan.objects.filter(agent_name=employee, status="ACTIVE").count(),
    }


def _calculate_payroll_snapshot(
    employee,
    period_start,
    period_end,
    *,
    include_commissions=True,
    include_loan_recovery=True,
    company_profile=None,
):
    adjustments = _payroll_adjustments_for_period(employee, period_start, period_end)
    period_metrics = _employee_period_metrics(employee, period_start, period_end)
    policy = _payroll_policy(company_profile)

    bonus_total = Decimal("0.00")
    overtime_total = Decimal("0.00")
    other_earnings = Decimal("0.00")
    manual_statutory_deductions = Decimal("0.00")
    loan_recovery_deductions = Decimal("0.00")
    other_deductions = Decimal("0.00")
    notes = []

    for adjustment in adjustments:
        amount = _money(adjustment.amount)
        if adjustment.adjustment_type == "EARNING":
            if adjustment.category == "BONUS":
                bonus_total += amount
            elif adjustment.category == "OVERTIME":
                overtime_total += amount
            else:
                other_earnings += amount
        else:
            if adjustment.category in {"TAX", "PENSION", "WELFARE"}:
                manual_statutory_deductions += amount
            elif adjustment.category in {"ADVANCE_RECOVERY", "LOAN_RECOVERY"} and include_loan_recovery:
                loan_recovery_deductions += amount
            else:
                other_deductions += amount
        notes.append(f"{adjustment.get_adjustment_type_display()}: {adjustment.label}")

    commission_total = Decimal("0.00")
    if include_commissions and employee.commission_rate > 0:
        commission_total = (
            period_metrics["collections"] * employee.commission_rate / Decimal("100.00")
        ).quantize(Decimal("0.01"))

    base_salary = _money(employee.base_salary)
    fixed_allowances = _money(employee.allowances_total)
    gross_pay = _money(base_salary + fixed_allowances + bonus_total + overtime_total + other_earnings + commission_total)
    employee_pension_deduction = Decimal("0.00")
    if policy["employee_pension_enabled"] and policy["employee_pension_rate"] > 0:
        employee_pension_deduction = _money(base_salary * policy["employee_pension_rate"] / Decimal("100.00"))

    chargeable_income = _money(max(gross_pay - employee_pension_deduction - policy["personal_relief"], Decimal("0.00")))
    tax_deduction = Decimal("0.00")
    if policy["tax_enabled"]:
        tax_deduction = calculate_progressive_tax(chargeable_income, policy["tax_brackets"])

    welfare_deduction = Decimal("0.00")
    if policy["welfare_enabled"]:
        welfare_deduction = _money(
            (gross_pay * policy["welfare_rate"] / Decimal("100.00")) + policy["welfare_fixed_amount"]
        )

    employer_statutory_contributions = Decimal("0.00")
    if policy["employer_pension_enabled"] and policy["employer_pension_rate"] > 0:
        employer_statutory_contributions = _money(
            base_salary * policy["employer_pension_rate"] / Decimal("100.00")
        )

    statutory_deductions = _money(
        tax_deduction
        + employee_pension_deduction
        + welfare_deduction
        + manual_statutory_deductions
    )
    total_deductions = _money(statutory_deductions + loan_recovery_deductions + other_deductions)
    net_pay = _money(gross_pay - total_deductions)

    return {
        "employee": employee,
        "payment_method": employee.preferred_payment_method,
        "base_salary": base_salary,
        "fixed_allowances": fixed_allowances,
        "bonus_total": _money(bonus_total),
        "commission_total": _money(commission_total),
        "overtime_total": _money(overtime_total),
        "other_earnings": _money(other_earnings),
        "variable_earnings_total": _money(bonus_total + overtime_total + other_earnings + commission_total),
        "tax_deduction": _money(tax_deduction),
        "employee_pension_deduction": _money(employee_pension_deduction),
        "welfare_deduction": _money(welfare_deduction),
        "manual_statutory_deductions": _money(manual_statutory_deductions),
        "employer_statutory_contributions": _money(employer_statutory_contributions),
        "statutory_deductions": _money(statutory_deductions),
        "loan_recovery_deductions": _money(loan_recovery_deductions),
        "other_deductions": _money(other_deductions),
        "gross_pay": gross_pay,
        "total_deductions": total_deductions,
        "net_pay": net_pay,
        "chargeable_income": chargeable_income,
        "collections_tracked": period_metrics["collections"],
        "disbursements_tracked": period_metrics["disbursements"],
        "period_metrics": period_metrics,
        "notes": "; ".join(notes),
        "adjustments": adjustments,
        "policy": policy,
    }


def _build_workforce_row(employee):
    loans = list(employee.loans.all()) if hasattr(employee, "loans") else []
    total_loans = len(loans)
    active_loans = sum(1 for loan in loans if loan.status == "ACTIVE")
    default_loans = sum(1 for loan in loans if loan.status == "DEFAULT")
    total_outstanding = _money(sum((loan.balance_amount for loan in loans), Decimal("0.00")))

    return {
        "employee": employee,
        "total_loans": total_loans,
        "active_loans": active_loans,
        "default_loans": default_loans,
        "total_outstanding": total_outstanding,
        "gross_regular_pay": employee.gross_regular_pay,
        "payroll_ready": employee.payroll_active and employee.base_salary > 0,
    }


def _create_payroll_run_lines(run):
    company_profile = CompanyProfile.get_solo()
    employees = Agent.objects.order_by("name")
    if run.include_active_only:
        employees = employees.filter(employment_status="ACTIVE")
    employees = employees.filter(payroll_active=True)

    created = 0
    PayrollLine.objects.filter(run=run).delete()
    for employee in employees:
        snapshot = _calculate_payroll_snapshot(
            employee,
            run.period_start,
            run.period_end,
            include_commissions=run.include_commissions,
            include_loan_recovery=run.include_loan_recovery,
            company_profile=company_profile,
        )
        PayrollLine.objects.create(
            run=run,
            employee=employee,
            payment_method=snapshot["payment_method"],
            base_salary=snapshot["base_salary"],
            fixed_allowances=snapshot["fixed_allowances"],
            bonus_total=snapshot["bonus_total"],
            commission_total=snapshot["commission_total"],
            overtime_total=snapshot["overtime_total"],
            other_earnings=snapshot["other_earnings"],
            tax_deduction=snapshot["tax_deduction"],
            employee_pension_deduction=snapshot["employee_pension_deduction"],
            welfare_deduction=snapshot["welfare_deduction"],
            manual_statutory_deductions=snapshot["manual_statutory_deductions"],
            employer_statutory_contributions=snapshot["employer_statutory_contributions"],
            statutory_deductions=snapshot["statutory_deductions"],
            loan_recovery_deductions=snapshot["loan_recovery_deductions"],
            other_deductions=snapshot["other_deductions"],
            gross_pay=snapshot["gross_pay"],
            total_deductions=snapshot["total_deductions"],
            net_pay=snapshot["net_pay"],
            collections_tracked=snapshot["collections_tracked"],
            disbursements_tracked=snapshot["disbursements_tracked"],
            notes=snapshot["notes"],
        )
        created += 1
    return created


def _payroll_run_excel_response(run):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = slugify(run.title)[:28] or "payroll"
    headers = [
        "Employee Code",
        "Name",
        "Role",
        "Department",
        "Payment Method",
        "Base Salary",
        "Fixed Allowances",
        "Bonus",
        "Commission",
        "Overtime",
        "Other Earnings",
        "Gross Pay",
        "Tax Deduction",
        "Employee Pension",
        "Welfare Deduction",
        "Manual Statutory",
        "Employer Statutory",
        "Statutory Deductions",
        "Loan Recovery",
        "Other Deductions",
        "Total Deductions",
        "Net Pay",
        "Collections Tracked",
        "Disbursements Tracked",
    ]
    sheet.append(headers)
    header_fill = PatternFill(fill_type="solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font

    for line in run.lines.select_related("employee"):
        employee = line.employee
        sheet.append(
            [
                employee.agent_id,
                employee.name,
                employee.get_workforce_role_display(),
                employee.department,
                line.get_payment_method_display(),
                float(line.base_salary),
                float(line.fixed_allowances),
                float(line.bonus_total),
                float(line.commission_total),
                float(line.overtime_total),
                float(line.other_earnings),
                float(line.gross_pay),
                float(line.tax_deduction),
                float(line.employee_pension_deduction),
                float(line.welfare_deduction),
                float(line.manual_statutory_deductions),
                float(line.employer_statutory_contributions),
                float(line.statutory_deductions),
                float(line.loan_recovery_deductions),
                float(line.other_deductions),
                float(line.total_deductions),
                float(line.net_pay),
                float(line.collections_tracked),
                float(line.disbursements_tracked),
            ]
        )

    for idx in range(1, len(headers) + 1):
        sheet.column_dimensions[get_column_letter(idx)].width = 18

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{slugify(run.title) or "payroll-run"}-export.xlsx"'
    return response


@admin_required
def agent_list(request):
    agents = Agent.objects.all().select_related("supervisor").order_by("-created_at").prefetch_related(
        Prefetch("loans", queryset=Loan.objects.select_related("borrower").prefetch_related("payments"))
    )
    workforce_all = Agent.objects.all()

    q = (request.GET.get("q") or "").strip()
    location = (request.GET.get("location") or "").strip()
    group_name = (request.GET.get("group_name") or "").strip()
    workforce_role = (request.GET.get("workforce_role") or "").strip()
    department = (request.GET.get("department") or "").strip()
    employment_status = (request.GET.get("employment_status") or "").strip()
    access = (request.GET.get("access") or "").strip()
    risk = (request.GET.get("risk") or "").strip()
    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")

    if q:
        agents = agents.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q) |
            Q(email__icontains=q) |
            Q(agent_id__icontains=q) |
            Q(ghana_card_number__icontains=q) |
            Q(job_title__icontains=q) |
            Q(department__icontains=q)
        )

    if location:
        agents = agents.filter(location__icontains=location)

    if group_name:
        agents = agents.filter(group_name__icontains=group_name)

    if workforce_role:
        agents = agents.filter(workforce_role=workforce_role)

    if department:
        agents = agents.filter(department__icontains=department)

    if employment_status:
        agents = agents.filter(employment_status=employment_status)

    if access == "ADMIN":
        agents = agents.filter(has_admin_access=True)
    elif access == "STANDARD":
        agents = agents.filter(has_admin_access=False)

    if from_date:
        parsed_from = parse_date(from_date)
        if parsed_from:
            agents = agents.filter(created_at__date__gte=parsed_from)

    if to_date:
        parsed_to = parse_date(to_date)
        if parsed_to:
            agents = agents.filter(created_at__date__lte=parsed_to)

    agent_rows = []
    portfolio_principal = Decimal("0.00")
    portfolio_expected = Decimal("0.00")
    portfolio_collected = Decimal("0.00")
    portfolio_principal_outstanding = Decimal("0.00")
    portfolio_roic_outstanding = Decimal("0.00")
    portfolio_total_outstanding = Decimal("0.00")
    agents_with_loans = 0
    agents_with_active_loans = 0
    agents_with_default_loans = 0

    for agent in agents:
        loans = list(agent.loans.all())
        total_loans = len(loans)
        active_loans = sum(1 for l in loans if l.status == "ACTIVE")
        default_loans = sum(1 for l in loans if l.status == "DEFAULT")
        total_expected = sum((l.total_expected_amount for l in loans), Decimal("0.00"))
        total_collected = sum((l.total_paid_amount for l in loans), Decimal("0.00"))
        total_outstanding = sum((l.balance_amount for l in loans), Decimal("0.00"))
        total_disbursed = sum((l.amount for l in loans), Decimal("0.00"))
        total_principal_collected = sum((l.total_principal_paid for l in loans), Decimal("0.00"))
        total_roic = sum((l.roic_amount for l in loans), Decimal("0.00"))
        total_roic_collected = sum((l.total_roic_paid for l in loans), Decimal("0.00"))
        principal_outstanding = sum((l.principal_outstanding for l in loans), Decimal("0.00"))
        roic_outstanding = sum((l.roic_outstanding for l in loans), Decimal("0.00"))
        distinct_borrowers = len({l.borrower_id for l in loans})
        collection_rate = (
            (total_collected / total_expected) * Decimal("100")
        ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")
        risk_label = "Low"
        if default_loans > 0 or total_outstanding >= Decimal("20000.00"):
            risk_label = "High"
        elif active_loans > 0 and total_outstanding > Decimal("0.00"):
            risk_label = "Medium"

        row = _build_workforce_row(agent)
        row.update({
            "distinct_borrowers": distinct_borrowers,
            "total_disbursed": _money(total_disbursed),
            "total_roic": _money(total_roic),
            "total_expected": _money(total_expected),
            "total_collected": _money(total_collected),
            "total_principal_collected": _money(total_principal_collected),
            "total_roic_collected": _money(total_roic_collected),
            "principal_outstanding": _money(principal_outstanding),
            "roic_outstanding": _money(roic_outstanding),
            "collection_rate": collection_rate,
            "risk_label": risk_label,
        })
        agent_rows.append(row)

        portfolio_principal += total_disbursed
        portfolio_expected += total_expected
        portfolio_collected += total_collected
        portfolio_principal_outstanding += principal_outstanding
        portfolio_roic_outstanding += roic_outstanding
        portfolio_total_outstanding += total_outstanding
        if total_loans > 0:
            agents_with_loans += 1
        if active_loans > 0:
            agents_with_active_loans += 1
        if default_loans > 0:
            agents_with_default_loans += 1

    if risk:
        agent_rows = [r for r in agent_rows if r["risk_label"] == risk]

    agent_rows.sort(
        key=lambda x: (
            -int(x["payroll_ready"]),
            -x["gross_regular_pay"],
            x["employee"].name.lower(),
        )
    )
    pagination = paginate_items(request, agent_rows, per_page=12)

    total_workforce = workforce_all.count()
    active_workforce = workforce_all.filter(employment_status="ACTIVE").count()
    payroll_enabled_count = workforce_all.filter(payroll_active=True).count()
    admin_access_count = workforce_all.filter(has_admin_access=True).count()
    monthly_base_payroll = _money(sum((employee.gross_regular_pay for employee in workforce_all), Decimal("0.00")))
    monthly_base_salary = _money(sum((employee.base_salary for employee in workforce_all), Decimal("0.00")))
    role_totals = []
    for code, label in ROLE_KPIS:
        role_totals.append({"code": code, "label": label, "count": workforce_all.filter(workforce_role=code).count()})

    context = {
        "agents": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "title": "Workforce Directory",

        "total_agents": total_workforce,
        "active_workforce": active_workforce,
        "payroll_enabled_count": payroll_enabled_count,
        "admin_access_count": admin_access_count,
        "agents_with_loans": agents_with_loans,
        "agents_with_active_loans": agents_with_active_loans,
        "agents_with_default_loans": agents_with_default_loans,
        "monthly_base_payroll": monthly_base_payroll,
        "monthly_base_salary": monthly_base_salary,
        "role_totals": role_totals,

        "portfolio_principal": portfolio_principal.quantize(Decimal("0.01")),
        "portfolio_expected": portfolio_expected.quantize(Decimal("0.01")),
        "portfolio_collected": portfolio_collected.quantize(Decimal("0.01")),
        "portfolio_principal_outstanding": portfolio_principal_outstanding.quantize(Decimal("0.01")),
        "portfolio_roic_outstanding": portfolio_roic_outstanding.quantize(Decimal("0.01")),
        "portfolio_total_outstanding": portfolio_total_outstanding.quantize(Decimal("0.01")),

        "q": q,
        "location": location,
        "group_name": group_name,
        "workforce_role": workforce_role,
        "department": department,
        "employment_status": employment_status,
        "access": access,
        "risk": risk,
        "from_date": from_date,
        "to_date": to_date,
        "risk_choices": [("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
        "role_choices": Agent._meta.get_field("workforce_role").choices,
        "employment_status_choices": Agent._meta.get_field("employment_status").choices,
        "access_choices": [("ADMIN", "Admin Console Access"), ("STANDARD", "Standard / Field Access")],
    }

    return render(request, "agents/agent_list.html", context)


@admin_required
def agents_analytics(request):
    agents = Agent.objects.all().prefetch_related(
        Prefetch("loans", queryset=Loan.objects.select_related("borrower").prefetch_related("payments"))
    ).order_by("name")

    q = (request.GET.get("q") or "").strip()
    location = (request.GET.get("location") or "").strip()
    group_name = (request.GET.get("group_name") or "").strip()
    risk = (request.GET.get("risk") or "").strip()
    export = (request.GET.get("export") or "").strip().lower()
    printable = (request.GET.get("print") or "").strip()

    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")

    if q:
        agents = agents.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q) |
            Q(email__icontains=q) |
            Q(agent_id__icontains=q) |
            Q(ghana_card_number__icontains=q)
        )

    if location:
        agents = agents.filter(location__icontains=location)

    if group_name:
        agents = agents.filter(group_name__icontains=group_name)

    if from_date:
        parsed_from = parse_date(from_date)
        if parsed_from:
            agents = agents.filter(created_at__date__gte=parsed_from)

    if to_date:
        parsed_to = parse_date(to_date)
        if parsed_to:
            agents = agents.filter(created_at__date__lte=parsed_to)

    agent_rows = []

    total_agents = agents.count()
    agents_with_loans = 0
    agents_without_loans = 0
    agents_with_active_loans = 0
    agents_with_default_loans = 0
    agents_fully_paid = 0

    total_loans = 0
    total_active_loans = 0
    total_closed_loans = 0
    total_default_loans = 0
    total_distinct_borrowers = 0

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
    risk_map = {"Low": 0, "Medium": 0, "High": 0}
    status_map = {"No Loan": 0, "Active": 0, "Closed": 0, "Default": 0}

    for agent in agents:
        loans = list(agent.loans.all())

        total_loans_a = len(loans)
        active_loans = sum(1 for l in loans if l.status == "ACTIVE")
        closed_loans = sum(1 for l in loans if l.status == "CLOSED")
        default_loans = sum(1 for l in loans if l.status == "DEFAULT")
        distinct_borrowers = len({l.borrower_id for l in loans})

        total_disbursed = sum((l.amount for l in loans), Decimal("0.00"))
        total_roic = sum((l.roic_amount for l in loans), Decimal("0.00"))
        total_expected = sum((l.total_expected_amount for l in loans), Decimal("0.00"))
        total_collected = sum((l.total_paid_amount for l in loans), Decimal("0.00"))
        total_principal_collected = sum((l.total_principal_paid for l in loans), Decimal("0.00"))
        total_roic_collected = sum((l.total_roic_paid for l in loans), Decimal("0.00"))
        principal_outstanding = sum((l.principal_outstanding for l in loans), Decimal("0.00"))
        roic_outstanding = sum((l.roic_outstanding for l in loans), Decimal("0.00"))
        total_outstanding = sum((l.balance_amount for l in loans), Decimal("0.00"))

        avg_loan_size = (total_disbursed / total_loans_a).quantize(Decimal("0.01")) if total_loans_a > 0 else Decimal("0.00")
        collection_rate = (
            (total_collected / total_expected) * Decimal("100")
        ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")

        latest_loan = max((l.created_at for l in loans), default=None)
        latest_payment = None
        payment_dates = []
        for l in loans:
            for p in l.payments.filter(is_void=False):
                payment_dates.append(p.payment_date)
        if payment_dates:
            latest_payment = max(payment_dates)

        if total_loans_a == 0:
            agents_without_loans += 1
            status_label = "No Loan"
        else:
            agents_with_loans += 1
            if default_loans > 0:
                status_label = "Default"
            elif active_loans > 0:
                status_label = "Active"
            else:
                status_label = "Closed"

        if active_loans > 0:
            agents_with_active_loans += 1
        if default_loans > 0:
            agents_with_default_loans += 1
        if total_loans_a > 0 and total_outstanding <= Decimal("0.00"):
            agents_fully_paid += 1

        risk_label = "Low"
        if default_loans > 0 or total_outstanding >= Decimal("20000.00"):
            risk_label = "High"
        elif active_loans > 0 and total_outstanding > Decimal("0.00"):
            risk_label = "Medium"

        row = {
            "agent": agent,
            "distinct_borrowers": distinct_borrowers,
            "total_loans": total_loans_a,
            "active_loans": active_loans,
            "closed_loans": closed_loans,
            "default_loans": default_loans,
            "total_disbursed": total_disbursed.quantize(Decimal("0.01")),
            "total_roic": total_roic.quantize(Decimal("0.01")),
            "total_expected": total_expected.quantize(Decimal("0.01")),
            "total_collected": total_collected.quantize(Decimal("0.01")),
            "total_principal_collected": total_principal_collected.quantize(Decimal("0.01")),
            "total_roic_collected": total_roic_collected.quantize(Decimal("0.01")),
            "principal_outstanding": principal_outstanding.quantize(Decimal("0.01")),
            "roic_outstanding": roic_outstanding.quantize(Decimal("0.01")),
            "total_outstanding": total_outstanding.quantize(Decimal("0.01")),
            "avg_loan_size": avg_loan_size,
            "collection_rate": collection_rate,
            "latest_loan": latest_loan,
            "latest_payment": latest_payment,
            "risk_label": risk_label,
            "status_label": status_label,
        }
        agent_rows.append(row)

        total_loans += total_loans_a
        total_active_loans += active_loans
        total_closed_loans += closed_loans
        total_default_loans += default_loans
        total_distinct_borrowers += distinct_borrowers

        portfolio_principal += total_disbursed
        portfolio_roic += total_roic
        portfolio_expected += total_expected
        portfolio_collected += total_collected
        portfolio_principal_collected += total_principal_collected
        portfolio_roic_collected += total_roic_collected
        portfolio_principal_outstanding += principal_outstanding
        portfolio_roic_outstanding += roic_outstanding
        portfolio_total_outstanding += total_outstanding

        location_key = agent.location or "Unknown"
        location_map.setdefault(location_key, Decimal("0.00"))
        location_map[location_key] += total_outstanding

        group_key = agent.group_name or "Unknown"
        group_map.setdefault(group_key, Decimal("0.00"))
        group_map[group_key] += total_outstanding

        risk_map[risk_label] += 1
        status_map[status_label] += 1

    if risk:
        agent_rows = [r for r in agent_rows if r["risk_label"] == risk]

    agent_rows.sort(key=lambda x: (-x["total_outstanding"], -x["active_loans"], x["agent"].name.lower()))

    avg_collection_rate = (
        (portfolio_collected / portfolio_expected) * Decimal("100")
    ).quantize(Decimal("0.01")) if portfolio_expected > 0 else Decimal("0.00")

    avg_loan_size_portfolio = (
        portfolio_principal / total_loans
    ).quantize(Decimal("0.01")) if total_loans > 0 else Decimal("0.00")

    top_10_outstanding = agent_rows[:10]

    chart_location_labels = list(location_map.keys())
    chart_location_values = [float(v) for v in location_map.values()]

    chart_group_labels = list(group_map.keys())
    chart_group_values = [float(v) for v in group_map.values()]

    chart_risk_labels = list(risk_map.keys())
    chart_risk_values = list(risk_map.values())

    chart_status_labels = list(status_map.keys())
    chart_status_values = list(status_map.values())

    top_agent_labels = [r["agent"].name for r in top_10_outstanding]
    top_agent_outstanding = [float(r["total_outstanding"]) for r in top_10_outstanding]
    top_agent_principal_outstanding = [float(r["principal_outstanding"]) for r in top_10_outstanding]
    top_agent_roic_outstanding = [float(r["roic_outstanding"]) for r in top_10_outstanding]
    top_agent_collections = [float(r["total_collected"]) for r in top_10_outstanding]

    if export == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="agents_analytics.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Agent ID", "Name", "Phone", "Location", "Group",
            "Borrowers Served", "Total Loans", "Active Loans", "Closed Loans", "Default Loans",
            "Disbursed", "ROIC", "Expected", "Collected",
            "Principal Collected", "ROIC Collected",
            "Principal Outstanding", "ROIC Outstanding", "Total Outstanding",
            "Collection Rate", "Average Loan Size", "Risk", "Status"
        ])

        for row in agent_rows:
            a = row["agent"]
            writer.writerow([
                a.agent_id,
                a.name,
                a.phone,
                a.location,
                a.group_name,
                row["distinct_borrowers"],
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
                row["avg_loan_size"],
                row["risk_label"],
                row["status_label"],
            ])
        return response

    if export == "excel":
        wb = Workbook()
        ws = wb.active
        ws.title = "Agents Analytics"

        headers = [
            "Agent ID", "Name", "Phone", "Location", "Group",
            "Borrowers Served", "Total Loans", "Active Loans", "Closed Loans", "Default Loans",
            "Disbursed", "ROIC", "Expected", "Collected",
            "Principal Collected", "ROIC Collected",
            "Principal Outstanding", "ROIC Outstanding", "Total Outstanding",
            "Collection Rate", "Average Loan Size", "Risk", "Status"
        ]
        ws.append(headers)

        header_fill = PatternFill("solid", fgColor="1E3A8A")
        header_font = Font(color="FFFFFF", bold=True)

        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font

        for row in agent_rows:
            a = row["agent"]
            ws.append([
                a.agent_id,
                a.name,
                a.phone,
                a.location,
                a.group_name,
                row["distinct_borrowers"],
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
                float(row["avg_loan_size"]),
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
        response["Content-Disposition"] = 'attachment; filename="agents_analytics.xlsx"'
        return response

    pagination = paginate_items(request, agent_rows, per_page=20)

    context = {
        "title": "Agents Analytics",
        "agents": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],
        "printable": printable,

        "total_agents": total_agents,
        "agents_with_loans": agents_with_loans,
        "agents_without_loans": agents_without_loans,
        "agents_with_active_loans": agents_with_active_loans,
        "agents_with_default_loans": agents_with_default_loans,
        "agents_fully_paid": agents_fully_paid,

        "total_loans": total_loans,
        "total_active_loans": total_active_loans,
        "total_closed_loans": total_closed_loans,
        "total_default_loans": total_default_loans,
        "total_distinct_borrowers": total_distinct_borrowers,

        "portfolio_principal": portfolio_principal.quantize(Decimal("0.01")),
        "portfolio_roic": portfolio_roic.quantize(Decimal("0.01")),
        "portfolio_expected": portfolio_expected.quantize(Decimal("0.01")),
        "portfolio_collected": portfolio_collected.quantize(Decimal("0.01")),
        "portfolio_principal_collected": portfolio_principal_collected.quantize(Decimal("0.01")),
        "portfolio_roic_collected": portfolio_roic_collected.quantize(Decimal("0.01")),
        "portfolio_principal_outstanding": portfolio_principal_outstanding.quantize(Decimal("0.01")),
        "portfolio_roic_outstanding": portfolio_roic_outstanding.quantize(Decimal("0.01")),
        "portfolio_total_outstanding": portfolio_total_outstanding.quantize(Decimal("0.01")),

        "avg_collection_rate": avg_collection_rate,
        "avg_loan_size_portfolio": avg_loan_size_portfolio,

        "q": q,
        "location": location,
        "group_name": group_name,
        "risk": risk,
        "from_date": from_date,
        "to_date": to_date,

        "risk_choices": [("Low", "Low"), ("Medium", "Medium"), ("High", "High")],

        "chart_location_labels": chart_location_labels,
        "chart_location_values": chart_location_values,
        "chart_group_labels": chart_group_labels,
        "chart_group_values": chart_group_values,
        "chart_risk_labels": chart_risk_labels,
        "chart_risk_values": chart_risk_values,
        "chart_status_labels": chart_status_labels,
        "chart_status_values": chart_status_values,
        "top_agent_labels": top_agent_labels,
        "top_agent_outstanding": top_agent_outstanding,
        "top_agent_principal_outstanding": top_agent_principal_outstanding,
        "top_agent_roic_outstanding": top_agent_roic_outstanding,
        "top_agent_collections": top_agent_collections,
    }

    return render(request, "agents/agents_analytics.html", context)



@admin_required
def agents_monthly_range_analysis(request):
    today = timezone.localdate()

    start_date = parse_date(request.GET.get("start_date") or "")
    end_date = parse_date(request.GET.get("end_date") or "")
    q = (request.GET.get("q") or "").strip()
    location = (request.GET.get("location") or "").strip()
    group_name = (request.GET.get("group_name") or "").strip()
    risk = (request.GET.get("risk") or "").strip()

    if not start_date:
        start_date = today.replace(day=1)

    if not end_date:
        end_date = today

    agents = Agent.objects.all().prefetch_related(
        Prefetch(
            "loans",
            queryset=Loan.objects.select_related("borrower", "agent_name").prefetch_related("payments")
        )
    ).order_by("name")

    if q:
        agents = agents.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q) |
            Q(email__icontains=q) |
            Q(agent_id__icontains=q) |
            Q(ghana_card_number__icontains=q)
        )

    if location:
        agents = agents.filter(location__icontains=location)

    if group_name:
        agents = agents.filter(group_name__icontains=group_name)

    agent_rows = []

    total_agents = agents.count()
    total_loans = 0
    total_active_loans = 0
    total_closed_loans = 0
    total_default_loans = 0
    total_borrowers = 0

    portfolio_disbursed = Decimal("0.00")
    portfolio_roic = Decimal("0.00")
    portfolio_expected = Decimal("0.00")
    portfolio_collected = Decimal("0.00")
    portfolio_principal_collected = Decimal("0.00")
    portfolio_roic_collected = Decimal("0.00")
    portfolio_principal_outstanding = Decimal("0.00")
    portfolio_roic_outstanding = Decimal("0.00")
    portfolio_total_outstanding = Decimal("0.00")

    location_map = defaultdict(lambda: Decimal("0.00"))
    group_map = defaultdict(lambda: Decimal("0.00"))
    risk_map = {"Low": 0, "Medium": 0, "High": 0}

    for agent in agents:
        range_loans = [
            loan for loan in agent.loans.all()
            if start_date <= loan.created_at.date() <= end_date
        ]

        total_loans_a = len(range_loans)
        active_loans = sum(1 for l in range_loans if l.status == "ACTIVE")
        closed_loans = sum(1 for l in range_loans if l.status == "CLOSED")
        default_loans = sum(1 for l in range_loans if l.status == "DEFAULT")
        distinct_borrowers = len({l.borrower_id for l in range_loans})

        total_disbursed = sum((Decimal(l.amount) for l in range_loans), Decimal("0.00"))
        total_roic = sum((l.roic_amount for l in range_loans), Decimal("0.00"))
        total_expected = sum((l.total_expected_amount for l in range_loans), Decimal("0.00"))

        range_payments = []
        for loan in range_loans:
            for p in loan.payments.filter(is_void=False):
                if start_date <= p.payment_date <= end_date:
                    range_payments.append(p)

        total_collected = sum((Decimal(p.amount) for p in range_payments), Decimal("0.00"))
        total_principal_collected = sum((Decimal(p.principal_paid) for p in range_payments), Decimal("0.00"))
        total_roic_collected = sum((Decimal(p.roic_paid) for p in range_payments), Decimal("0.00"))

        principal_outstanding = (total_disbursed - total_principal_collected).quantize(Decimal("0.01"))
        if principal_outstanding < 0:
            principal_outstanding = Decimal("0.00")

        roic_outstanding = (total_roic - total_roic_collected).quantize(Decimal("0.01"))
        if roic_outstanding < 0:
            roic_outstanding = Decimal("0.00")

        total_outstanding = (total_expected - total_collected).quantize(Decimal("0.01"))
        if total_outstanding < 0:
            total_outstanding = Decimal("0.00")

        collection_rate = (
            (total_collected / total_expected) * Decimal("100")
        ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")

        avg_loan_size = (
            total_disbursed / Decimal(total_loans_a)
        ).quantize(Decimal("0.01")) if total_loans_a > 0 else Decimal("0.00")

        risk_label = "Low"
        if default_loans > 0 or total_outstanding >= Decimal("20000.00"):
            risk_label = "High"
        elif active_loans > 0 and total_outstanding > Decimal("0.00"):
            risk_label = "Medium"

        row = {
            "agent": agent,
            "distinct_borrowers": distinct_borrowers,
            "total_loans": total_loans_a,
            "active_loans": active_loans,
            "closed_loans": closed_loans,
            "default_loans": default_loans,
            "total_disbursed": total_disbursed.quantize(Decimal("0.01")),
            "total_roic": total_roic.quantize(Decimal("0.01")),
            "total_expected": total_expected.quantize(Decimal("0.01")),
            "total_collected": total_collected.quantize(Decimal("0.01")),
            "total_principal_collected": total_principal_collected.quantize(Decimal("0.01")),
            "total_roic_collected": total_roic_collected.quantize(Decimal("0.01")),
            "principal_outstanding": principal_outstanding,
            "roic_outstanding": roic_outstanding,
            "total_outstanding": total_outstanding,
            "collection_rate": collection_rate,
            "avg_loan_size": avg_loan_size,
            "risk_label": risk_label,
        }
        agent_rows.append(row)

        total_loans += total_loans_a
        total_active_loans += active_loans
        total_closed_loans += closed_loans
        total_default_loans += default_loans
        total_borrowers += distinct_borrowers

        portfolio_disbursed += total_disbursed
        portfolio_roic += total_roic
        portfolio_expected += total_expected
        portfolio_collected += total_collected
        portfolio_principal_collected += total_principal_collected
        portfolio_roic_collected += total_roic_collected
        portfolio_principal_outstanding += principal_outstanding
        portfolio_roic_outstanding += roic_outstanding
        portfolio_total_outstanding += total_outstanding

        location_map[agent.location or "Unknown"] += total_outstanding
        group_map[agent.group_name or "Unknown"] += total_outstanding
        risk_map[risk_label] += 1

    if risk:
        agent_rows = [r for r in agent_rows if r["risk_label"] == risk]

    agent_rows.sort(key=lambda x: (-x["total_outstanding"], -x["total_loans"], x["agent"].name.lower()))

    avg_collection_rate = (
        (portfolio_collected / portfolio_expected) * Decimal("100")
    ).quantize(Decimal("0.01")) if portfolio_expected > 0 else Decimal("0.00")

    avg_loan_size_portfolio = (
        portfolio_disbursed / Decimal(total_loans)
    ).quantize(Decimal("0.01")) if total_loans > 0 else Decimal("0.00")

    top_agents = agent_rows[:10]

    chart_agent_labels = [r["agent"].name for r in top_agents]
    chart_agent_outstanding = [float(r["total_outstanding"]) for r in top_agents]
    chart_agent_collected = [float(r["total_collected"]) for r in top_agents]
    chart_agent_disbursed = [float(r["total_disbursed"]) for r in top_agents]

    chart_location_labels = list(location_map.keys())
    chart_location_values = [float(v) for v in location_map.values()]

    chart_group_labels = list(group_map.keys())
    chart_group_values = [float(v) for v in group_map.values()]

    chart_risk_labels = list(risk_map.keys())
    chart_risk_values = list(risk_map.values())

    pagination = paginate_items(request, agent_rows, per_page=20)

    context = {
        "title": "Agents Monthly Range Analysis",
        "start_date": start_date,
        "end_date": end_date,
        "q": q,
        "location": location,
        "group_name": group_name,
        "risk": risk,
        "risk_choices": [("Low", "Low"), ("Medium", "Medium"), ("High", "High")],

        "agents": pagination["page_obj"],
        "page_obj": pagination["page_obj"],
        "page_numbers": pagination["page_numbers"],
        "pagination_query": pagination["pagination_query"],

        "total_agents": total_agents,
        "total_borrowers": total_borrowers,
        "total_loans": total_loans,
        "total_active_loans": total_active_loans,
        "total_closed_loans": total_closed_loans,
        "total_default_loans": total_default_loans,

        "portfolio_disbursed": portfolio_disbursed.quantize(Decimal("0.01")),
        "portfolio_roic": portfolio_roic.quantize(Decimal("0.01")),
        "portfolio_expected": portfolio_expected.quantize(Decimal("0.01")),
        "portfolio_collected": portfolio_collected.quantize(Decimal("0.01")),
        "portfolio_principal_collected": portfolio_principal_collected.quantize(Decimal("0.01")),
        "portfolio_roic_collected": portfolio_roic_collected.quantize(Decimal("0.01")),
        "portfolio_principal_outstanding": portfolio_principal_outstanding.quantize(Decimal("0.01")),
        "portfolio_roic_outstanding": portfolio_roic_outstanding.quantize(Decimal("0.01")),
        "portfolio_total_outstanding": portfolio_total_outstanding.quantize(Decimal("0.01")),
        "avg_collection_rate": avg_collection_rate,
        "avg_loan_size_portfolio": avg_loan_size_portfolio,

        "chart_agent_labels": chart_agent_labels,
        "chart_agent_outstanding": chart_agent_outstanding,
        "chart_agent_collected": chart_agent_collected,
        "chart_agent_disbursed": chart_agent_disbursed,
        "chart_location_labels": chart_location_labels,
        "chart_location_values": chart_location_values,
        "chart_group_labels": chart_group_labels,
        "chart_group_values": chart_group_values,
        "chart_risk_labels": chart_risk_labels,
        "chart_risk_values": chart_risk_values,
    }

    return render(request, "agents/agents_monthly_range_analysis.html", context)


@agent_or_admin_required
def agent_detail(request, pk):
    # Agents can only see their own detail page
    if get_user_role(request.user) == "agent":
        own_agent = get_agent_for_user(request.user)
        if own_agent is None or own_agent.pk != pk:
            from django.contrib import messages as _msg
            _msg.error(request, "You can only view your own agent page.")
            return redirect("agent_detail", pk=own_agent.pk if own_agent else pk)
    agent = get_object_or_404(Agent, pk=pk)
    today = timezone.localdate()

    month_start = today.replace(day=1)
    next_month = (month_start.replace(day=28) + timezone.timedelta(days=4)).replace(day=1)

    loans_qs = (
        Loan.objects
        .filter(agent_name=agent)
        .select_related("borrower", "agent_name")
        .prefetch_related("payments")
        .order_by("-created_at")
    )

    total_loans = loans_qs.count()
    new_loans_this_month = loans_qs.filter(created_at__date__gte=month_start, created_at__date__lt=next_month).count()

    total_borrowers = loans_qs.values("borrower_id").distinct().count()

    total_disbursed = loans_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    total_disbursed = Decimal(total_disbursed).quantize(Decimal("0.01"))

    total_roic = sum((loan.roic_amount for loan in loans_qs), Decimal("0.00")).quantize(Decimal("0.01"))
    total_expected = sum((loan.total_expected_amount for loan in loans_qs), Decimal("0.00")).quantize(Decimal("0.01"))

    payments_qs = (
        Payment.objects
        .filter(is_void=False, loan__in=loans_qs)
        .select_related("loan", "loan__borrower", "loan__agent_name")
    )

    total_payments_count = payments_qs.count()
    total_collected = payments_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    total_principal_collected = payments_qs.aggregate(s=Sum("principal_paid"))["s"] or Decimal("0.00")
    total_roic_collected = payments_qs.aggregate(s=Sum("roic_paid"))["s"] or Decimal("0.00")

    total_collected = Decimal(total_collected).quantize(Decimal("0.01"))
    total_principal_collected = Decimal(total_principal_collected).quantize(Decimal("0.01"))
    total_roic_collected = Decimal(total_roic_collected).quantize(Decimal("0.01"))

    principal_outstanding = (total_disbursed - total_principal_collected).quantize(Decimal("0.01"))
    if principal_outstanding < 0:
        principal_outstanding = Decimal("0.00")

    roic_outstanding = (total_roic - total_roic_collected).quantize(Decimal("0.01"))
    if roic_outstanding < 0:
        roic_outstanding = Decimal("0.00")

    total_outstanding = (total_expected - total_collected).quantize(Decimal("0.01"))
    if total_outstanding < 0:
        total_outstanding = Decimal("0.00")

    if total_expected > 0:
        collections_rate = (total_collected / total_expected * Decimal("100")).quantize(Decimal("0.01"))
    else:
        collections_rate = Decimal("0.00")

    active_loans = loans_qs.filter(status="ACTIVE").count()
    closed_loans = loans_qs.filter(status="CLOSED").count()
    default_loans = loans_qs.filter(status="DEFAULT").count()

    seasoned_cutoff = today - timezone.timedelta(weeks=4)
    par_amount = Decimal("0.00")
    top_outstanding_rows = []

    for ln in loans_qs:
        bal_amt = ln.balance_amount
        if bal_amt > 0 and ln.start_date and ln.start_date <= seasoned_cutoff:
            par_amount += bal_amt

        top_outstanding_rows.append({
            "loan": ln,
            "expected": ln.total_expected_amount,
            "collected": ln.total_paid_amount,
            "balance": bal_amt,
        })

    top_outstanding_rows.sort(key=lambda r: r["balance"], reverse=True)
    top_outstanding = top_outstanding_rows[:8]

    if total_expected > 0:
        par_rate = (par_amount / total_expected * Decimal("100")).quantize(Decimal("0.01"))
    else:
        par_rate = Decimal("0.00")
    par_amount = par_amount.quantize(Decimal("0.01"))

    if total_loans > 0:
        avg_loan_size = (total_disbursed / Decimal(total_loans)).quantize(Decimal("0.01"))
    else:
        avg_loan_size = Decimal("0.00")

    # This month collections and disbursement
    month_disbursed = loans_qs.filter(created_at__date__gte=month_start, created_at__date__lt=next_month).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    month_collected = payments_qs.filter(payment_date__gte=month_start, payment_date__lt=next_month).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    month_principal_collected = payments_qs.filter(payment_date__gte=month_start, payment_date__lt=next_month).aggregate(s=Sum("principal_paid"))["s"] or Decimal("0.00")
    month_roic_collected = payments_qs.filter(payment_date__gte=month_start, payment_date__lt=next_month).aggregate(s=Sum("roic_paid"))["s"] or Decimal("0.00")

    month_disbursed = Decimal(month_disbursed).quantize(Decimal("0.01"))
    month_collected = Decimal(month_collected).quantize(Decimal("0.01"))
    month_principal_collected = Decimal(month_principal_collected).quantize(Decimal("0.01"))
    month_roic_collected = Decimal(month_roic_collected).quantize(Decimal("0.01"))

    # Top borrowers under this agent
    borrower_map = defaultdict(lambda: {
        "borrower": None,
        "loans_count": 0,
        "total_disbursed": Decimal("0.00"),
        "total_expected": Decimal("0.00"),
        "total_collected": Decimal("0.00"),
        "principal_outstanding": Decimal("0.00"),
        "roic_outstanding": Decimal("0.00"),
        "total_outstanding": Decimal("0.00"),
    })

    for ln in loans_qs:
        item = borrower_map[ln.borrower_id]
        item["borrower"] = ln.borrower
        item["loans_count"] += 1
        item["total_disbursed"] += ln.amount
        item["total_expected"] += ln.total_expected_amount
        item["total_collected"] += ln.total_paid_amount
        item["principal_outstanding"] += ln.principal_outstanding
        item["roic_outstanding"] += ln.roic_outstanding
        item["total_outstanding"] += ln.balance_amount

    top_borrowers = list(borrower_map.values())
    top_borrowers.sort(key=lambda x: x["total_outstanding"], reverse=True)
    top_borrowers = top_borrowers[:10]

    recent_loans = loans_qs[:10]
    recent_payments = payments_qs.order_by("-created_at")[:10]
    payroll_snapshot = _calculate_payroll_snapshot(agent, month_start, today)
    recent_payroll_lines = agent.payroll_lines.select_related("run").order_by("-run__period_end", "-created_at")[:6]
    recent_adjustments = agent.payroll_adjustments.order_by("-effective_from", "-created_at")[:6]
    direct_reports_count = agent.team_members.count()
    title_prefix = "Employee" if not agent.is_field_agent else "Agent"

    context = {
        "agent": agent,

        "total_borrowers": total_borrowers,
        "total_loans": total_loans,
        "new_loans_this_month": new_loans_this_month,
        "active_loans": active_loans,
        "closed_loans": closed_loans,
        "default_loans": default_loans,
        "total_payments_count": total_payments_count,

        "total_disbursed": total_disbursed,
        "total_roic": total_roic,
        "total_expected": total_expected,
        "total_collected": total_collected,
        "total_principal_collected": total_principal_collected,
        "total_roic_collected": total_roic_collected,
        "principal_outstanding": principal_outstanding,
        "roic_outstanding": roic_outstanding,
        "total_outstanding": total_outstanding,
        "avg_loan_size": avg_loan_size,

        "month_disbursed": month_disbursed,
        "month_collected": month_collected,
        "month_principal_collected": month_principal_collected,
        "month_roic_collected": month_roic_collected,

        "collections_rate": collections_rate,
        "par_amount": par_amount,
        "par_rate": par_rate,

        "top_outstanding": top_outstanding,
        "top_borrowers": top_borrowers,
        "recent_loans": recent_loans,
        "recent_payments": recent_payments,
        "payroll_snapshot": payroll_snapshot,
        "recent_payroll_lines": recent_payroll_lines,
        "recent_adjustments": recent_adjustments,
        "direct_reports_count": direct_reports_count,

        "title": f"{title_prefix}: {agent.name}",
    }
    return render(request, "agents/agent_detail.html", context)

@admin_required
def agent_create(request):
    agent_limit = can_create_agent(schema_name=current_schema_name(request))
    if not agent_limit.allowed:
        messages.error(request, agent_limit.reason)
        return redirect("agent_list")

    form = AgentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        agent = form.save()
        return redirect("agent_detail", pk=agent.pk)
    return render(request, "agents/agent_form.html", {"form": form, "title": "Add Workforce Member"})


@admin_required
def agent_bulk_import(request):
    form = AgentBulkImportForm(request.POST or None, request.FILES or None)
    import_result = None

    if request.method == "POST" and form.is_valid():
        uploaded_file = form.cleaned_data["data_file"]
        selected_type = form.cleaned_data["file_type"]
        import_mode = form.cleaned_data["import_mode"]

        file_type = selected_type
        if selected_type == "auto":
            file_type = infer_agent_import_format(uploaded_file.name)
            if not file_type:
                form.add_error(
                    "data_file",
                    "Could not infer the file type. Choose CSV, Excel, JSON, or XML explicitly.",
                )

        if file_type and not form.errors:
            try:
                rows = parse_agent_import(uploaded_file, file_type)
                import_result = import_agent_rows(rows, import_mode=import_mode)
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
        "agents/agent_bulk_import.html",
        {
            "title": "Bulk Import Workforce",
            "form": form,
            "format_options": get_agent_import_formats(),
            "column_help": get_agent_import_column_help(),
            "import_result": import_result,
        },
    )


@admin_required
def agent_bulk_import_sample(request, file_type):
    supported = {item["slug"] for item in get_agent_import_formats()}
    if file_type not in supported:
        raise Http404("Unsupported sample file type.")

    filename, content_type, payload = build_agent_import_sample(file_type)
    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response



@agent_or_admin_required
def agent_comprehensive_analysis(request, pk):
    if get_user_role(request.user) == "agent":
        own_agent = get_agent_for_user(request.user)
        if own_agent is None or own_agent.pk != pk:
            return redirect("agent_comprehensive_analysis", pk=own_agent.pk if own_agent else pk)
    agent = get_object_or_404(Agent, pk=pk)
    today = timezone.localdate()

    loans_qs = (
        Loan.objects
        .filter(agent_name=agent)
        .select_related("borrower", "agent_name")
        .prefetch_related("payments")
        .order_by("-created_at")
    )

    payments_qs = (
        Payment.objects
        .filter(is_void=False, loan__agent_name=agent)
        .select_related("loan", "loan__borrower")
        .order_by("-created_at")
    )

    total_loans = loans_qs.count()
    total_borrowers = loans_qs.values("borrower_id").distinct().count()

    total_disbursed = loans_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    total_disbursed = Decimal(total_disbursed).quantize(Decimal("0.01"))

    total_roic = sum((loan.roic_amount for loan in loans_qs), Decimal("0.00")).quantize(Decimal("0.01"))
    total_expected = sum((loan.total_expected_amount for loan in loans_qs), Decimal("0.00")).quantize(Decimal("0.01"))

    total_collected = payments_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    total_principal_collected = payments_qs.aggregate(s=Sum("principal_paid"))["s"] or Decimal("0.00")
    total_roic_collected = payments_qs.aggregate(s=Sum("roic_paid"))["s"] or Decimal("0.00")

    total_collected = Decimal(total_collected).quantize(Decimal("0.01"))
    total_principal_collected = Decimal(total_principal_collected).quantize(Decimal("0.01"))
    total_roic_collected = Decimal(total_roic_collected).quantize(Decimal("0.01"))

    principal_outstanding = (total_disbursed - total_principal_collected).quantize(Decimal("0.01"))
    if principal_outstanding < 0:
        principal_outstanding = Decimal("0.00")

    roic_outstanding = (total_roic - total_roic_collected).quantize(Decimal("0.01"))
    if roic_outstanding < 0:
        roic_outstanding = Decimal("0.00")

    total_outstanding = (total_expected - total_collected).quantize(Decimal("0.01"))
    if total_outstanding < 0:
        total_outstanding = Decimal("0.00")

    active_loans = loans_qs.filter(status="ACTIVE").count()
    closed_loans = loans_qs.filter(status="CLOSED").count()
    default_loans = loans_qs.filter(status="DEFAULT").count()

    collections_rate = (
        (total_collected / total_expected) * Decimal("100")
    ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")

    avg_loan_size = (
        total_disbursed / Decimal(total_loans)
    ).quantize(Decimal("0.01")) if total_loans > 0 else Decimal("0.00")

    # 6-month trend
    monthly_map = defaultdict(lambda: {
        "loan_count": 0,
        "disbursed": Decimal("0.00"),
        "collected": Decimal("0.00"),
        "principal_collected": Decimal("0.00"),
        "roic_collected": Decimal("0.00"),
    })

    for i in range(5, -1, -1):
        d = today.replace(day=1)
        for _ in range(i):
            d = (d - timezone.timedelta(days=1)).replace(day=1)
        monthly_map[d.strftime("%Y-%m")]

    for ln in loans_qs:
        key = ln.created_at.strftime("%Y-%m")
        monthly_map[key]["loan_count"] += 1
        monthly_map[key]["disbursed"] += Decimal(ln.amount)

    for p in payments_qs:
        key = p.payment_date.strftime("%Y-%m")
        monthly_map[key]["collected"] += Decimal(p.amount)
        monthly_map[key]["principal_collected"] += Decimal(p.principal_paid)
        monthly_map[key]["roic_collected"] += Decimal(p.roic_paid)

    trend_labels = sorted(monthly_map.keys())
    trend_loan_counts = [monthly_map[k]["loan_count"] for k in trend_labels]
    trend_disbursed = [float(monthly_map[k]["disbursed"]) for k in trend_labels]
    trend_collected = [float(monthly_map[k]["collected"]) for k in trend_labels]
    trend_principal_collected = [float(monthly_map[k]["principal_collected"]) for k in trend_labels]
    trend_roic_collected = [float(monthly_map[k]["roic_collected"]) for k in trend_labels]

    # Borrower exposure ranking
    borrower_rows = []
    grouped = defaultdict(list)
    for ln in loans_qs:
        grouped[ln.borrower].append(ln)

    for borrower, items in grouped.items():
        borrower_rows.append({
            "borrower": borrower,
            "total_loans": len(items),
            "disbursed": sum((x.amount for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "expected": sum((x.total_expected_amount for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "collected": sum((x.total_paid_amount for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "principal_outstanding": sum((x.principal_outstanding for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "roic_outstanding": sum((x.roic_outstanding for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "total_outstanding": sum((x.balance_amount for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
        })

    borrower_rows.sort(key=lambda x: x["total_outstanding"], reverse=True)
    top_borrowers = borrower_rows[:15]

    context = {
        "title": f"Comprehensive Analysis - {agent.name}",
        "agent": agent,

        "total_borrowers": total_borrowers,
        "total_loans": total_loans,
        "active_loans": active_loans,
        "closed_loans": closed_loans,
        "default_loans": default_loans,

        "total_disbursed": total_disbursed,
        "total_roic": total_roic,
        "total_expected": total_expected,
        "total_collected": total_collected,
        "total_principal_collected": total_principal_collected,
        "total_roic_collected": total_roic_collected,
        "principal_outstanding": principal_outstanding,
        "roic_outstanding": roic_outstanding,
        "total_outstanding": total_outstanding,
        "collections_rate": collections_rate,
        "avg_loan_size": avg_loan_size,

        "trend_labels": trend_labels,
        "trend_loan_counts": trend_loan_counts,
        "trend_disbursed": trend_disbursed,
        "trend_collected": trend_collected,
        "trend_principal_collected": trend_principal_collected,
        "trend_roic_collected": trend_roic_collected,

        "top_borrowers": top_borrowers,
        "recent_loans": loans_qs[:12],
        "recent_payments": payments_qs[:12],
    }
    return render(request, "agents/agent_comprehensive_analysis.html", context)


@agent_or_admin_required
def agent_monthly_range_analysis(request, pk):
    if get_user_role(request.user) == "agent":
        own_agent = get_agent_for_user(request.user)
        if own_agent is None or own_agent.pk != pk:
            return redirect("agent_monthly_range_analysis", pk=own_agent.pk if own_agent else pk)
    agent = get_object_or_404(Agent, pk=pk)
    today = timezone.localdate()

    start_date = parse_date(request.GET.get("start_date") or "")
    end_date = parse_date(request.GET.get("end_date") or "")

    if not start_date:
        start_date = today.replace(day=1)

    if not end_date:
        end_date = today

    loans_qs = (
        Loan.objects
        .filter(agent_name=agent, created_at__date__gte=start_date, created_at__date__lte=end_date)
        .select_related("borrower", "agent_name")
        .prefetch_related("payments")
        .order_by("-created_at")
    )

    payments_qs = (
        Payment.objects
        .filter(
            is_void=False,
            loan__agent_name=agent,
            payment_date__gte=start_date,
            payment_date__lte=end_date,
        )
        .select_related("loan", "loan__borrower")
        .order_by("-created_at")
    )

    total_loans = loans_qs.count()
    total_borrowers = loans_qs.values("borrower_id").distinct().count()

    total_disbursed = loans_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    total_disbursed = Decimal(total_disbursed).quantize(Decimal("0.01"))

    total_roic = sum((loan.roic_amount for loan in loans_qs), Decimal("0.00")).quantize(Decimal("0.01"))
    total_expected = sum((loan.total_expected_amount for loan in loans_qs), Decimal("0.00")).quantize(Decimal("0.01"))

    total_collected = payments_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    total_principal_collected = payments_qs.aggregate(s=Sum("principal_paid"))["s"] or Decimal("0.00")
    total_roic_collected = payments_qs.aggregate(s=Sum("roic_paid"))["s"] or Decimal("0.00")

    total_collected = Decimal(total_collected).quantize(Decimal("0.01"))
    total_principal_collected = Decimal(total_principal_collected).quantize(Decimal("0.01"))
    total_roic_collected = Decimal(total_roic_collected).quantize(Decimal("0.01"))

    principal_outstanding = (total_disbursed - total_principal_collected).quantize(Decimal("0.01"))
    if principal_outstanding < 0:
        principal_outstanding = Decimal("0.00")

    roic_outstanding = (total_roic - total_roic_collected).quantize(Decimal("0.01"))
    if roic_outstanding < 0:
        roic_outstanding = Decimal("0.00")

    total_outstanding = (total_expected - total_collected).quantize(Decimal("0.01"))
    if total_outstanding < 0:
        total_outstanding = Decimal("0.00")

    active_loans = loans_qs.filter(status="ACTIVE").count()
    closed_loans = loans_qs.filter(status="CLOSED").count()
    default_loans = loans_qs.filter(status="DEFAULT").count()

    collections_rate = (
        (total_collected / total_expected) * Decimal("100")
    ).quantize(Decimal("0.01")) if total_expected > 0 else Decimal("0.00")

    borrower_rows = []
    grouped = defaultdict(list)
    for ln in loans_qs:
        grouped[ln.borrower].append(ln)

    for borrower, items in grouped.items():
        borrower_rows.append({
            "borrower": borrower,
            "total_loans": len(items),
            "disbursed": sum((x.amount for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "expected": sum((x.total_expected_amount for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "collected": sum((x.total_paid_amount for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "principal_outstanding": sum((x.principal_outstanding for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "roic_outstanding": sum((x.roic_outstanding for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
            "total_outstanding": sum((x.balance_amount for x in items), Decimal("0.00")).quantize(Decimal("0.01")),
        })

    borrower_rows.sort(key=lambda x: x["total_outstanding"], reverse=True)

    context = {
        "title": f"Monthly Range Analysis - {agent.name}",
        "agent": agent,
        "start_date": start_date,
        "end_date": end_date,

        "total_borrowers": total_borrowers,
        "total_loans": total_loans,
        "active_loans": active_loans,
        "closed_loans": closed_loans,
        "default_loans": default_loans,

        "total_disbursed": total_disbursed,
        "total_roic": total_roic,
        "total_expected": total_expected,
        "total_collected": total_collected,
        "total_principal_collected": total_principal_collected,
        "total_roic_collected": total_roic_collected,
        "principal_outstanding": principal_outstanding,
        "roic_outstanding": roic_outstanding,
        "total_outstanding": total_outstanding,
        "collections_rate": collections_rate,

        "borrower_rows": borrower_rows[:20],
        "recent_loans": loans_qs[:15],
        "recent_payments": payments_qs[:15],
    }
    return render(request, "agents/agent_monthly_range_analysis.html", context)


@admin_required
def agent_delete(request, pk):
    agent = get_object_or_404(Agent, pk=pk)
    if request.method == "POST":
        agent.delete()
        return redirect("agent_list")
    return render(request, "agents/agent_confirm_delete.html", {"agent": agent, "title": "Delete Agent"})

# ─── Agent registration (admin only) ─────────────────────────────────────────

@admin_required
def agent_register(request):
    """Admin creates a new agent WITH a login account."""
    agent_limit = can_create_agent(schema_name=current_schema_name(request))
    if not agent_limit.allowed:
        messages.error(request, agent_limit.reason)
        return redirect("agent_list")

    if request.method == "POST":
        form = AgentRegisterForm(request.POST, request.FILES)
        if form.is_valid():
            agent = form.save()
            from django.contrib import messages as _msg
            _msg.success(request, f"Workforce member '{agent.name}' registered with login '{agent.user.username}'.")
            return redirect("agent_detail", pk=agent.pk)
    else:
        form = AgentRegisterForm()
    return render(request, "agents/agent_register.html", {
        "form": form,
        "title": "Register Workforce Login",
    })


@admin_required
def agent_reset_password(request, pk):
    """Admin resets an agent's login password."""
    agent = get_object_or_404(Agent, pk=pk)
    if not agent.user:
        from django.contrib import messages as _msg
        _msg.error(request, "This workforce profile has no login account yet. Use 'Register Workforce Login' to create one.")
        return redirect("agent_detail", pk=pk)

    if request.method == "POST":
        form = AgentResetPasswordForm(request.POST)
        if form.is_valid():
            agent.user.set_password(form.cleaned_data["new_password"])
            agent.user.save()
            from django.contrib import messages as _msg
            _msg.success(request, f"Password reset for {agent.name}.")
            return redirect("agent_detail", pk=pk)
    else:
        form = AgentResetPasswordForm()
    return render(request, "agents/agent_reset_password.html", {
        "form": form,
        "agent": agent,
        "title": f"Reset Password — {agent.name}",
    })


@admin_required
def payroll_hub(request):
    run_form = PayrollRunForm(request.POST or None, prefix="run")
    adjustment_form = PayrollAdjustmentForm(request.POST or None, prefix="adj")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_run" and run_form.is_valid():
            run = run_form.save(commit=False)
            run.created_by = request.user
            run.save()
            created_lines = _create_payroll_run_lines(run)
            log_activity(
                category="PAYROLL",
                action="run_created",
                actor=request.user,
                object_type="PayrollRun",
                object_id=run.pk,
                object_label=run.title,
                message=f"Payroll run '{run.title}' created with {created_lines} line items.",
                metadata={"run_id": run.pk, "line_count": created_lines},
                request=request,
            )
            messages.success(request, f"Payroll run '{run.title}' created with {created_lines} employee line items.")
            return redirect("payroll_run_detail", pk=run.pk)
        if action == "create_adjustment" and adjustment_form.is_valid():
            adjustment = adjustment_form.save()
            log_activity(
                category="PAYROLL",
                action="adjustment_created",
                actor=request.user,
                object_type="PayrollAdjustment",
                object_id=adjustment.pk,
                object_label=adjustment.label,
                message=f"Payroll adjustment '{adjustment.label}' created for {adjustment.employee.name}.",
                metadata={"employee_id": adjustment.employee_id},
                request=request,
            )
            messages.success(request, "Payroll adjustment saved successfully.")
            return redirect("payroll_hub")

    workforce = Agent.objects.select_related("supervisor").order_by("name")
    payroll_ready = workforce.filter(payroll_active=True, employment_status="ACTIVE")
    runs = PayrollRun.objects.all()[:10]
    adjustments = PayrollAdjustment.objects.select_related("employee").order_by("-effective_from", "-created_at")[:12]
    latest_run = PayrollRun.objects.first()
    latest_lines = latest_run.lines.select_related("employee")[:12] if latest_run else []

    role_breakdown = []
    for code, label in ROLE_KPIS:
        employees = workforce.filter(workforce_role=code)
        role_breakdown.append(
            {
                "code": code,
                "label": label,
                "count": employees.count(),
                "monthly_payroll": _money(sum((employee.gross_regular_pay for employee in employees), Decimal("0.00"))),
            }
        )

    payroll_preview = []
    today = timezone.localdate()
    period_start = today.replace(day=1)
    company_profile = CompanyProfile.get_solo()
    for employee in payroll_ready[:10]:
        payroll_preview.append(
            _calculate_payroll_snapshot(employee, period_start, today, company_profile=company_profile)
        )

    context = {
        "title": "Payroll Center",
        "company_profile": company_profile,
        "run_form": run_form,
        "adjustment_form": adjustment_form,
        "runs": runs,
        "adjustments": adjustments,
        "latest_run": latest_run,
        "latest_lines": latest_lines,
        "role_breakdown": role_breakdown,
        "total_workforce": workforce.count(),
        "payroll_ready_count": payroll_ready.count(),
        "admin_access_count": workforce.filter(has_admin_access=True).count(),
        "monthly_regular_payroll": _money(sum((employee.gross_regular_pay for employee in payroll_ready), Decimal("0.00"))),
        "monthly_base_salary": _money(sum((employee.base_salary for employee in payroll_ready), Decimal("0.00"))),
        "active_adjustments_count": PayrollAdjustment.objects.filter(is_active=True).count(),
        "draft_runs_count": PayrollRun.objects.filter(status="DRAFT").count(),
        "approved_runs_count": PayrollRun.objects.filter(status="APPROVED").count(),
        "paid_runs_count": PayrollRun.objects.filter(status="PAID").count(),
        "payroll_preview": payroll_preview,
    }
    return render(request, "agents/payroll_hub.html", context)


@admin_required
def payroll_run_detail(request, pk):
    run = get_object_or_404(PayrollRun.objects.prefetch_related("lines__employee"), pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "recalculate" and run.status == "DRAFT":
            created_lines = _create_payroll_run_lines(run)
            log_activity(
                category="PAYROLL",
                action="run_recalculated",
                actor=request.user,
                object_type="PayrollRun",
                object_id=run.pk,
                object_label=run.title,
                message=f"Payroll run '{run.title}' recalculated for {created_lines} employees.",
                metadata={"run_id": run.pk, "line_count": created_lines},
                request=request,
            )
            messages.success(request, f"Payroll run recalculated for {created_lines} employees.")
            return redirect("payroll_run_detail", pk=pk)
        if action == "approve" and run.status == "DRAFT":
            approval = create_approval_request(
                workflow_type="PAYROLL_RUN_APPROVAL",
                title=f"Approve payroll run {run.title}",
                description=f"Approval required before payroll run '{run.title}' can move from draft to approved.",
                submitted_by=request.user,
                payload={"run_id": run.pk},
                metadata={"run_id": run.pk, "status": run.status, "pay_date": run.pay_date.isoformat()},
                source_path=request.path,
                target_reference=run.title,
                request=request,
            )
            log_activity(
                category="PAYROLL",
                action="approval_requested",
                actor=request.user,
                object_type="ApprovalRequest",
                object_id=approval.pk,
                object_label=approval.title,
                message=f"Approval requested for payroll run '{run.title}'.",
                metadata={"run_id": run.pk, "approval_id": approval.pk},
                request=request,
            )
            messages.success(request, "Payroll approval request submitted. A different admin must approve it from Approval Controls.")
            return redirect("payroll_run_detail", pk=pk)
        if action == "mark_paid" and run.status == "APPROVED":
            run.status = "PAID"
            run.paid_at = timezone.now()
            run.save(update_fields=["status", "paid_at", "updated_at"])
            log_activity(
                category="PAYROLL",
                action="marked_paid",
                actor=request.user,
                object_type="PayrollRun",
                object_id=run.pk,
                object_label=run.title,
                message=f"Payroll run '{run.title}' marked as paid.",
                metadata={"run_id": run.pk},
                request=request,
            )
            messages.success(request, "Payroll run marked as paid.")
            return redirect("payroll_run_detail", pk=pk)
        if action == "cancel":
            run.status = "CANCELLED"
            run.save(update_fields=["status", "updated_at"])
            log_activity(
                category="PAYROLL",
                action="cancelled",
                actor=request.user,
                object_type="PayrollRun",
                object_id=run.pk,
                object_label=run.title,
                message=f"Payroll run '{run.title}' cancelled.",
                metadata={"run_id": run.pk},
                request=request,
            )
            messages.success(request, "Payroll run cancelled.")
            return redirect("payroll_run_detail", pk=pk)
        if action == "export_csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{slugify(run.title) or "payroll-run"}-export.csv"'
            writer = csv.writer(response)
            writer.writerow([
                "Employee Code", "Name", "Role", "Department", "Payment Method",
                "Base Salary", "Fixed Allowances", "Bonus", "Commission", "Overtime",
                "Other Earnings", "Gross Pay", "Tax Deduction", "Employee Pension",
                "Welfare Deduction", "Manual Statutory", "Employer Statutory",
                "Statutory Deductions", "Loan Recovery",
                "Other Deductions", "Total Deductions", "Net Pay",
            ])
            for line in run.lines.select_related("employee"):
                employee = line.employee
                writer.writerow([
                    employee.agent_id,
                    employee.name,
                    employee.get_workforce_role_display(),
                    employee.department,
                    line.get_payment_method_display(),
                    line.base_salary,
                    line.fixed_allowances,
                    line.bonus_total,
                    line.commission_total,
                    line.overtime_total,
                    line.other_earnings,
                    line.gross_pay,
                    line.tax_deduction,
                    line.employee_pension_deduction,
                    line.welfare_deduction,
                    line.manual_statutory_deductions,
                    line.employer_statutory_contributions,
                    line.statutory_deductions,
                    line.loan_recovery_deductions,
                    line.other_deductions,
                    line.total_deductions,
                    line.net_pay,
                ])
            return response
        if action == "export_excel":
            return _payroll_run_excel_response(run)

    lines = list(run.lines.select_related("employee"))
    highest_paid = sorted(lines, key=lambda item: item.net_pay, reverse=True)[:8]
    total_employer_statutory = _money(sum((line.employer_statutory_contributions for line in lines), Decimal("0.00")))
    total_tax_deduction = _money(sum((line.tax_deduction for line in lines), Decimal("0.00")))
    total_employee_pension = _money(sum((line.employee_pension_deduction for line in lines), Decimal("0.00")))
    total_welfare_deduction = _money(sum((line.welfare_deduction for line in lines), Decimal("0.00")))
    total_manual_statutory = _money(sum((line.manual_statutory_deductions for line in lines), Decimal("0.00")))
    context = {
        "title": f"Payroll Run — {run.title}",
        "run": run,
        "lines": lines,
        "highest_paid": highest_paid,
        "total_employees": len(lines),
        "total_gross": run.total_gross,
        "total_net": run.total_net,
        "total_deductions": run.total_deductions,
        "total_employer_statutory": total_employer_statutory,
        "total_tax_deduction": total_tax_deduction,
        "total_employee_pension": total_employee_pension,
        "total_welfare_deduction": total_welfare_deduction,
        "total_manual_statutory": total_manual_statutory,
        "company_profile": CompanyProfile.get_solo(),
    }
    return render(request, "agents/payroll_run_detail.html", context)


# ─── Borrower login management (admin only) ──────────────────────────────────

@admin_required
def borrower_create_login(request, pk):
    """Admin creates a login account for an existing borrower."""
    from apps.loans.models import Borrower
    from apps.accounts.forms import BorrowerCreateLoginForm
    borrower = get_object_or_404(Borrower, pk=pk)
    schema_name = current_schema_name(request)

    if borrower.user:
        from django.contrib import messages as _msg
        _msg.warning(
            request,
            f"{borrower.full_name} already has a login account ({visible_portal_username(borrower.user.username, schema_name=schema_name)})."
        )
        return redirect("loans:borrower_detail", pk=pk)

    if request.method == "POST":
        form = BorrowerCreateLoginForm(request.POST)
        if form.is_valid():
            from django.contrib.auth.models import User
            alias_username = form.cleaned_data["username"]
            user = User.objects.create_user(
                username=build_tenant_scoped_username(alias_username, schema_name=schema_name),
                email=(borrower.email or "").strip().lower(),
                password=form.cleaned_data["password"],
            )
            borrower.user = user
            borrower.save(update_fields=["user"])
            from django.contrib import messages as _msg
            _msg.success(request, f"Login created for {borrower.full_name} (username: {alias_username}).")
            return redirect("loans:borrower_detail", pk=pk)
    else:
        form = BorrowerCreateLoginForm()

    return render(request, "agents/borrower_create_login.html", {
        "form": form,
        "borrower": borrower,
        "borrower_login_username": visible_portal_username(
            getattr(getattr(borrower, "user", None), "username", ""),
            schema_name=schema_name,
        ),
        "title": f"Create Login — {borrower.full_name}",
    })


@admin_required
def borrower_reset_login(request, pk):
    """Admin resets a borrower's login password."""
    from apps.loans.models import Borrower
    from apps.accounts.forms import AgentResetPasswordForm
    borrower = get_object_or_404(Borrower, pk=pk)
    schema_name = current_schema_name(request)

    if not borrower.user:
        from django.contrib import messages as _msg
        _msg.error(request, "This borrower has no login account yet.")
        return redirect("loans:borrower_detail", pk=pk)

    if request.method == "POST":
        form = AgentResetPasswordForm(request.POST)
        if form.is_valid():
            borrower.user.set_password(form.cleaned_data["new_password"])
            borrower.user.save()
            from django.contrib import messages as _msg
            _msg.success(request, f"Password reset for {borrower.full_name}.")
            return redirect("loans:borrower_detail", pk=pk)
    else:
        form = AgentResetPasswordForm()

    return render(request, "agents/borrower_reset_login.html", {
        "form": form,
        "borrower": borrower,
        "borrower_login_username": visible_portal_username(
            getattr(getattr(borrower, "user", None), "username", ""),
            schema_name=schema_name,
        ),
        "title": f"Reset Login — {borrower.full_name}",
    })
