from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.db.models import Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounting.models import (
    Counterparty,
    JournalEntry,
    create_journal_entry,
    ensure_default_accounting_period,
    ensure_default_ledger_accounts,
    get_ledger_account,
)

from .asset_imports import (
    build_asset_import_sample,
    get_asset_import_column_help,
    get_asset_import_formats,
    import_asset_rows,
    infer_asset_import_format,
    parse_asset_import,
)
from .forms import (
    AssetAssignmentForm,
    AssetBulkImportForm,
    AssetCategoryForm,
    AssetDisposalForm,
    AssetItemForm,
    AssetMaintenanceForm,
    DepreciationRunForm,
)
from .models import (
    AssetAssignment,
    AssetCategory,
    AssetDisposal,
    AssetItem,
    AssetMaintenance,
    DepreciationLine,
    DepreciationRun,
)


QUANT = Decimal("0.01")
REQUIRED_ASSET_TABLES = [
    "assets_assetcategory",
    "assets_assetitem",
    "assets_assetassignment",
    "assets_assetmaintenance",
    "assets_depreciationrun",
    "assets_depreciationline",
    "assets_assetdisposal",
]


def _money(value):
    return Decimal(value or Decimal("0.00")).quantize(QUANT)


def _ensure_setup():
    ensure_default_accounting_period()
    ensure_default_ledger_accounts()


def _missing_asset_tables():
    existing_tables = set(connection.introspection.table_names())
    return [table for table in REQUIRED_ASSET_TABLES if table not in existing_tables]


def _render_assets_setup_required(request, missing_tables):
    return render(request, "assets/setup_required.html", {
        "title": "Assets Setup Required",
        "missing_tables": missing_tables,
    })


def _posted_depreciation_up_to(asset, as_of_date):
    total = (
        asset.depreciation_lines.filter(
            run__status="POSTED",
            run__posting_date__lte=as_of_date,
        ).aggregate(total=Sum("depreciation_amount"))["total"] or Decimal("0.00")
    )
    return _money(total)


def _post_asset_acquisition(asset, user):
    if asset.acquisition_entry_id:
        return asset.acquisition_entry
    if not asset.asset_account_id or not asset.funding_account_id:
        raise ValueError("Asset account and funding account are required for capitalization.")

    entry = create_journal_entry(
        entry_date=asset.acquisition_date,
        memo=f"Capitalize asset {asset.asset_code} - {asset.name}",
        lines=[
            {"account": asset.asset_account, "debit": _money(asset.purchase_cost), "credit": Decimal("0.00"), "description": asset.name},
            {"account": asset.funding_account, "debit": Decimal("0.00"), "credit": _money(asset.purchase_cost), "description": asset.vendor.name if asset.vendor_id else "Asset funding"},
        ],
        created_by=user,
        reference=asset.asset_code,
        source_type="ADJUSTMENT",
        source_key=f"asset:{asset.pk}:acquisition",
        source_label=asset.asset_code,
    )
    asset.acquisition_entry = entry
    asset.save(update_fields=["acquisition_entry"])
    return entry


def _post_maintenance(record, user):
    if record.posted_entry_id:
        return record.posted_entry
    if record.status != "COMPLETED" or _money(record.actual_cost) <= 0:
        return None

    expense_account = record.expense_account or record.asset.maintenance_expense_account
    settlement_account = record.settlement_account or record.asset.funding_account
    if not expense_account or not settlement_account:
        raise ValueError("Maintenance posting needs both an expense account and a settlement account.")

    entry = create_journal_entry(
        entry_date=record.completed_on or record.requested_on,
        memo=f"Asset maintenance - {record.asset.asset_code}",
        lines=[
            {"account": expense_account, "debit": _money(record.actual_cost), "credit": Decimal("0.00"), "description": record.description or record.get_maintenance_type_display()},
            {"account": settlement_account, "debit": Decimal("0.00"), "credit": _money(record.actual_cost), "description": record.vendor.name if record.vendor_id else "Maintenance settlement"},
        ],
        created_by=user,
        reference=record.asset.asset_code,
        source_type="ADJUSTMENT",
        source_key=f"asset:{record.asset_id}:maintenance:{record.pk}",
        source_label=record.asset.asset_code,
    )
    record.posted_entry = entry
    record.save(update_fields=["posted_entry"])
    return entry


def _build_depreciation_run(run, user):
    eligible_assets = AssetItem.objects.exclude(status__in=["DRAFT", "DISPOSED", "WRITTEN_OFF"]).order_by("asset_code")
    expense_totals = defaultdict(lambda: Decimal("0.00"))
    accumulated_totals = defaultdict(lambda: Decimal("0.00"))
    lines_payload = []

    for asset in eligible_assets:
        if not asset.in_service_date or asset.in_service_date > run.period_end:
            continue
        theoretical_end = asset.theoretical_accumulated_depreciation_as_of(run.period_end)
        already_posted = _posted_depreciation_up_to(asset, run.period_end)
        due = max(theoretical_end - already_posted, Decimal("0.00")).quantize(QUANT)
        if due <= 0:
            continue

        opening_accumulated = _posted_depreciation_up_to(asset, run.period_start)
        closing_accumulated = _money(already_posted + due)
        closing_book = max(_money(asset.purchase_cost) - closing_accumulated, _money(asset.residual_value))
        lines_payload.append({
            "asset": asset,
            "opening_cost": _money(asset.purchase_cost),
            "opening_accumulated_depreciation": opening_accumulated,
            "depreciation_amount": due,
            "closing_accumulated_depreciation": closing_accumulated,
            "closing_book_value": _money(closing_book),
        })
        expense_totals[asset.depreciation_expense_account] += due
        accumulated_totals[asset.accumulated_depreciation_account] += due

    if not lines_payload:
        raise ValueError("No assets are due for additional depreciation in the selected period.")

    journal_lines = []
    for account, amount in expense_totals.items():
        journal_lines.append({"account": account, "debit": _money(amount), "credit": Decimal("0.00"), "description": f"Depreciation expense - {run.title}"})
    for account, amount in accumulated_totals.items():
        journal_lines.append({"account": account, "debit": Decimal("0.00"), "credit": _money(amount), "description": f"Accumulated depreciation - {run.title}"})

    entry = create_journal_entry(
        entry_date=run.posting_date,
        memo=f"Asset depreciation - {run.title}",
        lines=journal_lines,
        created_by=user,
        reference=run.title,
        source_type="ADJUSTMENT",
        source_key=f"asset:depreciation:{run.pk}",
        source_label=run.title,
    )

    for payload in lines_payload:
        DepreciationLine.objects.create(run=run, **payload)

    run.posted_entry = entry
    run.status = "POSTED"
    run.save(update_fields=["posted_entry", "status"])
    return entry


def _post_disposal(disposal, user):
    if disposal.posted_entry_id:
        return disposal.posted_entry

    asset = disposal.asset
    accumulated = asset.posted_accumulated_depreciation
    proceeds = _money(disposal.proceeds)
    selling_cost = _money(disposal.selling_cost)
    settlement_account = disposal.settlement_account or asset.funding_account
    gain_account = disposal.gain_account or get_ledger_account("4091")
    loss_account = disposal.loss_account or get_ledger_account("5093")
    if not settlement_account:
        raise ValueError("A settlement account is required for disposal posting.")
    if not gain_account or not loss_account:
        raise ValueError("Gain and loss ledger accounts must exist before posting disposal.")

    debit_total = Decimal("0.00")
    credit_total = Decimal("0.00")
    lines = []

    if proceeds > 0:
        lines.append({"account": settlement_account, "debit": proceeds, "credit": Decimal("0.00"), "description": f"Proceeds on disposal of {asset.asset_code}"})
        debit_total += proceeds
    if accumulated > 0:
        lines.append({"account": asset.accumulated_depreciation_account, "debit": accumulated, "credit": Decimal("0.00"), "description": f"Reverse accumulated depreciation for {asset.asset_code}"})
        debit_total += accumulated
    if selling_cost > 0:
        lines.append({"account": settlement_account, "debit": Decimal("0.00"), "credit": selling_cost, "description": f"Selling cost for {asset.asset_code}"})
        credit_total += selling_cost

    asset_cost = _money(asset.purchase_cost)
    lines.append({"account": asset.asset_account, "debit": Decimal("0.00"), "credit": asset_cost, "description": f"Remove asset cost for {asset.asset_code}"})
    credit_total += asset_cost

    difference = _money(debit_total - credit_total)
    if difference > 0:
        lines.append({"account": gain_account, "debit": Decimal("0.00"), "credit": difference, "description": f"Gain on disposal of {asset.asset_code}"})
    elif difference < 0:
        lines.append({"account": loss_account, "debit": abs(difference), "credit": Decimal("0.00"), "description": f"Loss on disposal of {asset.asset_code}"})

    entry = create_journal_entry(
        entry_date=disposal.disposal_date,
        memo=f"Asset disposal - {asset.asset_code}",
        lines=lines,
        created_by=user,
        reference=asset.asset_code,
        source_type="ADJUSTMENT",
        source_key=f"asset:{asset.pk}:disposal",
        source_label=asset.asset_code,
    )
    disposal.posted_entry = entry
    disposal.save(update_fields=["posted_entry"])
    asset.status = "WRITTEN_OFF" if disposal.disposal_type in {"WRITE_OFF", "LOSS", "DONATION"} else "DISPOSED"
    asset.save(update_fields=["status"])
    return entry


@staff_member_required
def assets_hub(request):
    missing_tables = _missing_asset_tables()
    if missing_tables:
        return _render_assets_setup_required(request, missing_tables)

    _ensure_setup()

    active_tab = request.GET.get("tab", "overview")

    category_form = AssetCategoryForm(prefix="category")
    asset_form = AssetItemForm(prefix="asset")
    assignment_form = AssetAssignmentForm(prefix="assignment")
    maintenance_form = AssetMaintenanceForm(prefix="maintenance")
    depreciation_form = DepreciationRunForm(
        prefix="depreciation",
        initial={"posting_date": timezone.localdate()},
    )
    disposal_form = AssetDisposalForm(prefix="disposal")

    if request.method == "POST":
        if "create_category" in request.POST:
            active_tab = "register"
            category_form = AssetCategoryForm(request.POST, prefix="category")
            if category_form.is_valid():
                category_form.save()
                messages.success(request, "Asset category saved successfully.")
                return redirect("assets:hub")

        elif "create_asset" in request.POST:
            active_tab = "register"
            asset_form = AssetItemForm(request.POST, prefix="asset")
            if asset_form.is_valid():
                asset = asset_form.save(commit=False)
                asset.created_by = request.user
                asset.save()
                if asset_form.cleaned_data.get("post_acquisition", True) and not asset.acquisition_entry_id:
                    try:
                        _post_asset_acquisition(asset, request.user)
                        messages.success(request, f"Asset {asset.asset_code} saved and capitalized into accounting.")
                    except Exception as exc:
                        messages.warning(request, f"Asset saved, but acquisition was not posted to accounting: {exc}")
                else:
                    messages.success(request, f"Asset {asset.asset_code} saved successfully.")
                return redirect("assets:hub")

        elif "create_assignment" in request.POST:
            active_tab = "care"
            assignment_form = AssetAssignmentForm(request.POST, prefix="assignment")
            if assignment_form.is_valid():
                assignment = assignment_form.save()
                asset = assignment.asset
                if assignment.assigned_to_id:
                    asset.custodian = assignment.assigned_to
                if assignment.location:
                    asset.location = assignment.location
                asset.save(update_fields=["custodian", "location"])
                messages.success(request, f"Assignment recorded for {asset.asset_code}.")
                return redirect("assets:hub")

        elif "create_maintenance" in request.POST:
            active_tab = "care"
            maintenance_form = AssetMaintenanceForm(request.POST, prefix="maintenance")
            if maintenance_form.is_valid():
                record = maintenance_form.save(commit=False)
                record.created_by = request.user
                record.save()
                asset = record.asset
                if record.status == "COMPLETED":
                    asset.status = "ACTIVE"
                    asset.save(update_fields=["status"])
                elif record.status in {"SCHEDULED", "IN_PROGRESS"}:
                    asset.status = "IN_MAINTENANCE"
                    asset.save(update_fields=["status"])
                if maintenance_form.cleaned_data.get("post_maintenance", True):
                    try:
                        _post_maintenance(record, request.user)
                    except Exception as exc:
                        messages.warning(request, f"Maintenance saved, but accounting posting was skipped: {exc}")
                messages.success(request, f"Maintenance record saved for {asset.asset_code}.")
                return redirect("assets:hub")

        elif "create_depreciation_run" in request.POST:
            active_tab = "depreciation"
            depreciation_form = DepreciationRunForm(request.POST, prefix="depreciation")
            if depreciation_form.is_valid():
                run = depreciation_form.save(commit=False)
                run.created_by = request.user
                run.save()
                try:
                    _build_depreciation_run(run, request.user)
                    messages.success(request, f"Depreciation run '{run.title}' posted successfully.")
                    return redirect("assets:hub")
                except Exception as exc:
                    run.delete()
                    messages.error(request, f"Could not post depreciation run: {exc}")

        elif "create_disposal" in request.POST:
            active_tab = "depreciation"
            disposal_form = AssetDisposalForm(request.POST, prefix="disposal")
            if disposal_form.is_valid():
                disposal = disposal_form.save(commit=False)
                disposal.created_by = request.user
                disposal.save()
                try:
                    _post_disposal(disposal, request.user)
                    messages.success(request, f"Asset {disposal.asset.asset_code} disposed and posted to accounting.")
                    return redirect("assets:hub")
                except Exception as exc:
                    disposal.delete()
                    messages.error(request, f"Could not post asset disposal: {exc}")

    today = timezone.localdate()
    categories = AssetCategory.objects.order_by("name")
    assets = AssetItem.objects.select_related("category", "custodian", "vendor").order_by("asset_code")
    recent_assets = assets[:12]
    assignments = AssetAssignment.objects.select_related("asset", "assigned_to").order_by("-assigned_date", "-created_at")[:12]
    maintenance_records = AssetMaintenance.objects.select_related("asset", "assigned_to", "vendor").order_by("-requested_on", "-created_at")[:12]
    depreciation_runs = DepreciationRun.objects.prefetch_related("lines__asset").order_by("-posting_date", "-created_at")[:10]
    disposals = AssetDisposal.objects.select_related("asset").order_by("-disposal_date", "-created_at")[:10]

    active_assets = [asset for asset in assets if asset.status == "ACTIVE"]
    disposed_assets = [asset for asset in assets if asset.status in {"DISPOSED", "WRITTEN_OFF"}]
    maintenance_due = AssetMaintenance.objects.filter(status__in=["SCHEDULED", "IN_PROGRESS"]).count()
    overdue_maintenance = AssetMaintenance.objects.filter(status="SCHEDULED", scheduled_for__lt=today).count()

    total_cost = _money(sum((asset.purchase_cost for asset in assets), Decimal("0.00")))
    accumulated_depreciation = _money(sum((asset.posted_accumulated_depreciation for asset in assets), Decimal("0.00")))
    net_book_value = _money(sum((asset.net_book_value for asset in assets), Decimal("0.00")))
    depreciation_due_total = _money(sum((asset.depreciation_due for asset in assets if asset.status not in {"DISPOSED", "WRITTEN_OFF"}), Decimal("0.00")))
    maintenance_cost_total = _money(sum((asset.total_maintenance_cost for asset in assets), Decimal("0.00")))

    category_breakdown = []
    for category in categories:
        cat_assets = list(category.assets.all())
        category_breakdown.append({
            "category": category,
            "count": len(cat_assets),
            "cost": _money(sum((asset.purchase_cost for asset in cat_assets), Decimal("0.00"))),
            "book_value": _money(sum((asset.net_book_value for asset in cat_assets), Decimal("0.00"))),
        })

    accounting_links = [
        {"label": "Fixed Asset Ledger", "account": get_ledger_account("1500")},
        {"label": "Accumulated Depreciation", "account": get_ledger_account("1590")},
        {"label": "Depreciation Expense", "account": get_ledger_account("5091")},
        {"label": "Maintenance Expense", "account": get_ledger_account("5092")},
        {"label": "Gain On Disposal", "account": get_ledger_account("4091")},
        {"label": "Loss On Disposal", "account": get_ledger_account("5093")},
    ]

    context = {
        "title": "Assets & Fixed Asset Control",
        "active_tab": active_tab,
        "category_form": category_form,
        "asset_form": asset_form,
        "assignment_form": assignment_form,
        "maintenance_form": maintenance_form,
        "depreciation_form": depreciation_form,
        "disposal_form": disposal_form,
        "categories": categories,
        "assets": recent_assets,
        "assignments": assignments,
        "maintenance_records": maintenance_records,
        "depreciation_runs": depreciation_runs,
        "disposals": disposals,
        "category_breakdown": category_breakdown,
        "asset_count": assets.count(),
        "active_asset_count": len(active_assets),
        "disposed_asset_count": len(disposed_assets),
        "maintenance_due": maintenance_due,
        "overdue_maintenance": overdue_maintenance,
        "total_cost": total_cost,
        "accumulated_depreciation": accumulated_depreciation,
        "net_book_value": net_book_value,
        "depreciation_due_total": depreciation_due_total,
        "maintenance_cost_total": maintenance_cost_total,
        "accounting_links": accounting_links,
        "counterparties": Counterparty.objects.filter(is_active=True).order_by("name")[:10],
    }
    return render(request, "assets/hub.html", context)


@staff_member_required
def asset_bulk_import(request):
    missing_tables = _missing_asset_tables()
    if missing_tables:
        return _render_assets_setup_required(request, missing_tables)

    _ensure_setup()
    form = AssetBulkImportForm(request.POST or None, request.FILES or None)
    import_result = None

    if request.method == "POST" and form.is_valid():
        uploaded_file = form.cleaned_data["data_file"]
        selected_type = form.cleaned_data["file_type"]
        import_mode = form.cleaned_data["import_mode"]
        post_acquisitions = form.cleaned_data["post_acquisitions"]

        file_type = selected_type
        if selected_type == "auto":
            file_type = infer_asset_import_format(uploaded_file.name)
            if not file_type:
                form.add_error(
                    "data_file",
                    "Could not infer the file type. Choose CSV, Excel, JSON, or XML explicitly.",
                )

        if file_type and not form.errors:
            try:
                rows = parse_asset_import(uploaded_file, file_type)
                import_result = import_asset_rows(
                    rows,
                    import_mode=import_mode,
                    post_acquisitions=post_acquisitions,
                    acquisition_hook=_post_asset_acquisition,
                    user=request.user,
                )
                if import_result["errors"]:
                    messages.warning(
                        request,
                        f"Bulk import completed: {import_result['created']} created, "
                        f"{import_result['updated']} updated, {len(import_result['errors'])} failed.",
                    )
                else:
                    messages.success(
                        request,
                        f"Bulk import completed successfully: {import_result['created']} created"
                        + (f", {import_result['updated']} updated." if import_result["updated"] else ".")
                    )
            except Exception as exc:
                form.add_error("data_file", str(exc))

    return render(
        request,
        "assets/asset_bulk_import.html",
        {
            "title": "Bulk Import Assets",
            "form": form,
            "format_options": get_asset_import_formats(),
            "column_help": get_asset_import_column_help(),
            "import_result": import_result,
        },
    )


@staff_member_required
def asset_bulk_import_sample(request, file_type):
    supported = {item["slug"] for item in get_asset_import_formats()}
    if file_type not in supported:
        raise Http404("Unsupported sample file type.")

    filename, content_type, payload = build_asset_import_sample(file_type)
    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@staff_member_required
def asset_detail(request, pk):
    missing_tables = _missing_asset_tables()
    if missing_tables:
        return _render_assets_setup_required(request, missing_tables)

    asset = get_object_or_404(
        AssetItem.objects.select_related(
            "category",
            "custodian",
            "vendor",
            "asset_account",
            "accumulated_depreciation_account",
            "depreciation_expense_account",
            "maintenance_expense_account",
            "funding_account",
            "acquisition_entry",
        ).prefetch_related(
            "assignments__assigned_to",
            "maintenance_records__assigned_to",
            "maintenance_records__vendor",
            "depreciation_lines__run",
        ),
        pk=pk,
    )
    return render(request, "assets/detail.html", {
        "title": f"Asset {asset.asset_code}",
        "asset": asset,
    })
