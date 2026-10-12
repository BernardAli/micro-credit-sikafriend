import csv

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse, HttpResponseBadRequest, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import Agent
from apps.core.roles import admin_required, agent_or_admin_required, get_user_role
from apps.core.pagination import paginate_items
from .models import Borrower, Loan, Portfolio, PortfolioAssignment
from .portfolios import assign_customer, set_portfolio_agents
from .portfolio_analytics import PortfolioPeriodForm, visible_portfolios, portfolio_snapshot
from .portfolio_exports import export_report, make_report, summary_row


def _period_form(request):
    data = request.GET.copy()
    today = timezone.localdate()
    if not data.get("date_from"):
        data["date_from"] = today.replace(day=1).isoformat()
    if not data.get("date_to"):
        data["date_to"] = today.isoformat()
    return PortfolioPeriodForm(data)


class PortfolioForm(forms.ModelForm):
    agents = forms.ModelMultipleChoiceField(
        queryset=Agent.objects.filter(workforce_role="AGENT", employment_status="ACTIVE"),
        required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Selected officers get access immediately. Removed officers lose access immediately.",
    )

    class Meta:
        model = Portfolio
        fields = ["name", "is_active", "agents"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["agents"].initial = [assignment.agent_id for assignment in self.instance.assignments.all() if assignment.ended_at is None]


@agent_or_admin_required
def portfolio_list(request):
    form = _period_form(request)
    if not form.is_valid():
        return render(request, "loans/portfolios/list.html", {"period_form": form, "title": "Loan Portfolios", "invalid_filters": True}, status=400)
    portfolios = visible_portfolios(request.user)
    q = (request.GET.get("q") or "").strip()
    state = request.GET.get("state", "")
    officer = request.GET.get("officer", "")
    if q:
        portfolios = portfolios.filter(Q(number__icontains=q) | Q(name__icontains=q) | Q(assignments__agent__name__icontains=q, assignments__ended_at__isnull=True)).distinct()
    if state in {"active", "inactive"}:
        portfolios = portfolios.filter(is_active=state == "active")
    if officer:
        if not officer.isdigit():
            return HttpResponseBadRequest("Choose a valid officer.")
        portfolios = portfolios.filter(assignments__agent_id=officer, assignments__ended_at__isnull=True).distinct()
    is_admin = get_user_role(request.user) == "admin"
    snapshot = portfolio_snapshot(portfolios, form.cleaned_data["date_from"], form.cleaned_data["date_to"],
                                  include_unassigned=is_admin and not (q or state or officer), include_private_history=is_admin, summary_only=True)
    if request.GET.get("export"):
        return _export(snapshot, request)
    rows = [{**book, "summary": summary_row(book)} for pk, book in snapshot["books"].items() if pk is not None]
    export_params = _export_params(request)
    return render(request, "loans/portfolios/list.html", {
        "rows": rows, "snapshot": snapshot, "totals": snapshot["totals"], "period_form": form,
        "unassigned": snapshot["books"].get(None), "q": q, "state": state, "officer": officer,
        "officers": Agent.objects.filter(portfolio_assignments__portfolio__in=visible_portfolios(request.user), portfolio_assignments__ended_at__isnull=True).distinct(),
        "export_params": export_params, "is_admin": is_admin, "title": "Loan Portfolios",
    })


def _export_params(request):
    params = request.GET.copy()
    for key in ("page", "export", "section"):
        params.pop(key, None)
    return params.urlencode()


def _export(snapshot, request, book=None):
    try:
        report = make_report(snapshot, book=book)
        filters = {key: request.GET[key] for key in ("q", "loan_status", "state", "officer") if request.GET.get(key)}
        report["filters"] = filters
        if filters:
            report["notes"] += " Applied filters: " + "; ".join(f"{key}={value}" for key, value in filters.items()) + ". Register filters do not change whole-portfolio financial totals."
        return export_report(report, request.GET["export"], section=request.GET.get("section"))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))


@agent_or_admin_required
def portfolio_detail(request, pk):
    portfolio = get_object_or_404(visible_portfolios(request.user), pk=pk)
    form = _period_form(request)
    if not form.is_valid():
        return render(request, "loans/portfolios/detail.html", {"period_form": form, "portfolio": portfolio, "invalid_filters": True, "title": str(portfolio)}, status=400)
    snapshot = portfolio_snapshot(visible_portfolios(request.user).filter(pk=pk), form.cleaned_data["date_from"], form.cleaned_data["date_to"], include_private_history=get_user_role(request.user) == "admin")
    book = snapshot["books"][pk]
    q = (request.GET.get("q") or "").strip()
    status = request.GET.get("loan_status", "")
    # Registers can be searched; financial summary stays the complete portfolio book.
    loan_rows = book["loans"]
    customer_rows = book["customers"]
    payment_rows = book["payments"]
    if q:
        def matches(row):
            return any(q.casefold() in str(row.get(key, "")).casefold() for key in ("customer_id", "legacy_id", "customer", "name", "phone", "reference", "pk"))
        loan_rows = [row for row in loan_rows if matches(row)]
        customer_rows = [row for row in customer_rows if matches(row)]
        payment_rows = [row for row in payment_rows if matches(row)]
    if status in {"ACTIVE", "CLOSED", "DEFAULT"}:
        loan_rows = [row for row in loan_rows if row["status"] == status]
    if request.GET.get("export"):
        # Use all matching rows, rather than only the page currently displayed.
        export_book = {**book, "loans": loan_rows, "customers": customer_rows, "payments": payment_rows}
        return _export(snapshot, request, export_book)
    tab = request.GET.get("tab", "overview")
    if tab not in {"overview", "customers", "loans", "payments", "risk", "deposits", "collections", "officers", "ids"}:
        tab = "overview"
    register = {"customers": customer_rows, "loans": loan_rows, "payments": payment_rows, "deposits": book["deposits"], "collections": book["collections"], "ids": book["issuance"]}.get(tab, [])
    pagination = paginate_items(request, register, per_page=25)
    tab_params = request.GET.copy()
    for key in ("tab", "page", "export", "section"):
        tab_params.pop(key, None)
    return render(request, "loans/portfolios/detail.html", {
        "portfolio": portfolio, "book": book, "metrics": book["metrics"], "snapshot": snapshot,
        "period_form": form, "tab": tab, "tab_params": tab_params.urlencode(), "export_params": _export_params(request),
        "q": q, "loan_status": status, "register_count": len(register), **pagination,
        "top_customers": sorted(book["customers"], key=lambda row: row["outstanding"], reverse=True)[:10],
        "is_admin": get_user_role(request.user) == "admin", "title": str(portfolio),
    })


@admin_required
def portfolio_update(request, pk):
    portfolio = get_object_or_404(Portfolio.objects.prefetch_related(Prefetch(
        "assignments", queryset=PortfolioAssignment.objects.select_related("agent", "assigned_by"),
    )), pk=pk)
    form = PortfolioForm(request.POST or None, instance=portfolio)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # Serialize name/status changes with ID issuance and officer changes.
            Portfolio.objects.select_for_update().get(pk=portfolio.pk)
            portfolio = form.save(commit=False)
            portfolio.save()
            set_portfolio_agents(portfolio, form.cleaned_data["agents"], actor=request.user)
        messages.success(request, f"Portfolio {portfolio.number} updated.")
        return redirect("loans:portfolio_detail", pk=portfolio.pk)
    return render(request, "loans/portfolios/update.html", {
        "portfolio": portfolio, "form": form, "history": portfolio.assignments.all(),
        "title": f"Manage {portfolio}",
    })


@admin_required
def portfolio_customers(request):
    history = Loan.objects.select_related("agent_name").only("pk", "borrower_id", "agent_name_id", "created_at", "agent_name__id", "agent_name__name")
    customers = Borrower.objects.select_related("portfolio").only(
        "pk", "full_name", "borrower_id", "legacy_borrower_id", "portfolio_id", "portfolio__id", "portfolio__number", "portfolio__name",
    ).prefetch_related(Prefetch("loans", queryset=history, to_attr="portfolio_loan_history"))
    q = (request.GET.get("q") or "").strip()
    if q:
        customers = customers.filter(Q(full_name__icontains=q) | Q(borrower_id__icontains=q) | Q(legacy_borrower_id__icontains=q))
    if request.GET.get("show") != "all":
        customers = customers.filter(portfolio__isnull=True)
    if request.GET.get("portfolio", "").isdigit():
        customers = customers.filter(portfolio_id=request.GET["portfolio"])
    if request.method == "POST":
        try:
            portfolio = Portfolio.objects.get(pk=request.POST.get("portfolio"), is_active=True)
            selected = list(Borrower.objects.filter(pk__in=request.POST.getlist("customers")))
            if not selected:
                raise ValidationError("Select at least one customer.")
            customer_id = (request.POST.get("customer_id") or "").strip().upper()
            if customer_id and len(selected) != 1:
                raise ValidationError("Select one customer when importing an already-issued Customer ID.")
            with transaction.atomic():
                for customer in sorted(selected, key=lambda customer: customer.pk):
                    assign_customer(customer, portfolio, actor=request.user, customer_id=customer_id)
            messages.success(request, f"Assigned {len(selected)} customer(s) to {portfolio}. Their loans belong to this portfolio too.")
            return redirect("loans:portfolio_customers")
        except (ValidationError, Portfolio.DoesNotExist, ValueError, TypeError) as exc:
            messages.error(request, "; ".join(exc.messages) if isinstance(exc, ValidationError) else "Select an active portfolio and valid customers.")
    pagination = paginate_items(request, customers, per_page=50)
    return render(request, "loans/portfolios/customers.html", {
        "customers": pagination["page_obj"], **pagination, "portfolios": Portfolio.objects.filter(is_active=True),
        "target_portfolio": request.GET.get("target_portfolio", ""),
        "q": q, "show": request.GET.get("show", "pending"), "title": "Customer Portfolio Assignment",
    })


@admin_required
def portfolio_export(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="customer_portfolios.csv"'
    writer = csv.writer(response)
    writer.writerow(["borrower_pk", "legacy_reference", "full_name", "portfolio_number", "customer_id"])
    customers = Borrower.objects.order_by("pk").values("pk", "legacy_borrower_id", "borrower_id", "full_name", "portfolio__number", "identity__customer_id")
    for customer in customers.iterator():
        writer.writerow([customer["pk"], customer["legacy_borrower_id"] or customer["borrower_id"], customer["full_name"],
                         customer["portfolio__number"] or "", customer["borrower_id"] if customer["identity__customer_id"] else ""])
    return response
