from collections import Counter
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from apps.accounts.models import Agent
from apps.loans.models import Borrower, Loan, Payment


class Command(BaseCommand):
    help = "Copy legacy users, agents, borrowers, loans and payments into the current schema."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if "legacy" not in connections.databases:
            raise CommandError("Set LEGACY_DB_NAME, LEGACY_DB_USER, LEGACY_DB_PASSWORD and LEGACY_DB_HOST.")
        if connections["legacy"].settings_dict["NAME"] == connections["default"].settings_dict["NAME"]:
            raise CommandError("Legacy and default databases must be different.")
        self.counts = Counter()
        self.warnings = []
        self._check_tables()
        try:
            with transaction.atomic():
                users = self._users()
                agents = self._agents(users)
                borrowers = self._borrowers(users)
                loans = self._loans(agents, borrowers)
                self._payments(loans)
                for loan in set(loans.values()):
                    loan.refresh_status()
                for borrower in set(borrowers.values()):
                    borrower.refresh_status()
                if options["dry_run"]:
                    transaction.set_rollback(True)
        except Exception as exc:
            raise CommandError(f"Import rolled back: {exc}") from exc
        label = "DRY RUN (rolled back)" if options["dry_run"] else "COMMITTED"
        self.stdout.write(self.style.SUCCESS(f"Legacy import {label}"))
        for kind in ("users", "agents", "borrowers", "loans", "payments"):
            self.stdout.write(f"{kind}: created={self.counts[kind + '_created']} existing={self.counts[kind + '_existing']}")
        for warning in self.warnings[:50]:
            self.stdout.write(self.style.WARNING(warning))

    def _rows(self, table):
        with connections["legacy"].cursor() as cursor:
            cursor.execute(f"SELECT * FROM `{table}` ORDER BY id")
            names = [item[0] for item in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _check_tables(self):
        required = {"auth_user", "accounts_agent", "loans_borrower", "loans_loan", "loans_payment"}
        with connections["legacy"].cursor() as cursor:
            found = set(connections["legacy"].introspection.table_names(cursor))
        if required - found:
            raise CommandError(f"Missing legacy tables: {', '.join(sorted(required - found))}")

    def _users(self):
        User = get_user_model(); result = {}
        for row in self._rows("auth_user"):
            user = User.objects.filter(username=row["username"]).first()
            if user:
                self.counts["users_existing"] += 1
            else:
                user = User.objects.create(username=row["username"], password=row["password"],
                    first_name=row["first_name"], last_name=row["last_name"], email=(row["email"] or "").lower(),
                    is_active=bool(row["is_active"]), is_staff=False, is_superuser=False,
                    date_joined=row["date_joined"], last_login=row["last_login"])
                self.counts["users_created"] += 1
            result[row["id"]] = user
        return result

    def _agents(self, users):
        result = {}
        for row in self._rows("accounts_agent"):
            obj = Agent.objects.filter(agent_id=row["agent_id"]).first()
            if obj: self.counts["agents_existing"] += 1
            else:
                user = users.get(row["user_id"])
                if user and Agent.objects.filter(user=user).exists(): user = None
                obj = Agent.objects.create(user=user, agent_id=row["agent_id"], name=row["name"], phone=row["phone"],
                    email=user.email if user else "", location=row["location"], photo=row["photo"] or None,
                    ghana_card_front=row["ghana_card_front"] or None, ghana_card_back=row["ghana_card_back"] or None,
                    ghana_card_number=row["ghana_card_number"] or None, group_name=row["group_name"])
                Agent.objects.filter(pk=obj.pk).update(created_at=row["created_at"]); self.counts["agents_created"] += 1
            result[row["id"]] = obj
        return result

    def _borrowers(self, users):
        result = {}
        for row in self._rows("loans_borrower"):
            obj = (Borrower.objects.filter(borrower_id=row["borrower_id"]).first()
                   or Borrower.objects.filter(national_id=row["national_id"]).first())
            if obj: self.counts["borrowers_existing"] += 1
            else:
                user = users.get(row["user_id"])
                if user and Borrower.objects.filter(user=user).exists(): user = None
                obj = Borrower.objects.create(user=user, borrower_id=row["borrower_id"], full_name=row["full_name"],
                    national_id=row["national_id"], phone=row["phone"], location=row["location"], photo=row["photo"],
                    ghana_card_front=row["ghana_card_front"], ghana_card_back=row["ghana_card_back"],
                    ghana_card_number=row["ghana_card_number"], group_name=row["group_name"],
                    preferred_language=row["preferred_language"] or "Twi", status=row["status"] or "CLOSED")
                Borrower.objects.filter(pk=obj.pk).update(created_at=row["created_at"]); self.counts["borrowers_created"] += 1
            result[row["id"]] = obj
        return result

    def _loans(self, agents, borrowers):
        result = {}
        for row in self._rows("loans_loan"):
            agent, borrower = agents.get(row["agent_name_id"]), borrowers.get(row["borrower_id"])
            if not agent or not borrower:
                self.warnings.append(f"loan {row['id']} skipped: missing relationship"); continue
            obj = Loan.objects.filter(borrower=borrower, agent_name=agent, amount=row["amount"],
                start_date=row["start_date"], weekly_payment=row["weekly_payment"], created_at=row["created_at"]).first()
            if obj: self.counts["loans_existing"] += 1
            else:
                obj = Loan.objects.create(borrower=borrower, agent_name=agent, amount=row["amount"],
                    duration_weeks=row["duration_weeks"], start_date=row["start_date"],
                    weekly_payment=row["weekly_payment"], status=row["status"])
                Loan.objects.filter(pk=obj.pk).update(created_at=row["created_at"]); self.counts["loans_created"] += 1
            result[row["id"]] = obj
        return result

    def _payments(self, loans):
        for row in self._rows("loans_payment"):
            loan = loans.get(row["loan_id"])
            if not loan: self.warnings.append(f"payment {row['id']} skipped: missing loan"); continue
            obj = Payment.objects.filter(loan=loan, payment_date=row["payment_date"], amount=row["amount"],
                reference=row["reference"], created_at=row["created_at"]).first()
            if obj: self.counts["payments_existing"] += 1; continue
            obj = Payment.objects.create(loan=loan, payment_date=row["payment_date"], amount=row["amount"],
                reference=row["reference"], note=row["note"], is_void=bool(row["is_void"]), payment_method="CASH")
            Payment.objects.filter(pk=obj.pk).update(principal_paid=Decimal(row["principal_paid"]),
                roic_paid=Decimal(row["roic_paid"]), created_at=row["created_at"])
            self.counts["payments_created"] += 1
