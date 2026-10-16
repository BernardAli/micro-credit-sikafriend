"""The same portfolio rows feed the UI and complete CSV, workbook, JSON, and PDF exports."""
import csv
from datetime import datetime
from decimal import Decimal
from io import BytesIO, StringIO
import zipfile

from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from weasyprint import HTML
from apps.core.pdf import LocalPDFResources
from apps.company.models import CompanyProfile


SUMMARY_COLUMNS = [
    ("number", "Portfolio No."), ("name", "Portfolio"), ("status", "Status"), ("officers", "Current Officers"),
    ("customers", "Customers"), ("loans", "Loans"), ("principal", "Loan Principal"), ("expected", "Expected Repayment"),
    ("collected", "Lifetime Applied Repayments"), ("customer_credit", "Customer Credit Held"), ("cash_received", "Lifetime Cash Received"), ("outstanding", "Current Outstanding"), ("principal_outstanding", "Principal Outstanding"),
    ("roic_outstanding", "ROIC Outstanding"), ("arrears", "Scheduled Amount Unpaid"), ("overdue_loans", "Overdue Loans"),
    ("par30_rate", "PAR30 Principal %"), ("period_disbursed", "Period Disbursed"), ("period_collected", "Period Applied Repayments"), ("period_customer_credit", "Period Customer Credit"),
    ("deposit_held", "Security Deposits Held"), ("issued_count", "IDs Issued"), ("remaining_numbers", "Automatic Numbers Available"), ("next_id", "Next Customer ID"),
]


def summary_row(book):
    portfolio = book["portfolio"]
    return {
        **book["metrics"], "number": portfolio.number if portfolio else "Unassigned",
        "name": portfolio.name if portfolio else "Customers awaiting portfolio confirmation",
        "status": "Active" if portfolio and portfolio.is_active else "Inactive" if portfolio else "Needs review",
        "officers": ", ".join(assignment.agent.name for assignment in book["officers"]) or "No officer assigned",
        "issued_count": book["issued_count"], "remaining_numbers": book["remaining_numbers"],
        "next_id": book["next_id"],
    }


def table(key, title, columns, rows, note=""):
    return {"key": key, "title": title, "columns": columns, "rows": list(rows), "note": note}


def book_tables(book):
    metrics = book["metrics"]
    summary = summary_row(book)
    metric_labels = {key: label for key, label in SUMMARY_COLUMNS}
    additional = {
        "active_customers": "Active Customers", "closed_customers": "Closed Customers", "bad_customers": "Bad Customers",
        "new_customers": "New Customers in Period", "customers_without_loans": "Customers Without Loans", "active_loans": "Active Loans",
        "closed_loans": "Closed Loans", "default_loans": "Default Loans", "payments": "Lifetime Settled Payments", "period_payments": "Settled Payments in Period",
        "period_principal": "Period Principal Collected", "period_roic": "Period ROIC Collected", "pending_payments": "Pending Payments in Period",
        "pending_amount": "Pending Payment Amount in Period", "void_payments": "Void Payments in Period", "awaiting_disbursement": "Loans Awaiting Disbursement",
        "current_pending_payments": "All Current Pending Payments", "current_pending_amount": "All Current Pending Payment Amount",
        "awaiting_amount": "Principal Awaiting Disbursement", "principal_collected": "Lifetime Principal Collected", "roic_collected": "Lifetime ROIC Collected",
        "deposit_applied": "Deposits Applied to Loans", "deposit_required": "Required Security Deposits", "deposit_due": "Security Deposit Shortfall",
        "overdue_balance": "Overdue Loan Exposure", "par30_principal": "Principal at Risk Over 30 Days", "risk_principal": "Disbursed Principal Outstanding",
        "collection_rate": "Settled Collections / Expected Repayment %", "average_loan": "Average Loan Principal",
        "period_cash_movement": "Period Collections Less Disbursements", "pipeline_amount": "Unresolved Collection Amount", "review_collections": "Collections in Manual Review",
    }
    metric_labels.update(additional)
    rows = [{"metric": label, "value": summary.get(key, metrics.get(key, ""))} for key, label in metric_labels.items()]
    result = [table("summary", "Portfolio Summary", [("metric", "Metric"), ("value", "Value")], rows)]
    result += [
        table("customers", "Customer Register", [("customer_id", "Customer ID"), ("legacy_id", "Legacy ID"), ("name", "Customer"), ("phone", "Phone"), ("email", "Email"), ("status", "Status"), ("gender", "Gender"), ("language", "Language"), ("location", "Location"), ("group", "Group"), ("issuing_portfolio", "Issuing Portfolio"), ("registered", "Registered"), ("loans", "Loans"), ("principal", "Principal"), ("collected", "Applied Repayments"), ("customer_credit", "Customer Credit Held"), ("outstanding", "Outstanding"), ("arrears", "Scheduled Amount Unpaid"), ("max_days_overdue", "Maximum Days Overdue")], book["customers"]),
        table("loans", "Loan Register", [("pk", "Loan"), ("customer_id", "Customer ID"), ("customer", "Customer"), ("phone", "Phone"), ("status", "Status"), ("original_officer", "Original Officer"), ("category", "Category"), ("sector", "Sector"), ("frequency", "Frequency"), ("start_date", "Start Date"), ("disbursement_date", "Disbursement / Legacy Start"), ("disbursed", "Disbursed"), ("duration", "Scheduled Installments"), ("installment", "Installment"), ("principal", "Principal"), ("expected", "Expected Repayment"), ("collected", "Applied Repayments"), ("cash_received", "Cash Received"), ("customer_credit", "Customer Credit Held"), ("deposit_applied", "Deposit Applied"), ("outstanding", "Outstanding"), ("principal_outstanding", "Principal Outstanding"), ("roic_outstanding", "ROIC Outstanding"), ("arrears", "Scheduled Amount Unpaid"), ("days_overdue", "Days Overdue"), ("missed_installments", "Unpaid Installment Equivalents"), ("aging", "Aging"), ("collateral", "Collateral"), ("collateral_value", "Collateral Value")], book["loans"]),
        table("payments", "Period Payment Register", [("pk", "Payment"), ("date", "Date"), ("loan_pk", "Loan"), ("customer_id", "Customer ID"), ("customer", "Customer"), ("status", "Status"), ("method", "Method"), ("reference", "Reference"), ("collector", "Collector"), ("collector_id", "Collector ID"), ("amount", "Cash Received"), ("loan_applied", "Applied to Loan"), ("principal", "Principal"), ("roic", "ROIC"), ("customer_credit", "Customer Credit Held"), ("note", "Note")], book["payments"], "Only settled receipts contribute to balances. Customer credit is held separately from loan principal and income; pending and void rows remain visible."),
        table("deposits", "Security Deposits", [("loan_pk", "Loan"), ("customer_id", "Customer ID"), ("customer", "Customer"), ("status", "Recorded Status"), ("required", "Required"), ("collected", "Collected"), ("refunded", "Refunded"), ("applied", "Applied"), ("transferred_in", "Transferred In"), ("transferred_out", "Transferred Out"), ("held", "Held"), ("due", "Shortfall")], book["deposits"], "Security deposits are shown separately from repayment collections."),
        table("collections", "Collection Pipeline", [("pk", "Collection"), ("initiated", "Initiated"), ("loan_pk", "Loan"), ("customer_id", "Customer ID"), ("customer", "Customer"), ("amount", "Amount"), ("status", "Status"), ("method", "Method"), ("reference", "Reference"), ("reconciled", "Reconciled"), ("reason", "Review / Failure Reason")], book["collections"], "Includes all unresolved attempts plus resolved attempts initiated during the activity period. Attempts are not counted as additional repayments."),
        table("assignments", "Officer Assignment History", [("agent", "Officer"), ("agent_id", "Officer ID"), ("phone", "Phone"), ("employment", "Employment Status"), ("started", "Started"), ("ended", "Ended"), ("assigned_by", "Assigned By")], [{"agent": item.agent.name, "agent_id": item.agent.agent_id, "phone": item.agent.phone, "employment": item.agent.get_employment_status_display(), "started": item.started_at, "ended": item.ended_at or "Current", "assigned_by": str(item.assigned_by) if item.assigned_by_id else "Initial setup"} for item in book["assignments"]]),
        table("issuance", "Permanent Customer ID Register", [("customer_id", "Customer ID"), ("number", "Customer Number"), ("issued", "Issued"), ("customer", "Customer"), ("current_portfolio", "Current Portfolio"), ("state", "State")], book["issuance"]),
    ]
    for key, title in (("aging", "Repayment Aging"), ("sectors", "Sector Concentration"), ("locations", "Location Concentration"), ("groups", "Customer Groups"), ("categories", "Loan Categories")):
        result.append(table(key, title, [("label", "Segment"), ("loans", "Loans"), ("customers", "Customers"), ("principal", "Principal"), ("outstanding", "Outstanding"), ("arrears", "Scheduled Amount Unpaid"), ("share", "Outstanding Share %")], book["analytics"][key]))
    result += [
        table("monthly", "Monthly Activity", [("label", "Month"), ("loans", "Loans Disbursed"), ("disbursed", "Disbursed"), ("payments", "Settled Payments"), ("collected", "Cash Received"), ("customer_credit", "Customer Credit Held")], book["analytics"]["monthly"]),
        table("methods", "Collection Methods", [("label", "Method"), ("payments", "Payments"), ("collected", "Cash Received"), ("customer_credit", "Customer Credit Held")], book["analytics"]["methods"]),
        table("collectors", "Recorded Collector Activity", [("label", "Collector"), ("agent_id", "Collector ID"), ("payments", "Payments"), ("collected", "Cash Received"), ("customer_credit", "Customer Credit Held"), ("principal", "Principal"), ("roic", "ROIC")], book["analytics"]["collectors"]),
    ]
    return result


def make_report(snapshot, *, book=None):
    if book:
        title = str(book["portfolio"])
        tables = book_tables(book)
    else:
        title = "SikaFriend Portfolio Overview"
        tables = [table("overview", "All Portfolios", SUMMARY_COLUMNS, [summary_row(item) for item in snapshot["books"].values()])]
    return {
        "title": title, "as_of": snapshot["as_of"], "date_from": snapshot["start"], "date_to": snapshot["end"],
        "generated": timezone.now(), "tables": tables,
        "currency": CompanyProfile.get_solo().formatted_currency,
        "notes": "Balances and ownership describe the current book. Activity dates filter disbursements and payments. Aging uses scheduled amounts unpaid, including partial payments, after disbursement. PAR30 is principal outstanding on loans more than 30 days overdue divided by disbursed principal outstanding. Excess settled receipts are held as customer credit, a liability separate from applied repayments and interest income. Security deposits and collection attempts are not counted as cash repayments. Transfers are reported under current portfolio ownership.",
    }


def csv_text(section):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([label for key, label in section["columns"]])
    for row in section["rows"]:
        values = []
        for key, label in section["columns"]:
            value = row.get(key, "")
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return "\ufeff" + output.getvalue()


def export_report(report, fmt, *, section=None):
    sections = report["tables"]
    if section:
        sections = [item for item in sections if item["key"] == section]
        if not sections:
            raise ValueError("Unknown export section.")
    filename = "portfolio-" + report["title"].split(" — ")[0].replace(" ", "-") + f"-{report['date_from']}-{report['date_to']}"
    if fmt == "json":
        response = JsonResponse({**report, "tables": sections}, json_dumps_params={"indent": 2})
        extension = "json"
    elif fmt == "csv":
        if len(sections) == 1:
            response = HttpResponse(csv_text(sections[0]), content_type="text/csv; charset=utf-8")
            extension = "csv"
        else:
            output = BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for item in sections:
                    archive.writestr(item["key"] + ".csv", csv_text(item))
                archive.writestr("report-notes.txt", f"{report['title']}\nBalances as of {report['as_of']}\nActivity: {report['date_from']} to {report['date_to']}\n\n{report['notes']}")
            response = HttpResponse(output.getvalue(), content_type="application/zip")
            extension = "zip"
    elif fmt == "excel":
        workbook = Workbook()
        metadata = workbook.active
        metadata.title = "Report Information"
        for row in [("Report", report["title"]), ("Currency", report["currency"]), ("Balances As Of", str(report["as_of"])), ("Activity From", str(report["date_from"])), ("Activity To", str(report["date_to"])), ("Notes", report["notes"])]:
            metadata.append(row)
        metadata.column_dimensions["A"].width = 24
        metadata.column_dimensions["B"].width = 90
        for item in sections:
            sheet = workbook.create_sheet(item["title"][:31])
            sheet.append([label for key, label in item["columns"]])
            for row in item["rows"]:
                values = [row.get(key, "") for key, label in item["columns"]]
                values = [timezone.localtime(value).replace(tzinfo=None) if isinstance(value, datetime) and timezone.is_aware(value) else value for value in values]
                sheet.append(values)
                for cell, value in zip(sheet[sheet.max_row], values):
                    if isinstance(value, str):
                        cell.data_type = "s"
                    if isinstance(value, Decimal):
                        cell.number_format = "#,##0.00"
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="9D0751")
            for column in sheet.columns:
                sheet.column_dimensions[column[0].column_letter].width = min(42, max(14, max(len(str(cell.value or "")) for cell in column) + 2))
        output = BytesIO()
        workbook.save(output)
        response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        extension = "xlsx"
    elif fmt == "pdf":
        # Compact registers keep the printable report readable; every row is retained.
        pdf_sections = []
        compact = {"customers": {"customer_id", "name", "phone", "status", "loans", "outstanding", "arrears"},
                   "loans": {"pk", "customer_id", "status", "principal", "collected", "outstanding", "days_overdue"},
                   "payments": {"date", "loan_pk", "customer_id", "status", "amount", "collector"},
                   "overview": {"number", "name", "customers", "loans", "outstanding", "par30_rate", "period_collected"}}
        for item in sections:
            columns = [column for column in item["columns"] if item["key"] not in compact or column[0] in compact[item["key"]]]
            pdf_sections.append({**item, "columns": columns, "cells": [[row.get(key, "") for key, label in columns] for row in item["rows"]]})
        html = render_to_string("loans/portfolios/pdf.html", {"report": report, "sections": pdf_sections})
        response = HttpResponse(HTML(string=html, url_fetcher=LocalPDFResources()).write_pdf(), content_type="application/pdf")
        extension = "pdf"
    else:
        raise ValueError("Choose CSV, Excel, PDF, or JSON.")
    response["Content-Disposition"] = f'attachment; filename="{filename}{"-" + section if section else ""}.{extension}"'
    return response
