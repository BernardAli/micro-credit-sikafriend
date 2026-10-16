from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.accounts.models import AuthenticationThrottle


class Command(BaseCommand):
    help = "Remove expired authentication budgets. Schedule this daily or hourly."

    def handle(self, *args, **options):
        count, _ = AuthenticationThrottle.objects.filter(expires_at__lte=timezone.now()).delete()
        self.stdout.write(f"Removed {count} expired authentication budgets.")
