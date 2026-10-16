from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from apps.core.import_security import bounded_import, excel_rows, limited_rows, safe_xml
from openpyxl import Workbook, load_workbook

from apps.core.limits import can_create_agent

from .models import Agent

UserModel = get_user_model()

AGENT_IMPORT_FORMATS = [
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

AGENT_SAMPLE_COLUMNS = [
    "agent_id",
    "name",
    "phone",
    "email",
    "workforce_role",
    "department",
    "job_title",
    "location",
    "ghana_card_number",
    "group_name",
    "employment_status",
    "base_salary",
    "commission_rate",
]


@dataclass
class AgentImportError:
    row_number: int
    message: str
    row_data: dict


def get_agent_import_formats():
    return AGENT_IMPORT_FORMATS


def get_agent_import_column_help():
    return [
        {"name": "agent_id", "required": True, "help": "Unique agent code used in the platform."},
        {"name": "name", "required": True, "help": "Agent full name as it should appear on records."},
        {"name": "phone", "required": True, "help": "Primary mobile or contact number."},
        {"name": "email", "required": False, "help": "Optional recovery email for future portal access."},
        {"name": "workforce_role", "required": False, "help": "AGENT, HR, STAFF, FINANCE, OPERATIONS, RECOVERY, or MANAGEMENT."},
        {"name": "department", "required": False, "help": "Department or business unit name."},
        {"name": "job_title", "required": False, "help": "Role title shown in the workforce directory."},
        {"name": "location", "required": True, "help": "Town, branch area, or operational location."},
        {"name": "ghana_card_number", "required": False, "help": "Optional Ghana Card number or national ID reference."},
        {"name": "group_name", "required": False, "help": "Team, branch group, or field cluster name."},
        {"name": "employment_status", "required": False, "help": "ACTIVE, ONBOARDING, ON_LEAVE, SUSPENDED, or EXITED."},
        {"name": "base_salary", "required": False, "help": "Monthly base salary amount."},
        {"name": "commission_rate", "required": False, "help": "Commission rate percentage for collections-based payroll."},
    ]


def infer_agent_import_format(filename: str) -> str | None:
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
def parse_agent_import(uploaded_file, file_type: str) -> list[dict]:
    if file_type == "csv":
        return _parse_csv(uploaded_file)
    if file_type == "excel":
        return _parse_excel(uploaded_file)
    if file_type == "json":
        return _parse_json(uploaded_file)
    if file_type == "xml":
        return _parse_xml(uploaded_file)
    raise ValueError(f"Unsupported agent import type: {file_type}")


def import_agent_rows(rows: list[dict], *, import_mode: str = "create_only") -> dict:
    created = 0
    updated = 0
    errors: list[AgentImportError] = []
    touched = []

    for index, raw_row in enumerate(rows, start=2):
        row = _normalize_row(raw_row)
        try:
            agent, action = _save_agent_row(row, import_mode=import_mode)
        except Exception as exc:
            errors.append(AgentImportError(index, str(exc), row))
            continue

        touched.append(
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
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


def build_agent_import_sample(file_type: str):
    sample_rows = [
        {
            "agent_id": "AGT-1001",
            "name": "Efua Asiedu",
            "phone": "0242000001",
            "email": "efua.asiedu@example.com",
            "workforce_role": "AGENT",
            "department": "Field Operations",
            "job_title": "Senior Loan Officer",
            "location": "Accra Central",
            "ghana_card_number": "GHA-223456789-1",
            "group_name": "Central Field Team",
            "employment_status": "ACTIVE",
            "base_salary": "2500.00",
            "commission_rate": "3.50",
        },
        {
            "agent_id": "AGT-1002",
            "name": "Yaw Boadu",
            "phone": "0242000002",
            "email": "yaw.boadu@example.com",
            "workforce_role": "HR",
            "department": "People Operations",
            "job_title": "HR Officer",
            "location": "Tema Community 2",
            "ghana_card_number": "",
            "group_name": "Head Office",
            "employment_status": "ACTIVE",
            "base_salary": "3200.00",
            "commission_rate": "0.00",
        },
    ]

    if file_type == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=AGENT_SAMPLE_COLUMNS)
        writer.writeheader()
        writer.writerows(sample_rows)
        return ("agent_import_sample.csv", "text/csv", stream.getvalue().encode("utf-8"))

    if file_type == "excel":
        book = Workbook()
        sheet = book.active
        sheet.title = "Agents"
        sheet.append(AGENT_SAMPLE_COLUMNS)
        for row in sample_rows:
            sheet.append([row.get(column, "") for column in AGENT_SAMPLE_COLUMNS])
        output = io.BytesIO()
        book.save(output)
        return (
            "agent_import_sample.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            output.getvalue(),
        )

    if file_type == "json":
        payload = json.dumps(sample_rows, indent=2)
        return ("agent_import_sample.json", "application/json", payload.encode("utf-8"))

    if file_type == "xml":
        root = ET.Element("agents")
        for row in sample_rows:
            node = ET.SubElement(root, "agent")
            for column in AGENT_SAMPLE_COLUMNS:
                child = ET.SubElement(node, column)
                child.text = str(row.get(column, ""))
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return ("agent_import_sample.xml", "application/xml", payload)

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
        payload = payload.get("agents", [])
    if not isinstance(payload, list):
        raise ValueError("JSON import must be a list of agent objects or a {'agents': [...]} payload.")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _parse_xml(uploaded_file) -> list[dict]:
    uploaded_file.seek(0)
    root = safe_xml(uploaded_file.read())
    if root.tag.lower() == "agent":
        nodes = [root]
    else:
        nodes = [child for child in root if child.tag.lower() == "agent"]
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
    return str(value).strip()


def _save_agent_row(row: dict, *, import_mode: str):
    agent_id = row.get("agent_id", "")
    if not agent_id:
        raise ValueError("Missing required field: agent_id.")

    name = row.get("name", "")
    phone = row.get("phone", "")
    location = row.get("location", "")
    ghana_card_number = (row.get("ghana_card_number", "") or "").upper()
    group_name = row.get("group_name", "")
    workforce_role = (row.get("workforce_role", "") or "AGENT").upper()
    department = row.get("department", "")
    job_title = row.get("job_title", "")
    employment_status = (row.get("employment_status", "") or "ACTIVE").upper()
    base_salary = row.get("base_salary", "") or "0"
    commission_rate = row.get("commission_rate", "") or "0"

    required_text = {
        "name": name,
        "phone": phone,
        "location": location,
    }
    for field_name, value in required_text.items():
        if not value:
            raise ValueError(f"Missing required field: {field_name}.")

    existing = Agent.objects.filter(agent_id=agent_id).first()
    if existing is not None and import_mode == "create_only":
        raise ValueError(f"Agent ID '{agent_id}' already exists.")
    if existing is None:
        limit_check = can_create_agent()
        if not limit_check.allowed:
            raise ValueError(limit_check.reason)

    target = existing or Agent()
    email = row.get("email", "").lower()
    _validate_import_email(email, exclude_user_id=target.user_id)
    _assert_unique_agent_fields(target, ghana_card_number=ghana_card_number)

    target.agent_id = agent_id
    target.name = name
    target.phone = phone
    target.email = email
    target.workforce_role = workforce_role if workforce_role in dict(Agent._meta.get_field("workforce_role").choices) else "AGENT"
    target.department = department
    target.job_title = job_title
    target.location = location
    target.ghana_card_number = ghana_card_number
    target.group_name = group_name
    target.employment_status = employment_status if employment_status in dict(Agent._meta.get_field("employment_status").choices) else "ACTIVE"
    target.base_salary = Decimal(base_salary)
    target.commission_rate = Decimal(commission_rate)

    with transaction.atomic():
        target.save()

    return target, "updated" if existing else "created"


def _validate_import_email(email: str, *, exclude_user_id=None):
    if not email:
        return
    users = UserModel._default_manager.filter(email__iexact=email)
    if exclude_user_id:
        users = users.exclude(pk=exclude_user_id)
    if users.exists():
        raise ValueError(f"Email '{email}' is already linked to another login account.")


def _assert_unique_agent_fields(target: Agent, *, ghana_card_number: str):
    if not ghana_card_number:
        return
    card_match = Agent.objects.filter(ghana_card_number=ghana_card_number)
    if target.pk:
        card_match = card_match.exclude(pk=target.pk)

    if card_match.exists():
        raise ValueError(f"Ghana Card number '{ghana_card_number}' already belongs to another agent.")
