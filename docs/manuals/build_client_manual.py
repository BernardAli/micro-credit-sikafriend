"""Build the client handover edition from its curated operating guide and pictures.

Run from the project root:
    .venv/bin/python docs/manuals/build_client_manual.py

This builder does not initialize the application or access a database.
"""
import base64
import hashlib
import json
from pathlib import Path
import re

from build_complete_manual import OutlineParser, esc, table

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TITLE = "SikaFriend Client User Manual"
STEM = "SikaFriend_Client_User_Manual"


def embedded_image(path, mime):
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def add_pictures(content):
    source = json.loads((HERE / "manual_illustrations.json").read_text())
    chapters = re.findall(r'<section class="chapter" id="([^"]+)">', content)
    order = {chapter: index for index, chapter in enumerate(chapters)}
    # The technical backup screen shows installation details and is excluded.
    pictures = [item for item in source["illustrations"] if item["chapter"] in order]
    pictures.sort(key=lambda item: order[item["chapter"]])
    caption_changes = {
        "loan-requests": "A submitted application waits for review. Confirm approval and the resulting loan before proceeding.",
        "reversal-pending": "A different active administrator reviews the original receipt, proposed offsets and supporting evidence.",
        "reversal-completed": "The completed case retains its permanent reference, original transaction and decision history.",
        "reversal-offsets": "Use the completed case to review linked offset entries and the original transaction details.",
        "journal-detail": "Inspect the posted entry and supporting reference. Correct an operational entry through its original business transaction.",
        "held-credit-statement": "This sample loan is fully settled. GHS 60 remains held for the customer and is shown separately from repayment.",
        "operations-settings": "Review approved lending defaults and payroll values before using them for a new agreement or pay period.",
    }
    groups = {}
    for number, item in enumerate(pictures, 1):
        path = (HERE / item["image"]).resolve()
        if not path.is_relative_to(HERE / "images") or not path.is_file():
            raise ValueError("Illustrations must be stored in the manual image directory.")
        caption = caption_changes.get(item["id"], item["caption"])
        groups.setdefault(item["chapter"], []).append(
            f'<figure class="manual-figure"><div class="figure-title">Figure {number:02d} · {esc(item["title"])}</div>'
            f'<img src="{embedded_image(path, "image/jpeg")}" alt="{esc(item["title"])} — sample account details">'
            f'<figcaption>{esc(caption)} <span class="sample-label">Example screen.</span></figcaption></figure>'
        )

    def insert(match):
        chapter, body = match.group(1), match.group(2)
        if chapter in groups:
            body += '<div class="illustrations"><h2>Screen guide</h2>' + ''.join(groups.pop(chapter)) + '</div>'
        return f'<section class="chapter" id="{chapter}">{body}</section>'

    result = re.sub(r'<section class="chapter" id="([^"]+)">(.*?)</section>', insert, content, flags=re.S)
    assert not groups
    return result, len(pictures)


def main():
    content = (HERE / "client_manual_content.html").read_text()
    reports = json.loads((HERE / "project_reference.json").read_text())["reports"]
    catalog = table(["Report", "Use"], [[esc(item["title"]), esc(item["description"])] for item in reports])
    content = content.replace("{{REPORT_CATALOG}}", catalog)
    content, picture_count = add_pictures(content)
    assert not re.search(r"\{\{\w+\}\}", content)
    outline = OutlineParser()
    outline.feed(content)
    if missing := set(outline.links) - outline.ids:
        raise ValueError(f"Broken internal links: {missing}")
    # Keep internal engineering/installation detail out of this deliverable.
    plain = ' '.join(outline.all_text)
    forbidden = [r"Django", r"PythonAnywhere", r"SQLite", r"MySQL", r"SECRET_KEY", r"\.env\b",
                 r"127\.0\.0\.1", r"localhost", r"manage\.py", r"apps/", r"config/", r"docs/manuals",
                 r"repair_payment_allocations", r"source code", r"developer", r"database schema",
                 r"Loan\s*#?\s*(?:1688|2058|2683|2693|3084)\b"]
    for pattern in forbidden:
        if re.search(pattern, plain, re.I):
            raise ValueError(f"Internal content in client manual: {pattern}")
    css = (HERE / "complete_manual.css").read_text().replace("PROJECT MANUAL", "USER GUIDE")
    css += '\n.cover h1 { font-size: 38pt; }\n.cover .eyebrow { letter-spacing: 1.4pt; }\n'
    toc = '<ol class="toc">' + ''.join(f'<li><a href="#{esc(key)}">{esc(title)}</a></li>' for key, title in outline.chapters) + '</ol>'
    logo = embedded_image(ROOT / "static/website/images/sikafriend-logo.webp", "image/webp")
    photo = embedded_image(ROOT / "static/website/images/microcredit-hero-office.webp", "image/webp")
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{TITLE}</title>
<meta name="author" content="SikaFriend Micro-Credit Enterprise"><meta name="description" content="Illustrated client user guide for lending, repayments, approvals, statements, reporting and everyday administration. October 2026.">
<style>{css}</style></head><body>
<section class="cover"><img class="cover-photo" src="{photo}" alt="SikaFriend service illustration"><img class="cover-logo" src="{logo}" alt="SikaFriend Micro-Credit Enterprise">
<p class="eyebrow">SIKAFRIEND MICRO-CREDIT ENTERPRISE</p><h1>Operations &amp;<br>User Guide</h1><p class="cover-subtitle">Lending · Repayments · Statements<br>Approvals · Reporting · Administration</p><div class="cover-rule"></div><p class="cover-edition">Client edition · October 2026</p><p class="cover-caption">A practical guide for management, finance,<br>portfolio officers, administrators and borrowers.</p></section>
<section class="contents"><h1>Contents</h1><p>Select a chapter to open it. The PDF bookmarks provide quick access to individual topics.</p>{toc}</section>{content}</body></html>'''
    (HERE / f"{STEM}.html").write_text(document)
    from weasyprint import HTML, default_url_fetcher

    def embedded_only(url):
        if not url.startswith("data:"):
            raise ValueError("Client manual resources must be embedded.")
        return default_url_fetcher(url)

    rendered = HTML(string=document, url_fetcher=embedded_only).render()
    path = HERE / f"{STEM}.pdf"
    rendered.write_pdf(path, pdf_tags=True)
    anchors = {}
    for number, page in enumerate(rendered.pages, 1):
        for key in page.anchors:
            anchors.setdefault(key, number)
    manifest = {"title": TITLE, "audience": "Client operations and end users", "edition": "1.0",
                "date": "2026-10-12", "pages": len(rendered.pages), "screenshots": picture_count,
                "chapters_and_appendices": len(outline.chapters), "approximate_words": len(plain.split()),
                "pdf_bytes": path.stat().st_size, "pdf_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "chapters": [{"id": key, "title": title, "page": anchors[key]} for key, title in outline.chapters]}
    (HERE / "client_manual_build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: value for key, value in manifest.items() if key != "chapters"}, indent=2))


if __name__ == "__main__":
    main()
