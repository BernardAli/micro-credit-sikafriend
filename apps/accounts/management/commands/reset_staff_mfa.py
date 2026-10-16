from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.accounts.models import Authenticator
from apps.core.audit import log_activity


class Command(BaseCommand):
    help = "Owner-operated recovery after identity verification; retain the reason in the audit trail."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--reason", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        reason = options['reason'].strip()
        if not 10 <= len(reason) <= 1000:
            raise CommandError("Provide an identity-verification reason of 10–1,000 characters.")
        try:
            user = get_user_model().objects.select_for_update().get(username=options['username'])
        except get_user_model().DoesNotExist:
            raise CommandError("Account not found.")
        if not (user.is_staff or user.is_superuser or getattr(user, 'agent_profile', None)):
            raise CommandError("This command is restricted to staff recovery.")
        Authenticator.objects.filter(user=user).delete()
        log_activity(category="SYSTEM", action="MFA_OWNER_RECOVERY", message=reason,
                     object_type="User", object_id=user.pk, metadata={"source": "owner-console"})
        self.stdout.write("Authenticator reset recorded. The account must verify its password and enroll again.")
