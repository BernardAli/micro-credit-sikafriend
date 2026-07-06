from .models import CompanyProfile


def company_profile(request):
    try:
        profile = CompanyProfile.get_solo()
    except Exception:
        profile = None

    if profile is None:
        return {
            "company": None,
            "company_name": "MicroCredit",
            "company_tagline": "Micro-Credit Enterprise",
            "company_currency": "GHS",
            "company_theme": "forest",
        }

    # Role context
    from apps.core.roles import get_user_role, get_agent_for_user, get_borrower_for_user
    role = get_user_role(request.user)

    return {
        "company": profile,
        "company_name": profile.company_name,
        "company_tagline": profile.tagline,
        "company_currency": profile.formatted_currency,
        "company_theme": profile.color_theme,
        # Role helpers available in every template
        "user_role": role,
        "is_admin": role == "admin",
        "is_agent": role == "agent",
        "is_borrower": role == "borrower",
        "current_agent": get_agent_for_user(request.user) if role == "agent" else None,
        "current_borrower": get_borrower_for_user(request.user) if role == "borrower" else None,
    }
