"""Read-only portfolio snapshots shared by screens and unpaginated exports."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal, ROUND_CEILING

from django import forms
from django.db.models import Count, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.roles import get_user_role, get_agent_for_user
from .models import Borrower, CustomerIdentity, Loan, Payment, Portfolio, PortfolioAssignment, RepaymentCollection, SecurityDeposit
from .portfolios import agent_portfolio_ids
from .financial_queries import money_total, with_deposit_totals, with_repayment_totals

ZERO = Decimal("0.00")


def money(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


def rate(part, whole):
    return money(Decimal(part) * 100 / Decimal(whole)) if whole else ZERO


class PortfolioPeriodForm(forms.Form):
    date_from = forms.DateField(required=False, label="Activity from", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, label="Activity to", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        today = timezone.localdate()
        start = cleaned.get("date_from") or today.replace(day=1)
        end = cleaned.get("date_to") or today
        if not 1900 <= start.year <= 2100 or not 1900 <= end.year <= 2100:
            raise forms.ValidationError("Choose dates between 1900 and 2100.")
        if start > end:
            raise forms.ValidationError("The start date must be on or before the end date.")
        cleaned.update(date_from=start, date_to=end)
        return cleaned


def visible_portfolios(user):
    portfolios = Portfolio.objects.all()
    if get_user_role(user) == "admin":
        return portfolios
    if get_user_role(user) == "agent":
        return portfolios.filter(pk__in=agent_portfolio_ids(get_agent_for_user(user)))
    return portfolios.none()


def dashboard_portfolios(user=None, *, agent=None):
    scope = Portfolio.objects.filter(pk__in=agent_portfolio_ids(agent)) if agent is not None else visible_portfolios(user)

    def portfolio_count(model):
        rows = model.objects.filter(portfolio_id=OuterRef("pk")).order_by().values("portfolio_id").annotate(total=Count("pk"))
        return Coalesce(Subquery(rows.values("total")), Value(0), output_field=IntegerField())

    portfolios = list(scope.annotate(
        customer_count=portfolio_count(Borrower), loan_count=portfolio_count(Loan),
        issued_count=portfolio_count(CustomerIdentity),
    ).prefetch_related(Prefetch("assignments", queryset=PortfolioAssignment.objects.filter(ended_at__isnull=True).select_related("agent"))))
    return {
        "rows": portfolios, "count": len(portfolios),
        "active_count": sum(portfolio.is_active for portfolio in portfolios),
        "customer_count": sum(portfolio.customer_count for portfolio in portfolios),
        "issued_count": sum(portfolio.issued_count for portfolio in portfolios),
        "unassigned_count": Borrower.objects.filter(portfolio__isnull=True).count() if agent is None and get_user_role(user) == "admin" else 0,
    }


def empty_metrics():
    counts = ("customers", "active_customers", "closed_customers", "bad_customers", "new_customers", "customers_without_loans",
              "loans", "active_loans", "closed_loans", "default_loans", "overdue_loans", "par30_loans", "period_loans",
              "payments", "period_payments", "pending_payments", "current_pending_payments", "void_payments", "awaiting_disbursement", "collection_attempts", "review_collections")
    amounts = ("principal", "expected", "collected", "customer_credit", "cash_received", "principal_collected", "roic_collected", "deposit_applied", "outstanding",
               "principal_outstanding", "roic_outstanding", "arrears", "overdue_balance", "par30_principal", "risk_principal",
               "period_disbursed", "period_collected", "period_customer_credit", "period_principal", "period_roic", "pending_amount", "current_pending_amount", "awaiting_amount",
               "deposit_required", "deposit_held", "deposit_due", "pipeline_amount")
    return {**dict.fromkeys(counts, 0), **dict.fromkeys(amounts, ZERO)}


def finish_metrics(metrics):
    for key, value in list(metrics.items()):
        if isinstance(value, Decimal):
            metrics[key] = money(value)
    metrics["collection_rate"] = rate(metrics["collected"], metrics["expected"])
    metrics["par30_rate"] = rate(metrics["par30_principal"], metrics["risk_principal"])
    metrics["overdue_rate"] = rate(metrics["overdue_loans"], metrics["loans"])
    metrics["average_loan"] = money(metrics["principal"] / metrics["loans"]) if metrics["loans"] else ZERO
    metrics["period_cash_movement"] = money(metrics["period_collected"] + metrics["period_customer_credit"] - metrics["period_disbursed"])
    return metrics


def loan_record(loan, today, deposits):
    paid = loan.total_paid_amount
    applied = loan.security_deposit_applied_amount
    balance = loan.balance_amount
    principal_outstanding = loan.principal_outstanding
    deposit = deposits.get(loan.pk)
    disbursed = bool(loan.disbursed_at or paid > 0 or applied > 0 or deposit is None or deposit["held"] >= deposit["required"])
    step = 1 if loan.repayment_frequency == "DAILY" else 7
    elapsed = max(0, (today - loan.start_date).days) if loan.start_date else 0
    installments_due = min(loan.expected_payments_count, elapsed // step)
    arrears = money(min(balance, max(ZERO, Decimal(installments_due) * loan.weekly_payment - paid - applied))) if disbursed else ZERO
    days_overdue = 0
    if arrears and loan.weekly_payment > 0 and loan.start_date:
        covered = int((paid + applied) // loan.weekly_payment)
        first_unpaid_date = loan.start_date + timedelta(days=(covered + 1) * step)
        days_overdue = max(0, (today - first_unpaid_date).days)
    bucket = "Awaiting disbursement" if not disbursed else "Current / due today" if days_overdue == 0 else "1–30 days" if days_overdue <= 30 else "31–60 days" if days_overdue <= 60 else "61–90 days" if days_overdue <= 90 else "Over 90 days"
    return {
        "pk": loan.pk, "borrower_pk": loan.borrower_id, "customer_id": loan.borrower.borrower_id,
        "legacy_id": loan.borrower.legacy_borrower_id, "customer": loan.borrower.full_name,
        "phone": loan.borrower.phone, "location": loan.borrower.location, "group": loan.borrower.group_name,
        "gender": loan.borrower.get_gender_display() or "Unspecified", "category": loan.get_loan_category_display(),
        "sector": loan.sector_other if loan.sector == "OTHER" and loan.sector_other else loan.get_sector_display() or "Unspecified",
        "status": loan.status, "start_date": loan.start_date, "disbursement_date": loan.disbursed_at or loan.start_date,
        "original_officer": loan.agent_name.name, "frequency": loan.get_repayment_frequency_display(),
        "duration": loan.expected_payments_count, "installment": money(loan.weekly_payment),
        "principal": money(loan.amount), "expected": loan.total_expected_amount, "collected": paid,
        "customer_credit": loan.total_customer_credit, "cash_received": loan.total_cash_received,
        "principal_collected": loan.total_principal_paid, "roic_collected": loan.total_roic_paid,
        "deposit_applied": applied, "outstanding": balance, "principal_outstanding": principal_outstanding,
        "roic_outstanding": loan.roic_outstanding, "arrears": arrears, "days_overdue": days_overdue,
        "missed_installments": int((arrears / loan.weekly_payment).to_integral_value(rounding=ROUND_CEILING)) if arrears and loan.weekly_payment > 0 else 0,
        "aging": bucket, "disbursed": disbursed, "collateral": loan.collateral_type or "None recorded",
        "collateral_value": money(loan.collateral_estimated_value), "created_at": loan.created_at,
    }


def deposit_records(loans):
    records = {}
    for deposit in with_deposit_totals(SecurityDeposit.objects.filter(loan_id__in=[loan.pk for loan in loans]).select_related("borrower")):
        held = money(max(ZERO, deposit.collected + deposit.incoming - deposit.outgoing - deposit.refunded - deposit.applied))
        records[deposit.loan_id] = {
            "loan_pk": deposit.loan_id, "customer_id": deposit.borrower.borrower_id, "customer": deposit.borrower.full_name,
            "status": deposit.get_status_display(), "required": money(deposit.required_amount), "collected": money(deposit.collected),
            "refunded": money(deposit.refunded), "applied": money(deposit.applied),
            "transferred_in": money(deposit.incoming), "transferred_out": money(deposit.outgoing), "held": held,
            "due": money(max(ZERO, deposit.required_amount - held)),
        }
    return records


def portfolio_snapshot(portfolios, start, end, *, include_unassigned=False, include_private_history=False, summary_only=False):
    """Current balances and risk; selected dates filter activity rather than reconstructing an old book."""
    today = timezone.localdate()
    assignments = PortfolioAssignment.objects.select_related("agent", "assigned_by")
    if summary_only:
        assignments = assignments.filter(ended_at__isnull=True)
    portfolios = list(portfolios.prefetch_related(Prefetch("assignments", queryset=assignments)).annotate(issued_count=Count("issued_ids", distinct=True)))
    ids = [portfolio.pk for portfolio in portfolios]
    scope = Q(portfolio_id__in=ids)
    if include_unassigned:
        scope |= Q(portfolio__isnull=True)
    customers = list(Borrower.objects.filter(scope).select_related("portfolio", "identity__portfolio"))
    loans = list(with_repayment_totals(Loan.objects.filter(scope).select_related("borrower", "agent_name"), include_pending=True))
    loans_by_id = {loan.pk: loan for loan in loans}
    loan_owners = {loan.pk: loan.portfolio_id for loan in loans}
    deposits = deposit_records(loans)
    books = {}
    for portfolio in portfolios:
        assignments = list(portfolio.assignments.all())
        current = [assignment for assignment in assignments if assignment.ended_at is None]
        books[portfolio.pk] = {
            "portfolio": portfolio, "metrics": empty_metrics(), "customers": [], "loans": [], "payments": [], "deposits": [],
            "collections": [], "assignments": assignments, "officers": current, "issuance": [],
            "active_officers": sum(assignment.agent.employment_status == "ACTIVE" for assignment in current),
            "issued_count": portfolio.issued_count, "next_id": f"SF{portfolio.number}{portfolio.next_customer_number:04d}" if portfolio.next_customer_number <= 1000 else "Capacity reached",
            "remaining_numbers": max(0, 1001 - portfolio.next_customer_number),
        }
    if include_unassigned:
        books[None] = {"portfolio": None, "metrics": empty_metrics(), "customers": [], "loans": [], "payments": [], "deposits": [], "collections": [], "assignments": [], "officers": [], "issuance": [], "active_officers": 0, "issued_count": 0, "next_id": "Confirm portfolio", "remaining_numbers": 0}
    customer_map = {}
    for customer in customers:
        identity = getattr(customer, "identity", None)
        row = {
            "pk": customer.pk, "customer_id": customer.borrower_id, "legacy_id": customer.legacy_borrower_id,
            "name": customer.full_name, "phone": customer.phone, "email": customer.email, "location": customer.location,
            "group": customer.group_name, "gender": customer.get_gender_display() or "Unspecified", "language": customer.preferred_language,
            "status": customer.status, "registered": customer.created_at, "issuing_portfolio": str(identity.portfolio) if identity else "Not issued",
            "loans": 0, "principal": ZERO, "collected": ZERO, "customer_credit": ZERO, "outstanding": ZERO, "arrears": ZERO, "max_days_overdue": 0,
        }
        customer_map[customer.pk] = row
        book = books[customer.portfolio_id]
        book["customers"].append(row)
        metrics = book["metrics"]
        metrics["customers"] += 1
        status_key = {"ACTIVE": "active_customers", "CLOSED": "closed_customers", "BAD": "bad_customers"}.get(customer.status)
        if status_key:
            metrics[status_key] += 1
        metrics["new_customers"] += start <= customer.created_at.date() <= end
    for loan in loans:
        row = loan_record(loan, today, deposits)
        book = books[loan.portfolio_id]
        book["loans"].append(row)
        metrics = book["metrics"]
        metrics["loans"] += 1
        metrics["payments"] += loan.actual_payments_count
        metrics["current_pending_payments"] += loan._pending_payment_count
        metrics["current_pending_amount"] += loan._pending_payment_amount
        status_key = {"ACTIVE": "active_loans", "CLOSED": "closed_loans", "DEFAULT": "default_loans"}.get(loan.status)
        if status_key:
            metrics[status_key] += 1
        for key in ("principal", "expected", "collected", "customer_credit", "cash_received", "principal_collected", "roic_collected", "deposit_applied", "outstanding", "principal_outstanding", "roic_outstanding", "arrears"):
            metrics[key] += row[key]
        if row["disbursed"]:
            metrics["risk_principal"] += row["principal_outstanding"]
            if row["disbursement_date"] and start <= row["disbursement_date"] <= end:
                metrics["period_disbursed"] += row["principal"]
                metrics["period_loans"] += 1
        else:
            metrics["awaiting_disbursement"] += 1
            metrics["awaiting_amount"] += row["principal"]
        if row["days_overdue"] > 0:
            metrics["overdue_loans"] += 1
            metrics["overdue_balance"] += row["outstanding"]
        if row["days_overdue"] > 30:
            metrics["par30_loans"] += 1
            metrics["par30_principal"] += row["principal_outstanding"]
        customer = customer_map.get(loan.borrower_id)
        if customer:
            customer["loans"] += 1
            for key in ("principal", "collected", "customer_credit", "outstanding", "arrears"):
                customer[key] += row[key]
            customer["max_days_overdue"] = max(customer["max_days_overdue"], row["days_overdue"])
        if loan.pk in deposits:
            deposit = deposits[loan.pk]
            book["deposits"].append(deposit)
            for destination, source in (("deposit_required", "required"), ("deposit_held", "held"), ("deposit_due", "due")):
                metrics[destination] += deposit[source]
    period_payments = Payment.objects.filter(loan_id__in=loans_by_id, payment_date__range=(start, end))
    if summary_only:
        settled = Q(is_void=False, is_pending=False)
        pending = Q(is_void=False, is_pending=True)
        activity = period_payments.order_by().values("loan_id").annotate(
            period_payments=Count("pk", filter=settled),
            period_collected=money_total(F("amount") - F("customer_credit"), filter=settled),
            period_customer_credit=money_total("customer_credit", filter=settled),
            period_principal=money_total("principal_paid", filter=settled),
            period_roic=money_total("roic_paid", filter=settled),
            pending_payments=Count("pk", filter=pending), pending_amount=money_total("amount", filter=pending),
            void_payments=Count("pk", filter=Q(is_void=True)),
        )
        for row in activity:
            metrics = books[loan_owners[row["loan_id"]]]["metrics"]
            for key, value in row.items():
                if key != "loan_id":
                    metrics[key] += value
    else:
        for payment in period_payments.select_related("collected_by").order_by("-payment_date", "-pk"):
            payment.loan = loans_by_id[payment.loan_id]
            book = books[loan_owners[payment.loan_id]]
            status = "Void" if payment.is_void else "Pending" if payment.is_pending else "Settled"
            row = {"pk": payment.pk, "loan_pk": payment.loan_id, "date": payment.payment_date, "customer_id": payment.loan.borrower.borrower_id,
                   "customer": payment.loan.borrower.full_name, "phone": payment.loan.borrower.phone, "amount": payment.amount, "principal": payment.principal_paid,
                   "roic": payment.roic_paid, "customer_credit": payment.customer_credit, "loan_applied": payment.loan_applied_amount, "status": status, "method": payment.get_payment_method_display(), "reference": payment.reference,
                   "collector": payment.collected_by.name if payment.collected_by_id else "Staff / unrecorded collector",
                   "collector_id": payment.collected_by.agent_id if payment.collected_by_id else "", "note": payment.note}
            book["payments"].append(row)
            metrics = book["metrics"]
            if status == "Settled":
                metrics["period_payments"] += 1
                metrics["period_collected"] += payment.loan_applied_amount
                metrics["period_customer_credit"] += payment.customer_credit
                metrics["period_principal"] += payment.principal_paid
                metrics["period_roic"] += payment.roic_paid
            elif status == "Pending":
                metrics["pending_payments"] += 1
                metrics["pending_amount"] += payment.amount
            else:
                metrics["void_payments"] += 1
    unresolved_scope = Q(payment_id__isnull=True, status__in={"PENDING", "PROCESSING", "SUCCEEDED", "MANUAL_REVIEW"})
    activity_scope = Q(initiated_at__gte=datetime.combine(start, time.min, tzinfo=datetime_timezone.utc),
                       initiated_at__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=datetime_timezone.utc))
    collections = RepaymentCollection.objects.filter(loan_id__in=loans_by_id).filter(unresolved_scope | activity_scope)
    if summary_only:
        activity = collections.order_by().values("loan_id").annotate(
            collection_attempts=Count("pk"), review_collections=Count("pk", filter=Q(status="MANUAL_REVIEW")),
            pipeline_amount=money_total("amount", filter=unresolved_scope),
        )
        for row in activity:
            metrics = books[loan_owners[row["loan_id"]]]["metrics"]
            for key, value in row.items():
                if key != "loan_id":
                    metrics[key] += value
    else:
        for collection in collections.select_related("borrower"):
            book = books[loan_owners[collection.loan_id]]
            unresolved = collection.payment_id is None and collection.status in {"PENDING", "PROCESSING", "SUCCEEDED", "MANUAL_REVIEW"}
            if not unresolved and not start <= collection.initiated_at.date() <= end:
                continue
            row = {"pk": collection.pk, "loan_pk": collection.loan_id, "customer_id": collection.borrower.borrower_id,
                   "customer": collection.borrower.full_name, "amount": collection.amount, "status": collection.get_status_display(),
                   "status_code": collection.status, "method": collection.get_payment_method_display(), "reference": collection.display_reference,
                   "initiated": collection.initiated_at, "reconciled": collection.reconciled_at, "reason": collection.failure_reason,
                   "unresolved": unresolved}
            book["collections"].append(row)
            book["metrics"]["collection_attempts"] += 1
            book["metrics"]["review_collections"] += collection.status == "MANUAL_REVIEW"
            if unresolved:
                book["metrics"]["pipeline_amount"] += collection.amount
    if not summary_only:
        for identity in CustomerIdentity.objects.filter(portfolio_id__in=ids).select_related("borrower__portfolio"):
            borrower = identity.borrower
            current = borrower and borrower.portfolio_id == identity.portfolio_id
            books[identity.portfolio_id]["issuance"].append({
                "customer_id": identity.customer_id, "number": identity.number, "issued": identity.issued_at,
                "customer": borrower.full_name if borrower and (current or include_private_history) else "Former customer" if borrower else "Deleted customer — ID reserved",
                "current_portfolio": str(borrower.portfolio) if borrower and borrower.portfolio_id and (current or include_private_history) else "Transferred out" if borrower else "",
                "state": "Current" if current else "Transferred out" if borrower else "Reserved after deletion",
            })
    totals = empty_metrics()
    for book in books.values():
        metrics = book["metrics"]
        metrics["customers_without_loans"] = sum(row["loans"] == 0 for row in book["customers"])
        book["loans"].sort(key=lambda row: (row["days_overdue"], row["outstanding"]), reverse=True)
        book["customers"].sort(key=lambda row: row["name"].casefold())
        book["issuance"].sort(key=lambda row: row["number"])
        book["analytics"] = {} if summary_only else breakdowns(book, start, end)
        for key in totals:
            totals[key] += metrics[key]
        finish_metrics(metrics)
    finish_metrics(totals)
    for book in books.values():
        book["metrics"]["outstanding_share"] = rate(book["metrics"]["outstanding"], totals["outstanding"])
    return {"books": books, "totals": totals, "start": start, "end": end, "as_of": today}


def breakdowns(book, start, end):
    result = {}
    for label, field in (("aging", "aging"), ("sectors", "sector"), ("locations", "location"), ("groups", "group"), ("categories", "category")):
        grouped = defaultdict(lambda: {"loans": 0, "customers": set(), "principal": ZERO, "outstanding": ZERO, "arrears": ZERO})
        for loan in book["loans"]:
            row = grouped[loan[field] or "Unspecified"]
            row["loans"] += 1
            row["customers"].add(loan["borrower_pk"])
            for key in ("principal", "outstanding", "arrears"):
                row[key] += loan[key]
        if label == "aging":
            order = ["Current / due today", "1–30 days", "31–60 days", "61–90 days", "Over 90 days", "Awaiting disbursement"]
        else:
            order = sorted(grouped, key=lambda name: grouped[name]["outstanding"], reverse=True)
        result[label] = [{"label": name, **grouped[name], "customers": len(grouped[name]["customers"]), "share": rate(grouped[name]["outstanding"], book["metrics"]["outstanding"])} for name in order]
    methods = defaultdict(lambda: {"payments": 0, "collected": ZERO, "customer_credit": ZERO})
    officers = defaultdict(lambda: {"payments": 0, "collected": ZERO, "customer_credit": ZERO, "principal": ZERO, "roic": ZERO})
    monthly = defaultdict(lambda: {"loans": 0, "disbursed": ZERO, "payments": 0, "collected": ZERO, "customer_credit": ZERO})
    for payment in book["payments"]:
        if payment["status"] != "Settled":
            continue
        methods[payment["method"]]["payments"] += 1
        methods[payment["method"]]["collected"] += payment["amount"]
        methods[payment["method"]]["customer_credit"] += payment["customer_credit"]
        officer = officers[(payment["collector_id"], payment["collector"])]
        officer["payments"] += 1
        officer["collected"] += payment["amount"]
        officer["customer_credit"] += payment["customer_credit"]
        officer["principal"] += payment["principal"]
        officer["roic"] += payment["roic"]
        monthly[payment["date"].strftime("%Y-%m")]["payments"] += 1
        monthly[payment["date"].strftime("%Y-%m")]["collected"] += payment["amount"]
        monthly[payment["date"].strftime("%Y-%m")]["customer_credit"] += payment["customer_credit"]
    for loan in book["loans"]:
        if loan["disbursed"] and loan["disbursement_date"] and start <= loan["disbursement_date"] <= end:
            row = monthly[loan["disbursement_date"].strftime("%Y-%m")]
            row["loans"] += 1
            row["disbursed"] += loan["principal"]
    month = start.replace(day=1)
    while month <= end:
        monthly[month.strftime("%Y-%m")]
        month = date(month.year + 1, 1, 1) if month.month == 12 else date(month.year, month.month + 1, 1)
    result["monthly"] = [{"label": name, **row} for name, row in sorted(monthly.items())]
    maximum = max((max(row["disbursed"], row["collected"]) for row in result["monthly"]), default=ZERO)
    for row in result["monthly"]:
        row["disbursed_share"] = rate(row["disbursed"], maximum)
        row["collected_share"] = rate(row["collected"], maximum)
    result["methods"] = [{"label": name, **row} for name, row in sorted(methods.items())]
    result["collectors"] = [{"agent_id": identity[0], "label": identity[1], **row} for identity, row in sorted(officers.items())]
    return result
