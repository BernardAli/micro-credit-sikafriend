"""Build the complete handbook offline, without reading installation/customer data.

Run from the project root with the project's virtual environment:
    .venv/bin/python docs/manuals/build_complete_manual.py --refresh-reference
    .venv/bin/python docs/manuals/build_complete_manual.py
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REFERENCE = HERE / "project_reference.json"
PDF_NAME = "SikaFriend_Complete_Project_Manual.pdf"


def refresh_reference():
    # Environment overrides prevent .env from selecting the live database.
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings", DB_ENGINE="sqlite",
                      SQLITE_NAME=":memory:", DJANGO_DEBUG="False")
    sys.path.insert(0, str(ROOT))
    from django.db.backends.base.base import BaseDatabaseWrapper

    def forbid_connection(self):
        raise RuntimeError("Documentation reference generation must never access a database.")

    BaseDatabaseWrapper.ensure_connection = forbid_connection
    import django
    django.setup()
    from django.apps import apps
    from django.urls import URLResolver, get_resolver
    from apps.loans.reports import REPORT_CATALOG
    from apps.loans.borrower_imports import BORROWER_SAMPLE_COLUMNS, get_borrower_import_column_help
    from apps.loans.loan_imports import LOAN_SAMPLE_COLUMNS, get_loan_import_column_help
    from apps.accounts.agent_imports import AGENT_SAMPLE_COLUMNS, get_agent_import_column_help
    from apps.assets.asset_imports import ASSET_SAMPLE_COLUMNS, get_asset_import_column_help

    models = []
    for model in sorted(apps.get_models(), key=lambda m: m._meta.label):
        if not model.__module__.startswith("apps."):
            continue
        fields = []
        for field in model._meta.local_fields + model._meta.local_many_to_many:
            notes = []
            if field.primary_key:
                notes.append("Primary key")
            elif field.unique:
                notes.append("Unique")
            if getattr(field, "max_length", None):
                notes.append(f"Maximum {field.max_length} characters")
            if hasattr(field, "decimal_places"):
                notes.append(f"{field.max_digits} digits; {field.decimal_places} decimal places")
            if field.is_relation:
                notes.append(f"Links to {field.related_model._meta.label}")
                on_delete = getattr(field.remote_field, "on_delete", None)
                if on_delete:
                    notes.append(f"Deletion: {on_delete.__name__}")
            if field.choices:
                notes.append("Choices: " + "; ".join(f"{key} = {value}" for key, value in field.flatchoices))
            if field.help_text:
                notes.append(str(field.help_text))
            if getattr(field, "auto_now_add", False):
                notes.append("Set when created")
            if getattr(field, "auto_now", False):
                notes.append("Updated automatically")
            fields.append({"name": field.name, "label": str(field.verbose_name),
                           "type": field.get_internal_type(), "nullable": field.null,
                           "blank": field.blank, "notes": ". ".join(notes)})
        models.append({"label": model._meta.label, "table": model._meta.db_table,
                       "fields": fields,
                       "constraints": [constraint.name for constraint in model._meta.constraints]})

    routes = []
    def walk(patterns, prefix="", namespace=""):
        for entry in patterns:
            route = prefix + str(entry.pattern)
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, route, namespace + (entry.namespace + ":" if entry.namespace else ""))
            elif not route.startswith(("admin/", "static/", "__debug__/")):
                callback = entry.callback
                routes.append({"route": "/" + route, "name": namespace + (entry.name or ""),
                               "view": callback.__module__ + "." + callback.__name__})
    walk(get_resolver().url_patterns)
    ref = {"documentation_date": "2026-10-12", "models": models, "routes": routes,
           "reports": REPORT_CATALOG,
           "import_columns": {"Borrowers": BORROWER_SAMPLE_COLUMNS, "Loans": LOAN_SAMPLE_COLUMNS,
                              "Workforce": AGENT_SAMPLE_COLUMNS, "Assets": ASSET_SAMPLE_COLUMNS},
           "import_help": {"Borrowers": get_borrower_import_column_help(),
                           "Loans": get_loan_import_column_help(),
                           "Workforce": get_agent_import_column_help(),
                           "Assets": get_asset_import_column_help()}}
    REFERENCE.write_text(json.dumps(ref, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def esc(value):
    return html.escape(str(value))


def table(headings, rows, css=""):
    return '<table class="' + css + '"><thead><tr>' + ''.join(f"<th>{esc(h)}</th>" for h in headings) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f"<td>{cell}</td>" for cell in row) + '</tr>' for row in rows) + '</tbody></table>'


def references(ref):
    data = []
    for model in ref["models"]:
        data.append(f'<h2>{esc(model["label"])}</h2><p class="reference-intro">Database table: <code>{esc(model["table"])}</code>. {len(model["fields"])} fields.</p>')
        rows = []
        for f in model["fields"]:
            optional = "Nullable" if f["nullable"] else "Non-null"
            optional += "; blank allowed" if f["blank"] else "; form value required"
            rows.append([f'<code>{esc(f["name"])}</code>', esc(f["type"]), esc(optional), esc(f["notes"] or f["label"])])
        data.append(table(["Field", "Storage type", "Model flags", "Definition / rules"], rows, "dictionary"))
        if model["constraints"]:
            data.append('<p class="small">Named database constraints: ' + ', '.join(f'<code>{esc(c)}</code>' for c in model["constraints"]) + '.</p>')
    routes = table(["Path", "Django route name"], [[f'<code>{esc(r["route"])}</code>', f'<code>{esc(r["name"])}</code>'] for r in ref["routes"]], "routes")
    reports = table(["Report", "Purpose"], [[esc(r["title"]), esc(r["description"])] for r in ref["reports"]])
    imports = []
    for name, columns in ref["import_columns"].items():
        imports.append(f'<h2>{esc(name)} sample columns</h2><p class="column-list">' + ', '.join(f'<code>{esc(c)}</code>' for c in columns) + '</p>')
        rows = [[f'<code>{esc(f["name"])}</code>', "Yes" if f["required"] else "No", esc(f["help"])] for f in ref["import_help"][name]]
        imports.append(table(["Column", "Required", "Module guidance"], rows, "import-help"))
    return {"DATA_DICTIONARY": ''.join(data), "ROUTE_REFERENCE": routes,
            "REPORT_CATALOG": reports, "IMPORT_COLUMNS": ''.join(imports)}


class OutlineParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chapters = []
        self.section_id = None
        self.heading = False
        self.parts = []
        self.ids = set()
        self.links = []
        self.all_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            if attrs["id"] in self.ids:
                raise ValueError(f'Duplicate document ID: {attrs["id"]}')
            self.ids.add(attrs["id"])
        if tag == "section" and "chapter" in attrs.get("class", "").split():
            self.section_id = attrs["id"]
        if tag == "h1":
            self.heading = True
            self.parts = []
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.links.append(attrs["href"][1:])

    def handle_data(self, text):
        self.all_text.append(text)
        if self.heading:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if tag == "h1" and self.heading:
            self.chapters.append((self.section_id, ''.join(self.parts).strip()))
            self.heading = False


def illustrate(content):
    """Embed captured sample screenshots; preserve offline, data-only rendering."""
    manifest_path = HERE / "manual_illustrations.json"
    if not manifest_path.exists():
        return content, 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = {}
    chapter_order = {chapter: index for index, chapter in enumerate(re.findall(r'<section class="chapter" id="([^"]+)">', content))}
    ordered = sorted(manifest["illustrations"], key=lambda item: chapter_order.get(item["chapter"], 999))
    for number, item in enumerate(ordered, start=1):
        path = (HERE / item["image"]).resolve()
        if not path.is_relative_to(HERE / "images") or not path.is_file():
            raise ValueError("Screenshot must be a local documentation image.")
        data = base64.b64encode(path.read_bytes()).decode()
        figure = f'<figure class="manual-figure"><div class="figure-title">Figure {number:02d} · {esc(item["title"])}</div><img src="data:image/jpeg;base64,{data}" alt="{esc(item["title"])} — fictional documentation records"><figcaption>{esc(item["caption"])} <span class="sample-label">Illustrative sample data.</span></figcaption></figure>'
        groups.setdefault(item["chapter"], []).append(figure)

    def add(match):
        chapter, body = match.group(1), match.group(2)
        figures = groups.pop(chapter, [])
        if figures:
            body += '<div class="illustrations"><h2>Illustrated walkthrough</h2><p class="small">Screenshots use the current project templates in an isolated training environment. Names, contacts, balances and employee records are fictional.</p>' + ''.join(figures) + '</div>'
        return f'<section class="chapter" id="{chapter}">{body}</section>'

    content = re.sub(r'<section class="chapter" id="([^"]+)">(.*?)</section>', add, content, flags=re.S)
    if groups:
        raise ValueError(f"Unknown screenshot chapter: {list(groups)}")
    return content, len(manifest["illustrations"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-reference", action="store_true")
    args = parser.parse_args()
    if args.refresh_reference or not REFERENCE.exists():
        refresh_reference()
    ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
    content = (HERE / "complete_manual_content.html").read_text(encoding="utf-8")
    for key, value in references(ref).items():
        content = content.replace("{{" + key + "}}", value)
    content, illustration_count = illustrate(content)
    if re.search(r"\{\{\w+\}\}", content):
        raise ValueError("Unexpanded handbook placeholder")
    outline = OutlineParser()
    outline.feed(content)
    if missing := set(outline.links) - outline.ids:
        raise ValueError(f"Broken internal links: {missing}")
    toc = '<ol class="toc">' + ''.join(f'<li><a href="#{esc(key)}">{esc(title)}</a></li>' for key, title in outline.chapters) + '</ol>'
    logo_file = ROOT / "static/website/images/sikafriend-logo.webp"
    logo = f'<img class="cover-logo" alt="SikaFriend" src="data:image/webp;base64,{base64.b64encode(logo_file.read_bytes()).decode()}">' if logo_file.exists() else '<p class="brand">SIKAFRIEND</p>'
    photo_file = ROOT / "static/website/images/microcredit-hero-office.webp"
    cover_photo = f'<img class="cover-photo" alt="Existing project office illustration" src="data:image/webp;base64,{base64.b64encode(photo_file.read_bytes()).decode()}">' if photo_file.exists() else ''
    css = (HERE / "complete_manual.css").read_text(encoding="utf-8")
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>SikaFriend Complete Project Manual</title><meta name="author" content="SikaFriend Micro-Credit Enterprise"><meta name="description" content="Comprehensive operations, governance, administration, deployment and developer handbook for the standalone ERP. Edition 12 October 2026."><style>{css}</style></head><body>
<section class="cover">{cover_photo}{logo}<p class="eyebrow">STANDALONE MICRO-CREDIT ERP</p><h1>Complete<br>Project Manual</h1><p class="cover-subtitle">Operations · Governance · Administration<br>Deployment · Recovery · Developer Reference</p><div class="cover-rule"></div><p class="cover-edition">Illustrated edition · 12 October 2026<br>Prepared from the local project source</p><p class="cover-caption">A practical handbook for management, administrators,<br>portfolio officers, borrowers and technical maintainers.</p></section>
<section class="contents"><h1>Contents</h1><p>Click a chapter title to open it. PDF bookmarks provide a second navigation panel. Page numbers refer to this complete handbook.</p>{toc}</section>{content}</body></html>'''
    html_path = HERE / "SikaFriend_Complete_Project_Manual.html"
    html_path.write_text(document, encoding="utf-8")
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher
    embedded_only = URLFetcher(allowed_protocols={"data"}, allow_redirects=False)

    rendered = HTML(string=document, url_fetcher=embedded_only).render()
    pdf_path = HERE / PDF_NAME
    rendered.write_pdf(pdf_path, pdf_tags=True)
    chapter_pages = {}
    for number, page in enumerate(rendered.pages, start=1):
        for key in page.anchors:
            chapter_pages.setdefault(key, number)
    manifest = {"title": "SikaFriend Complete Project Manual", "edition": "1.0",
                "date": "2026-10-12", "pages": len(rendered.pages),
                "chapters_and_appendices": len(outline.chapters),
                "approximate_words": len(' '.join(outline.all_text).split()),
                "models": len(ref["models"]), "fields": sum(len(m["fields"]) for m in ref["models"]),
                "routes": len(ref["routes"]), "reports": len(ref["reports"]),
                "screenshots": illustration_count,
                "brand_colors": {"primary": "#e60046", "accent": "#c6009f", "dark": "#160d15"},
                "pdf_bytes": pdf_path.stat().st_size,
                "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
                "chapters": [{"id": key, "title": title, "page": chapter_pages[key]}
                             for key, title in outline.chapters]}
    (HERE / "complete_manual_build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: val for key, val in manifest.items() if key != "chapters"}, indent=2))


if __name__ == "__main__":
    main()
