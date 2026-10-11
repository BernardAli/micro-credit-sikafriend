"""Portfolio ownership, access, and audited assignment changes."""
import re
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.audit import log_activity
from apps.accounts.models import Agent
from .models import Borrower, Portfolio, PortfolioAssignment


def agent_portfolio_ids(agent):
    if agent is None or agent.employment_status != "ACTIVE":
        return Portfolio.objects.none().values_list("pk", flat=True)
    return PortfolioAssignment.objects.filter(agent=agent, ended_at__isnull=True, portfolio__is_active=True).values_list("portfolio_id", flat=True)


def agent_can_access(agent, record):
    return bool(record.portfolio_id and record.portfolio_id in agent_portfolio_ids(agent))


def loan_contact_agent(loan, payment=None):
    if payment and payment.collected_by_id and agent_can_access(payment.collected_by, loan):
        return payment.collected_by
    return Agent.objects.filter(portfolio_assignments__portfolio_id=loan.portfolio_id,
                                portfolio_assignments__ended_at__isnull=True,
                                employment_status="ACTIVE").order_by("pk").first() if loan.portfolio_id else None


def customer_lookup(reference):
    """Accept a permanent ID or a retained legacy reference without ambiguous matches."""
    matches = list(Borrower.objects.filter(Q(borrower_id__iexact=reference) | Q(legacy_borrower_id__iexact=reference))[:2])
    if len(matches) != 1:
        raise ValueError("Customer ID was not found or matches multiple customers.")
    return matches[0]


@transaction.atomic
def set_portfolio_agents(portfolio, agents, *, actor=None):
    portfolio = Portfolio.objects.select_for_update().get(pk=portfolio.pk)
    agents = list(agents)
    if any(not agent.is_field_agent or agent.employment_status != "ACTIVE" for agent in agents):
        raise ValidationError("Select active field agents for portfolio assignments.")
    desired = {agent.pk for agent in agents}
    current = portfolio.assignments.filter(ended_at__isnull=True)
    previous = set(current.values_list("agent_id", flat=True))
    current.exclude(agent_id__in=desired).update(ended_at=timezone.now())
    for agent in agents:
        if agent.pk not in previous:
            PortfolioAssignment.objects.create(portfolio=portfolio, agent=agent, assigned_by=actor)
    if previous != desired:
        log_activity(category="AGENT", action="portfolio_assignment_changed", actor=actor,
                     object_type="Portfolio", object_id=portfolio.pk, object_label=str(portfolio),
                     message=f"Updated officers for portfolio {portfolio.number}.",
                     metadata={"previous_agents": sorted(previous), "current_agents": sorted(desired)})


@transaction.atomic
def assign_customer(borrower, portfolio, *, actor=None, customer_id=""):
    borrower = Borrower.objects.select_for_update().get(pk=borrower.pk)
    old_portfolio = borrower.portfolio_id
    if customer_id:
        if not re.fullmatch(r"SF(0[1-9]|[1-9][0-9])\d{4}", customer_id) or not 1 <= int(customer_id[4:]) <= 1000:
            raise ValidationError("Use an SF Customer ID with portfolio 01–99 and customer number 0001–1000.")
        if hasattr(borrower, "identity"):
            if borrower.borrower_id != customer_id:
                raise ValidationError("An existing permanent Customer ID cannot be replaced.")
        else:
            # Explicit IDs already issued outside the app are accepted only here,
            # with uniqueness and portfolio checks performed by Borrower.save().
            borrower.legacy_borrower_id = borrower.borrower_id
            Borrower.objects.filter(pk=borrower.pk).update(borrower_id=customer_id)
            borrower.borrower_id = customer_id
    borrower.portfolio = portfolio
    borrower.save()
    log_activity(category="BORROWER", action="portfolio_assigned", actor=actor,
                 object_type="Borrower", object_id=borrower.pk, object_label=str(borrower),
                 message=f"Assigned customer {borrower.borrower_id} to portfolio {portfolio.number}.",
                 metadata={"previous_portfolio": old_portfolio, "portfolio": portfolio.pk,
                           "customer_id": borrower.borrower_id, "legacy_id": borrower.legacy_borrower_id})
    return borrower
