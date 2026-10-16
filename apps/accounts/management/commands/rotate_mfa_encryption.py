from django.core.management.base import BaseCommand
from django.db import transaction
from apps.accounts.models import Authenticator
from apps.accounts.security import cipher


class Command(BaseCommand):
    help = "Re-encrypt authenticator secrets with the first configured MFA key; keep old keys during rotation."

    @transaction.atomic
    def handle(self, *args, **options):
        encryptor = cipher()
        count = 0
        for device in Authenticator.objects.select_for_update().all().iterator(chunk_size=100):
            device.secret_ciphertext = encryptor.rotate(device.secret_ciphertext.encode()).decode()
            device.save(update_fields=['secret_ciphertext'])
            count += 1
        self.stdout.write(f"Re-encrypted {count} authenticator records; credentials were not printed.")
