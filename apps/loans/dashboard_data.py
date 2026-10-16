"""Single-pass summaries with bounded dashboard registers and leaderboards."""
from bisect import insort
from decimal import Decimal
from django.db.models import Count, F, Q
from django.db.models.functions import Lower
from django.utils import timezone
from apps.accounts.models import Agent
from apps.company.models import CompanyProfile
from .dashboard_queries import iter_dashboard_loans, recent_dashboard_payments
from .financial_queries import money_total
from .models import Borrower, Loan, Payment
from .portfolio_analytics import dashboard_portfolios

ZERO = Decimal("0.00")

def quantize_amount(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))

def _company_name():
    return CompanyProfile.get_solo().company_name

def rate(part, whole):
    return quantize_amount(Decimal(part) * 100 / whole) if whole else ZERO

class RankedRows:
    """Keep only the displayed rows while streaming the complete book."""
    def __init__(self, limit):
        self.limit, self.rows = limit, []
    def add(self, key, row):
        if len(self.rows) < self.limit or key < self.rows[-1][0]:
            insort(self.rows, (key, row))
            del self.rows[self.limit:]
    def values(self):
        return [row for _, row in self.rows]

def empty_totals():
    return dict(count=0, disbursed=ZERO, expected=ZERO, roic=ZERO, collected=ZERO,
                balance=ZERO, principal_outstanding=ZERO, principal_collected=ZERO,
                roic_collected=ZERO, roic_outstanding=ZERO, payment_count=0, default_count=0)

def add_totals(target, values):
    for name, value in values.items():
        target[name] += value

def build_dashboard_context(user, *, report=False):
    today = timezone.localdate()
    company = CompanyProfile.get_solo()
    grace = company.overdue_grace_periods
    starts = [today, today - timezone.timedelta(days=7), today.replace(day=1),
              today - timezone.timedelta(days=30), today - timezone.timedelta(days=90)]
    labels = ["Today", "Last 7 Days", "Month to Date", "Last 30 Days", "Last 90 Days"]
    windows = [dict(label=label, loan_count=0, payment_count=0, disbursed=ZERO,
                    collected=ZERO, principal_collected=ZERO, roic_collected=ZERO) for label in labels]
    month_markers = []
    cursor = today.replace(day=1)
    for _ in range(6):
        month_markers.insert(0, cursor)
        cursor = (cursor - timezone.timedelta(days=1)).replace(day=1)
    daily_markers = [today - timezone.timedelta(days=offset) for offset in range(29, -1, -1)]
    month_disbursed_map = dict.fromkeys(month_markers, ZERO)
    month_collected_map = dict.fromkeys(month_markers, ZERO)
    month_loan_count_map = dict.fromkeys(month_markers, 0)
    month_payment_count_map = dict.fromkeys(month_markers, 0)
    daily_disbursed_map = dict.fromkeys(daily_markers, ZERO)
    daily_collected_map = dict.fromkeys(daily_markers, ZERO)
    borrower_counts = Borrower.objects.aggregate(
        total=Count("pk"), **{code: Count("pk", filter=Q(status=code)) for code, _ in Borrower.STATUS_CHOICES},
        month=Count("pk", filter=Q(created_at__date__range=(starts[2], today))),
        last30=Count("pk", filter=Q(created_at__date__range=(starts[3], today))))
    borrowers_count = borrower_counts["total"]
    borrower_active_count, borrower_closed_count, borrower_bad_count = (borrower_counts[code] for code in ("ACTIVE", "CLOSED", "BAD"))
    month_new_borrowers, last_30_new_borrowers = borrower_counts["month"], borrower_counts["last30"]
    agents_count = Agent.objects.count()
    loan_status = {code: empty_totals() for code, _ in Loan.STATUS_CHOICES}
    borrower_status = {code: empty_totals() for code, _ in Borrower.STATUS_CHOICES}
    category = {tier["code"]: {"code": tier["code"], "label": tier["label"], **empty_totals()} for tier in company.tiers_for_template}
    age_band_board = [dict(label=label, count=0, default_count=0, disbursed=ZERO, balance=ZERO)
                      for label in ("0-4 Weeks", "5-8 Weeks", "9-12 Weeks", "13+ Weeks")]
    agent_map, location_map, group_map = {}, {}, {}
    newest, watch, exposure, bad = RankedRows(50), RankedRows(15), RankedRows(15 if report else 12), RankedRows(10)
    report_risk = RankedRows(15) if report else None
    par_amount = overdue_total_amount = ZERO
    par_count = overdue_watch_count = critical_overdue_count = 0
    current = None

    def finish_borrower(entry):
        if entry is None:
            return
        borrower = entry["borrower"]
        for agent_id in entry["agent_ids"]:
            agent_map[agent_id]["borrowers_count"] += 1
        row = {**entry, "agent_count": len(entry["agent_ids"]), "collection_rate": rate(entry["collected"], entry["expected"])}
        row.pop("agent_ids")
        key = (-row["total_outstanding"], -row["default_loans"], borrower.full_name.lower(), borrower.pk)
        exposure.add(key, row)
        if borrower.status == "BAD" or row["default_loans"] or row["max_overdue_weeks"] > 6:
            bad.add(key, row)

    for loan in iter_dashboard_loans():
        borrower, agent = loan.borrower, loan.agent_name
        overdue = loan.overdue_weeks
        critical = loan.balance_amount > ZERO and overdue > grace
        values = dict(count=1, disbursed=loan.amount, expected=loan.total_expected_amount, roic=loan.roic_amount,
                      collected=loan.total_paid_amount, balance=loan.balance_amount,
                      principal_outstanding=loan.principal_outstanding, roic_outstanding=loan.roic_outstanding,
                      principal_collected=loan.total_principal_paid, roic_collected=loan.total_roic_paid,
                      payment_count=loan.actual_payments_count, default_count=int(loan.status == "DEFAULT"))
        add_totals(loan_status.setdefault(loan.status, empty_totals()), values)
        add_totals(borrower_status.setdefault(borrower.status, empty_totals()), values)
        if loan.loan_category in category:
            add_totals(category[loan.loan_category], values)
        age = loan.weeks_since_start
        band = 0 if age <= 4 else 1 if age <= 8 else 2 if age <= 12 else 3
        for key in ("count", "default_count", "disbursed", "balance"):
            age_band_board[band][key] += values[key]
        newest.add((-loan.created_at.timestamp(), -loan.pk), loan)
        if report:
            report_risk.add((loan.status != 'DEFAULT', -overdue, -loan.balance_amount, -loan.created_at.timestamp(), -loan.pk), loan)
        if loan.balance_amount > ZERO:
            severity = "Critical" if loan.status == "DEFAULT" or critical else "Warning" if overdue or loan.balance_amount >= 10000 else "Healthy"
            watch.add(({"Critical": 0, "Warning": 1, "Healthy": 2}[severity], -overdue, -loan.balance_amount, loan.pk),
                      dict(loan=loan, severity=severity, overdue_weeks=overdue, balance=loan.balance_amount,
                           principal_outstanding=loan.principal_outstanding, roic_outstanding=loan.roic_outstanding))
        if loan.status == "ACTIVE":
            if overdue:
                overdue_watch_count += 1
                overdue_total_amount += loan.balance_amount
            critical_overdue_count += int(critical)
            if loan.balance_amount > ZERO and loan.start_date and loan.start_date <= today - timezone.timedelta(weeks=4):
                par_count += 1
                par_amount += loan.balance_amount
        created_day = loan.created_at.date()
        for start, window in zip(starts, windows):
            if start <= created_day <= today:
                window["loan_count"] += 1
                window["disbursed"] += loan.amount
        marker = created_day.replace(day=1)
        if marker in month_disbursed_map:
            month_disbursed_map[marker] += loan.amount
            month_loan_count_map[marker] += 1
        if created_day in daily_disbursed_map:
            daily_disbursed_map[created_day] += loan.amount
        agent_id = agent.pk if agent else 0
        agent_entry = agent_map.setdefault(agent_id, {**empty_totals(), "agent": agent, "borrowers_count": 0,
                                                       "active_loans": 0, "closed_loans": 0, "default_loans": 0, "latest_payment": None})
        add_totals(agent_entry, values)
        if loan.status in {'ACTIVE','CLOSED','DEFAULT'}:
            agent_entry[f"{loan.status.lower()}_loans"] += 1
        if loan._latest_payment and (agent_entry["latest_payment"] is None or loan._latest_payment > agent_entry["latest_payment"]):
            agent_entry["latest_payment"] = loan._latest_payment
        first = current is None or current["borrower"].pk != borrower.pk
        if first:
            finish_borrower(current)
            current = dict(borrower=borrower, agent_ids=set(), total_loans=0, active_loans=0, closed_loans=0,
                           default_loans=0, disbursed=ZERO, expected=ZERO, collected=ZERO,
                           principal_outstanding=ZERO, roic_outstanding=ZERO, total_outstanding=ZERO,
                           max_overdue_weeks=0, latest_loan=None, latest_payment=None)
        current["agent_ids"].add(agent_id)
        current["total_loans"] += 1
        if loan.status in {'ACTIVE','CLOSED','DEFAULT'}:
            current[f"{loan.status.lower()}_loans"] += 1
        for name in ("disbursed", "expected", "collected", "principal_outstanding", "roic_outstanding"):
            current[name] += values[name]
        current["total_outstanding"] += values["balance"]
        current["max_overdue_weeks"] = max(current["max_overdue_weeks"], overdue)
        current["latest_loan"] = max(current["latest_loan"] or loan.created_at, loan.created_at)
        if loan._latest_payment:
            current["latest_payment"] = max(current["latest_payment"] or loan._latest_payment, loan._latest_payment)
        for mapping, key in ((location_map, (borrower.location or "Unknown").strip()), (group_map, (borrower.group_name or "Ungrouped").strip())):
            entry = mapping.setdefault(key, {**empty_totals(), "name": key, "borrowers_count": 0})
            add_totals(entry, values)
            entry["borrowers_count"] += int(first)
    finish_borrower(current)

    def empty_borrower_row(borrower):
        return dict(borrower=borrower, agent_count=0, total_loans=0, active_loans=0, closed_loans=0,
                    default_loans=0, disbursed=ZERO, expected=ZERO, collected=ZERO, principal_outstanding=ZERO,
                    roic_outstanding=ZERO, total_outstanding=ZERO, max_overdue_weeks=0,
                    latest_loan=None, latest_payment=None, collection_rate=ZERO)
    for queryset, board in ((Borrower.objects.filter(loans__isnull=True), exposure),
                             (Borrower.objects.filter(loans__isnull=True, status="BAD"), bad)):
        for borrower in queryset.only("pk", "full_name", "status").order_by(Lower("full_name"), "pk")[:board.limit]:
            board.add((ZERO, 0, borrower.full_name.lower(), borrower.pk), empty_borrower_row(borrower))

    payments = Payment.objects.filter(is_void=False, is_pending=False)
    expressions = {"total_payments_count": Count("pk"), "total_collected": money_total(F("amount") - F("customer_credit")),
                   "total_principal_collected": money_total("principal_paid"), "total_roic_collected": money_total("roic_paid")}
    for index, start in enumerate(starts):
        scope = Q(payment_date__range=(start, today))
        for name, expression in (("collected", F("amount") - F("customer_credit")), ("principal_collected", "principal_paid"), ("roic_collected", "roic_paid")):
            expressions[f"w{index}_{name}"] = money_total(expression, filter=scope)
        expressions[f"w{index}_payment_count"] = Count("pk", filter=scope)
    cash = payments.aggregate(**expressions)
    for index, window in enumerate(windows):
        for name in ("collected", "principal_collected", "roic_collected", "payment_count"):
            window[name] = cash[f"w{index}_{name}"]
    for item in payments.filter(payment_date__range=(min(month_markers[0], daily_markers[0]), today)).order_by().values("payment_date").annotate(collected=money_total(F("amount") - F("customer_credit")), count=Count("pk")).iterator(chunk_size=200):
        day, marker = item["payment_date"], item["payment_date"].replace(day=1)
        if marker in month_collected_map:
            month_collected_map[marker] += item["collected"]
            month_payment_count_map[marker] += item["count"]
        if day in daily_collected_map:
            daily_collected_map[day] += item["collected"]
    total = empty_totals()
    for entry in loan_status.values():
        add_totals(total, entry)
    active, closed, default = (loan_status[code] for code in ("ACTIVE", "CLOSED", "DEFAULT"))
    total_loans, active_count, closed_count, default_count = total["count"], active["count"], closed["count"], default["count"]
    total_disbursed, active_disbursed = quantize_amount(total["disbursed"]), quantize_amount(active["disbursed"])
    total_expected, active_expected = quantize_amount(total["expected"]), quantize_amount(active["expected"])
    total_roic, active_roic = quantize_amount(total["roic"]), quantize_amount(active["roic"])
    total_collected, total_principal_collected, total_roic_collected = (cash[name] for name in ("total_collected", "total_principal_collected", "total_roic_collected"))
    total_payments_count = cash["total_payments_count"]
    today_collected, week_collected, month_collected, last_30_collected = (window["collected"] for window in windows[:4])
    month_disbursed, last_30_disbursed = windows[2]["disbursed"], windows[3]["disbursed"]
    month_new_loans, last_30_new_loans = windows[2]["loan_count"], windows[3]["loan_count"]
    total_outstanding_active, active_principal_outstanding = quantize_amount(active["balance"]), quantize_amount(active["principal_outstanding"])
    active_roic_outstanding = quantize_amount(max(ZERO, active_roic - active["roic_collected"]))
    total_equity_outstanding = quantize_amount(max(ZERO, total_disbursed - total_collected))
    total_principal_outstanding = quantize_amount(total["principal_outstanding"])
    total_roic_outstanding = quantize_amount(max(ZERO, total_roic - total_roic_collected))
    default_expected, default_roic_expected = quantize_amount(default["expected"]), quantize_amount(default["roic"])
    total_default = quantize_amount(max(ZERO, default_expected - default["collected"]))
    principal_default = quantize_amount(max(ZERO, default["disbursed"] - default["collected"] + default["roic_collected"]))
    equity_default = quantize_amount(max(ZERO, default["disbursed"] - default["collected"]))
    collections_rate, active_collection_rate = rate(total_collected, total_expected), rate(active["collected"], active_expected)
    avg_loan_size = quantize_amount(total_disbursed / total_loans) if total_loans else ZERO
    default_rate_count, default_rate_balance = rate(default_count, Decimal(total_loans)), rate(total_default, total_expected)
    par_amount, overdue_total_amount = quantize_amount(par_amount), quantize_amount(overdue_total_amount)
    par_rate = rate(par_amount, active_expected)
    loans_list_all = newest.values()
    recent_loans, recent_payments = loans_list_all[:12], recent_dashboard_payments()
    top_borrowers_outstanding, top_bad_borrowers, watchlist_loans = exposure.values(), bad.values(), watch.values()
    recovery_windows = windows
    category_board = [{key: quantize_amount(entry[key]) if isinstance(entry[key], Decimal) else entry[key]
                       for key in ("code", "label", "count", "disbursed", "expected", "roic", "collected", "balance")} for entry in category.values()]
    loan_status_board = [dict(code=code, label=label, **{key: quantize_amount(loan_status[code][key]) if isinstance(loan_status[code][key], Decimal) else loan_status[code][key]
                           for key in ("count", "disbursed", "expected", "collected", "balance")}, share=rate(loan_status[code]["count"], Decimal(total_loans))) for code, label in Loan.STATUS_CHOICES]
    borrower_status_board = [dict(code=code, label=label, count=borrower_counts[code], loan_count=borrower_status[code]["count"],
                                 **{key: quantize_amount(borrower_status[code][key]) for key in ("disbursed", "expected", "collected", "balance")},
                                 share=rate(borrower_counts[code], Decimal(borrowers_count))) for code, label in Borrower.STATUS_CHOICES]
    agent_board = [dict(agent=entry["agent"], agent_id=entry["agent"].pk if entry["agent"] else None,
                        agent_name=entry["agent"].name if entry["agent"] else "Unknown Agent", borrowers_count=entry["borrowers_count"], loans_count=entry["count"],
                        **{key: quantize_amount(entry[source]) for key, source in (("disbursed", "disbursed"), ("expected", "expected"), ("roic_expected", "roic"), ("collected", "collected"),
                          ("principal_outstanding", "principal_outstanding"), ("roic_outstanding", "roic_outstanding"), ("total_outstanding", "balance"),
                          ("principal_collected", "principal_collected"), ("roic_collected", "roic_collected"))},
                        **{key: entry[key] for key in ("active_loans", "closed_loans", "default_loans", "payment_count", "latest_payment")},
                        avg_loan_size=quantize_amount(entry["disbursed"] / entry["count"]), collection_rate=rate(entry["collected"], entry["expected"])) for entry in agent_map.values()]
    agent_board.sort(key=lambda row: (-row["total_outstanding"], -row["disbursed"], row["agent_name"].lower()))
    top_collecting_agents = sorted([row for row in agent_board if row["expected"] > 0], key=lambda row: (-row["collection_rate"], -row["collected"], row["agent_name"].lower()))[:6]
    weak_agents = sorted([row for row in agent_board if row["expected"] > 0 and row["total_outstanding"] > 0], key=lambda row: (row["collection_rate"], -row["default_loans"], -row["total_outstanding"], row["agent_name"].lower()))[:6]
    agent_board = agent_board[:12]
    def segment_board(mapping):
        rows = [dict(name=entry["name"], borrowers_count=entry["borrowers_count"], loan_count=entry["count"], default_loans=entry["default_count"],
                     disbursed=quantize_amount(entry["disbursed"]), expected=quantize_amount(entry["expected"]), collected=quantize_amount(entry["collected"]),
                     total_outstanding=quantize_amount(entry["balance"]), collection_rate=rate(entry["collected"], entry["expected"])) for entry in mapping.values()]
        return sorted(rows, key=lambda row: (-row["total_outstanding"], -row["borrowers_count"], row["name"].lower()))[:10]
    location_board, group_board = segment_board(location_map), segment_board(group_map)
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

    context["portfolio_dashboard"] = dashboard_portfolios(user)
    if report:
        context['report_total_outstanding'] = total['balance']
        context['report_risk_loans'] = report_risk.values()
        context['agents_with_loans'] = sum(entry['agent'] is not None for entry in agent_map.values())
        context['report_agent_board'] = sorted([row for row in agent_board if row['agent']], key=lambda row:-row['total_outstanding'])[:12]

    return context
