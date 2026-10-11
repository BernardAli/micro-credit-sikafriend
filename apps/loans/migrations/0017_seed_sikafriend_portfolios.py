import re

from django.db import migrations
from django.utils import timezone


PORTFOLIOS = [
    ("01", "Harvest", "Akoto Raphael"),
    ("02", "Greatness", "Akyedepa Kofi"),
    ("03", "Faith", "Samuel Nkrumah"),
    ("04", "Love", "Regina Asiedu"),
    ("05", "Victory", "Joseph Brobbey"),
    ("06", "Favour", "Hegar"),
    ("07", "Wisdom", "Elizabeth"),
    ("08", "Increase", "Fowaa"),
    ("09", "Blessing", "Sharif"),
    ("10", "Excellence", "Joseph Yaw"),
    ("11", "Star", "Mavis Boafo"),
]


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Portfolio = apps.get_model("loans", "Portfolio")
    Assignment = apps.get_model("loans", "PortfolioAssignment")
    Identity = apps.get_model("loans", "CustomerIdentity")
    Borrower = apps.get_model("loans", "Borrower")
    Loan = apps.get_model("loans", "Loan")
    Payment = apps.get_model("loans", "Payment")
    Agent = apps.get_model("accounts", "Agent")
    agents = list(Agent.objects.using(alias).filter(workforce_role="AGENT", employment_status="ACTIVE"))
    for number, name, officer in PORTFOLIOS:
        portfolio, _ = Portfolio.objects.using(alias).get_or_create(number=number, defaults={"name": name})
        # Exact unambiguous matches only. Partial names are reviewed by management.
        matches = [agent for agent in agents if " ".join(agent.name.split()).casefold() == officer.casefold()]
        if len(matches) == 1 and not Assignment.objects.using(alias).filter(portfolio=portfolio, ended_at__isnull=True).exists():
            Assignment.objects.using(alias).create(portfolio=portfolio, agent=matches[0], started_at=timezone.now())
    for borrower in Borrower.objects.using(alias).all().iterator():
        match = re.fullmatch(r"SF(0[1-9]|[1-9][0-9])(\d{4})", borrower.borrower_id)
        if not match or not 1 <= int(match[2]) <= 1000:
            continue
        portfolio, _ = Portfolio.objects.using(alias).get_or_create(number=match[1], defaults={"name": f"Portfolio {match[1]}"})
        Identity.objects.using(alias).get_or_create(customer_id=borrower.borrower_id, defaults={"portfolio": portfolio, "number": int(match[2]), "borrower": borrower})
        Borrower.objects.using(alias).filter(pk=borrower.pk).update(portfolio=portfolio)
        Loan.objects.using(alias).filter(borrower=borrower).update(portfolio=portfolio)
        Portfolio.objects.using(alias).filter(pk=portfolio.pk, next_customer_number__lte=int(match[2])).update(next_customer_number=int(match[2]) + 1)
    agent_by_user = dict(Agent.objects.using(alias).exclude(user_id=None).values_list("user_id", "pk"))
    loan_agents = dict(Loan.objects.using(alias).values_list("pk", "agent_name_id"))
    batch = []
    for payment in Payment.objects.using(alias).filter(collected_by__isnull=True).iterator():
        # Preserve the historical allocation for old repayments lacking a collector.
        payment.collected_by_id = agent_by_user.get(payment.submitted_by_id) or loan_agents.get(payment.loan_id)
        batch.append(payment)
        if len(batch) == 500:
            Payment.objects.using(alias).bulk_update(batch, ["collected_by"], batch_size=500)
            batch = []
    if batch:
        Payment.objects.using(alias).bulk_update(batch, ["collected_by"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("loans", "0016_portfolios_and_permanent_customer_ids")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
