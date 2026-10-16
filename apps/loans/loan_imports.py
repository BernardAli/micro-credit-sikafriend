from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.dateparse import parse_date
from apps.core.import_security import bounded_import, excel_rows, limited_rows, safe_xml
from openpyxl import Workbook, load_workbook

from apps.accounts.models import Agent

from .models import Borrower, Loan

LOAN_IMPORT_FORMATS = [
    {
        "slug": "csv",
        "label": "CSV Spreadsheet",
        "extensions": ".csv",
        "description": "Simple comma-separated rows for spreadsheet tools and quick data preparation.",
    },
    {
        "slug": "excel",
        "label": "Excel Workbook",
        "extensions": ".xlsx",
        "description": "Structured worksheet import for operations teams working in Microsoft Excel.",
    },
    {
        "slug": "json",
        "label": "JSON Payload",
        "extensions": ".json",
        "description": "List-based structured payload for integrations, scripts, and data pipelines.",
    },
    {
        "slug": "xml",
        "label": "XML Document",
        "extensions": ".xml",
        "description": "Tag-based import format for legacy data exchange and structured archives.",
    },
]

LOAN_SAMPLE_COLUMNS = [
    "loan_id",
    "borrower_id",
    "agent_id",
    "amount",
    "duration_weeks",
    "start_date",
    "weekly_payment",
]


@dataclass
class LoanImportError:
    row_number: int
    message: str
    row_data: dict


def get_loan_import_formats():
    return LOAN_IMPORT_FORMATS


def get_loan_import_column_help():
    return [
        {"name": "loan_id", "required": False, "help": "Existing database loan ID for updates. Leave blank for new loans."},
        {"name": "borrower_id", "required": True, "help": "Borrower code matching an existing borrower record."},
        {"name": "agent_id", "required": True, "help": "Agent code matching an existing agent record."},
        {"name": "amount", "required": True, "help": "Principal amount to disburse."},
        {"name": "duration_weeks", "required": True, "help": "Loan term in whole weeks."},
        {"name": "start_date", "required": True, "help": "Repayment start date in YYYY-MM-DD format."},
        {"name": "weekly_payment", "required": True, "help": "Weekly repayment amount expected from the borrower."},
    ]


def infer_loan_import_format(filename: str) -> str | None:
    lowered = (filename or "").lower()
    if lowered.endswith(".csv"):
        return "csv"
    if lowered.endswith(".xlsx"):
        return "excel"
    if lowered.endswith(".json"):
        return "json"
    if lowered.endswith(".xml"):
        return "xml"
    return None


@bounded_import
def parse_loan_import(uploaded_file, file_type: str) -> list[dict]:
    if file_type == "csv":
        return _parse_csv(uploaded_file)
    if file_type == "excel":
        return _parse_excel(uploaded_file)
    if file_type == "json":
        return _parse_json(uploaded_file)
    if file_type == "xml":
        return _parse_xml(uploaded_file)
    raise ValueError(f"Unsupported loan import type: {file_type}")


def import_loan_rows(rows: list[dict], *, import_mode: str = "create_only") -> dict:
    created = 0
    updated = 0
    errors: list[LoanImportError] = []
    touched = []

    for index, raw_row in enumerate(rows, start=2):
        row = _normalize_row(raw_row)
        try:
            loan, action = _save_loan_row(row, import_mode=import_mode)
        except Exception as exc:
            errors.append(LoanImportError(index, str(exc), row))
            continue

        touched.append(
            {
                "loan_id": loan.pk,
                "borrower_name": loan.borrower.full_name,
                "borrower_id": loan.borrower.borrower_id,
                "agent_name": loan.agent_name.name,
                "action": action,
            }
        )
        if action == "created":
            created += 1
        else:
            updated += 1

    return {
        "total_rows": len(rows),
        "created": created,
        "updated": updated,
        "errors": errors,
        "touched": touched,
    }


def build_loan_import_sample(file_type: str):
    sample_rows = [
        {
            "loan_id": "",
            "borrower_id": "BRW-1001",
            "agent_id": "AGT-1001",
            "amount": "2500.00",
            "duration_weeks": "12",
            "start_date": "2026-05-01",
            "weekly_payment": "250.00",
        },
        {
            "loan_id": "",
            "borrower_id": "BRW-1002",
            "agent_id": "AGT-1002",
            "amount": "4000.00",
            "duration_weeks": "16",
            "start_date": "2026-05-08",
            "weekly_payment": "320.00",
        },
    ]

    if file_type == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=LOAN_SAMPLE_COLUMNS)
        writer.writeheader()
        writer.writerows(sample_rows)
        return ("loan_import_sample.csv", "text/csv", stream.getvalue().encode("utf-8"))

    if file_type == "excel":
        book = Workbook()
        sheet = book.active
        sheet.title = "Loans"
        sheet.append(LOAN_SAMPLE_COLUMNS)
        for row in sample_rows:
            sheet.append([row.get(column, "") for column in LOAN_SAMPLE_COLUMNS])
        output = io.BytesIO()
        book.save(output)
        return (
            "loan_import_sample.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            output.getvalue(),
        )

    if file_type == "json":
        payload = json.dumps(sample_rows, indent=2)
        return ("loan_import_sample.json", "application/json", payload.encode("utf-8"))

    if file_type == "xml":
        root = ET.Element("loans")
        for row in sample_rows:
            node = ET.SubElement(root, "loan")
            for column in LOAN_SAMPLE_COLUMNS:
                child = ET.SubElement(node, column)
                child.text = str(row.get(column, ""))
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return ("loan_import_sample.xml", "application/xml", payload)

    raise ValueError(f"Unsupported sample type: {file_type}")


def _parse_csv(uploaded_file) -> list[dict]:
    uploaded_file.seek(0)
    text = uploaded_file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return limited_rows(dict(row) for row in reader if any(str(value or "").strip() for value in row.values()))


def _parse_excel(uploaded_file) -> list[dict]:
    uploaded_file.seek(0)
    rows = excel_rows(uploaded_file)
    if not rows:
        return []

    headers = [_normalize_header(cell) for cell in rows[0]]
    data = []
    for values in rows[1:]:
        if not any(value not in (None, "") for value in values):
            continue
        item = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            item[header] = values[index] if index < len(values) else ""
        data.append(item)
    return data


def _parse_json(uploaded_file) -> list[dict]:
    uploaded_file.seek(0)
    payload = json.loads(uploaded_file.read().decode("utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("loans", [])
    if not isinstance(payload, list):
        raise ValueError("JSON import must be a list of loan objects or a {'loans': [...]} payload.")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _parse_xml(uploaded_file) -> list[dict]:
    uploaded_file.seek(0)
    root = safe_xml(uploaded_file.read())
    if root.tag.lower() == "loan":
        nodes = [root]
    else:
        nodes = [child for child in root if child.tag.lower() == "loan"]
    rows = []
    for node in nodes:
        row = {}
        for child in node:
            row[_normalize_header(child.tag)] = child.text or ""
        if any(str(value or "").strip() for value in row.values()):
            rows.append(row)
    return rows


def _normalize_header(value) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _normalize_row(row: dict) -> dict:
    normalized = {}
    for key, value in row.items():
        header = _normalize_header(key)
        if not header:
            continue
        normalized[header] = _stringify(value)
    return normalized


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value).strip()


def _save_loan_row(row: dict, *, import_mode: str):
    borrower_code = row.get("borrower_id", "")
    agent_code = row.get("agent_id", "")
    amount = _parse_positive_decimal(row.get("amount", ""), "amount")
    duration_weeks = _parse_positive_int(row.get("duration_weeks", ""), "duration_weeks")
    start_date = _parse_required_date(row.get("start_date", ""), "start_date")
    weekly_payment = _parse_positive_decimal(row.get("weekly_payment", ""), "weekly_payment")

    if not borrower_code:
        raise ValueError("Missing required field: borrower_id.")
    if not agent_code:
        raise ValueError("Missing required field: agent_id.")

    from .portfolios import customer_lookup, agent_can_access
    borrower = customer_lookup(borrower_code)

    agent = Agent.objects.filter(agent_id=agent_code).first()
    if agent is None:
        raise ValueError(f"Agent ID '{agent_code}' does not exist.")

    loan_id_text = row.get("loan_id", "")
    existing = None
    if loan_id_text:
        if not loan_id_text.isdigit():
            raise ValueError("loan_id must be a whole number when provided.")
        existing = Loan.objects.select_related("borrower", "agent_name").filter(pk=int(loan_id_text)).first()
        if existing is None:
            raise ValueError(f"Loan ID '{loan_id_text}' does not exist for update.")
        if import_mode == "create_only":
            raise ValueError("loan_id should be left blank when creating new loans.")

    previous_borrower = existing.borrower if existing is not None else None
    if existing is None and not agent_can_access(agent, borrower):
        raise ValueError("Assign the customer and officer to the same portfolio before importing a new loan.")
    if existing is not None and existing.agent_name_id != agent.pk:
        raise ValueError("The original loan officer is historical. Change current officers through portfolio assignments.")
    target = existing or Loan()
    target.borrower = borrower
    target.portfolio_id = borrower.portfolio_id
    target.agent_name = agent
    target.amount = amount
    target.duration_weeks = duration_weeks
    target.start_date = start_date
    target.weekly_payment = weekly_payment
    target._skip_new_loan_notifications = True

    with transaction.atomic():
        target.save()
        target.refresh_status(save=True)
        target.borrower.refresh_status(save=True)
        if previous_borrower and previous_borrower.pk != target.borrower_id:
            previous_borrower.refresh_status(save=True)

    return target, "updated" if existing else "created"


def _parse_positive_decimal(value: str, field_name: str) -> Decimal:
    if value in ("", None):
        raise ValueError(f"Missing required field: {field_name}.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")
    if amount <= Decimal("0.00"):
        raise ValueError(f"{field_name} must be greater than 0.")
    return amount.quantize(Decimal("0.01"))


def _parse_positive_int(value: str, field_name: str) -> int:
    if value in ("", None):
        raise ValueError(f"Missing required field: {field_name}.")
    try:
        integer_value = int(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a whole number.")
    if integer_value <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")
    return integer_value


def _parse_required_date(value: str, field_name: str):
    if not value:
        raise ValueError(f"Missing required field: {field_name}.")
    parsed = parse_date(str(value))
    if parsed is None:
        raise ValueError(f"{field_name} must be a valid date in YYYY-MM-DD format.")
    return parsed
