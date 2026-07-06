"""
apps/core/roles.py
──────────────────
Role helpers for the three user types:
  - Admin   : Django staff/superuser — full access to everything
  - Agent   : has agent_profile — sees only their own portfolio + borrowers
  - Borrower: has borrower_profile — sees only their own loan records

Single login URL for all user types; role_redirect_view routes them after login.
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required


# ─── Role detection ──────────────────────────────────────────────────────────

def get_user_role(user):
    """Return 'admin', 'agent', 'borrower', or None."""
    if not user or not user.is_authenticated:
        return None
    if user.is_staff or user.is_superuser:
        return "admin"
    if hasattr(user, "agent_profile"):
        try:
            _ = user.agent_profile  # triggers RelatedObjectDoesNotExist if not set
            return "agent"
        except Exception:
            pass
    if hasattr(user, "borrower_profile"):
        try:
            _ = user.borrower_profile
            return "borrower"
        except Exception:
            pass
    return None


def get_agent_for_user(user):
    """Return Agent instance if user is an agent, else None."""
    try:
        return user.agent_profile
    except Exception:
        return None


def get_borrower_for_user(user):
    """Return Borrower instance if user is a borrower, else None."""
    try:
        return user.borrower_profile
    except Exception:
        return None


# ─── Role-based redirect after login ─────────────────────────────────────────

@login_required
def role_redirect_view(request):
    """
    Called by LOGIN_REDIRECT_URL = '/redirect/'.
    Routes each user type to their correct landing page without separate dashboards.
    """
    role = get_user_role(request.user)
    if role == "admin":
        return redirect("loans:dashboard")
    if role == "agent":
        agent = get_agent_for_user(request.user)
        if agent:
            return redirect("agent_detail", pk=agent.pk)
        # Agent user with no profile — send to dashboard with message
        messages.warning(request, "Your agent profile is not configured yet. Contact admin.")
        return redirect("loans:dashboard")
    if role == "borrower":
        return redirect("borrower:portal")
    # Unknown role — admin should sort this out
    messages.error(request, "Your account type is not recognised. Contact admin.")
    return redirect("login")


def _role_redirect(request):
    """Internal: send user to their appropriate home after a permission denial."""
    role = get_user_role(request.user)
    if role == "agent":
        agent = get_agent_for_user(request.user)
        if agent:
            return redirect("agent_detail", pk=agent.pk)
    if role == "borrower":
        return redirect("borrower:portal")
    return redirect("loans:dashboard")


# ─── Context processor helper ─────────────────────────────────────────────────

def user_role_context(request):
    """
    Template context processor — adds 'user_role', 'agent_profile',
    and 'borrower_profile' to every template.
    Register in settings.py TEMPLATES context_processors.
    """
    role = get_user_role(request.user) if request.user.is_authenticated else None
    ctx = {"user_role": role}
    if role == "agent":
        ctx["agent_profile"] = get_agent_for_user(request.user)
    elif role == "borrower":
        ctx["borrower_profile"] = get_borrower_for_user(request.user)
    return ctx


# ─── Decorators ──────────────────────────────────────────────────────────────

def admin_required(view_func):
    """Allow only staff/superusers."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, "You don't have permission to access that page.")
            return _role_redirect(request)
        return view_func(request, *args, **kwargs)
    return wrapper


def agent_or_admin_required(view_func):
    """Allow agents (own portfolio only) and admins (all)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        role = get_user_role(request.user)
        if role not in ("admin", "agent"):
            messages.error(request, "You don't have permission to access that page.")
            return _role_redirect(request)
        return view_func(request, *args, **kwargs)
    return wrapper


def login_required_any(view_func):
    """Require login; redirect role-appropriately if not authenticated."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper
