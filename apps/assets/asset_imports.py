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
from apps.accounting.models import Counterparty, LedgerAccount

from .models import AssetCategory, AssetItem


ASSET_IMPORT_FORMATS = [
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

ASSET_SAMPLE_COLUMNS = [
    "asset_code",
    "name",
    "category_code",
    "purchase_cost",
    "acquisition_date",
    "in_service_date",
    "residual_value",
    "useful_life_months",
    "depreciation_method",
    "status",
    "condition",
    "serial_number",
    "manufacturer",
    "model_name",
    "location",
    "branch_name",
    "custodian_agent_id",
    "vendor_name",
    "vendor_phone",
    "vendor_email",
    "warranty_expiry",
    "asset_account_code",
    "accumulated_depreciation_account_code",
    "depreciation_expense_account_code",
    "maintenance_expense_account_code",
    "funding_account_code",
]


@dataclass
class AssetImportError:
    row_number: int
    message: str
    row_data: dict


def get_asset_import_formats():
    return ASSET_IMPORT_FORMATS


def get_asset_import_column_help():
    return [
        {"name": "asset_code", "required": True, "help": "Unique asset code used in the register."},
        {"name": "name", "required": True, "help": "Readable asset name shown in the asset register."},
        {"name": "category_code", "required": True, "help": "Existing asset category code that controls accounting and depreciation defaults."},
        {"name": "purchase_cost", "required": True, "help": "Capitalized acquisition cost for the asset."},
        {"name": "acquisition_date", "required": True, "help": "Acquisition date in YYYY-MM-DD format."},
        {"name": "in_service_date", "required": False, "help": "In-service date in YYYY-MM-DD format. Defaults to acquisition_date."},
        {"name": "residual_value", "required": False, "help": "Optional residual value. Defaults from category percentage when omitted."},
        {"name": "useful_life_months", "required": False, "help": "Optional useful life in months. Defaults from the selected category."},
        {"name": "depreciation_method", "required": False, "help": "STRAIGHT_LINE or REDUCING_BALANCE. Defaults from the category."},
        {"name": "status", "required": False, "help": "DRAFT, ACTIVE, IN_MAINTENANCE, DISPOSED, or WRITTEN_OFF."},
        {"name": "condition", "required": False, "help": "EXCELLENT, GOOD, FAIR, POOR, or CRITICAL."},
        {"name": "serial_number", "required": False, "help": "Optional serial number or manufacturer tracking code."},
        {"name": "manufacturer", "required": False, "help": "Optional manufacturer name."},
        {"name": "model_name", "required": False, "help": "Optional model or variant name."},
        {"name": "location", "required": False, "help": "Office, branch, or operational location."},
        {"name": "branch_name", "required": False, "help": "Branch or business unit name."},
        {"name": "custodian_agent_id", "required": False, "help": "Existing workforce code for the responsible custodian."},
        {"name": "vendor_name", "required": False, "help": "Vendor or supplier name. Created automatically if missing."},
        {"name": "vendor_phone", "required": False, "help": "Optional vendor phone number."},
        {"name": "vendor_email", "required": False, "help": "Optional vendor email address."},
        {"name": "warranty_expiry", "required": False, "help": "Optional warranty expiry date in YYYY-MM-DD format."},
        {"name": "asset_account_code", "required": False, "help": "Override category fixed-asset account using an existing ledger code."},
        {"name": "accumulated_depreciation_account_code", "required": False, "help": "Override category accumulated depreciation account code."},
        {"name": "depreciation_expense_account_code", "required": False, "help": "Override category depreciation expense account code."},
        {"name": "maintenance_expense_account_code", "required": False, "help": "Override category maintenance expense account code."},
        {"name": "funding_account_code", "required": False, "help": "Override category funding or settlement account code."},
    ]


def infer_asset_import_format(filename: str) -> str | None:
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
def parse_asset_import(uploaded_file, file_type: str) -> list[dict]:
    if file_type == "csv":
        return _parse_csv(uploaded_file)
    if file_type == "excel":
        return _parse_excel(uploaded_file)
    if file_type == "json":
        return _parse_json(uploaded_file)
    if file_type == "xml":
        return _parse_xml(uploaded_file)
    raise ValueError(f"Unsupported asset import type: {file_type}")


def import_asset_rows(
    rows: list[dict],
    *,
    import_mode: str = "create_only",
    post_acquisitions: bool = True,
    acquisition_hook=None,
    user=None,
) -> dict:
    created = 0
    updated = 0
    errors: list[AssetImportError] = []
    touched = []

    for index, raw_row in enumerate(rows, start=2):
        row = _normalize_row(raw_row)
        try:
            asset, action = _save_asset_row(row, import_mode=import_mode)
            if post_acquisitions and acquisition_hook and not asset.acquisition_entry_id:
                acquisition_hook(asset, user)
        except Exception as exc:
            errors.append(AssetImportError(index, str(exc), row))
            continue

        touched.append(
            {
                "asset_id": asset.pk,
                "asset_code": asset.asset_code,
                "name": asset.name,
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


def build_asset_import_sample(file_type: str):
    sample_rows = [
        {
            "asset_code": "AST-1001",
            "name": "Dell Latitude Field Laptop",
            "category_code": "IT",
            "purchase_cost": "6200.00",
            "acquisition_date": "2026-05-01",
            "in_service_date": "2026-05-03",
            "residual_value": "620.00",
            "useful_life_months": "36",
            "depreciation_method": "STRAIGHT_LINE",
            "status": "ACTIVE",
            "condition": "GOOD",
            "serial_number": "DL-LAT-001",
            "manufacturer": "Dell",
            "model_name": "Latitude 5520",
            "location": "Head Office",
            "branch_name": "Accra Main",
            "custodian_agent_id": "AGT-1001",
            "vendor_name": "TechSupply Ghana",
            "vendor_phone": "0245000001",
            "vendor_email": "sales@techsupply.example",
            "warranty_expiry": "2027-05-01",
            "asset_account_code": "1500",
            "accumulated_depreciation_account_code": "1590",
            "depreciation_expense_account_code": "5091",
            "maintenance_expense_account_code": "5092",
            "funding_account_code": "1010",
        },
        {
            "asset_code": "AST-1002",
            "name": "Branch Office Generator",
            "category_code": "EQUIP",
            "purchase_cost": "18500.00",
            "acquisition_date": "2026-05-10",
            "in_service_date": "2026-05-12",
            "residual_value": "1850.00",
            "useful_life_months": "60",
            "depreciation_method": "STRAIGHT_LINE",
            "status": "ACTIVE",
            "condition": "EXCELLENT",
            "serial_number": "GEN-AC-02",
            "manufacturer": "Perkins",
            "model_name": "12KVA",
            "location": "Kasoa Branch",
            "branch_name": "Kasoa",
            "custodian_agent_id": "",
            "vendor_name": "PowerBase Systems",
            "vendor_phone": "0245000002",
            "vendor_email": "service@powerbase.example",
            "warranty_expiry": "2028-05-10",
            "asset_account_code": "1500",
            "accumulated_depreciation_account_code": "1590",
            "depreciation_expense_account_code": "5091",
            "maintenance_expense_account_code": "5092",
            "funding_account_code": "1010",
        },
    ]

    if file_type == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=ASSET_SAMPLE_COLUMNS)
        writer.writeheader()
        writer.writerows(sample_rows)
        return ("asset_import_sample.csv", "text/csv", stream.getvalue().encode("utf-8"))

    if file_type == "excel":
        book = Workbook()
        sheet = book.active
        sheet.title = "Assets"
        sheet.append(ASSET_SAMPLE_COLUMNS)
        for row in sample_rows:
            sheet.append([row.get(column, "") for column in ASSET_SAMPLE_COLUMNS])
        output = io.BytesIO()
        book.save(output)
        return (
            "asset_import_sample.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            output.getvalue(),
        )

    if file_type == "json":
        payload = json.dumps(sample_rows, indent=2)
        return ("asset_import_sample.json", "application/json", payload.encode("utf-8"))

    if file_type == "xml":
        root = ET.Element("assets")
        for row in sample_rows:
            node = ET.SubElement(root, "asset")
            for column in ASSET_SAMPLE_COLUMNS:
                child = ET.SubElement(node, column)
                child.text = str(row.get(column, ""))
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return ("asset_import_sample.xml", "application/xml", payload)

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
        payload = payload.get("assets", [])
    if not isinstance(payload, list):
        raise ValueError("JSON import must be a list of asset objects or a {'assets': [...]} payload.")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _parse_xml(uploaded_file) -> list[dict]:
    uploaded_file.seek(0)
    root = safe_xml(uploaded_file.read())
    if root.tag.lower() == "asset":
        nodes = [root]
    else:
        nodes = [child for child in root if child.tag.lower() == "asset"]
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


def _save_asset_row(row: dict, *, import_mode: str):
    asset_code = row.get("asset_code", "")
    if not asset_code:
        raise ValueError("Missing required field: asset_code.")

    name = row.get("name", "")
    if not name:
        raise ValueError("Missing required field: name.")

    category_code = row.get("category_code", "")
    if not category_code:
        raise ValueError("Missing required field: category_code.")
    category = AssetCategory.objects.filter(code=category_code).first()
    if category is None:
        raise ValueError(f"Asset category code '{category_code}' does not exist.")

    purchase_cost = _parse_positive_decimal(row.get("purchase_cost", ""), "purchase_cost")
    acquisition_date = _parse_required_date(row.get("acquisition_date", ""), "acquisition_date")
    in_service_date = _parse_optional_date(row.get("in_service_date", "")) or acquisition_date
    warranty_expiry = _parse_optional_date(row.get("warranty_expiry", ""))

    residual_value_text = row.get("residual_value", "")
    if residual_value_text:
        residual_value = _parse_non_negative_decimal(residual_value_text, "residual_value")
    else:
        residual_value = (
            purchase_cost * Decimal(category.default_residual_value_rate or Decimal("0.00")) / Decimal("100.00")
        ).quantize(Decimal("0.01"))

    if residual_value > purchase_cost:
        raise ValueError("Residual value cannot exceed purchase cost.")

    useful_life_text = row.get("useful_life_months", "")
    useful_life_months = _parse_positive_int(useful_life_text, "useful_life_months") if useful_life_text else category.default_useful_life_months

    depreciation_method = (row.get("depreciation_method", "") or category.default_depreciation_method).upper()
    valid_methods = {choice for choice, _label in AssetItem._meta.get_field("depreciation_method").choices}
    if depreciation_method not in valid_methods:
        raise ValueError(f"Invalid depreciation_method '{depreciation_method}'.")

    status = (row.get("status", "") or "ACTIVE").upper()
    valid_statuses = {choice for choice, _label in AssetItem._meta.get_field("status").choices}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'.")

    condition = (row.get("condition", "") or "GOOD").upper()
    valid_conditions = {choice for choice, _label in AssetItem._meta.get_field("condition").choices}
    if condition not in valid_conditions:
        raise ValueError(f"Invalid condition '{condition}'.")

    custodian = None
    custodian_code = row.get("custodian_agent_id", "")
    if custodian_code:
        custodian = Agent.objects.filter(agent_id=custodian_code).first()
        if custodian is None:
            raise ValueError(f"Custodian agent ID '{custodian_code}' does not exist.")

    vendor = _resolve_vendor(
        row.get("vendor_name", ""),
        phone=row.get("vendor_phone", ""),
        email=row.get("vendor_email", ""),
    )

    asset_account = _resolve_account(row.get("asset_account_code", ""), fallback=category.asset_account, label="asset_account_code")
    accumulated_account = _resolve_account(
        row.get("accumulated_depreciation_account_code", ""),
        fallback=category.accumulated_depreciation_account,
        label="accumulated_depreciation_account_code",
    )
    depreciation_expense_account = _resolve_account(
        row.get("depreciation_expense_account_code", ""),
        fallback=category.depreciation_expense_account,
        label="depreciation_expense_account_code",
    )
    maintenance_expense_account = _resolve_account(
        row.get("maintenance_expense_account_code", ""),
        fallback=category.maintenance_expense_account,
        label="maintenance_expense_account_code",
    )
    funding_account = _resolve_account(
        row.get("funding_account_code", ""),
        fallback=category.default_funding_account,
        label="funding_account_code",
        required=False,
    )

    existing = AssetItem.objects.select_related("category").filter(asset_code=asset_code).first()
    if existing and import_mode == "create_only":
        raise ValueError(f"Asset code '{asset_code}' already exists.")
    if not existing and row.get("asset_id"):
        raise ValueError("asset_id is not supported for asset imports. Use asset_code to match existing assets.")

    target = existing or AssetItem()
    target.asset_code = asset_code
    target.name = name
    target.category = category
    target.status = status
    target.condition = condition
    target.serial_number = row.get("serial_number", "")
    target.manufacturer = row.get("manufacturer", "")
    target.model_name = row.get("model_name", "")
    target.location = row.get("location", "")
    target.branch_name = row.get("branch_name", "")
    target.custodian = custodian
    target.vendor = vendor
    target.acquisition_date = acquisition_date
    target.in_service_date = in_service_date
    target.warranty_expiry = warranty_expiry
    target.purchase_cost = purchase_cost
    target.residual_value = residual_value
    target.useful_life_months = useful_life_months
    target.depreciation_method = depreciation_method
    target.asset_account = asset_account
    target.accumulated_depreciation_account = accumulated_account
    target.depreciation_expense_account = depreciation_expense_account
    target.maintenance_expense_account = maintenance_expense_account
    target.funding_account = funding_account
    target.notes = row.get("notes", "") or target.notes

    with transaction.atomic():
        target.save()

    return target, "updated" if existing else "created"


def _resolve_vendor(name: str, *, phone: str = "", email: str = ""):
    vendor_name = (name or "").strip()
    if not vendor_name:
        return None
    vendor = Counterparty.objects.filter(name=vendor_name).first()
    if vendor:
        changed = False
        if phone and not vendor.phone:
            vendor.phone = phone
            changed = True
        if email and not vendor.email:
            vendor.email = email
            changed = True
        if vendor.counterparty_type != "VENDOR":
            vendor.counterparty_type = "VENDOR"
            changed = True
        if changed:
            vendor.save()
        return vendor
    return Counterparty.objects.create(
        name=vendor_name,
        counterparty_type="VENDOR",
        phone=phone,
        email=email,
        is_active=True,
    )


def _resolve_account(code: str, *, fallback, label: str, required: bool = True):
    ledger_code = (code or "").strip()
    if ledger_code:
        account = LedgerAccount.objects.filter(code=ledger_code, is_active=True).first()
        if account is None:
            raise ValueError(f"Ledger account code '{ledger_code}' does not exist for {label}.")
        return account
    if required and fallback is None:
        raise ValueError(f"No fallback ledger account is configured for {label}.")
    return fallback


def _parse_required_date(value: str, field_name: str):
    parsed = parse_date((value or "").strip())
    if parsed is None:
        raise ValueError(f"Field '{field_name}' must be a valid date in YYYY-MM-DD format.")
    return parsed


def _parse_optional_date(value: str):
    text = (value or "").strip()
    if not text:
        return None
    parsed = parse_date(text)
    if parsed is None:
        raise ValueError("Optional dates must use YYYY-MM-DD format.")
    return parsed


def _parse_positive_decimal(value: str, field_name: str):
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"Field '{field_name}' must be a valid decimal amount.") from None
    if parsed <= 0:
        raise ValueError(f"Field '{field_name}' must be greater than zero.")
    return parsed.quantize(Decimal("0.01"))


def _parse_non_negative_decimal(value: str, field_name: str):
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"Field '{field_name}' must be a valid decimal amount.") from None
    if parsed < 0:
        raise ValueError(f"Field '{field_name}' cannot be negative.")
    return parsed.quantize(Decimal("0.01"))


def _parse_positive_int(value: str, field_name: str):
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError(f"Field '{field_name}' must be a whole number.")
    parsed = int(text)
    if parsed <= 0:
        raise ValueError(f"Field '{field_name}' must be greater than zero.")
    return parsed
