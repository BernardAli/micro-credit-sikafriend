# Security and performance update — 12 October 2026

This release strengthens authentication, limits expensive requests and reduces financial-report memory use. It updates the local project; PythonAnywhere installation and hosted configuration still require verification on the hosting account.

## Changes

- Administrators, management users and field officers must enroll an authenticator. Borrowers can enable one through Account Security. Verification also covers Django admin and private media.
- Authenticator secrets are encrypted with independent Fernet keys. Codes cannot be replayed; recovery codes are hashed, shown once and consumed once. Replacing recovery codes invalidates other MFA sessions. Suspended/exited workforce users cannot sign in, and their existing sessions are cleared when used.
- Password, recovery, MFA and public-contact attempts use shared database budgets. Proxy address headers are accepted only from explicitly trusted networks. Password recovery gives the same response for existing and unknown accounts. Temporary credentials use cryptographic randomness and staff-created/reset passwords use Django validators.
- Authenticated responses use private/no-store cache headers. Health monitoring requires a Bearer token and returns only availability status. PDF resource fetching rejects network URLs and access outside approved public assets.
- Imports reject oversized files, excessive rows, expanded spreadsheets, deeply nested JSON and XML entities/DTDs. Spreadsheet reading is streamed. Expensive exports are limited to six per account per minute.
- The dashboard uses database receipt summaries and keyset batches of 500 loans. Visible registers retain 50 loans, 12 receipts and bounded leaderboards. Newest-loan ordering is explicit. The management business PDF reuses these summaries and escapes customer/company text.
- Portfolio screens aggregate receipt analytics and fetch the displayed payment/pipeline/ID page in the database. Complete exports retain all matching records and ownership checks. Receipt and loan indexes support these queries.
- MySQL application backups use a repeatable-read, read-only snapshot. SQL exports retain timestamp microseconds and handle string escaping for the target database.
- CI checks repository hygiene, dependencies, production security defaults, migrations and tests on SQLite and MySQL. CI uses synthetic databases and credentials.

## Local verification

All **226 tests pass on MySQL**, including financial row-locking tests. SQLite discovers the same 226 tests: 217 pass and nine requiring database features it does not provide are skipped. Dependency auditing checks 31 packages and reports no known vulnerabilities in the patched runtime requirements. Production-default, migration-drift, compilation and repository checks pass. Actual WeasyPrint rendering also passes for the management report and borrower, loan and agent statements using isolated fictional training records. The 121-page client PDF contains authenticator instructions and excludes internal loan-review details. [The verification record](../docs/verification/security_performance_20261012.json) records these results; rerun the checks after later changes.

An isolated synthetic benchmark used 3,000 loans and 60,000 receipts. Dashboard generation under Python allocation tracing changed from **53.549 seconds / 104.28 MiB peak Python memory** to **7.660 seconds / 2.92 MiB**. Financial totals, charts and summary boards matched the prior implementation. Recent-loan ordering was deliberately corrected. Rendering, network latency and hosted load are excluded; these figures are not hosted response-time guarantees. Batching increased query count from 9 to 25 to bound memory on MySQL as well as SQLite.

Both the native MySQL backup and the newly generated application SQL backup were restored into a private, network-disabled test instance. Hash comparisons matched every row in five core customer/financial tables. The local application's root database connection was replaced with a random-password account scoped to its own database, without changing root credentials. The new account can connect and create application backups. Private backups and environment files remain ignored and owner-only. These local credentials must not be copied to PythonAnywhere.

The five loans awaiting management's agreed terms remain unchanged: **1688, 2058, 2683, 2693 and 3084**. Live payment initiation remains unconfigured; portal requests require verified staff confirmation.

## PythonAnywhere installation

The local release package is `backups/sikafriend-security-performance-update-20261012.zip`. It includes source, migrations, static assets, deployment instructions, verification evidence and the 121-page client manual. It excludes environment files, customer uploads, databases, dumps, virtual environments, commercial quotations and Git metadata. Each packaged file has a checksum in `RELEASE_MANIFEST.json`. Build a fresh copy after source changes with:

```bash
python scripts/build_release.py --output backups/sikafriend-security-performance-update-20261012.zip
```

1. Arrange a maintenance window. Preserve a consistent hosted database backup, source release, production environment, public company media and private uploads. Restore-test a backup in a separate database. Keep the encryption keys needed by that backup.
2. Use Python 3.12 or later and a compatible system image. Install the updated requirements; WeasyPrint 70 uses its new URLFetcher API. Test statement/report rendering on the host.
3. Keep the hosted database and environment. Configure a fresh independent Fernet key in `MFA_ENCRYPTION_KEYS`, set `STAFF_MFA_REQUIRED=True`, and choose a random `HEALTHCHECK_TOKEN`. Configure allowed hosts, HTTPS/cookies, proxy handling and callback secrets as described in [the deployment guide](PYTHONANYWHERE.md). Do not trust `0.0.0.0/0` or `::/0` as proxy networks. Use the provider's database account and restrict its scope where the platform permits.
4. Apply the supplied migrations, including `accounts.0010` and `loans.0022`. Do not use `--fake` or generate new migrations on the host. Collect static files, run checks, then reload.

```bash
source /path/to/existing/virtualenv/bin/activate
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
```

Generate an MFA key in a protected operator console with `Fernet.generate_key()`. Store it in the production environment and password manager; never commit or send it in a public support message. Keep it independently from `DJANGO_SECRET_KEY` so a Django-key rotation does not destroy authenticator access.

5. Enroll at least two administrators, securely retain their recovery codes, and verify staff/officer/borrower access. Test that password-only sessions cannot access admin, financial views or private media. Verify export throttling, statements, portfolio totals, a controlled independent reversal and failed-operation rollback.
6. Run concurrency tests against a **separate synthetic MySQL test database**. Never set the Django test database name to the production database. Reconcile historical financial findings using [SECURITY_UPDATE.md](SECURITY_UPDATE.md), retaining the five exclusions until management confirms their terms.
7. Verify the authenticated `/health/` endpoint from the monitoring system. Schedule `python manage.py prune_auth_throttles` daily or hourly. Configure the provider's error/availability monitoring and secure backups.

Previously exposed hosted credentials and shared Git history still require the owner actions in [SECURITY_UPDATE.md](SECURITY_UPDATE.md). Checking local values does not prove hosted credentials were rotated. This update does not rewrite shared Git history, initiate provider payments or issue cash refunds.

## Account recovery and key rotation

Users with a lost device can sign in with their password and an unused recovery code. They can replace recovery codes through Account Security using a current password and fresh authenticator code.

If a staff member loses both, the authorized server operator must verify their identity and record the reason:

```bash
python manage.py reset_staff_mfa USERNAME --reason "Identity verified by management; device and recovery codes unavailable."
```

This requires fresh password verification and enrollment. It does not change the password or financial records. The event remains in the activity history.

To rotate encryption keys, back up the database and environment, put the new key first in `MFA_ENCRYPTION_KEYS` while retaining the old keys, and run:

```bash
python manage.py rotate_mfa_encryption
```

Retain previous keys until outstanding enrollment/recovery sessions expire, and retain their versions securely for older encrypted backups. Verify recovery before retiring any key.

## Release checks

```bash
python scripts/check_repository_hygiene.py
python scripts/check_production_defaults.py
python -m pip check
python -m pip_audit --disable-pip --no-deps -r requirements.txt
DB_ENGINE=sqlite python manage.py test --settings=config.test_settings --noinput
```

`check_production_defaults.py` uses synthetic configuration to verify the source defaults. Run the real `manage.py check --deploy` on the hosting account as well. The offline client manual now includes authenticator setup and recovery instructions; share that edition with end users.
