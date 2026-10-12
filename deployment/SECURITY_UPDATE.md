# Security and financial integrity update — 12 October 2026

The cumulative package `backups/sikafriend-security-update-20261012.zip` includes the portfolio/dashboard changes and repairs from the project review.

The dashboard loads repayment and security-deposit totals in grouped queries and reuses loan records for recent payments. Portfolio counts use independent totals to avoid multiplying customer, loan, and issued-ID rows. The Loan Portfolios card appears below Comprehensive Management Reports. These dashboard changes require no additional database migration.

Portfolio overview pages use grouped activity totals without loading detailed payment or ID registers. Detail pages retain complete registers and exports, reuse grouped repayment/deposit balances, and load officer history with its related users in one query. Customer assignment pages fetch only the displayed customer and loan-officer fields. Assignment CSV exports fetch permanent IDs together with customers rather than querying each customer separately. Filters, current ownership, transfer history, and financial totals are preserved; no additional migration is needed.

Borrower, loan, and agent profiles now offer printable statements with a shared branded A4 layout, PDF preview/download, repeating table headers, and page numbers. Borrower and loan statements include full receipt and deposit histories, running loan balances, principal/interest allocations, customer credit, pending/void entries, and recorded terms. Agent statements include current portfolio coverage, recorded collections, and complete payroll history. Existing ownership checks apply to previews and PDFs; borrowers can print their own accounts through the portal, and agents can print their own statement and currently assigned customers. Undated deposit applications and records awaiting management review remain explicit. This feature requires no migration.

Transaction reversals now use an independent administrator approval workflow. Source records remain available, ledger offsets use the approval date, and loan, customer credit, deposit, payroll and asset balances update together. Statements show original receipts/applications and separate negative reversal movements with references, approvers and reasons. These controls require the additional migrations listed below.

## Protect credentials and existing data

Arrange a maintenance window and stop financial writes. Download a MySQL backup and copies of the source, production `.env`, and uploads using [the backup procedure](PORTFOLIO_UPDATE.md).

The removed `db.txt` contained deployment secrets. Rotate the hosted MySQL password through PythonAnywhere, update the production `.env`, and rotate `DJANGO_SECRET_KEY` and `PAYMENT_WEBHOOK_SECRET`. Update callback senders with the new webhook secret. Rotating the Django key logs out existing sessions; do not retain the exposed key in `SECRET_KEY_FALLBACKS`. Change any other account where the database password was reused.

The removed `restore_data.json` contained customer records and password hashes. Review access and reset affected login passwords. Owner-only local copies are preserved under ignored `backups/private/pre-hardening-20261012/`; never publish them. This source update cannot change hosted credentials or remove earlier Git commits.

Remove these files from shared Git history. Run `git filter-repo --invert-paths --path db.txt --path restore_data.json` in a fresh mirror clone after coordinating replacement of the shared history. Removing files in a new commit cannot invalidate credentials copied earlier.

## Install and migrate

Extract the package inside the existing hosted project. Keep its production `.env`, database, WSGI configuration, and upload directories.

```bash
cd ~/micro-credit-sikafriend
unzip -o sikafriend-security-update-20261012.zip
source /path/to/existing/virtualenv/bin/activate
pip install -r requirements.txt
rm -f db.txt restore_data.json
python manage.py check
python manage.py migrate
python manage.py collectstatic --noinput
```

This release requires Django 6.0.9 and migrations through `core.0003`, `accounting.0007`, `accounts.0009`, `assets.0002`, and `loans.0021`. They add the approval-linked reversal register, protected transaction history, reversal links and source dates, private upload storage, preservation of already-serviced loan eligibility, a unique provider receipt register, customer credit balances, and liability account 2066. Schema migrations do not reverse, replace or delete existing customer/financial records. Do not generate migrations on the host or use `--fake`.

## Request and approve transaction reversals

Open **Transaction Reversals** from the management menu, or use **Request reversal** on a receipt, deposit, cashbook, payroll, depreciation or manual journal record. Assigned officers can submit requests for receipts and deposits in their current portfolios; accounting and payroll requests require an administrator. Only an active administrator can execute a reversal, and the reviewer must differ from the requester, including for superusers and management accounts.

1. Check the source transaction and supporting cash evidence. Enter a clear reason and, where available, a receipt, incident or reconciliation reference.
2. Submit the request. Submission changes no financial balance. A pending request can be withdrawn by its requester.
3. A different administrator opens the case through **Approvals** or the reversal register, reviews the source and proposed ledger offsets, and enters a review note before approving or rejecting.
4. Approval rechecks the source under row locks and executes atomically. The case receives a permanent `REV-000001` style reference, actor/date history, source snapshot and links to posted offsets. Print the case record for the reconciliation file.

| Source | Effect of an approved reversal |
| --- | --- |
| Settled loan repayment | Excludes the receipt from current collections and credit; restores outstanding principal/interest and recalculates loan/customer status. Original cash, dates, allocations and references remain visible. |
| Security deposit collection, refund or application | Removes the original effect from held funds; an application reversal also restores loan principal outstanding. |
| Deposit carry-forward | Restores the source deposit and reduces the target; combined held funds and the deposit liability ledger stay unchanged. |
| Posted cashbook/bank entry | Offsets the original posting, including both accounts of a bank transfer. |
| Unsettled posted invoice/bill | Voids the document, offsets the accrual and removes its outstanding balance from aging. |
| Paid payroll run | Cancels the run and offsets all its posted costs, deductions and payment; employee lines and the original paid timestamp remain available. |
| Manual general journal | Posts an equal offset while retaining the original entry. Operational postings must use their source workflow. |
| Posted depreciation run | Cancels the run, offsets depreciation and restores the affected asset book values. |

Original journals remain posted as evidence with linked offsets. Offsets must fall in the current open accounting period; a closed period or other posting failure rolls back every financial change and preserves the failed review result. Unposted receipts/payroll need no offset and remain excluded from future ledger sync. Reversed provider receipts remain reserved; callbacks and reconciliation cannot reactivate them.

Duplicate pending requests, repeated execution, changed source/ledger records, mismatched postings and invalid loan allocations are blocked. Used deposit funds require reversal of later movements first. Later depreciation or a recorded disposal requires reconciliation before reversing earlier depreciation. Settled/partially settled documents, future-dated transactions, loan disbursements and asset disposals require a separate management reconciliation; the general journal screen cannot bypass operational source controls. The five deferred historical loans still require management's agreed terms.

Reversals correct recorded errors. They do not initiate a bank/provider refund or recover cash from a customer or employee. Arrange genuine cash movements and use the appropriate receipt/refund process. A reversal cannot be undone; record a new, verified transaction when a replacement is needed. Django admin financial records and approval/audit evidence are read-only; direct receipt void/restore and paid-payroll cancellation shortcuts are removed. Historical allocation repair preserves completed reversal evidence.

## Protect uploads

Remove the PythonAnywhere Web tab mapping for the entire `/media/` directory. Keep only:

| URL | Directory |
| --- | --- |
| `/static/` | `/home/YOUR_USERNAME/micro-credit-sikafriend/staticfiles` |
| `/media/company/` | `/home/YOUR_USERNAME/micro-credit-sikafriend/media/company` |

Never map `/private-media/`, `/media/borrowers/`, or `/media/agents/` directly to disk. Django checks management access, assigned portfolios, and borrower ownership. A host-level `/media/` mapping bypasses these checks.

New identity images use `private-media/` with owner-only permissions. Existing files remain readable through authenticated URLs while being moved:

```bash
python manage.py secure_private_uploads
python manage.py secure_private_uploads --apply
```

The first command is a dry run. The second validates destinations, then moves borrower/workforce files. Public company media stays under `media/company/`. Include `private-media/` in secure backups.

## Reconcile historical financial records

The update prevents new defects. Historical excess receipts are held as customer credit, as instructed by management. Cash receipt amounts, dates, references, and ownership are preserved. Loan principal and interest allocations are capped at the agreed schedule after applied deposits. Customer credit is a liability, separate from security deposits and income, and is visible in borrower accounts, statements, and portfolio exports. It is held until a separately authorized refund or application; this update does not spend that credit.

```bash
mkdir -p backups/private/security-update
chmod 700 backups/private backups/private/security-update
python manage.py audit_financial_integrity --report backups/private/security-update/before.json
python manage.py repair_payment_allocations --report backups/private/security-update/repair-preview.json
python manage.py repair_payment_allocations --apply --report backups/private/security-update/repair-applied.json
python manage.py audit_financial_integrity --fail --report backups/private/security-update/after.json
```

The audit and repair preview change no records. Review the preview against receipts and retain the database backup before applying. Repairs run atomically and refuse invalid schedules or nonpositive receipt amounts rather than inventing missing terms. The private repair report contains the previous and corrected allocations. Credit-bearing receipts without a linked journal are posted in the current open period; existing linked journals are reversed and replaced. All cash is debited once per linked receipt, with credits to principal, interest, and liability account 2066. Original journals remain as evidence, and corrected journals retain the receipt's source date. Closed periods reject new postings; a closed current period causes the whole repair to roll back.

The Accounting Hub's operational sync also reverses postings for voided/deleted repayments and replaces corrected postings. Repeating the repair or sync does not post the same receipt twice. Duplicate provider receipts and collection/status mismatches still require source evidence; the allocation repair does not change them.

If specific loan terms need clarification, management may defer those reviewed IDs with repeated `--exclude-loan ID` arguments on both preview and apply. They remain unchanged and appear in the report's `excluded_loans`. Confirm their agreed terms from the original contract, correct the terms through the normal management workflow, then rerun the repair without exclusions. Do not infer a new repayment total solely from receipts.

No live payment-provider initiation is configured in this edition. Borrowers submit payment details for staff verification; the form does not charge wallets or cards. Simulation routes/buttons are removed. Trusted callbacks and manual reconciliation remain protected and idempotent.

## Reload and verify

Reload the web application and verify:

1. Role-based login/navigation, light/dark themes, portfolios, statements, imports, and exports.
2. Simulation URLs return 404; payment confirmation/rejection requires POST and CSRF protection.
3. Unassigned accounts cannot view loans or post repayments. Logged-out/unrelated users cannot access identity files, including old URLs.
4. Tiny partial payments leave unpaid installments overdue; overpayments are rejected; applied deposits reduce remaining principal.
5. Repeated approvals/callbacks do not create duplicate loans/payments. A test reversal requires a different administrator and a review note, retains the source record, updates balances once, and appears in statements. Failed reversals/depreciation runs leave no partial financial writes.
6. The integrity audit completes and every historical finding receives management review.

Rollback requires matching pre-update source/database backups with writes stopped. Keep private upload directories and secure media mappings; do not restore exposed secrets or public identity-document mappings.
