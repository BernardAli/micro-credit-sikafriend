# SikaFriend Micro-Credit ERP

Comprehensive operating, development, and deployment documentation for the standalone SikaFriend Micro-Credit Enterprise platform.

## 1. System Purpose

SikaFriend Micro-Credit ERP manages the complete operating cycle of one micro-credit company:

- Public company website and customer enquiries
- Borrower onboarding and identity records
- Loan applications, controlled approvals, disbursement, and statements
- Repayment recording, confirmation, online collection, and reconciliation
- Workforce records, access accounts, payroll, and statutory calculations
- General accounting, banking, invoices, bills, and budgets
- Fixed assets, maintenance, depreciation, assignment, and disposal
- SMS, email, marketing, USSD, and in-app notifications
- Borrower self-service portal
- Audit history, approval controls, reports, imports, and backups

This repository is the **standalone edition**. It operates one company profile and one database. It does not use tenant schemas, subscriptions, or a SaaS owner portal.

## 2. Technology Stack

| Layer | Technology |
| --- | --- |
| Application | Python 3.12+, Django 6.0 |
| Database | SQLite by default |
| Templates | Django Templates, HTML, CSS, JavaScript |
| Spreadsheet import | OpenPyXL |
| PDF generation | WeasyPrint |
| Images | Pillow |
| HTTP integrations | Requests |
| Configuration | python-dotenv and `.env` |

## 3. Repository Structure

```text
apps/
  accounting/       Ledger, journals, banking, invoices, bills, budgets
  accounts/         Workforce, agents, payroll, user-account helpers
  assets/           Asset register, maintenance, depreciation, disposal
  borrower_portal/  Borrower self-service pages
  communication/    Leads, campaigns, SMS, email, USSD
  company/          Company profile, public website, branding, backups
  core/             Roles, approvals, audit trail, checks, shared helpers
  loans/            Borrowers, loans, repayments, reports, collections
  notifications/    In-app and optional email notifications
config/              Django settings, URL routing, WSGI and ASGI
static/              Public images and other static assets
templates/           Dashboard, public website, portal, and module templates
manage.py            Django management entry point
setup.sh             First-time environment setup
run.sh               Development server launcher
```

## 4. Installation

### Automated setup

```bash
bash setup.sh
```

The script creates `.venv`, installs dependencies, creates `.env`, applies migrations, and prompts for a superuser.

### Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

If port 8000 is occupied:

```bash
python manage.py runserver 127.0.0.1:8001
```

## 5. Configuration

### Development minimum

```env
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=local-development-secret
TIME_ZONE=Africa/Accra
```

### Production minimum

```env
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_ALLOWED_HOSTS=credit.example.com
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
DJANGO_SECURE_HSTS_PRELOAD=True
```

When HTTPS terminates at a trusted reverse proxy:

```env
DJANGO_TRUST_PROXY_HTTPS=True
```

Do not enable this unless the proxy removes untrusted forwarded headers.

### Email

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DEFAULT_FROM_EMAIL=no-reply@example.com
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=<username>
EMAIL_HOST_PASSWORD=<secret>
EMAIL_USE_TLS=true
```

Company Settings can override channel configuration. Fields retaining a `tenant_` prefix are legacy field names and represent company-level settings in this edition.

### SMS

```env
ARKESEL_API_KEY=<api-key>
ARKESEL_SENDER_ID=SikaFriend
ARKESEL_BASE_URL=https://sms.arkesel.com/api/v2
```

### Payment webhooks

```env
PAYMENT_WEBHOOK_SECRET=<strong-shared-secret>
ALLOW_INSECURE_PAYMENT_WEBHOOKS=False
```

### USSD callbacks

Configure the provider, API key, shortcode, username, and callback token in Company Settings. Production deployments should set:

```env
ALLOW_INSECURE_USSD_CALLBACKS=False
```

## 6. Authentication and Roles

All users sign in through `/login/`. `/redirect/` sends each account to the correct workspace.

### Administrator

A Django user with `is_staff` or `is_superuser`. Administrators can manage back-office modules. Only administrators can access governance queues.

### Management workforce user

An account linked to an `Agent` record whose `workforce_role` is `MANAGEMENT`. Management access normally also requires Admin Console Access so the user is marked as staff.

### Agent

A user linked through `Agent.user`. Agents see their own portfolio, assigned borrowers, lending activities, collections, and notifications.

### Borrower

A user linked through `Borrower.user`. Borrowers can access only their own portal, loans, statements, password, and payment initiation.

### Username compatibility

New accounts use plain usernames. Accounts migrated from the tenant edition with names such as `schema__username` can still authenticate using the visible `username` alias.

## 7. Company Setup and Branding

Use `/setup/` for first configuration and `/settings/` for later changes.

Company settings include:

- Legal and contact details
- Logo, favicon, public color scheme, and fonts
- Loan tiers, rates, duration, and repayment defaults
- Public website headlines, pages, services, team, FAQs, and testimonials
- Email, SMS, and USSD channel settings
- Tax, pension, payroll, and statutory configuration
- Public documents, partners, awards, and branch information

The SikaFriend logo asset is stored at `static/website/images/sikafriend-logo.webp` and is used by the public site and dashboard when no uploaded logo overrides it.

## 8. Borrower Management

Main routes:

- `/borrowers/` directory
- `/borrowers/new/` create borrower
- `/borrowers/<id>/` borrower detail
- `/borrowers/<id>/edit/` update borrower
- `/borrowers/import/` bulk import
- `/borrowers/analytics/` analysis

Borrower records include identity, contacts, Ghana Card documents, demographic information, location, group, assigned agent, status, portal user, loans, and payment history.

An administrator can create or reset a borrower portal login from the borrower detail page.

## 9. Loan Lifecycle

### 9.1 Application

An administrator or agent opens `/loans/new/`, selects a borrower and agent, and completes the application, repayment, declaration, guarantor, collateral, and approval information.

Submitting the form does **not** create a loan immediately. It creates an `ApprovalRequest` with workflow `LOAN_CREATION` and status `PENDING`.

### 9.2 Loan Requests queue

Loan applications appear only at `/loan-requests/`. They are separated from payroll, accounting, and asset approvals.

The reviewer may:

- Approve and execute the request
- Reject the request
- Add a review note

### 9.3 Maker-checker policy

By default, a submitting user cannot review their own request. Self-review is allowed only when the submitting user:

- Is a Django superuser, or
- Has a linked workforce record with role `MANAGEMENT`

This exception applies to approval and rejection.

### 9.4 Execution

Approval creates the actual loan inside a database transaction. The system then:

- Links borrower and responsible agent
- Refreshes borrower status
- Sends configured borrower and agent SMS messages
- Builds the loan statement
- Creates notifications
- Writes approval and loan audit events

Execution errors mark the request `FAILED`. No partially executed approval should be treated as successful.

### 9.5 Approval statuses

| Status | Meaning |
| --- | --- |
| `PENDING` | Waiting for review |
| `EXECUTED` | Approved and applied successfully |
| `REJECTED` | Declined by reviewer |
| `FAILED` | Execution attempted but failed |
| `CANCELLED` | Withdrawn or cancelled |

## 10. Repayments and Collections

Repayments can be entered against a loan and may require confirmation depending on the workflow.

Important routes:

- `/loans/<id>/payments/new/` enter payment
- `/payments/pending/` pending confirmations
- `/payments/<id>/confirm/` confirm payment
- `/payments/<id>/reject/` reject payment
- `/payments/reconciliation/` reconciliation queue
- `/payments/collections/webhook/<provider>/` provider callback

Online collections use a `RepaymentCollection` record to track client reference, provider reference, status, raw callback data, reconciliation, and resulting payment.

Production webhooks must be protected by `PAYMENT_WEBHOOK_SECRET`. Never enable insecure callbacks in production.

## 11. Statements, Analytics, and Reports

- `/loans/<id>/statement/` statement view
- `/loans/<id>/statement/pdf/` statement PDF
- `/reports/` reports center
- `/reports/business-state/pdf/` business state PDF
- `/loans/analytics/` loan analysis
- `/loans/monthly-analytics/` monthly performance
- `/borrowers/analytics/` borrower analysis

Reports include portfolio balances, collections, principal and return components, PAR indicators, status distributions, agent performance, borrower exposure, locations, groups, and time-series data.

## 12. Workforce and Payroll

### Workforce

- `/agents/` workforce directory
- `/agents/agents/new/` create workforce member
- `/agents/agents/<id>/` employee details
- `/agents/agents/import/` bulk import
- `/agents/agents/register/` create workforce login

Employee detail pages contain Overview, Payroll, and Portfolio tabs. Records include role, department, reporting line, contacts, compensation, payment details, emergency information, compliance IDs, documents, access, and portfolio performance.

### Payroll

- `/agents/payroll/` payroll center
- `/agents/payroll/<id>/` payroll run detail

Payroll supports fixed salary, recurring allowances, collection commissions, earnings, deductions, statutory breakdowns, adjustments, payroll lines, and run approval.

Payroll approval requests appear at `/approvals/`, not Loan Requests.

## 13. Accounting

The accounting hub is `/accounting/`.

Core records include:

- Accounting periods
- Ledger accounts
- Counterparties
- Journal entries and lines
- Bank accounts and transactions
- Customer invoices
- Supplier bills
- Budgets and budget lines

Sensitive accounting journals can use the approval workflow. Approved journals are executed from `/approvals/` and recorded in `/audit/`.

## 14. Fixed Assets

The asset hub is `/assets/`.

The module supports:

- Categories and asset items
- Acquisition and carrying values
- Assignment to workforce
- Maintenance history
- Depreciation runs and lines
- Disposal requests
- Accounting postings
- CSV, Excel, JSON, and XML imports

Asset disposal approval requests appear at `/approvals/`.

## 15. Governance

### Loan Requests

`/loan-requests/` contains only loan applications.

### Approvals

`/approvals/` contains only payroll, accounting, and asset workflows.

### Audit Trail

`/audit/` records actors, categories, actions, affected objects, messages, metadata, IP addresses, and timestamps. It supports search and category filtering.

Do not treat application logs as a substitute for database backups.

## 16. Communications

### Management messages

`/communication/management/messages/` sends targeted SMS messages to workforce and borrower groups. Recipient selection supports operational filters and normalized Ghana phone numbers.

### Marketing

`/communication/management/marketing/` manages templates, campaigns, dispatch logs, audience selection, and public marketing popups.

### Website leads

The public `/contact/` form stores `WebsiteLead` records and notifies an administrator. It includes CSRF protection, a honeypot, and cache-backed per-IP throttling. Persistence failures display an error instead of a false success confirmation.

### USSD

- `/communication/hubtel/ussd/`
- `/communication/arkesel/ussd/`

USSD callbacks validate company configuration and callback authentication before returning account or loan information.

## 17. Borrower Portal

Borrower routes begin with `/my-account/`:

- Overview and loan list
- Individual loan details
- Password change
- Payment initiation

Authorization always scopes data to the authenticated borrower profile.

## 18. Public Website

Public routes:

- `/` home
- `/about/`
- `/services/`
- `/services/<slug>/`
- `/team/`
- `/documents/`
- `/contact/`
- `/privacy-policy/`

Content and visibility are managed through Company Settings. Public team listings intentionally avoid exposing internal workforce IDs.

## 19. Imports

Borrowers, loans, workforce, and assets support bulk import. Supported formats vary by module and include CSV, XLSX, JSON, and XML.

Recommended process:

1. Download the sample for the selected format.
2. Preserve column names and identifiers.
3. Test with a small file.
4. Review row-level errors.
5. Use upsert only when intentional updates are required.
6. Back up the database before large imports.

## 20. Backup and Restore

Use `/settings/database-backup/` to inspect and export the database. Available formats are defined by the backup helper and may include native database and structured exports.

For SQLite, an offline copy can also be made after stopping writes:

```bash
cp db.sqlite3 backups/db-$(date +%Y%m%d-%H%M%S).sqlite3
```

Restore procedure:

1. Stop the application.
2. Back up the current database.
3. Replace `db.sqlite3` with the verified backup.
4. Run `python manage.py migrate`.
5. Run `python manage.py check`.
6. Start the application and verify critical totals.

## 21. Testing and Quality Checks

Run the complete suite:

```bash
python manage.py test
```

Run focused suites:

```bash
python manage.py test apps.core
python manage.py test apps.accounts
python manage.py test apps.loans
python manage.py test apps.communication
```

Static checks:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
git diff --check
```

Production security check:

```bash
DJANGO_DEBUG=False \
DJANGO_SECRET_KEY='<long-random-secret>' \
DJANGO_ALLOWED_HOSTS='credit.example.com' \
python manage.py check --deploy
```

## 22. Production Deployment

Recommended sequence:

1. Provision Python, database storage, TLS, and a reverse proxy.
2. Create `.venv` and install `requirements.txt`.
3. Configure production environment variables.
4. Run `python manage.py migrate`.
5. Run `python manage.py collectstatic --noinput`.
6. Run `python manage.py check --deploy`.
7. Start a production WSGI or ASGI server.
8. Proxy HTTPS traffic to the application.
9. Configure persistent media and backup storage.
10. Verify login, loan request, approval, payment, and backup workflows.

Do not use Django's development server in production.

## 23. Troubleshooting

### `TemplateDoesNotExist`

Confirm the file exists under `templates/`, verify `TEMPLATES[0]["DIRS"]`, then restart the application process. A stale server may continue serving an older checkout.

### `NoReverseMatch` or unregistered namespace

Confirm the app's `urls.py` defines `app_name` and is included by `config/urls.py`. Active core names include `core:loan_requests`, `core:approvals`, and `core:audit_trail`.

### Form submits but appears unchanged

Check the visible validation summary. Tabbed forms automatically open the first panel containing an invalid field. Also inspect server logs for persistence or upload errors.

### User cannot approve own request

Self-review requires either `is_superuser=True` or a linked workforce record with role `MANAGEMENT`. Ordinary staff remain subject to maker-checker separation.

### SMS does not send

Check provider, API key, sender ID, number normalization, network access, and application logs. Incomplete configuration intentionally skips dispatch.

### Password reset email does not arrive

Confirm the user has an email, the backend is SMTP rather than console, credentials are valid, and the mail provider accepts the configured sender.

### Port already in use

Start another local port:

```bash
python manage.py runserver 127.0.0.1:8001
```

### SQLite is locked

Reduce concurrent writes, stop duplicate development servers, and consider a production database when concurrency grows.

## 24. Operational Checklist

### Daily

- Review Loan Requests and other Approvals
- Review pending payments and reconciliation
- Monitor overdue loans and PAR indicators
- Check notifications, failed callbacks, and communication logs
- Confirm previous-day collections

### Weekly

- Export a verified database backup
- Review agent and borrower performance
- Reconcile bank and online payment records
- Review audit activity and failed approvals
- Check upcoming payroll adjustments

### Monthly

- Close and review payroll
- Review accounting periods and journals
- Run depreciation where applicable
- Produce management reports
- Test restoration of a recent backup
- Review workforce access and inactive accounts

## 25. Important Security Rules

- Never commit `.env`, API secrets, passwords, or production databases.
- Use HTTPS and secure cookies in production.
- Require secrets for payment and USSD callbacks.
- Give Admin Console Access only to appropriate workforce roles.
- Review management and superuser accounts regularly because they can self-review requests.
- Keep borrower, workforce, payroll, and identity documents private.
- Back up before imports, migrations, or bulk corrections.
- Preserve audit records and investigate failed approval executions.

## 26. Primary Code References

| Concern | Location |
| --- | --- |
| Settings | `config/settings.py` |
| Root routing | `config/urls.py` |
| Roles | `apps/core/roles.py` |
| Approval rules and execution | `apps/core/approvals.py` |
| Approval and audit screens | `apps/core/views.py` |
| Loan workflows | `apps/loans/views.py`, `apps/loans/services.py` |
| Loan models | `apps/loans/models.py` |
| Workforce and payroll | `apps/accounts/models.py`, `apps/accounts/views.py` |
| Accounting | `apps/accounting/models.py`, `apps/accounting/views.py` |
| Assets | `apps/assets/models.py`, `apps/assets/views.py` |
| Company configuration | `apps/company/models.py`, `apps/company/views.py` |
| Communications | `apps/communication/views.py`, `apps/company/messaging.py` |
| Dashboard shell | `templates/base.html` |
| Public website | `templates/website/` |

