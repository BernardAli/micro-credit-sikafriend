from apps.loans.portfolios import agent_portfolio_ids
import re
from decimal import Decimal
from dataclasses import dataclass
from typing import Iterable

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from apps.accounts.models import Agent
from apps.company.messaging import get_company_ussd_config, send_company_email, validate_company_ussd_request
from apps.loans.models import Borrower, Loan
from apps.company.models import CompanyProfile
from apps.core.roles import admin_required
from .forms import (
    ManagementSMSForm,
    MarketingCampaignLauncherForm,
    MarketingTemplateForm,
    WebsiteMarketingPopupForm,
)
from .models import (
    MarketingCampaign,
    MarketingDispatchLog,
    MarketingTemplate,
    WebsiteLead,
    WebsiteMarketingPopup,
)
from .services_sms import normalize_phone as sms_normalize_phone, safe_send_sms


User = get_user_model()
USSD_MAX_MESSAGE_LENGTH = 182


@dataclass
class RecipientItem:
    label: str
    phone: str
    category: str


@dataclass
class MarketingRecipient:
    name: str
    category: str
    phone: str = ""
    email: str = ""
    source: str = ""


def normalize_phone(phone: str) -> str:
    return sms_normalize_phone(phone)


def _company_name() -> str:
    try:
        company = CompanyProfile.get_solo()
        return (company.company_name or "Micro-Credit").strip()
    except Exception:
        return "Micro-Credit"


def _currency_prefix() -> str:
    try:
        company = CompanyProfile.get_solo()
        return company.formatted_currency or "GHS"
    except Exception:
        return "GHS"


def _format_money(value: Decimal) -> str:
    amount = Decimal(value or Decimal("0.00")).quantize(Decimal("0.01"))
    return f"{_currency_prefix()} {amount:,.2f}"


def _find_borrower_by_phone(phone: str) -> Borrower | None:
    normalized = normalize_phone(phone)
    if not normalized:
        return None

    borrowers = Borrower.objects.all()
    for borrower in borrowers:
        if normalize_phone(borrower.phone) == normalized:
            return borrower
    return None


def _select_loan_for_borrower(borrower: Borrower) -> Loan | None:
    active_loan = (
        borrower.loans.select_related("agent_name")
        .prefetch_related("payments")
        .filter(status="ACTIVE")
        .order_by("-created_at")
        .first()
    )
    if active_loan:
        return active_loan

    return (
        borrower.loans.select_related("agent_name")
        .prefetch_related("payments")
        .order_by("-created_at")
        .first()
    )


def _company_contact_text() -> str:
    try:
        company = CompanyProfile.get_solo()
    except Exception:
        company = None

    phone = (getattr(company, "phone", "") or "").strip() if company else ""
    email = (getattr(company, "email", "") or "").strip() if company else ""
    address = (getattr(company, "address", "") or "").strip() if company else ""

    company_name = (getattr(company, "company_name", "") or "Micro-Credit").strip()

    if not phone and not email and not address:
        return f"Please contact your nearest {company_name} branch for support."

    parts = [f"{company_name} Support"]
    if phone:
        parts.append(f"Phone: {phone}")
    if email:
        parts.append(f"Email: {email}")
    if address:
        parts.append(f"Address: {address}")
    return "\n".join(parts)


def _ussd_main_menu() -> str:
    company_name = _company_name()
    return _ussd_continue(
        f"Welcome to {company_name}\n"
        "1. Loan Repayment\n"
        "2. Loan Disbursement Confirmation\n"
        "3. Check Balance\n"
        "4. Referrals\n"
        "5. Contact Us\n"
        "6. Customer ID / Balance"
    )


def _normalize_ussd_message(message: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", (message or "").strip())


def _truncate_ussd_message(message: str) -> str:
    message = _normalize_ussd_message(message)
    if len(message) <= USSD_MAX_MESSAGE_LENGTH:
        return message
    return f"{message[: USSD_MAX_MESSAGE_LENGTH - 3].rstrip()}..."


def _ussd_reply(prefix: str, body: str) -> str:
    return _truncate_ussd_message(f"{prefix} {body.strip()}")


def _ussd_continue(body: str) -> str:
    return _ussd_reply("CON", body)


def _ussd_end(body: str) -> str:
    return _ussd_reply("END", body)


def _loan_repayment_message(borrower: Borrower | None) -> str:
    company_name = _company_name()
    if not borrower:
        return _ussd_end(
            "We could not match your number to a borrower profile. "
            f"Please contact {company_name} for help."
        )

    loan = _select_loan_for_borrower(borrower)
    if not loan:
        return _ussd_end(f"Hello {borrower.full_name}. No loan record was found for this number.")

    if loan.status != "ACTIVE":
        return _ussd_end(
            f"Hello {borrower.full_name}. "
            f"Your latest loan is {loan.status.lower()} with balance {_format_money(loan.balance_amount)}."
        )

    return _ussd_end(
        f"Hello {borrower.full_name}. "
        f"Your current repayment due is {_format_money(loan.weekly_payment)}. "
        f"Outstanding balance: {_format_money(loan.balance_amount)}. "
        f"Please pay through your loan officer or nearest {company_name} office."
    )


def _loan_disbursement_message(borrower: Borrower | None) -> str:
    company_name = _company_name()
    if not borrower:
        return _ussd_end(
            f"We could not confirm a borrower profile for this number. Please contact {company_name}."
        )

    loan = _select_loan_for_borrower(borrower)
    if not loan:
        return _ussd_end(f"Hello {borrower.full_name}. No disbursed loan record was found yet.")

    return _ussd_end(
        f"Hello {borrower.full_name}. "
        f"Your loan disbursement of {_format_money(loan.amount)} is on record. "
        f"Loan status: {loan.status}. "
        f"Weekly payment: {_format_money(loan.weekly_payment)}."
    )


def _check_balance_message(borrower: Borrower | None) -> str:
    company_name = _company_name()
    if not borrower:
        return _ussd_end(
            f"We could not match your number to a borrower profile. Please contact {company_name}."
        )

    loan = _select_loan_for_borrower(borrower)
    if not loan:
        return _ussd_end(f"Hello {borrower.full_name}. No loan balance is available for this number.")

    return _ussd_end(
        f"Hello {borrower.full_name}. "
        f"Balance: {_format_money(loan.balance_amount)}. "
        f"Paid: {loan.actual_payments_count}/{loan.expected_payments_count} installments. "
        f"Remaining: {loan.outstanding_payments_count}. "
        f"Status: {loan.status}."
    )


def _referral_message() -> str:
    try:
        company = CompanyProfile.get_solo()
        company_name = (company.company_name or "Micro-Credit").strip()
        phone = (company.phone or "").strip()
    except Exception:
        company_name = "Micro-Credit"
        phone = ""

    message = f"Refer a friend to {company_name} for fast and reliable micro-credit."
    if phone:
        message += f" Tell them to call {phone} for registration."
    else:
        message += " Tell them to contact the nearest branch for registration."
    return _ussd_end(message)


def _build_ussd_response(phone_number: str, text: str) -> str:
    borrower = _find_borrower_by_phone(phone_number)
    menu_parts = [part.strip() for part in (text or "").split("*") if part.strip()]

    if not menu_parts:
        return _ussd_main_menu()

    option = menu_parts[0]
    if option == "6":
        if len(menu_parts) == 1:
            return _ussd_continue("Enter your permanent Customer ID (e.g. SF070428):")
        from apps.loans.portfolios import customer_lookup
        try:
            customer = customer_lookup(menu_parts[1].upper())
        except ValueError:
            return _ussd_end("Customer ID could not be verified for this phone number.")
        if not normalize_phone(phone_number) or normalize_phone(customer.phone) != normalize_phone(phone_number):
            return _ussd_end("Customer ID could not be verified for this phone number.")
        return _check_balance_message(customer)
    if option == "1":
        return _loan_repayment_message(borrower)
    if option == "2":
        return _loan_disbursement_message(borrower)
    if option == "3":
        return _check_balance_message(borrower)
    if option == "4":
        return _referral_message()
    if option == "5":
        return _ussd_end(_company_contact_text())

    return _ussd_end("Invalid option. Please dial again and choose a valid menu item.")


def _extract_ussd_phone(request) -> str:
    for key in (
        "Mobile",
        "mobile",
        "MSISDN",
        "msisdn",
        "phoneNumber",
        "phone_number",
        "phone",
    ):
        value = request.POST.get(key) or request.GET.get(key)
        if value:
            return value
    return ""


def _extract_ussd_text(request) -> str:
    for key in ("Message", "message", "text", "Text", "input", "Input"):
        value = request.POST.get(key) or request.GET.get(key)
        if value is not None:
            return value
    return ""


def extract_manual_numbers(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[\s,;\n\r\t]+", raw.strip())
    return [normalize_phone(p) for p in parts if normalize_phone(p)]


def get_user_phone(user) -> str:
    for attr in ["phone", "phone_number", "mobile", "mobile_number"]:
        value = getattr(user, attr, None)
        if value:
            return normalize_phone(value)
    for rel_attr in ["agent_profile", "borrower_profile"]:
        try:
            related = getattr(user, rel_attr)
        except Exception:
            related = None
        if related:
            phone = getattr(related, "phone", None)
            if phone:
                return normalize_phone(phone)
    return ""


def get_agent_phone(agent) -> str:
    return normalize_phone(getattr(agent, "phone", "") or "")


def get_borrower_phone(borrower) -> str:
    return normalize_phone(getattr(borrower, "phone", "") or "")


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def get_agent_email(agent) -> str:
    return normalize_email(getattr(agent, "email", "") or "")


def get_borrower_email(borrower) -> str:
    return normalize_email(getattr(borrower, "email", "") or "")


def get_lead_email(lead) -> str:
    return normalize_email(getattr(lead, "email", "") or "")


def extract_manual_emails(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[\s,;\n\r\t]+", raw.strip())
    emails = []
    seen = set()
    for part in parts:
        email = normalize_email(part)
        if email and "@" in email and "." in email.split("@")[-1] and email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def _borrower_phone_map() -> dict[str, Borrower]:
    borrowers = Borrower.objects.all().prefetch_related("loans")
    phone_map: dict[str, Borrower] = {}
    for borrower in borrowers:
        phone = get_borrower_phone(borrower)
        if phone and phone not in phone_map:
            phone_map[phone] = borrower
    return phone_map


def dedupe_recipients(items: Iterable[RecipientItem]) -> list[RecipientItem]:
    seen = set()
    deduped = []
    for item in items:
        phone = normalize_phone(item.phone)
        if not phone:
            continue
        if phone in seen:
            continue
        seen.add(phone)
        deduped.append(RecipientItem(label=item.label, phone=phone, category=item.category))
    return deduped


def dedupe_marketing_recipients(items: Iterable[MarketingRecipient], channel: str) -> list[MarketingRecipient]:
    deduped: list[MarketingRecipient] = []
    seen = set()

    for item in items:
        if channel in {"SMS", "WHATSAPP"}:
            key = normalize_phone(item.phone)
            if not key or key in seen:
                continue
            item.phone = key
        else:
            key = normalize_email(item.email)
            if not key or key in seen:
                continue
            item.email = key

        seen.add(key)
        deduped.append(item)

    return deduped


def _borrowers_matching_campaign(cleaned_data):
    audience = cleaned_data.get("audience")
    agent = cleaned_data.get("agent")
    location = (cleaned_data.get("location") or "").strip()
    group_name = (cleaned_data.get("group_name") or "").strip()
    preferred_language = cleaned_data.get("preferred_language")
    loan_category = cleaned_data.get("loan_category")
    borrower_status = cleaned_data.get("borrower_status")
    loan_status = cleaned_data.get("loan_status")

    borrowers = Borrower.objects.all().prefetch_related("loans").order_by("full_name")

    if audience == "ACTIVE_BORROWERS":
        borrowers = borrowers.filter(status="ACTIVE")
    elif audience == "CLOSED_BORROWERS":
        borrowers = borrowers.filter(status="CLOSED")
    elif audience == "BAD_BORROWERS":
        borrowers = borrowers.filter(status="BAD")
    elif audience == "BORROWERS_BY_AGENT" and agent:
        borrowers = borrowers.filter(portfolio_id__in=agent_portfolio_ids(agent))
    elif audience == "BORROWERS_BY_LOCATION" and location:
        borrowers = borrowers.filter(location__icontains=location)
    elif audience == "BORROWERS_BY_GROUP" and group_name:
        borrowers = borrowers.filter(group_name__icontains=group_name)
    elif audience == "BORROWERS_BY_LANGUAGE" and preferred_language:
        borrowers = borrowers.filter(preferred_language=preferred_language)
    elif audience == "BORROWERS_BY_LOAN_CATEGORY" and loan_category:
        borrowers = borrowers.filter(loans__loan_category=loan_category).distinct()

    if borrower_status:
        borrowers = borrowers.filter(status=borrower_status)

    if loan_status:
        borrowers = borrowers.filter(loans__status=loan_status).distinct()

    return borrowers


def build_marketing_recipients(cleaned_data, *, channel: str) -> list[MarketingRecipient]:
    audience = cleaned_data.get("audience")
    lead_status = cleaned_data.get("lead_status")
    manual_contacts = cleaned_data.get("manual_contacts") or ""

    recipients: list[MarketingRecipient] = []

    borrower_audiences = {
        "ALL_BORROWERS",
        "ACTIVE_BORROWERS",
        "CLOSED_BORROWERS",
        "BAD_BORROWERS",
        "BORROWERS_BY_AGENT",
        "BORROWERS_BY_LOCATION",
        "BORROWERS_BY_GROUP",
        "BORROWERS_BY_LANGUAGE",
        "BORROWERS_BY_LOAN_CATEGORY",
    }

    if audience in borrower_audiences:
        for borrower in _borrowers_matching_campaign(cleaned_data):
            recipients.append(
                MarketingRecipient(
                    name=borrower.full_name,
                    category="Borrower Segment",
                    phone=get_borrower_phone(borrower),
                    email=get_borrower_email(borrower),
                    source=f"Borrower:{borrower.borrower_id}",
                )
            )

    elif audience == "ALL_AGENTS":
        for agent in Agent.objects.all().order_by("name"):
            recipients.append(
                MarketingRecipient(
                    name=agent.name,
                    category="Agent",
                    phone=get_agent_phone(agent),
                    email=get_agent_email(agent),
                    source=f"Agent:{agent.agent_id}",
                )
            )

    elif audience == "AGENTS_WITH_ACTIVE_LOANS":
        for agent in Agent.objects.filter(loans__status="ACTIVE").distinct().order_by("name"):
            recipients.append(
                MarketingRecipient(
                    name=agent.name,
                    category="Agent Active Portfolio",
                    phone=get_agent_phone(agent),
                    email=get_agent_email(agent),
                    source=f"Agent:{agent.agent_id}",
                )
            )

    elif audience == "AGENTS_WITH_DEFAULT_LOANS":
        for agent in Agent.objects.filter(loans__status="DEFAULT").distinct().order_by("name"):
            recipients.append(
                MarketingRecipient(
                    name=agent.name,
                    category="Agent Default Portfolio",
                    phone=get_agent_phone(agent),
                    email=get_agent_email(agent),
                    source=f"Agent:{agent.agent_id}",
                )
            )

    elif audience == "ALL_WEBSITE_LEADS":
        leads = WebsiteLead.objects.all()
        if lead_status:
            leads = leads.filter(status=lead_status)
        for lead in leads.order_by("-created_at"):
            recipients.append(
                MarketingRecipient(
                    name=lead.name,
                    category=f"Lead {lead.status.title()}",
                    phone=normalize_phone(lead.phone),
                    email=get_lead_email(lead),
                    source=f"Lead:{lead.pk}",
                )
            )

    elif audience == "WEBSITE_LEADS_BY_STATUS":
        leads = WebsiteLead.objects.filter(status=lead_status).order_by("-created_at")
        for lead in leads:
            recipients.append(
                MarketingRecipient(
                    name=lead.name,
                    category=f"Lead {lead.status.title()}",
                    phone=normalize_phone(lead.phone),
                    email=get_lead_email(lead),
                    source=f"Lead:{lead.pk}",
                )
            )

    elif audience == "ALL_CONTACTS":
        for borrower in Borrower.objects.all().order_by("full_name"):
            recipients.append(
                MarketingRecipient(
                    name=borrower.full_name,
                    category="Borrower",
                    phone=get_borrower_phone(borrower),
                    email=get_borrower_email(borrower),
                    source=f"Borrower:{borrower.borrower_id}",
                )
            )
        for agent in Agent.objects.all().order_by("name"):
            recipients.append(
                MarketingRecipient(
                    name=agent.name,
                    category="Agent",
                    phone=get_agent_phone(agent),
                    email=get_agent_email(agent),
                    source=f"Agent:{agent.agent_id}",
                )
            )
        for lead in WebsiteLead.objects.all().order_by("-created_at"):
            recipients.append(
                MarketingRecipient(
                    name=lead.name,
                    category=f"Lead {lead.status.title()}",
                    phone=normalize_phone(lead.phone),
                    email=get_lead_email(lead),
                    source=f"Lead:{lead.pk}",
                )
            )

    elif audience == "MANUAL_CONTACTS":
        for number in extract_manual_numbers(manual_contacts):
            recipients.append(
                MarketingRecipient(
                    name=number,
                    category="Manual Contact",
                    phone=number,
                    source="Manual",
                )
            )
        for email in extract_manual_emails(manual_contacts):
            recipients.append(
                MarketingRecipient(
                    name=email,
                    category="Manual Contact",
                    email=email,
                    source="Manual",
                )
            )

    return dedupe_marketing_recipients(recipients, channel)


def build_recipients(cleaned_data) -> list[RecipientItem]:
    recipient_group = cleaned_data.get("recipient_group")
    agent = cleaned_data.get("agent")
    borrower_status = cleaned_data.get("borrower_status")
    loan_status = cleaned_data.get("loan_status")
    loan_category = cleaned_data.get("loan_category")
    location = (cleaned_data.get("location") or "").strip()
    group_name = (cleaned_data.get("group_name") or "").strip()
    preferred_language = cleaned_data.get("preferred_language")
    manual_numbers = cleaned_data.get("manual_numbers") or ""

    recipients: list[RecipientItem] = []

    if recipient_group == "ALL_USERS":
        users = User.objects.all()
        for user in users:
            phone = get_user_phone(user)
            if phone:
                recipients.append(
                    RecipientItem(
                        label=getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "User"),
                        phone=phone,
                        category="User",
                    )
                )

    elif recipient_group == "STAFF_USERS":
        users = User.objects.filter(is_staff=True)
        for user in users:
            phone = get_user_phone(user)
            if phone:
                recipients.append(
                    RecipientItem(
                        label=getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "Staff"),
                        phone=phone,
                        category="Staff User",
                    )
                )

    elif recipient_group == "ALL_AGENTS":
        agents = Agent.objects.all().order_by("name")
        for ag in agents:
            phone = get_agent_phone(ag)
            if phone:
                recipients.append(RecipientItem(label=ag.name, phone=phone, category="Agent"))

    elif recipient_group == "AGENTS_WITH_ACTIVE_LOANS":
        agents = Agent.objects.filter(loans__status="ACTIVE").distinct().order_by("name")
        for ag in agents:
            phone = get_agent_phone(ag)
            if phone:
                recipients.append(RecipientItem(label=ag.name, phone=phone, category="Agent Active Portfolio"))

    elif recipient_group == "AGENTS_WITH_DEFAULT_LOANS":
        agents = Agent.objects.filter(loans__status="DEFAULT").distinct().order_by("name")
        for ag in agents:
            phone = get_agent_phone(ag)
            if phone:
                recipients.append(RecipientItem(label=ag.name, phone=phone, category="Agent Default Portfolio"))

    elif recipient_group == "ALL_BORROWERS":
        borrowers = Borrower.objects.all().order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower"))

    elif recipient_group == "BORROWERS_ACTIVE":
        borrowers = Borrower.objects.filter(status="ACTIVE").order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower ACTIVE"))

    elif recipient_group == "BORROWERS_CLOSED":
        borrowers = Borrower.objects.filter(status="CLOSED").order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower CLOSED"))

    elif recipient_group == "BORROWERS_BAD":
        borrowers = Borrower.objects.filter(status="BAD").order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower BAD"))

    elif recipient_group == "BORROWERS_WITH_ACTIVE_LOANS":
        borrowers = Borrower.objects.filter(loans__status="ACTIVE").distinct().order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower Active Loan"))

    elif recipient_group == "BORROWERS_WITH_DEFAULT_LOANS":
        borrowers = Borrower.objects.filter(loans__status="DEFAULT").distinct().order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower Default Loan"))

    elif recipient_group == "BORROWERS_BY_LOAN_CATEGORY":
        borrowers = Borrower.objects.filter(loans__loan_category=loan_category).distinct().order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower Loan Category"))

    elif recipient_group == "BORROWERS_BY_AGENT":
        borrowers = Borrower.objects.filter(portfolio_id__in=agent_portfolio_ids(agent)).order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower By Agent"))

    elif recipient_group == "BORROWERS_BY_LOCATION":
        borrowers = Borrower.objects.filter(location__icontains=location).order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower By Location"))

    elif recipient_group == "BORROWERS_BY_GROUP":
        borrowers = Borrower.objects.filter(group_name__icontains=group_name).order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower By Group"))

    elif recipient_group == "BORROWERS_BY_LANGUAGE":
        borrowers = Borrower.objects.filter(preferred_language=preferred_language).order_by("full_name")
        for b in borrowers:
            phone = get_borrower_phone(b)
            if phone:
                recipients.append(RecipientItem(label=b.full_name, phone=phone, category="Borrower By Language"))

    elif recipient_group == "MANUAL_NUMBERS":
        for number in extract_manual_numbers(manual_numbers):
            recipients.append(RecipientItem(label=number, phone=number, category="Manual"))

    # Optional extra narrowing if user selected these filters
    if recipient_group.startswith("BORROWERS") and (borrower_status or loan_status):
        filtered = []
        borrower_by_phone = _borrower_phone_map()
        for item in recipients:
            borrower = borrower_by_phone.get(normalize_phone(item.phone))
            if not borrower:
                continue

            ok = True
            if borrower_status and borrower.status != borrower_status:
                ok = False

            if loan_status and not borrower.loans.filter(status=loan_status).exists():
                ok = False

            if ok:
                filtered.append(item)
        recipients = filtered

    return dedupe_recipients(recipients)


def _render_marketing_copy(template_text: str, recipient: MarketingRecipient) -> str:
    text = (template_text or "").strip()
    if not text:
        return ""
    return (
        text.replace("{name}", recipient.name or "Customer")
        .replace("{first_name}", (recipient.name or "Customer").split()[0])
    )


def _campaign_filter_snapshot(cleaned_data) -> dict:
    return {
        "audience": cleaned_data.get("audience"),
        "borrower_status": cleaned_data.get("borrower_status"),
        "loan_status": cleaned_data.get("loan_status"),
        "loan_category": cleaned_data.get("loan_category"),
        "location": cleaned_data.get("location"),
        "group_name": cleaned_data.get("group_name"),
        "preferred_language": cleaned_data.get("preferred_language"),
        "lead_status": cleaned_data.get("lead_status"),
    }


def _launch_marketing_campaign(request, cleaned_data, recipients: list[MarketingRecipient]) -> tuple[MarketingCampaign, int]:
    template = None
    template_id = cleaned_data.get("template_id")
    if template_id:
        template = MarketingTemplate.objects.filter(pk=template_id).first()

    campaign = MarketingCampaign.objects.create(
        title=cleaned_data["title"],
        template=template,
        channel=cleaned_data["channel"],
        audience_type=cleaned_data["audience"],
        objective=cleaned_data["objective"],
        status="SENT",
        subject=cleaned_data.get("subject", ""),
        message=cleaned_data["message"],
        call_to_action_label=cleaned_data.get("cta_label", ""),
        call_to_action_url=cleaned_data.get("cta_url", ""),
        filters_json=_campaign_filter_snapshot(cleaned_data),
        preview_count=len(recipients),
        created_by=request.user,
        last_sent_at=timezone.now(),
    )

    sent_count = 0
    logs = []

    for recipient in recipients:
        message_text = _render_marketing_copy(cleaned_data["message"], recipient)
        subject_text = _render_marketing_copy(cleaned_data.get("subject", ""), recipient)
        status = "SKIPPED"

        if campaign.channel == "SMS":
            if recipient.phone:
                safe_send_sms(recipient.phone, message_text)
                status = "SENT"
                sent_count += 1

        elif campaign.channel == "EMAIL":
            if recipient.email:
                send_company_email(
                    subject_text or campaign.title,
                    message_text,
                    [recipient.email],
                    fail_silently=True,
                )
                status = "SENT"
                sent_count += 1

        elif campaign.channel == "WHATSAPP":
            if recipient.phone:
                status = "COPIED"
                sent_count += 1

        logs.append(
            MarketingDispatchLog(
                campaign=campaign,
                channel=campaign.channel,
                recipient_name=recipient.name,
                recipient_phone=recipient.phone,
                recipient_email=recipient.email,
                recipient_segment=recipient.category,
                status=status,
                message_preview=message_text,
                created_by=request.user,
            )
        )

    if logs:
        MarketingDispatchLog.objects.bulk_create(logs)

    campaign.sent_count = sent_count
    campaign.save(update_fields=["sent_count", "updated_at"])
    return campaign, sent_count


@admin_required
def marketing_hub(request):
    latest_popup = WebsiteMarketingPopup.objects.order_by("-updated_at").first()
    active_popup = WebsiteMarketingPopup.get_live_popup()

    template_form = MarketingTemplateForm(prefix="template")
    campaign_form = MarketingCampaignLauncherForm(prefix="campaign")
    popup_form = WebsiteMarketingPopupForm(prefix="popup", instance=latest_popup)

    preview_recipients: list[MarketingRecipient] = []
    preview_count = 0
    ready_count = 0
    channel_note = ""

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "save_template":
            template_form = MarketingTemplateForm(request.POST, prefix="template")
            campaign_form = MarketingCampaignLauncherForm(prefix="campaign")
            popup_form = WebsiteMarketingPopupForm(prefix="popup", instance=latest_popup)
            if template_form.is_valid():
                template = template_form.save(commit=False)
                template.is_example = False
                template.save()
                messages.success(request, f"Marketing template '{template.title}' saved.")
                template_form = MarketingTemplateForm(prefix="template")

        elif action in {"preview_campaign", "send_campaign"}:
            campaign_form = MarketingCampaignLauncherForm(request.POST, prefix="campaign")
            template_form = MarketingTemplateForm(prefix="template")
            popup_form = WebsiteMarketingPopupForm(prefix="popup", instance=latest_popup)
            if campaign_form.is_valid():
                preview_recipients = build_marketing_recipients(
                    campaign_form.cleaned_data,
                    channel=campaign_form.cleaned_data["channel"],
                )
                preview_count = len(preview_recipients)
                ready_count = preview_count

                if campaign_form.cleaned_data["channel"] == "WHATSAPP":
                    channel_note = (
                        "WhatsApp campaigns are prepared as copy-ready message runs. "
                        "Recipient logs are stored, but direct WhatsApp delivery is not yet integrated."
                    )

                if action == "preview_campaign":
                    if not preview_recipients:
                        messages.warning(request, "No recipients matched the selected audience.")
                    else:
                        messages.success(request, f"Preview ready for {preview_count} recipient(s).")
                else:
                    if not preview_recipients:
                        messages.warning(request, "No recipients matched the selected audience. Nothing was sent.")
                    else:
                        campaign, sent_count = _launch_marketing_campaign(request, campaign_form.cleaned_data, preview_recipients)
                        if campaign.channel == "WHATSAPP":
                            messages.info(
                                request,
                                f"WhatsApp copy campaign '{campaign.title}' logged for {sent_count} recipient(s).",
                            )
                        else:
                            messages.success(
                                request,
                                f"Marketing campaign '{campaign.title}' processed for {sent_count} recipient(s).",
                            )

        elif action == "save_popup":
            popup_form = WebsiteMarketingPopupForm(
                request.POST,
                request.FILES,
                prefix="popup",
                instance=latest_popup,
            )
            campaign_form = MarketingCampaignLauncherForm(prefix="campaign")
            template_form = MarketingTemplateForm(prefix="template")
            if popup_form.is_valid():
                popup = popup_form.save(commit=False)
                if not popup.pk:
                    popup.created_by = request.user
                popup.save()
                if popup.is_active:
                    WebsiteMarketingPopup.objects.exclude(pk=popup.pk).update(is_active=False)
                messages.success(request, "Website marketing popup updated.")
                latest_popup = popup
                active_popup = WebsiteMarketingPopup.get_live_popup()
                popup_form = WebsiteMarketingPopupForm(prefix="popup", instance=latest_popup)

        elif action == "deactivate_popup":
            if latest_popup:
                latest_popup.is_active = False
                latest_popup.save(update_fields=["is_active", "updated_at"])
                active_popup = WebsiteMarketingPopup.get_live_popup()
                messages.warning(request, "Website marketing popup deactivated.")
            popup_form = WebsiteMarketingPopupForm(prefix="popup", instance=latest_popup)

        elif action == "update_lead":
            lead_id = request.POST.get("lead_id")
            new_status = request.POST.get("new_status")
            if lead_id and new_status:
                lead = WebsiteLead.objects.filter(pk=lead_id).first()
                allowed = {value for value, _ in WebsiteLead.STATUS_CHOICES}
                if lead and new_status in allowed:
                    lead.status = new_status
                    lead.save(update_fields=["status", "updated_at"])
                    messages.success(request, f"Lead '{lead.name}' marked as {lead.get_status_display()}.")

    templates = MarketingTemplate.objects.all()
    example_templates = templates.filter(is_example=True)
    custom_templates = templates.filter(is_example=False)[:8]
    recent_campaigns = MarketingCampaign.objects.select_related("template", "created_by")[:8]
    recent_dispatches = MarketingDispatchLog.objects.select_related("campaign", "created_by")[:12]
    leads = WebsiteLead.objects.all()[:10]

    active_borrowers = Borrower.objects.filter(status="ACTIVE").count()
    bad_borrowers = Borrower.objects.filter(status="BAD").count()
    sms_ready_contacts = (
        Borrower.objects.exclude(phone="").count()
        + Agent.objects.exclude(phone="").count()
        + WebsiteLead.objects.exclude(phone="").count()
    )
    email_ready_contacts = (
        Borrower.objects.exclude(email="").count()
        + Agent.objects.exclude(email="").count()
        + WebsiteLead.objects.exclude(email="").count()
    )

    lead_status_counts = []
    for value, label in WebsiteLead.STATUS_CHOICES:
        lead_status_counts.append(
            {
                "value": value,
                "label": label,
                "count": WebsiteLead.objects.filter(status=value).count(),
            }
        )

    popup_preview = active_popup or latest_popup

    context = {
        "title": "Marketing Center",
        "template_form": template_form,
        "campaign_form": campaign_form,
        "popup_form": popup_form,
        "example_templates": example_templates,
        "custom_templates": custom_templates,
        "recent_campaigns": recent_campaigns,
        "recent_dispatches": recent_dispatches,
        "leads": leads,
        "lead_status_counts": lead_status_counts,
        "website_lead_status_choices": WebsiteLead.STATUS_CHOICES,
        "active_popup": active_popup,
        "popup_preview": popup_preview,
        "preview_recipients": preview_recipients[:120],
        "preview_count": preview_count,
        "ready_count": ready_count,
        "channel_note": channel_note,
        "templates_count": templates.count(),
        "campaigns_count": MarketingCampaign.objects.count(),
        "leads_count": WebsiteLead.objects.count(),
        "sms_ready_contacts": sms_ready_contacts,
        "email_ready_contacts": email_ready_contacts,
        "active_borrowers": active_borrowers,
        "bad_borrowers": bad_borrowers,
        "dispatches_this_month": MarketingDispatchLog.objects.filter(created_at__month=timezone.now().month, created_at__year=timezone.now().year).count(),
    }
    return render(request, "communications/marketing_hub.html", context)


@staff_member_required
def management_message_center(request):
    form = ManagementSMSForm(request.POST or None)

    preview_recipients = []
    preview_count = 0
    sent_count = 0
    message_text = ""

    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "preview")
        cleaned = form.cleaned_data
        message_text = cleaned["message"]

        preview_recipients = build_recipients(cleaned)
        preview_count = len(preview_recipients)

        if action == "send":
            if not preview_recipients:
                messages.warning(request, "No recipients matched the current selection. Nothing was sent.")
            else:
                for recipient in preview_recipients:
                    safe_send_sms(recipient.phone, message_text)
                    sent_count += 1

                messages.success(request, f"{sent_count} message dispatch attempt(s) completed.")

    context = {
        "title": "Management Messaging Center",
        "form": form,
        "preview_recipients": preview_recipients[:200],
        "preview_count": preview_count,
        "sent_count": sent_count,
        "message_text": message_text,
    }
    return render(request, "communications/message_center.html", context)


@csrf_exempt
def _ussd_http_response(request, allowed_providers: set[str]) -> HttpResponse:
    if request.method not in {"GET", "POST"}:
        return HttpResponse(_ussd_end("Method not allowed."), content_type="text/plain", status=405)
    provider = get_company_ussd_config().get("provider", "")
    if provider and provider not in allowed_providers:
        return HttpResponse(_ussd_end("USSD provider mismatch."), content_type="text/plain", status=400)
    if not validate_company_ussd_request(request):
        return HttpResponse(_ussd_end("USSD authentication failed."), content_type="text/plain", status=403)

    phone_number = _extract_ussd_phone(request)
    text = _extract_ussd_text(request)
    response_text = _build_ussd_response(phone_number, text)
    return HttpResponse(response_text, content_type="text/plain")


@csrf_exempt
def hubtel_ussd(request):
    return _ussd_http_response(request, {"HUBTEL", "CUSTOM"})


@csrf_exempt
def arkesel_ussd(request):
    return _ussd_http_response(request, {"ARKESEL", "CUSTOM"})
