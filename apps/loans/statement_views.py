"""Authenticated print previews and PDFs share the same statement data."""
import base64
import mimetypes
import re
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET
from weasyprint import HTML
from weasyprint.urls import URLFetcher

from apps.accounts.models import Agent
from apps.company.models import CompanyProfile
from apps.core.roles import get_agent_for_user, get_user_role
from apps.core.export_limits import export_limit_response
from .models import Borrower, Loan, Portfolio
from .portfolios import agent_can_access, agent_portfolio_ids
from .statements import account_statement


def _role(request):
    role = get_user_role(request.user)
    if role not in {"admin", "agent", "borrower"}:
        raise PermissionDenied("Your account has no assigned role.")
    return role


def _customer_access(request, record, borrower):
    role = _role(request)
    if role == "admin" or (role == "borrower" and borrower.user_id == request.user.pk):
        return role
    if role == "agent" and agent_can_access(get_agent_for_user(request.user), record):
        return role
    raise Http404


def _document(request, context, *, pdf, pdf_url, back_url, filename):
    company = CompanyProfile.get_solo()
    logo = ""
    if company.logo:
        try:
            with company.logo.open("rb") as stream:
                data = stream.read()
            mime = mimetypes.guess_type(company.logo.name)[0] or "image/png"
            if mime in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                logo = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        except (OSError, ValueError):
            pass
    context.update(company=company, logo=logo, generated_at=timezone.localtime(), pdf=pdf, pdf_url=pdf_url, back_url=back_url,
                   company_initials="".join(word[0] for word in company.company_name.split()[:2]).upper(),
                   document_reference=f"{context['kind'].upper()}-{context['subject_id']}-{timezone.localdate():%Y%m%d}")
    context["statement_primary"] = company.site_primary_color if re.fullmatch(r"#[0-9a-fA-F]{6}", company.site_primary_color or "") else "#173f35"
    context["statement_accent"] = company.site_secondary_color if re.fullmatch(r"#[0-9a-fA-F]{6}", company.site_secondary_color or "") else "#b99545"
    if pdf:
        html = render_to_string("statements/document.html", context, request=request)
        response = HttpResponse(HTML(string=html, url_fetcher=_inline_resource).write_pdf(), content_type="application/pdf")
        disposition = "attachment" if request.GET.get("download") == "1" else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{filename}.pdf"'
    else:
        response = render(request, "statements/document.html", context)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


_inline_resource = URLFetcher(allowed_protocols={"data"}, allow_redirects=False)


def _loan_document(request, loan_id, pdf):
    loan = get_object_or_404(Loan.objects.select_related("borrower", "portfolio"), pk=loan_id)
    role = _customer_access(request, loan, loan.borrower)
    if pdf and (limited := export_limit_response(request)) is not None:
        return limited
    data = account_statement(Loan.objects.filter(pk=loan.pk))
    context = {**data, "kind": "loan", "title": "Loan Repayment Statement", "subject_name": loan.borrower.full_name,
               "subject_id": str(loan.pk), "borrower": loan.borrower, "loan": data["loans"][0]["loan"], "subtitle": f"Loan #{loan.pk} · {loan.borrower.borrower_id}"}
    return _document(request, context, pdf=pdf, pdf_url=reverse("loans:loan_statement_pdf", args=[loan.pk]),
                     back_url=reverse("borrower:loan_detail", args=[loan.pk]) if role=="borrower" else reverse("loans:loan_detail", args=[loan.pk]), filename=f"loan-statement-{loan.pk}")


@login_required
@require_GET
def loan_statement(request, loan_id):
    return _loan_document(request, loan_id, False)


@login_required
@require_GET
def loan_statement_pdf(request, loan_id):
    return _loan_document(request, loan_id, True)


def _borrower_document(request, pk, pdf):
    borrower = get_object_or_404(Borrower.objects.select_related("portfolio"), pk=pk)
    role = _customer_access(request, borrower, borrower)
    if pdf and (limited := export_limit_response(request)) is not None:
        return limited
    loans = Loan.objects.filter(borrower=borrower)
    if role=="agent":
        loans = loans.filter(portfolio_id__in=agent_portfolio_ids(get_agent_for_user(request.user)))
    context = {**account_statement(loans), "kind": "borrower", "title": "Borrower Account Statement", "subject_name": borrower.full_name,
               "subject_id": borrower.borrower_id, "borrower": borrower, "subtitle": f"Customer {borrower.borrower_id} · {borrower.portfolio or 'Awaiting portfolio assignment'}"}
    return _document(request, context, pdf=pdf, pdf_url=reverse("loans:borrower_statement_pdf", args=[pk]),
                     back_url=reverse("borrower:portal") if role=="borrower" else reverse("loans:borrower_detail", args=[pk]), filename=f"borrower-statement-{slugify(borrower.borrower_id)}")


@login_required
@require_GET
def borrower_statement(request, pk):
    return _borrower_document(request, pk, False)


@login_required
@require_GET
def borrower_statement_pdf(request, pk):
    return _borrower_document(request, pk, True)


def _agent_document(request, pk, pdf):
    role = _role(request)
    if role != "admin" and not (role=="agent" and get_agent_for_user(request.user).pk==pk):
        raise Http404
    agent = get_object_or_404(Agent.objects.select_related("supervisor"), pk=pk)
    if pdf and (limited := export_limit_response(request)) is not None:
        return limited
    portfolios = list(Portfolio.objects.filter(pk__in=agent_portfolio_ids(agent)))
    data = account_statement(Loan.objects.filter(portfolio_id__in=[portfolio.pk for portfolio in portfolios]))
    payroll = list(agent.payroll_lines.select_related("run__reversal__approved_by").order_by("run__period_start", "pk"))
    paid = [line for line in payroll if line.run.status=="PAID"]
    earnings = {key: sum((getattr(line, field) for line in paid), Decimal("0.00")) for key, field in (("gross", "gross_pay"), ("deductions", "total_deductions"), ("net", "net_pay"))}
    earnings["awaiting"] = sum((line.net_pay for line in payroll if line.run.status=="APPROVED"), Decimal("0.00"))
    recorded = [row for row in data["receipts"] if row["payment"].collected_by_id==agent.pk]
    context = {**data, "kind": "agent", "title": "Agent Portfolio & Earnings Statement", "subject_name": agent.name, "subject_id": agent.agent_id,
               "subtitle": f"Officer {agent.agent_id} · {agent.role_label}", "agent": agent, "portfolios": portfolios, "payroll": payroll, "earnings": earnings,
               "recorded_cash": sum((row["amount"] for row in recorded), Decimal("0.00")), "recorded_count": len(recorded)}
    return _document(request, context, pdf=pdf, pdf_url=reverse("agent_statement_pdf", args=[pk]), back_url=reverse("agent_detail", args=[pk]), filename=f"agent-statement-{slugify(agent.agent_id)}")


@login_required
@require_GET
def agent_statement(request, pk):
    return _agent_document(request, pk, False)


@login_required
@require_GET
def agent_statement_pdf(request, pk):
    return _agent_document(request, pk, True)
