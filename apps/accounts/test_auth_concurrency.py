from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth.models import User
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from .models import Authenticator
from .security import cipher, new_recovery_codes, reserve_attempt, verify_code
import pyotp


@skipUnlessDBFeature('has_select_for_update')
class AuthenticationConcurrencyTests(TransactionTestCase):
    def concurrent(self, operation):
        barrier = Barrier(2)
        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation(index)
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, range(2)))

    def test_single_use_recovery_code_cannot_authenticate_two_sessions(self):
        user = User.objects.create_user('parallel-security-admin', is_staff=True)
        codes, hashes = new_recovery_codes()
        Authenticator.objects.create(user=user, confirmed_at=timezone.now(),
                                     secret_ciphertext=cipher().encrypt(pyotp.random_base32().encode()).decode(), recovery_hashes=hashes)
        results = self.concurrent(lambda index: verify_code(User.objects.get(pk=user.pk), codes[0]) is not None)
        self.assertEqual(results.count(True), 1)

    def test_shared_attempt_budget_cannot_be_overspent(self):
        results = self.concurrent(lambda index: reserve_attempt('parallel-budget', 'same-account', 1))
        self.assertEqual(results.count(0), 1)
