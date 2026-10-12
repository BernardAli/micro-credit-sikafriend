from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import PayrollRun
from apps.company.models import CompanyProfile
from apps.core.approvals import create_approval_request
from apps.core.audit import log_activity
from apps.loans.models import Loan, Payment

from .forms import (
    AccountingPeriodForm,
    BankAccountForm,
    BankTransactionForm,
    BillForm,
    BudgetForm,
    BudgetLineForm,
    CounterpartyForm,
    InvoiceForm,
    JournalEntryHeaderForm,
    JournalLineFormSet,
    LedgerAccountForm,
)
from .models import (
    AccountingPeriod,
    BankAccount,
    BankTransaction,
    Bill,
    Budget,
    BudgetLine,
    Counterparty,
    Invoice,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    create_journal_entry,
    reverse_journal_entry,
    ensure_default_accounting_period,
    ensure_default_ledger_accounts,
    get_ledger_account,
)


QUANT = Decimal("0.01")


def _money(value):
    return Decimal(value or Decimal("0.00")).quantize(QUANT)


def _signed_balance(account_type, debit, credit):
    debit = _money(debit)
    credit = _money(credit)
    if account_type in {"ASSET", "EXPENSE"}:
        return _money(debit - credit)
    return _money(credit - debit)


def _bucket_days(days_past_due):
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1_30"
    if days_past_due <= 60:
        return "31_60"
    if days_past_due <= 90:
        return "61_90"
    return "90_plus"


def _ensure_accounting_setup():
    ensure_default_ledger_accounts()
    ensure_default_accounting_period()


def _report_window(request):
    today = timezone.localdate()
    fy = AccountingPeriod.objects.filter(start_date__lte=today, end_date__gte=today).order_by("-start_date").first()
    default_start = fy.start_date if fy else today.replace(month=1, day=1)
    default_end = fy.end_date if fy else today.replace(month=12, day=31)

    start_text = (request.GET.get("report_start") or "").strip()
    end_text = (request.GET.get("report_end") or "").strip()

    try:
        start = date.fromisoformat(start_text) if start_text else default_start
    except ValueError:
        start = default_start
    try:
        end = date.fromisoformat(end_text) if end_text else default_end
    except ValueError:
        end = default_end

    if start > end:
        start, end = end, start

    return start, end


def _post_bank_transaction(bank_tx, user):
    if bank_tx.posted_entry_id:
        return bank_tx.posted_entry

    source_account = bank_tx.bank_account.linked_account
    amount = _money(bank_tx.amount)
    memo = bank_tx.description or f"{bank_tx.get_transaction_type_display()} - {bank_tx.bank_account.name}"
    lines = []

    if bank_tx.transaction_type == "TRANSFER_OUT":
        target_bank = bank_tx.target_bank_account
        if not target_bank:
            raise ValueError("Transfer transactions need a destination bank account.")
        lines = [
            {"account": target_bank.linked_account, "debit": amount, "credit": Decimal("0.00"), "description": f"Transfer from {bank_tx.bank_account.name}"},
            {"account": source_account, "debit": Decimal("0.00"), "credit": amount, "description": f"Transfer to {target_bank.name}"},
        ]
    elif bank_tx.transaction_type in {"DEPOSIT", "INTEREST"}:
        if not bank_tx.offset_account_id:
            raise ValueError("Select an offset account for deposits or interest.")
        lines = [
            {"account": source_account, "debit": amount, "credit": Decimal("0.00"), "description": memo},
            {"account": bank_tx.offset_account, "debit": Decimal("0.00"), "credit": amount, "description": memo},
        ]
    else:
        if not bank_tx.offset_account_id:
            raise ValueError("Select an offset account for this bank transaction.")
        lines = [
            {"account": bank_tx.offset_account, "debit": amount, "credit": Decimal("0.00"), "description": memo},
            {"account": source_account, "debit": Decimal("0.00"), "credit": amount, "description": memo},
        ]

    entry = create_journal_entry(
        entry_date=bank_tx.transaction_date,
        memo=memo,
        lines=lines,
        created_by=user,
        reference=bank_tx.reference,
        source_type="BANK_TRANSACTION",
        source_key=f"bank_tx:{bank_tx.pk}",
        source_label=f"Bank transaction {bank_tx.pk}",
    )
    bank_tx.posted_entry = entry
    bank_tx.created_by = user
    bank_tx.save(update_fields=["posted_entry", "created_by"])
    return entry


def _post_invoice(invoice, user):
    if invoice.posted_entry_id:
        return invoice.posted_entry

    amount = _money(invoice.amount)
    entry = create_journal_entry(
        entry_date=invoice.issue_date,
        memo=f"Invoice {invoice.invoice_number} - {invoice.counterparty.name}",
        lines=[
            {"account": invoice.receivable_account, "debit": amount, "credit": Decimal("0.00"), "description": invoice.description},
            {"account": invoice.income_account, "debit": Decimal("0.00"), "credit": amount, "description": invoice.description},
        ],
        created_by=user,
        reference=invoice.invoice_number,
        source_type="INVOICE",
        source_key=f"invoice:{invoice.pk}",
        source_label=invoice.invoice_number,
    )
    invoice.posted_entry = entry
    invoice.created_by = user
    invoice.save(update_fields=["posted_entry", "created_by"])
    return entry


def _post_bill(bill, user):
    if bill.posted_entry_id:
        return bill.posted_entry

    amount = _money(bill.amount)
    entry = create_journal_entry(
        entry_date=bill.issue_date,
        memo=f"Bill {bill.bill_number} - {bill.counterparty.name}",
        lines=[
            {"account": bill.expense_account, "debit": amount, "credit": Decimal("0.00"), "description": bill.description},
            {"account": bill.payable_account, "debit": Decimal("0.00"), "credit": amount, "description": bill.description},
        ],
        created_by=user,
        reference=bill.bill_number,
        source_type="BILL",
        source_key=f"bill:{bill.pk}",
        source_label=bill.bill_number,
    )
    bill.posted_entry = entry
    bill.created_by = user
    bill.save(update_fields=["posted_entry", "created_by"])
    return entry


@transaction.atomic
def _sync_operational_entries(user):
    created_entries = 0
    company_profile = CompanyProfile.get_solo()

    loan_portfolio = get_ledger_account("1300")
    bank_current = get_ledger_account("1010")
    cash_on_hand = get_ledger_account("1000")
    momo_wallet = get_ledger_account("1005")
    suspense = get_ledger_account("1090")
    roic_income = get_ledger_account("4000")
    salary_expense = get_ledger_account("5000")
    allowance_expense = get_ledger_account("5010")
    commission_expense = get_ledger_account("5020")
    statutory_payable = get_ledger_account("2050")
    paye_payable = get_ledger_account(company_profile.paye_payable_account_code) or statutory_payable
    employee_pension_payable = get_ledger_account(company_profile.employee_pension_payable_account_code) or statutory_payable
    employer_pension_payable = get_ledger_account(company_profile.employer_pension_payable_account_code) or statutory_payable
    welfare_payable = get_ledger_account(company_profile.welfare_payable_account_code) or statutory_payable
    employer_statutory_expense = get_ledger_account(company_profile.employer_statutory_expense_account_code) or salary_expense
    other_deduction_clearing = get_ledger_account("2060")

    # Lock source rows before any accounting periods, matching reversal execution.
    locked_loans = list(Loan.objects.select_for_update().order_by("pk"))
    locked_payments = list(Payment.objects.select_for_update().select_related("loan__borrower").order_by("pk"))
    locked_payroll = list(PayrollRun.objects.select_for_update().prefetch_related("lines").filter(status="PAID").order_by("pk"))
    for loan in locked_loans:
        if not loan.is_ready_for_disbursement:
            continue
        source_key = f"loan:{loan.pk}:disbursement"
        if JournalEntry.objects.filter(source_key=source_key, source_type="LOAN_DISBURSEMENT").exists():
            continue
        if not loan_portfolio or not bank_current:
            continue
        create_journal_entry(
            entry_date=loan.disbursed_at or loan.created_at.date(),
            memo=f"Loan disbursed to {loan.borrower.full_name}",
            lines=[
                {"account": loan_portfolio, "debit": _money(loan.amount), "credit": Decimal("0.00"), "description": f"Loan #{loan.pk} principal"},
                {"account": bank_current, "debit": Decimal("0.00"), "credit": _money(loan.amount), "description": f"Loan #{loan.pk} funding"},
            ],
            created_by=user,
            reference=f"Loan {loan.pk}",
            source_type="LOAN_DISBURSEMENT",
            source_key=source_key,
            source_label=f"Loan #{loan.pk}",
        )
        created_entries += 1

    from .repayments import sync_repayment_entry
    for payment in locked_payments:
        created_entries += sync_repayment_entry(payment, user=user)

    # Deleted repayment rows also need to be offset in the ledger.
    for entry in JournalEntry.objects.filter(source_type="LOAN_REPAYMENT", status="POSTED", reversed_by__isnull=True):
        parts = entry.source_key.split(":")
        if len(parts) == 3 and parts[0] == "payment" and parts[1].isdigit() and not Payment.objects.filter(pk=int(parts[1])).exists():
            _reversal, created = reverse_journal_entry(entry, user=user, reason="Repayment deleted")
            created_entries += int(created)

    for run in locked_payroll:
        source_key = f"payroll:{run.pk}:paid"
        if JournalEntry.objects.filter(source_key=source_key, source_type="PAYROLL").exists():
            continue
        if not bank_current:
            continue
        gross_salary = _money(sum((line.base_salary for line in run.lines.all()), Decimal("0.00")))
        allowances = _money(sum((line.fixed_allowances + line.bonus_total + line.overtime_total + line.other_earnings for line in run.lines.all()), Decimal("0.00")))
        commissions = _money(sum((line.commission_total for line in run.lines.all()), Decimal("0.00")))
        tax_deductions = _money(sum((line.tax_deduction for line in run.lines.all()), Decimal("0.00")))
        employee_pension = _money(sum((line.employee_pension_deduction for line in run.lines.all()), Decimal("0.00")))
        welfare_deductions = _money(sum((line.welfare_deduction for line in run.lines.all()), Decimal("0.00")))
        manual_statutory = _money(sum((line.manual_statutory_deductions for line in run.lines.all()), Decimal("0.00")))
        employer_statutory = _money(sum((line.employer_statutory_contributions for line in run.lines.all()), Decimal("0.00")))
        other_deductions = _money(sum((line.loan_recovery_deductions + line.other_deductions for line in run.lines.all()), Decimal("0.00")))
        net_pay = _money(sum((line.net_pay for line in run.lines.all()), Decimal("0.00")))

        lines = []
        if gross_salary > 0 and salary_expense:
            lines.append({"account": salary_expense, "debit": gross_salary, "credit": Decimal("0.00"), "description": run.title})
        if allowances > 0 and allowance_expense:
            lines.append({"account": allowance_expense, "debit": allowances, "credit": Decimal("0.00"), "description": run.title})
        if commissions > 0 and commission_expense:
            lines.append({"account": commission_expense, "debit": commissions, "credit": Decimal("0.00"), "description": run.title})
        if employer_statutory > 0 and employer_statutory_expense:
            lines.append({"account": employer_statutory_expense, "debit": employer_statutory, "credit": Decimal("0.00"), "description": "Employer statutory payroll cost"})
        if tax_deductions > 0 and paye_payable:
            lines.append({"account": paye_payable, "debit": Decimal("0.00"), "credit": tax_deductions, "description": "PAYE deducted from payroll"})
        if employee_pension > 0 and employee_pension_payable:
            lines.append({"account": employee_pension_payable, "debit": Decimal("0.00"), "credit": employee_pension, "description": "Employee pension deducted from payroll"})
        if welfare_deductions > 0 and welfare_payable:
            lines.append({"account": welfare_payable, "debit": Decimal("0.00"), "credit": welfare_deductions, "description": "Staff welfare deductions"})
        if manual_statutory > 0 and statutory_payable:
            lines.append({"account": statutory_payable, "debit": Decimal("0.00"), "credit": manual_statutory, "description": "Manual statutory payroll deductions"})
        if employer_statutory > 0 and employer_pension_payable:
            lines.append({"account": employer_pension_payable, "debit": Decimal("0.00"), "credit": employer_statutory, "description": "Employer pension contribution payable"})
        if other_deductions > 0 and other_deduction_clearing:
            lines.append({"account": other_deduction_clearing, "debit": Decimal("0.00"), "credit": other_deductions, "description": "Loan recovery and other deductions"})
        if net_pay > 0:
            lines.append({"account": bank_current, "debit": Decimal("0.00"), "credit": net_pay, "description": "Net payroll paid"})

        if len(lines) >= 2:
            create_journal_entry(
                entry_date=run.pay_date,
                memo=f"Payroll paid - {run.title}",
                lines=lines,
                created_by=user,
                reference=run.title,
                source_type="PAYROLL",
                source_key=source_key,
                source_label=run.title,
            )
            created_entries += 1

    return created_entries


def _trial_balance(end_date, start_date=None):
    filters = {"entry__status": "POSTED", "entry__entry_date__lte": end_date}
    if start_date:
        filters["entry__entry_date__gte"] = start_date
    lines = JournalLine.objects.select_related("account", "entry").filter(**filters)
    rows_map = {}

    for line in lines:
        account = line.account
        item = rows_map.setdefault(account.pk, {
            "account": account,
            "debit": Decimal("0.00"),
            "credit": Decimal("0.00"),
        })
        item["debit"] += _money(line.debit)
        item["credit"] += _money(line.credit)

    rows = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for account in LedgerAccount.objects.filter(is_active=True).order_by("code"):
        item = rows_map.get(account.pk)
        debit = item["debit"] if item else Decimal("0.00")
        credit = item["credit"] if item else Decimal("0.00")
        balance = _signed_balance(account.account_type, debit, credit)
        if debit == 0 and credit == 0 and not account.is_system:
            continue
        rows.append({
            "account": account,
            "debit": _money(debit),
            "credit": _money(credit),
            "balance": balance,
        })
        total_debit += _money(debit)
        total_credit += _money(credit)

    return rows, _money(total_debit), _money(total_credit)


def _financial_statements(start_date, end_date):
    income_rows = []
    expense_rows = []
    asset_rows = []
    liability_rows = []
    equity_rows = []

    income_total = Decimal("0.00")
    expense_total = Decimal("0.00")
    asset_total = Decimal("0.00")
    liability_total = Decimal("0.00")
    equity_total = Decimal("0.00")

    period_rows, _, _ = _trial_balance(end_date, start_date)
    balance_sheet_rows, _, _ = _trial_balance(end_date)

    for row in period_rows:
        account = row["account"]
        if account.account_type == "INCOME":
            income_rows.append(row)
            income_total += row["balance"]
        elif account.account_type == "EXPENSE":
            expense_rows.append(row)
            expense_total += row["balance"]

    for row in balance_sheet_rows:
        account = row["account"]
        if account.account_type == "ASSET":
            asset_rows.append(row)
            asset_total += row["balance"]
        elif account.account_type == "LIABILITY":
            liability_rows.append(row)
            liability_total += row["balance"]
        elif account.account_type == "EQUITY":
            equity_rows.append(row)
            equity_total += row["balance"]

    net_profit = _money(income_total - expense_total)

    return {
        "income_rows": income_rows,
        "expense_rows": expense_rows,
        "asset_rows": asset_rows,
        "liability_rows": liability_rows,
        "equity_rows": equity_rows,
        "income_total": _money(income_total),
        "expense_total": _money(expense_total),
        "asset_total": _money(asset_total),
        "liability_total": _money(liability_total),
        "equity_total": _money(equity_total),
        "net_profit": net_profit,
    }


def _cashbook_summary(start_date, end_date):
    rows = []
    net_cash_movement = Decimal("0.00")
    cash_accounts = LedgerAccount.objects.filter(is_active=True).filter(Q(is_cash_account=True) | Q(is_bank_account=True)).order_by("code")
    for account in cash_accounts:
        period_lines = JournalLine.objects.filter(
            account=account,
            entry__status="POSTED",
            entry__entry_date__gte=start_date,
            entry__entry_date__lte=end_date,
        )
        debit = _money(period_lines.aggregate(total=Sum("debit"))["total"])
        credit = _money(period_lines.aggregate(total=Sum("credit"))["total"])
        movement = _signed_balance(account.account_type, debit, credit)
        net_cash_movement += movement
        rows.append({
            "account": account,
            "debit": debit,
            "credit": credit,
            "movement": movement,
            "closing_balance": account.current_balance,
        })
    return rows, _money(net_cash_movement)


def _aging_rows(items):
    today = timezone.localdate()
    rows = []
    totals = defaultdict(lambda: Decimal("0.00"))
    for item in items:
        outstanding = _money(item.outstanding_amount)
        if outstanding <= 0:
            continue
        days_past_due = (today - item.due_date).days
        bucket = _bucket_days(days_past_due)
        totals[bucket] += outstanding
        rows.append({
            "item": item,
            "outstanding": outstanding,
            "days_past_due": max(0, days_past_due),
            "bucket": bucket,
        })
    for key in ["current", "1_30", "31_60", "61_90", "90_plus"]:
        totals[key] = _money(totals[key])
    totals["total"] = _money(sum(totals.values(), Decimal("0.00")))
    totals["b1_30"] = totals["1_30"]
    totals["b31_60"] = totals["31_60"]
    totals["b61_90"] = totals["61_90"]
    return rows, totals


def _budget_report():
    rows = []
    budgets = Budget.objects.select_related("period").prefetch_related("lines__account").order_by("-created_at")[:6]
    for budget in budgets:
        for line in budget.lines.all():
            actual_lines = JournalLine.objects.filter(
                account=line.account,
                entry__status="POSTED",
                entry__entry_date__gte=budget.period.start_date,
                entry__entry_date__lte=budget.period.end_date,
            )
            debit = _money(actual_lines.aggregate(total=Sum("debit"))["total"])
            credit = _money(actual_lines.aggregate(total=Sum("credit"))["total"])
            actual = _signed_balance(line.account.account_type, debit, credit)
            variance = _money(line.amount - actual)
            rows.append({
                "budget": budget,
                "account": line.account,
                "budget_amount": _money(line.amount),
                "actual_amount": actual,
                "variance": variance,
            })
    return rows


def _operations_summary():
    loans = list(Loan.objects.select_related("borrower", "agent_name").prefetch_related("payments"))
    payments = list(Payment.objects.filter(is_void=False, is_pending=False).select_related("loan", "loan__borrower"))
    paid_runs = list(PayrollRun.objects.prefetch_related("lines").filter(status="PAID"))

    total_disbursed = _money(sum((loan.amount for loan in loans), Decimal("0.00")))
    total_roic_expected = _money(sum((loan.roic_amount for loan in loans), Decimal("0.00")))
    total_collected = _money(sum((payment.amount for payment in payments), Decimal("0.00")))
    total_principal_collected = _money(sum((payment.principal_paid for payment in payments), Decimal("0.00")))
    total_roic_collected = _money(sum((payment.roic_paid for payment in payments), Decimal("0.00")))
    principal_outstanding = _money(sum((loan.principal_outstanding for loan in loans), Decimal("0.00")))
    roic_outstanding = _money(sum((loan.roic_outstanding for loan in loans), Decimal("0.00")))
    active_default_balance = _money(sum((loan.balance_amount for loan in loans if loan.status in {"ACTIVE", "DEFAULT"}), Decimal("0.00")))
    payroll_paid_total = _money(sum((run.total_net for run in paid_runs), Decimal("0.00")))

    return {
        "loan_count": len(loans),
        "payment_count": len(payments),
        "paid_payroll_runs": len(paid_runs),
        "total_disbursed": total_disbursed,
        "total_roic_expected": total_roic_expected,
        "total_collected": total_collected,
        "customer_credit_held": _money(sum((payment.customer_credit for payment in payments), Decimal("0.00"))),
        "total_principal_collected": total_principal_collected,
        "total_roic_collected": total_roic_collected,
        "principal_outstanding": principal_outstanding,
        "roic_outstanding": roic_outstanding,
        "active_default_balance": active_default_balance,
        "payroll_paid_total": payroll_paid_total,
    }


@staff_member_required
def accounting_hub(request):
    _ensure_accounting_setup()
    company_profile = CompanyProfile.get_solo()

    active_tab = request.GET.get("tab", "overview")

    period_form = AccountingPeriodForm(prefix="period")
    account_form = LedgerAccountForm(prefix="account")
    counterparty_form = CounterpartyForm(prefix="party")
    bank_account_form = BankAccountForm(prefix="bank")
    bank_transaction_form = BankTransactionForm(prefix="tx")
    invoice_form = InvoiceForm(prefix="invoice")
    bill_form = BillForm(prefix="bill")
    budget_form = BudgetForm(prefix="budget")
    budget_line_form = BudgetLineForm(prefix="budgetline")
    journal_form = JournalEntryHeaderForm(
        initial={"entry_date": timezone.localdate()},
        prefix="journal",
    )
    journal_line_formset = JournalLineFormSet(prefix="lines")

    if request.method == "POST":
        if "sync_operations" in request.POST:
            try:
                created_entries = _sync_operational_entries(request.user)
                messages.success(request, f"Accounting sync completed. {created_entries} operational journal entries were created.")
            except Exception as exc:
                messages.error(request, f"Accounting sync failed: {exc}")
            return redirect("accounting:hub")

        if "create_period" in request.POST:
            active_tab = "controls"
            period_form = AccountingPeriodForm(request.POST, prefix="period")
            if period_form.is_valid():
                period_form.save()
                messages.success(request, "Accounting period created successfully.")
                return redirect("accounting:hub")

        elif "create_account" in request.POST:
            active_tab = "chart"
            account_form = LedgerAccountForm(request.POST, prefix="account")
            if account_form.is_valid():
                account_form.save()
                messages.success(request, "Ledger account added successfully.")
                return redirect("accounting:hub")

        elif "create_counterparty" in request.POST:
            active_tab = "receivables"
            counterparty_form = CounterpartyForm(request.POST, prefix="party")
            if counterparty_form.is_valid():
                counterparty_form.save()
                messages.success(request, "Counterparty saved successfully.")
                return redirect("accounting:hub")

        elif "create_bank_account" in request.POST:
            active_tab = "chart"
            bank_account_form = BankAccountForm(request.POST, prefix="bank")
            if bank_account_form.is_valid():
                bank_account_form.save()
                messages.success(request, "Bank or wallet account added successfully.")
                return redirect("accounting:hub")

        elif "create_bank_transaction" in request.POST:
            active_tab = "chart"
            bank_transaction_form = BankTransactionForm(request.POST, prefix="tx")
            if bank_transaction_form.is_valid():
                bank_tx = bank_transaction_form.save(commit=False)
                bank_tx.created_by = request.user
                bank_tx.save()
                try:
                    _post_bank_transaction(bank_tx, request.user)
                    messages.success(request, "Bank or cash transaction posted successfully.")
                    return redirect("accounting:hub")
                except Exception as exc:
                    bank_tx.delete()
                    messages.error(request, f"Could not post bank transaction: {exc}")

        elif "create_invoice" in request.POST:
            active_tab = "receivables"
            invoice_form = InvoiceForm(request.POST, prefix="invoice")
            if invoice_form.is_valid():
                invoice = invoice_form.save(commit=False)
                invoice.created_by = request.user
                invoice.save()
                try:
                    _post_invoice(invoice, request.user)
                    messages.success(request, "Invoice created and posted to the ledger.")
                    return redirect("accounting:hub")
                except Exception as exc:
                    invoice.delete()
                    messages.error(request, f"Could not post invoice: {exc}")

        elif "create_bill" in request.POST:
            active_tab = "receivables"
            bill_form = BillForm(request.POST, prefix="bill")
            if bill_form.is_valid():
                bill = bill_form.save(commit=False)
                bill.created_by = request.user
                bill.save()
                try:
                    _post_bill(bill, request.user)
                    messages.success(request, "Bill created and posted to the ledger.")
                    return redirect("accounting:hub")
                except Exception as exc:
                    bill.delete()
                    messages.error(request, f"Could not post bill: {exc}")

        elif "create_budget" in request.POST:
            active_tab = "controls"
            budget_form = BudgetForm(request.POST, prefix="budget")
            if budget_form.is_valid():
                budget_form.save()
                messages.success(request, "Budget header created successfully.")
                return redirect("accounting:hub")

        elif "create_budget_line" in request.POST:
            active_tab = "controls"
            budget_line_form = BudgetLineForm(request.POST, prefix="budgetline")
            if budget_line_form.is_valid():
                budget_line_form.save()
                messages.success(request, "Budget line added successfully.")
                return redirect("accounting:hub")

        elif "create_journal" in request.POST:
            active_tab = "journals"
            journal_form = JournalEntryHeaderForm(request.POST, prefix="journal")
            journal_line_formset = JournalLineFormSet(request.POST, prefix="lines")
            if journal_form.is_valid() and journal_line_formset.is_valid():
                cleaned_lines = []
                for form in journal_line_formset:
                    data = form.cleaned_data
                    if not data:
                        continue
                    account = data.get("account")
                    debit = data.get("debit") or Decimal("0.00")
                    credit = data.get("credit") or Decimal("0.00")
                    if not account and debit == 0 and credit == 0:
                        continue
                    cleaned_lines.append({
                        "account": account,
                        "description": data.get("description", ""),
                        "debit": debit,
                        "credit": credit,
                    })
                try:
                    approval = create_approval_request(
                        workflow_type="ACCOUNTING_JOURNAL",
                        title=journal_form.cleaned_data["memo"][:180],
                        description="Manual journal entry submitted for approval before posting to the general ledger.",
                        submitted_by=request.user,
                        payload={
                            "entry_date": journal_form.cleaned_data["entry_date"].isoformat(),
                            "memo": journal_form.cleaned_data["memo"],
                            "reference": journal_form.cleaned_data.get("reference", ""),
                            "period_id": journal_form.cleaned_data.get("period").pk if journal_form.cleaned_data.get("period") else None,
                            "lines": [
                                {
                                    "account_id": line["account"].pk,
                                    "description": line.get("description", ""),
                                    "debit": str(line.get("debit") or Decimal("0.00")),
                                    "credit": str(line.get("credit") or Decimal("0.00")),
                                }
                                for line in cleaned_lines
                            ],
                        },
                        metadata={"line_count": len(cleaned_lines)},
                        source_path=request.path,
                        target_reference=journal_form.cleaned_data.get("reference", "") or journal_form.cleaned_data["memo"][:60],
                        request=request,
                    )
                    log_activity(
                        category="ACCOUNTING",
                        action="approval_requested",
                        actor=request.user,
                        object_type="ApprovalRequest",
                        object_id=approval.pk,
                        object_label=approval.title,
                        message=f"Manual journal approval requested for '{approval.title}'.",
                        metadata={"approval_id": approval.pk, "line_count": len(cleaned_lines)},
                        request=request,
                    )
                    messages.success(request, "Journal approval request submitted. A different admin must approve it from Approval Controls.")
                    return redirect("accounting:hub")
                except Exception as exc:
                    messages.error(request, f"Could not submit journal approval request: {exc}")

    report_start, report_end = _report_window(request)
    trial_balance_rows, trial_balance_debits, trial_balance_credits = _trial_balance(report_end, report_start)
    statements = _financial_statements(report_start, report_end)
    cashbook_rows, net_cash_movement = _cashbook_summary(report_start, report_end)
    ar_rows, ar_totals = _aging_rows(Invoice.objects.select_related("counterparty").exclude(status__in=["PAID", "VOID"]).order_by("due_date"))
    ap_rows, ap_totals = _aging_rows(Bill.objects.select_related("counterparty").exclude(status__in=["PAID", "VOID"]).order_by("due_date"))
    budget_rows = _budget_report()
    operations = _operations_summary()

    recent_entries = JournalEntry.objects.prefetch_related("lines__account").order_by("-entry_date", "-created_at")[:12]
    accounts = LedgerAccount.objects.order_by("code")
    bank_accounts = BankAccount.objects.select_related("linked_account").order_by("name")
    bank_transactions = BankTransaction.objects.select_related("bank_account", "offset_account", "target_bank_account", "reversal").order_by("-transaction_date", "-created_at")[:12]
    counterparties = Counterparty.objects.order_by("name")[:12]
    invoices = Invoice.objects.select_related("counterparty").order_by("-issue_date", "-created_at")[:12]
    bills = Bill.objects.select_related("counterparty").order_by("-issue_date", "-created_at")[:12]
    periods = AccountingPeriod.objects.order_by("-start_date")
    budgets = Budget.objects.select_related("period").prefetch_related("lines__account").order_by("-created_at")[:8]
    statutory_accounts = [
        {"label": "PAYE", "account": get_ledger_account(company_profile.paye_payable_account_code)},
        {"label": "Employee Pension", "account": get_ledger_account(company_profile.employee_pension_payable_account_code)},
        {"label": "Employer Pension", "account": get_ledger_account(company_profile.employer_pension_payable_account_code)},
        {"label": "Welfare Deductions", "account": get_ledger_account(company_profile.welfare_payable_account_code)},
        {"label": "Employer Statutory Expense", "account": get_ledger_account(company_profile.employer_statutory_expense_account_code)},
    ]

    context = {
        "title": "Accounting Hub",
        "company_profile": company_profile,
        "active_tab": active_tab,
        "period_form": period_form,
        "account_form": account_form,
        "counterparty_form": counterparty_form,
        "bank_account_form": bank_account_form,
        "bank_transaction_form": bank_transaction_form,
        "invoice_form": invoice_form,
        "bill_form": bill_form,
        "budget_form": budget_form,
        "budget_line_form": budget_line_form,
        "journal_form": journal_form,
        "journal_line_formset": journal_line_formset,
        "accounts": accounts,
        "bank_accounts": bank_accounts,
        "bank_transactions": bank_transactions,
        "counterparties": counterparties,
        "invoices": invoices,
        "bills": bills,
        "periods": periods,
        "budgets": budgets,
        "statutory_accounts": statutory_accounts,
        "recent_entries": recent_entries,
        "trial_balance_rows": trial_balance_rows,
        "trial_balance_debits": trial_balance_debits,
        "trial_balance_credits": trial_balance_credits,
        "cashbook_rows": cashbook_rows,
        "net_cash_movement": net_cash_movement,
        "ar_rows": ar_rows,
        "ar_totals": ar_totals,
        "ap_rows": ap_rows,
        "ap_totals": ap_totals,
        "budget_rows": budget_rows,
        "operations": operations,
        "report_start": report_start,
        "report_end": report_end,
        **statements,
    }
    return render(request, "accounting/hub.html", context)


@staff_member_required
def journal_entry_detail(request, entry_id):
    entry = get_object_or_404(JournalEntry.objects.prefetch_related("lines__account", "period"), pk=entry_id)
    return render(request, "accounting/journal_detail.html", {
        "title": f"Journal Entry {entry.entry_no}",
        "entry": entry,
        "can_request_reversal": entry.status == "POSTED" and entry.source_type == "GENERAL" and not entry.reversed_by_id and not entry.source_key.startswith("reversal:"),
    })
