from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from django.apps import apps
from django.core import serializers
from django.db import connections, router
from django.utils import timezone
from openpyxl import Workbook


BACKUP_FORMATS = [
    {
        "slug": "json",
        "label": "JSON Snapshot",
        "extension": "json",
        "content_type": "application/json",
        "description": "Portable structured export of model data across the platform.",
        "best_for": "App migrations, integrations, and structured restore workflows.",
    },
    {
        "slug": "xml",
        "label": "XML Snapshot",
        "extension": "xml",
        "content_type": "application/xml",
        "description": "Serializer-based XML export of the active database models.",
        "best_for": "Legacy tooling, XML pipelines, and structured archival exchange.",
    },
    {
        "slug": "csv",
        "label": "CSV Bundle",
        "extension": "zip",
        "content_type": "application/zip",
        "description": "ZIP package containing one CSV file per backed-up model.",
        "best_for": "Spreadsheet review, ad hoc analysis, and flat-file sharing.",
    },
    {
        "slug": "excel",
        "label": "Excel Workbook",
        "extension": "xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "description": "Multi-sheet Excel workbook with one sheet per model.",
        "best_for": "Management review, audit packs, and offline tabular exploration.",
    },
    {
        "slug": "sql",
        "label": "SQL Dump",
        "extension": "sql",
        "content_type": "application/sql",
        "description": "Table-level schema and insert statements from the selected database.",
        "best_for": "Disaster recovery, low-level restore, and full database capture.",
    },
]


def resolve_database_alias(alias: str | None) -> str:
    if alias in connections.databases:
        return alias
    return "default"


def get_backup_models(using: str):
    models = []
    for model in apps.get_models():
        opts = model._meta
        if opts.proxy or not opts.managed:
            continue
        if not router.allow_migrate_model(using, model):
            continue
        models.append(model)
    return sorted(models, key=lambda model: (model._meta.app_label, model._meta.model_name))


def _ordered_queryset(model, using: str):
    manager = model._default_manager.using(using)
    pk_name = model._meta.pk.attname if model._meta.pk else None
    if pk_name:
        return manager.order_by(pk_name)
    return manager.all()


def _iter_model_instances(using: str):
    for model in get_backup_models(using):
        yield from _ordered_queryset(model, using).iterator()


def get_database_overview(using: str):
    connection = connections[using]
    with connection.cursor() as cursor:
        table_names = sorted(connection.introspection.table_names(cursor))

    model_rows = []
    total_rows = 0
    for model in get_backup_models(using):
        row_count = _ordered_queryset(model, using).count()
        total_rows += row_count
        model_rows.append(
            {
                "label": model._meta.verbose_name_plural.title(),
                "app_label": model._meta.app_label,
                "model_name": model._meta.model_name,
                "db_table": model._meta.db_table,
                "row_count": row_count,
            }
        )

    model_rows.sort(key=lambda item: (item["app_label"], item["label"]))

    settings_dict = connection.settings_dict
    return {
        "alias": using,
        "vendor": connection.vendor,
        "engine": settings_dict.get("ENGINE", ""),
        "database_name": settings_dict.get("NAME", ""),
        "host": settings_dict.get("HOST", "") or "local/socket",
        "port": settings_dict.get("PORT", "") or "default",
        "table_names": table_names,
        "table_count": len(table_names),
        "model_rows": model_rows,
        "model_count": len(model_rows),
        "total_rows": total_rows,
        "generated_at": timezone.localtime(),
    }


def build_backup_filename(using: str, extension: str) -> str:
    stamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    return f"{using}_database_backup_{stamp}.{extension}"


def export_database_backup(using: str, fmt: str):
    format_config = next((item for item in BACKUP_FORMATS if item["slug"] == fmt), None)
    if not format_config:
        raise ValueError(f"Unsupported backup format: {fmt}")

    if fmt == "json":
        content = serializers.serialize("json", _iter_model_instances(using), indent=2)
        return format_config, content.encode("utf-8")

    if fmt == "xml":
        content = serializers.serialize("xml", _iter_model_instances(using), indent=2)
        return format_config, content.encode("utf-8")

    if fmt == "csv":
        return format_config, _export_csv_zip(using)

    if fmt == "excel":
        return format_config, _export_excel_workbook(using)

    if fmt == "sql":
        return format_config, _export_sql_dump(using)

    raise ValueError(f"Unhandled backup format: {fmt}")


def _model_field_headers(model):
    return [field.attname for field in model._meta.concrete_fields]


def _model_row_values(instance):
    return [field.value_from_object(instance) for field in instance._meta.concrete_fields]


def _coerce_tabular_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return value
    # FieldFile / ImageFieldFile and any other non-primitive type
    try:
        from django.db.models.fields.files import FieldFile
        if isinstance(value, FieldFile):
            return str(value.name) if value.name else ""
    except ImportError:
        pass
    return str(value)


def _export_csv_zip(using: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = io.StringIO()
        manifest_writer = csv.writer(manifest)
        manifest_writer.writerow(["App", "Model", "Table", "Rows"])

        for model in get_backup_models(using):
            csv_stream = io.StringIO()
            writer = csv.writer(csv_stream)
            headers = _model_field_headers(model)
            writer.writerow(headers)

            row_count = 0
            for instance in _ordered_queryset(model, using).iterator():
                writer.writerow([_coerce_tabular_value(value) for value in _model_row_values(instance)])
                row_count += 1

            filename = f"{model._meta.app_label}_{model._meta.model_name}.csv"
            archive.writestr(filename, csv_stream.getvalue())
            manifest_writer.writerow(
                [
                    model._meta.app_label,
                    model._meta.model_name,
                    model._meta.db_table,
                    row_count,
                ]
            )

        archive.writestr("manifest.csv", manifest.getvalue())

    return buffer.getvalue()


def _safe_sheet_title(base: str, used_titles: dict[str, int]) -> str:
    title = base[:31] or "Sheet"
    if title not in used_titles:
        used_titles[title] = 1
        return title

    used_titles[title] += 1
    suffix = f"_{used_titles[title]}"
    trimmed = title[: 31 - len(suffix)]
    return f"{trimmed}{suffix}"


def _export_excel_workbook(using: str) -> bytes:
    workbook = Workbook()
    overview = get_database_overview(using)

    meta = workbook.active
    meta.title = "Backup Overview"
    meta.append(["Database Alias", overview["alias"]])
    meta.append(["Engine", overview["engine"]])
    meta.append(["Vendor", overview["vendor"]])
    meta.append(["Database Name", overview["database_name"]])
    meta.append(["Host", overview["host"]])
    meta.append(["Port", overview["port"]])
    meta.append(["Generated At", overview["generated_at"].strftime("%Y-%m-%d %H:%M:%S %Z")])
    meta.append(["Tables", overview["table_count"]])
    meta.append(["Models", overview["model_count"]])
    meta.append(["Rows", overview["total_rows"]])
    meta.append([])
    meta.append(["App", "Model", "Table", "Rows"])
    for item in overview["model_rows"]:
        meta.append([item["app_label"], item["label"], item["db_table"], item["row_count"]])

    used_titles = defaultdict(int)
    used_titles[meta.title] = 1

    for model in get_backup_models(using):
        sheet_title = _safe_sheet_title(
            f"{model._meta.app_label}_{model._meta.verbose_name_plural.title()}",
            used_titles,
        )
        sheet = workbook.create_sheet(title=sheet_title)
        headers = _model_field_headers(model)
        sheet.append(headers)

        for instance in _ordered_queryset(model, using).iterator():
            sheet.append([_coerce_tabular_value(value) for value in _model_row_values(instance)])

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _export_sql_dump(using: str) -> bytes:
    connection = connections[using]
    quote_name = connection.ops.quote_name
    vendor = connection.vendor

    output = io.StringIO()
    generated = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S %Z")
    output.write(f"-- Database backup for alias '{using}'\n")
    output.write(f"-- Generated at {generated}\n")
    output.write(f"-- Engine: {connection.settings_dict.get('ENGINE', '')}\n\n")

    if vendor == "mysql":
        output.write("SET FOREIGN_KEY_CHECKS=0;\n")
    elif vendor == "sqlite":
        output.write("PRAGMA foreign_keys=OFF;\n")
    output.write("\n")

    with connection.cursor() as cursor:
        table_names = sorted(connection.introspection.table_names(cursor))
        for table_name in table_names:
            create_statement = _get_create_table_statement(connection, cursor, table_name)
            output.write(f"--\n-- Table structure for {table_name}\n--\n")
            output.write(f"{create_statement};\n\n")

            cursor.execute(f"SELECT * FROM {quote_name(table_name)}")
            columns = [col[0] for col in cursor.description]

            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break

                output.write(f"-- Data for {table_name}\n")
                for row in rows:
                    values_sql = ", ".join(_sql_literal(value) for value in row)
                    columns_sql = ", ".join(quote_name(column) for column in columns)
                    output.write(
                        f"INSERT INTO {quote_name(table_name)} ({columns_sql}) VALUES ({values_sql});\n"
                    )
                output.write("\n")

    if vendor == "mysql":
        output.write("SET FOREIGN_KEY_CHECKS=1;\n")
    elif vendor == "sqlite":
        output.write("PRAGMA foreign_keys=ON;\n")

    return output.getvalue().encode("utf-8")


def _get_create_table_statement(connection, cursor, table_name: str) -> str:
    vendor = connection.vendor
    quoted_table = connection.ops.quote_name(table_name)

    if vendor == "mysql":
        cursor.execute(f"SHOW CREATE TABLE {quoted_table}")
        row = cursor.fetchone()
        return row[1] if row and len(row) > 1 else f"-- Could not extract CREATE TABLE for {table_name}"

    if vendor == "sqlite":
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=%s",
            [table_name],
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else f"-- Could not extract CREATE TABLE for {table_name}"

    return f"-- Schema extraction for vendor '{vendor}' is not implemented; table name: {table_name}"


def _sql_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(value, date):
        return "'" + value.isoformat() + "'"
    if isinstance(value, time):
        return "'" + value.isoformat() + "'"
    if isinstance(value, UUID):
        return "'" + str(value) + "'"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "X'" + bytes(value).hex() + "'"

    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"
