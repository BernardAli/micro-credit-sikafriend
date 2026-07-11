import logging

from django.core.cache import cache
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import connections
from django.shortcuts import render, redirect
from django.utils.text import slugify

from apps.core.db_backups import (
    BACKUP_FORMATS,
    build_backup_filename,
    export_database_backup,
    get_database_overview,
    resolve_database_alias,
)
from .forms import CompanyDocumentFormSet, CompanyProfileForm
from .models import CompanyDocument, CompanyProfile


logger = logging.getLogger(__name__)
CONTACT_RATE_LIMIT = 5
CONTACT_RATE_WINDOW = 15 * 60


def _contact_client_ip(request):
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _contact_rate_limited(request):
    key = f"website-contact:{_contact_client_ip(request)}"
    if cache.add(key, 1, CONTACT_RATE_WINDOW):
        return False
    try:
        return cache.incr(key) > CONTACT_RATE_LIMIT
    except ValueError:
        cache.set(key, 1, CONTACT_RATE_WINDOW)
        return False


def _match_service_blueprint(title):
    name = (title or "").strip().lower()
    checks = [
        ("personal", "personal-loans"),
        ("business", "business-loans"),
        ("group", "group-loans"),
        ("cooperative", "group-loans"),
        ("asset", "asset-finance"),
        ("equipment", "asset-finance"),
        ("vehicle", "asset-finance"),
        ("emergency", "emergency-loans"),
        ("quick", "emergency-loans"),
        ("salary", "emergency-loans"),
        ("education", "education-loans"),
        ("school", "education-loans"),
        ("training", "education-loans"),
    ]
    for needle, key in checks:
        if needle in name:
            return key
    return "general-credit"


def _service_blueprints(profile):
    cycle_label = profile.get_repayment_cycle_display()
    repayment_period = profile.repayment_unit
    duration = profile.default_loan_duration
    grace_periods = profile.overdue_grace_periods
    company_name = profile.company_name

    common_journey = [
        {
            "title": "Initial Discussion",
            "description": "Speak with our team about your need, target amount, repayment comfort level, and preferred disbursement timeline.",
        },
        {
            "title": "Application Review",
            "description": "We verify identity, income or business activity, and match you to the most responsible solution and loan tier.",
        },
        {
            "title": "Approval & Offer",
            "description": f"You receive clear repayment terms, expected {cycle_label.lower()} instalments, and your total repayment before you commit.",
        },
        {
            "title": "Disbursement & Follow-Up",
            "description": "Funds are released and your assigned team member stays available for repayment reminders, top-up planning, and account support.",
        },
    ]

    return {
        "personal-loans": {
            "badge": "Everyday Finance",
            "headline": "Personal loans built for urgent needs and steady progress",
            "detail_intro": "Cover medical bills, rent pressure, school supplies, family obligations, or working-capital gaps without navigating a complicated lending process.",
            "audience_label": "Ideal for salary earners, traders, artisans, and returning borrowers who need flexible support.",
            "best_for": [
                "Medical emergencies and family obligations",
                "Household stabilization during short-term cash gaps",
                "Lifestyle upgrades with clear repayment planning",
                "Repeat borrowers building eligibility for bigger facilities",
            ],
            "feature_points": [
                "Simple application flow with fast review",
                f"Structured {cycle_label.lower()} repayments for easier budgeting",
                "Suitable for both new and returning clients",
                "Top-up path available after good repayment performance",
            ],
            "documents": [
                "Valid national ID or government-issued identification",
                "Proof of income, salary flow, or business activity",
                "Active phone number and reachable address",
                "Recent photo and basic guarantor or referee details where required",
            ],
            "support_items": [
                "Pre-disbursement affordability check",
                "Borrower portal visibility for balances and schedules",
                f"Early support before accounts move beyond {grace_periods} missed periods",
                "Guidance on when to move into higher tiers responsibly",
            ],
            "use_cases": [
                "Bridge expenses while waiting for salary or receivables",
                "Fund family milestones without selling productive assets",
                "Handle urgent needs while keeping your business running",
            ],
            "related_keys": ["emergency-loans", "education-loans", "business-loans"],
            "cta_title": "Need a personal loan that stays manageable?",
            "cta_body": f"{company_name} can help you choose the right amount, the right tenure, and a repayment plan that fits your real cash flow.",
            "journey": common_journey,
        },
        "business-loans": {
            "badge": "Growth Capital",
            "headline": "Business loans for stock, expansion, and stronger daily cash flow",
            "detail_intro": "Strengthen inventory, buy in bulk, increase production capacity, or smooth out seasonal cash swings with lending designed around real business cycles.",
            "audience_label": "Designed for SMEs, traders, service providers, and growth-focused entrepreneurs.",
            "best_for": [
                "Inventory purchases and bulk stock opportunities",
                "Seasonal demand spikes and festive trading cycles",
                "Working capital to support receivables and payroll timing",
                "Expansion into new locations, equipment, or product lines",
            ],
            "feature_points": [
                "Facility sizing based on turnover and business rhythm",
                "Works well for repeat borrowers with strong collections history",
                f"Clear {cycle_label.lower()} instalments and renewal pathways",
                "Can pair with asset finance where equipment is part of the plan",
            ],
            "documents": [
                "Business location and activity verification",
                "Sales records, bank statements, momo history, or stock evidence",
                "Owner ID and key contact information",
                "Any permits, invoices, or supplier references that support the request",
            ],
            "support_items": [
                "Cash-flow review before approval",
                "Recommendation on ideal tier based on growth stage",
                "Access to repeat-cycle financing after consistent performance",
                "Portfolio guidance to avoid over-borrowing during expansion",
            ],
            "use_cases": [
                "Restock before high-demand trading periods",
                "Open a second outlet or add a new product category",
                "Keep operations stable while customers pay later",
            ],
            "related_keys": ["asset-finance", "group-loans", "personal-loans"],
            "cta_title": "Ready to finance growth with discipline?",
            "cta_body": "We help business owners borrow for stock, cash flow, and expansion without losing control of repayment pressure.",
            "journey": common_journey,
        },
        "group-loans": {
            "badge": "Community Lending",
            "headline": "Group loans that unlock bigger impact through shared accountability",
            "detail_intro": "Support cooperatives, trader groups, savings circles, or community associations that want access to capital with peer accountability and structured follow-up.",
            "audience_label": "Best for associations, cooperatives, market clusters, and organized savings groups.",
            "best_for": [
                "Women’s groups and rotating savings communities",
                "Producer associations, trade clusters, and cooperatives",
                "Borrowers seeking stronger eligibility through collective structure",
                "Groups planning synchronized business or farming cycles",
            ],
            "feature_points": [
                "Shared responsibility model can improve repayment discipline",
                "Suitable for cluster-based follow-up by agents",
                "Helps members build confidence toward individual facilities later",
                "Works well for trade, agriculture, and community-enterprise funding",
            ],
            "documents": [
                "Group leadership and membership list",
                "Meeting records, constitution, or contribution history where available",
                "Member IDs and phone contacts",
                "Purpose of facility and internal repayment arrangement",
            ],
            "support_items": [
                "Orientation for group leaders and coordinators",
                "Repayment tracking at both group and member level",
                "Support for staggered member follow-up",
                "Migration path from group borrowing to individual products",
            ],
            "use_cases": [
                "Finance group trading activity or seasonal agricultural inputs",
                "Pool capital for a women’s enterprise initiative",
                "Build collective repayment history for larger future access",
            ],
            "related_keys": ["business-loans", "personal-loans", "education-loans"],
            "cta_title": "Want a group solution that keeps everyone aligned?",
            "cta_body": "Our team can structure a group facility around member roles, repayment rhythm, and leadership accountability.",
            "journey": common_journey,
        },
        "asset-finance": {
            "badge": "Productive Assets",
            "headline": "Asset finance for equipment, mobility, and productive business tools",
            "detail_intro": "Acquire income-generating equipment, machinery, tools, vehicles, or business infrastructure with financing aligned to the asset’s earning potential.",
            "audience_label": "Built for entrepreneurs and operators investing in assets that directly improve revenue.",
            "best_for": [
                "Equipment upgrades that increase daily output",
                "Vehicle or mobility support for logistics and service delivery",
                "Productive tools for tailoring, farming, fabrication, or retail",
                "Capital improvements tied to revenue generation",
            ],
            "feature_points": [
                "Finance assets that strengthen business productivity",
                "Align repayment thinking to how the asset generates income",
                "Can complement business-loan facilities for working capital",
                "Suitable for disciplined borrowers planning medium-term expansion",
            ],
            "documents": [
                "Asset quotation, invoice, or proforma where available",
                "Business activity proof showing repayment source",
                "Valid owner identification and reachable contacts",
                "Supporting records that justify the asset’s use and income value",
            ],
            "support_items": [
                "Asset-purpose review before approval",
                "Guidance on balancing asset cost against cash-flow strength",
                "Structured follow-up after disbursement",
                "Upgrade pathway as the business scales",
            ],
            "use_cases": [
                "Buy a freezer, machine, generator, sewing unit, or vehicle",
                "Reduce downtime caused by old or shared equipment",
                "Expand capacity without paying full asset cost upfront",
            ],
            "related_keys": ["business-loans", "group-loans", "personal-loans"],
            "cta_title": "Looking to finance an income-producing asset?",
            "cta_body": f"{company_name} can help you structure a facility that turns equipment and tools into sustainable growth, not repayment stress.",
            "journey": common_journey,
        },
        "emergency-loans": {
            "badge": "Rapid Relief",
            "headline": "Emergency loans for urgent situations that cannot wait",
            "detail_intro": "Move quickly when you face health issues, urgent travel, business interruption, family emergencies, or sudden cash needs that require responsible speed.",
            "audience_label": "Strong fit for borrowers who need speed, clarity, and manageable short-term support.",
            "best_for": [
                "Hospital bills, urgent travel, and time-sensitive obligations",
                "Cash gaps that could interrupt livelihood or business continuity",
                "Returning borrowers who need same-day or next-step attention",
                "Short-term support before longer-term solutions are arranged",
            ],
            "feature_points": [
                "Fast review and quick communication",
                "Simple requirements compared with longer-cycle facilities",
                f"Built around short to medium {repayment_period} plans",
                "Ideal bridge product before transitioning into larger facilities",
            ],
            "documents": [
                "Valid borrower identification",
                "Basic repayment source confirmation",
                "Reachable phone contact and emergency context",
                "Any supporting document that explains urgency if available",
            ],
            "support_items": [
                "Rapid escalation and screening",
                "Clear repayment explanation before disbursement",
                "Follow-up support to prevent emergency borrowing from snowballing",
                "Upgrade path into personal or business lending if needed",
            ],
            "use_cases": [
                "Protect your household or business from a short-term shock",
                "Solve an urgent problem without selling productive stock",
                "Access a bridge facility while planning a larger product",
            ],
            "related_keys": ["personal-loans", "education-loans", "business-loans"],
            "cta_title": "Need support quickly and responsibly?",
            "cta_body": "We’re ready to review urgent situations fast while still keeping repayment realistic and transparent.",
            "journey": common_journey,
        },
        "education-loans": {
            "badge": "Future Investment",
            "headline": "Education loans for school fees, skills, and upward mobility",
            "detail_intro": "Invest in tuition, exam fees, academic materials, vocational programs, and professional training that can improve long-term income and stability.",
            "audience_label": "Suitable for parents, guardians, students, and professionals funding learning goals.",
            "best_for": [
                "School fees, semester costs, and boarding requirements",
                "Vocational tools, certification programs, and exam fees",
                "Parents managing school obligations across multiple children",
                "Professionals funding short courses that improve earning power",
            ],
            "feature_points": [
                "Supports both academic and practical training paths",
                "Useful for recurring term-based education expenses",
                "Can work alongside household budgeting plans",
                "Encourages disciplined repayment tied to future opportunity",
            ],
            "documents": [
                "ID for borrower or guardian",
                "School bill, invoice, admission note, or training quotation",
                "Repayment source confirmation",
                "Student and institution details where relevant",
            ],
            "support_items": [
                "Guidance on matching tenure to term cycles",
                "Support for repeat education financing where track record is strong",
                "Clear visibility of cost before commitment",
                "Access to related personal-loan options when needs overlap",
            ],
            "use_cases": [
                "Pay fees on time and avoid missing a term",
                "Fund a skill program that unlocks income growth",
                "Spread education costs without disrupting the household",
            ],
            "related_keys": ["personal-loans", "emergency-loans", "group-loans"],
            "cta_title": "Planning to finance education with confidence?",
            "cta_body": f"We can help structure learning-related borrowing with realistic repayment over up to {duration} {repayment_period}s where appropriate.",
            "journey": common_journey,
        },
        "general-credit": {
            "badge": "Flexible Lending",
            "headline": "A financing solution tailored to your actual need",
            "detail_intro": "Where your need does not fit neatly into one category, we help you identify the most suitable facility and the safest repayment path.",
            "audience_label": "Useful for mixed-purpose financing or custom borrower situations.",
            "best_for": [
                "Borrowers with blended personal and business needs",
                "Clients comparing several loan products before choosing",
                "Repeat customers planning their next financing step",
                "Situations requiring guidance more than a fixed product label",
            ],
            "feature_points": [
                "Flexible matching across the available service range",
                "Support to choose between speed, size, and affordability",
                f"Repayment structured around {cycle_label.lower()} planning",
                "Cross-referral to related solutions where a better fit exists",
            ],
            "documents": [
                "Valid identification",
                "Basic income or business verification",
                "Phone and address details",
                "Any documents that clarify the funding purpose",
            ],
            "support_items": [
                "Needs assessment before product matching",
                "Guidance on the right tier and repayment duration",
                "Transparent communication around total repayment",
                "Support migrating into more specialized solutions over time",
            ],
            "use_cases": [
                "Compare several products before making a decision",
                "Access funding for a mixed household and business need",
                "Start with the right product instead of the biggest one",
            ],
            "related_keys": ["personal-loans", "business-loans", "emergency-loans"],
            "cta_title": "Not sure which service fits best?",
            "cta_body": "Talk to us and we’ll guide you toward the safest, most useful lending option for your situation.",
            "journey": common_journey,
        },
    }


def _recommended_tiers_for_service(preset_key, tiers):
    if not tiers:
        return []
    selectors = {
        "personal-loans": tiers[:3],
        "business-loans": tiers[1:5] or tiers,
        "group-loans": tiers[:4],
        "asset-finance": tiers[2:] or tiers,
        "emergency-loans": tiers[:2] or tiers[:1],
        "education-loans": tiers[:4],
        "general-credit": tiers[:3],
    }
    return selectors.get(preset_key, tiers[:3])[:3]


def _build_service_catalog(profile, raw_services):
    blueprints = _service_blueprints(profile)
    seen_slugs = set()
    catalog = []
    for index, service in enumerate(raw_services):
        title = (service.get("title") or f"Service {index + 1}").strip()
        preset_key = _match_service_blueprint(title)
        blueprint = blueprints.get(preset_key, blueprints["general-credit"])
        base_slug = slugify(title) or f"service-{index + 1}"
        slug = base_slug
        counter = 2
        while slug in seen_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1
        seen_slugs.add(slug)
        catalog.append(
            {
                **service,
                **blueprint,
                "title": title,
                "icon": service.get("icon") or "💡",
                "description": service.get("description") or blueprint["detail_intro"],
                "highlight": bool(service.get("highlight")),
                "slug": slug,
                "preset_key": preset_key,
                "recommended_tiers": _recommended_tiers_for_service(preset_key, profile.tiers_for_template),
            }
        )

    slug_by_key = {}
    for item in catalog:
        slug_by_key.setdefault(item["preset_key"], item["slug"])

    for item in catalog:
        related = []
        for key in item.get("related_keys", []):
            related_slug = slug_by_key.get(key)
            if related_slug and related_slug != item["slug"]:
                related.append(related_slug)
        if not related:
            related = [entry["slug"] for entry in catalog if entry["slug"] != item["slug"]][:3]
        item["related_solution_slugs"] = related[:3]

    for item in catalog:
        item["related_solutions"] = [
            {
                "title": entry["title"],
                "slug": entry["slug"],
                "description": entry["description"],
                "icon": entry["icon"],
                "badge": entry["badge"],
            }
            for entry in catalog
            if entry["slug"] in item["related_solution_slugs"]
        ]

    return catalog


# ─── Setup wizard ─────────────────────────────────────────────────────────────

def setup_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not CompanyProfile.objects.filter(pk=1).exists():
            return redirect("company:setup")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


@staff_member_required
def company_setup(request):
    if CompanyProfile.objects.filter(pk=1).exists():
        return redirect("company:edit")
    if request.method == "POST":
        form = CompanyProfileForm(request.POST, request.FILES)
        document_formset = CompanyDocumentFormSet(
            request.POST,
            request.FILES,
            queryset=CompanyDocument.objects.none(),
            prefix="documents",
        )
        if form.is_valid() and document_formset.is_valid():
            profile = form.save(commit=False)
            profile.pk = 1
            profile.save()
            document_formset.save()
            messages.success(request, f"Welcome! {profile.company_name} is ready.")
            return redirect("loans:dashboard")
    else:
        form = CompanyProfileForm(initial={
            "tier_labels":    "Bronze\nSilver\nGold\nPlatinum\nDiamond\nExecutive",
            "tier_maxes":     "3000\n5000\n10000\n15000\n20000\n999999999",
            "languages_text": "Twi, Ewe, Ga, Hausa",
        })
        document_formset = CompanyDocumentFormSet(
            queryset=CompanyDocument.objects.none(),
            prefix="documents",
        )
    return render(request, "company/setup.html", {
        "form": form,
        "document_formset": document_formset,
        "title": "Set Up Your Micro-Credit Platform",
        "is_setup": True,
    })


@staff_member_required
def company_edit(request):
    profile = CompanyProfile.get_solo()
    if request.method == "POST":
        form = CompanyProfileForm(request.POST, request.FILES, instance=profile)
        document_formset = CompanyDocumentFormSet(
            request.POST,
            request.FILES,
            queryset=CompanyDocument.objects.all(),
            prefix="documents",
        )
        if form.is_valid() and document_formset.is_valid():
            form.save()
            document_formset.save()
            messages.success(request, "Company settings updated successfully.")
            return redirect("company:edit")
    else:
        form = CompanyProfileForm(instance=profile)
        document_formset = CompanyDocumentFormSet(
            queryset=CompanyDocument.objects.all(),
            prefix="documents",
        )
    return render(request, "company/setup.html", {
        "form": form,
        "document_formset": document_formset,
        "title": "Company Settings",
        "profile": profile,
        "is_setup": False,
    })


@staff_member_required
def database_backup_hub(request):
    alias = resolve_database_alias(request.GET.get("db"))
    overview = get_database_overview(alias)
    databases = []
    for key, settings_dict in connections.databases.items():
        databases.append(
            {
                "alias": key,
                "name": settings_dict.get("NAME", ""),
                "engine": settings_dict.get("ENGINE", ""),
                "selected": key == alias,
            }
        )

    return render(
        request,
        "company/database_backup.html",
        {
            "title": "Database Backup",
            "selected_database": alias,
            "databases": databases,
            "overview": overview,
            "backup_formats": BACKUP_FORMATS,
        },
    )


@staff_member_required
def database_backup_download(request, fmt):
    alias = resolve_database_alias(request.GET.get("db"))
    format_config = next((item for item in BACKUP_FORMATS if item["slug"] == fmt), None)
    if format_config is None:
        raise Http404("Backup format not found.")

    _, payload = export_database_backup(alias, fmt)
    filename = build_backup_filename(alias, format_config["extension"])
    response = HttpResponse(payload, content_type=format_config["content_type"])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ─── Shared context helper ────────────────────────────────────────────────────

def _base_ctx(profile):
    """Context keys shared by every public page."""
    try:
        from apps.communication.models import WebsiteMarketingPopup
        marketing_popup = WebsiteMarketingPopup.get_live_popup()
    except Exception:
        marketing_popup = None

    default_services = [
        {"title": "Personal Loans",  "icon": "👤", "highlight": False,
         "description": "Flexible personal loans for emergencies, education, healthcare and more. Quick approval with minimal documentation."},
        {"title": "Business Loans",  "icon": "🏪", "highlight": True,
         "description": "Working capital, stock financing and expansion loans tailored to small and medium enterprises."},
        {"title": "Group Loans",     "icon": "👥", "highlight": False,
         "description": "Savings group and cooperative lending with shared accountability and lower rates for qualifying groups."},
        {"title": "Asset Finance",   "icon": "🏗",  "highlight": False,
         "description": "Finance equipment, machinery, vehicles and productive assets with repayment aligned to your income."},
        {"title": "Emergency Loans", "icon": "⚡",  "highlight": False,
         "description": "Same-day disbursement for urgent needs. Pre-approved for existing borrowers in good standing."},
        {"title": "Education Loans", "icon": "🎓",  "highlight": False,
         "description": "School fees, professional training and skills development financing for a better future."},
    ]
    default_testimonials = [
        {"name": "Abena Asante",    "role": "Market Trader, Accra",       "avatar_initials": "AA",
         "quote": "I got my loan within 24 hours. The process was simple and professional. My business has grown threefold since."},
        {"name": "Kwame Boateng",   "role": "Small Business Owner, Kumasi", "avatar_initials": "KB",
         "quote": "The repayment schedule fits perfectly with my income cycle. I have taken three loans and every experience was excellent."},
        {"name": "Esi Mensah",      "role": "Seamstress, Takoradi",       "avatar_initials": "EM",
         "quote": "Finally a micro-credit company that treats you with respect. Transparent fees, no hidden charges, always available."},
        {"name": "Kofi Darko",      "role": "Poultry Farmer, Brong-Ahafo","avatar_initials": "KD",
         "quote": "The group loan programme changed everything for our cooperative. We expanded and paid off in six months."},
        {"name": "Akosua Frimpong", "role": "Hair Salon Owner, Tema",     "avatar_initials": "AF",
         "quote": "Professional, fast, and fair. I recommended them to my whole association and everyone is very happy."},
    ]
    default_faqs = [
        {"question": "Who can apply for a loan?",
         "answer": "Any individual or small business owner aged 18+ with a valid national ID and verifiable income."},
        {"question": "How quickly will I receive funds?",
         "answer": "Within 24–48 hours for new borrowers, same day for returning clients in good standing."},
        {"question": "What documents do I need?",
         "answer": "National ID (Ghana Card), proof of income or business activity, and a passport photo."},
        {"question": "What are the interest rates?",
         "answer": f"Rates vary by loan tier ({', '.join(t['label'] for t in profile.tiers_for_template)}) and duration. Contact us for a personalised quote."},
        {"question": "How do I repay?",
         "answer": f"Repayments are made {profile.repayment_cycle} via mobile money, bank transfer, or your field agent."},
        {"question": "Can I repay early?",
         "answer": "Yes — early repayment is encouraged and earns you access to larger amounts. No penalties."},
        {"question": "What if I miss a payment?",
         "answer": f"We allow {profile.overdue_grace_periods} grace periods before flagging an account. We always reach out first."},
        {"question": "Is there an online portal?",
         "answer": "Yes. Every borrower receives a personal portal to view balances, payment history and schedule."},
    ]
    default_goals = [
        {"title": "Financial Inclusion", "icon": "🌍",
         "description": "Reach every community with accessible credit, regardless of background or geography."},
        {"title": "Transparent Lending", "icon": "🔍",
         "description": "Zero hidden fees, clear terms, and honest communication at every step of the process."},
        {"title": "Community Growth",    "icon": "🌱",
         "description": "Invest in local entrepreneurs and watch entire communities flourish as businesses grow."},
        {"title": "Digital Empowerment", "icon": "📱",
         "description": "Give every borrower a secure digital portal to manage their account anytime, anywhere."},
        {"title": "Responsible Recovery","icon": "🤝",
         "description": "Collect with dignity. We prioritise relationships and work with borrowers during hardship."},
        {"title": "Agent Excellence",    "icon": "⭐",
         "description": "Train, equip and empower our field agents to deliver the best service in every community."},
    ]
    default_core_values = [
        {"icon": "🤝", "title": "Integrity",    "description": "We act with honesty and transparency in every interaction."},
        {"icon": "🌱", "title": "Growth",        "description": "We invest in our clients and communities for lasting impact."},
        {"icon": "⚡", "title": "Speed",         "description": "Fast decisions and disbursements without sacrificing quality."},
        {"icon": "🔒", "title": "Security",      "description": "Your data and money are protected at every step."},
    ]
    default_how_steps = [
        {"icon": "📋", "title": "Register",      "description": "Visit us or contact your agent with your ID and documents to open your borrower account."},
        {"icon": "📝", "title": "Apply",          "description": "Choose your loan amount and duration. Your agent guides you to the right product."},
        {"icon": "✅", "title": "Get Approved",   "description": "We review your application and notify you within hours based on need and capacity."},
        {"icon": "💰", "title": "Receive Funds",  "description": "Funds sent to your mobile money or bank — typically within 24 hours of approval."},
    ]
    default_branches = [
        {"name": "Head Office", "address": "123 Independence Avenue, Accra, Ghana",
         "phone": "+233 30 000 0001", "email": profile.email or "",
         "lat": "5.6037", "lng": "-0.1870", "is_head_office": True},
    ]
    tiers = profile.tiers_for_template
    stats = []
    if profile.years_in_business:        stats.append({"value": f"{profile.years_in_business}+", "label": "Years in Business"})
    if profile.clients_served:           stats.append({"value": f"{profile.clients_served:,}+", "label": "Clients Served"})
    if profile.loans_disbursed_display:  stats.append({"value": profile.loans_disbursed_display, "label": "Loans Disbursed"})
    if tiers:                            stats.append({"value": str(len(tiers)), "label": "Loan Products"})

    service_catalog = _build_service_catalog(profile, profile.services or default_services)

    return {
        "profile":      profile,
        "tiers":        tiers,
        "stats":        stats,
        "marketing_popup": marketing_popup,
        "services":     service_catalog,
        "testimonials": profile.testimonials or default_testimonials,
        "faqs":         profile.faqs         or default_faqs,
        "goals":        profile.goals        or default_goals,
        "branches":     profile.branches     or default_branches,
        "core_values":  profile.core_values  or default_core_values,
        "how_steps":    profile.how_steps    or default_how_steps,
        "partners":     profile.partners     or [],
        "certifications": profile.certifications or [],
        "awards":       profile.awards       or [],
        "business_hours": profile.business_hours or [],
        "documents": CompanyDocument.objects.filter(is_public=True).order_by("sort_order", "title", "id"),
    }


# ─── Public pages ─────────────────────────────────────────────────────────────

def website_home(request):
    profile = CompanyProfile.get_solo()
    ctx = _base_ctx(profile)
    ctx["title"] = f"{profile.company_name} — {profile.tagline or 'Micro-Credit'}"
    ctx["active_page"] = "home"
    return render(request, "website/home.html", ctx)


def website_about(request):
    profile = CompanyProfile.get_solo()
    from apps.accounts.models import Agent
    agents = Agent.objects.all().order_by("name")
    ctx = _base_ctx(profile)
    ctx.update({
        "title": f"About Us — {profile.company_name}",
        "active_page": "about",
        "agents": agents,
        "gallery": profile.gallery_items,
    })
    return render(request, "website/about.html", ctx)


def website_services(request):
    profile = CompanyProfile.get_solo()
    ctx = _base_ctx(profile)
    ctx.update({
        "title": f"Loan Products & Services — {profile.company_name}",
        "active_page": "services",
        "featured_services": ctx["services"][:3],
    })
    return render(request, "website/services.html", ctx)


def website_service_detail(request, service_slug):
    profile = CompanyProfile.get_solo()
    ctx = _base_ctx(profile)
    service = next((item for item in ctx["services"] if item["slug"] == service_slug), None)
    if service is None:
        raise Http404("Service not found.")

    ctx.update(
        {
            "title": f"{service['title']} — {profile.company_name}",
            "active_page": "services",
            "service": service,
            "related_services": service["related_solutions"],
            "recommended_tiers": service["recommended_tiers"],
        }
    )
    return render(request, "website/service_detail.html", ctx)


def website_team(request):
    profile = CompanyProfile.get_solo()
    from apps.accounts.models import Agent
    agents = Agent.objects.all().order_by("name")
    ctx = _base_ctx(profile)
    ctx.update({
        "title": f"Our Team — {profile.company_name}",
        "active_page": "team",
        "agents": agents,
    })
    return render(request, "website/team.html", ctx)


def website_contact(request):
    profile = CompanyProfile.get_solo()
    ctx = _base_ctx(profile)
    sent = False
    contact_error = ""
    if request.method == "POST":
        name    = request.POST.get("name", "").strip()
        email   = request.POST.get("email", "").strip()
        phone   = request.POST.get("phone", "").strip()
        subject = request.POST.get("subject", "").strip()
        msg     = request.POST.get("message", "").strip()
        if request.POST.get("website", "").strip():
            contact_error = "Unable to submit this message."
        elif _contact_rate_limited(request):
            contact_error = "Too many messages have been submitted. Please try again later."
        elif name and email and msg:
            try:
                from apps.communication.models import WebsiteLead
                WebsiteLead.objects.create(
                    name=name,
                    email=email,
                    phone=phone,
                    subject=subject,
                    message=msg,
                    source="CONTACT_FORM",
                )
            except DatabaseError:
                logger.exception("Unable to persist website contact submission")
                contact_error = "We could not receive your message right now. Please try again later."
            else:
                sent = True
                try:
                    from apps.notifications.services import notify_user
                    from django.contrib.auth.models import User
                    admins = User.objects.filter(is_staff=True)[:1]
                    if admins:
                        notify_user(
                            admins[0], "CONTACT",
                            f"Website enquiry from {name}: {subject or 'General'}",
                            f"From: {name} <{email}> {phone}\n\n{msg}",
                        )
                except Exception:
                    logger.exception("Unable to notify staff about website contact submission")
        else:
            contact_error = "Please provide your name, email address, and message."
    ctx.update({
        "title": f"Contact Us — {profile.company_name}",
        "active_page": "contact",
        "sent": sent,
        "contact_error": contact_error,
    })
    return render(request, "website/contact.html", ctx)


def website_privacy(request):
    profile = CompanyProfile.get_solo()
    ctx = _base_ctx(profile)
    ctx["title"] = "Privacy Policy"
    ctx["active_page"] = "privacy"
    return render(request, "website/privacy.html", ctx)


def website_documents(request):
    profile = CompanyProfile.get_solo()
    ctx = _base_ctx(profile)
    ctx["title"] = f"Documents — {profile.company_name}"
    ctx["active_page"] = "documents"
    return render(request, "website/documents.html", ctx)


def public_website(request):
    """Legacy redirect — keep backward compat."""
    return website_home(request)
