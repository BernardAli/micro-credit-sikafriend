# Micro Credit ERP

For the complete operating, development, deployment, security, workflow, and troubleshooting handbook, see [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md).

Standalone Django ERP for running a single micro-credit company. It includes borrower and loan operations, repayment tracking, workforce and payroll, accounting, fixed assets, communications, a borrower self-service portal, and a configurable public company website.

## Current Architecture

This repository is the standalone edition:

- One Django project
- One database
- One company profile
- No `django-tenants`
- No subscription plans, tenant schemas, public SaaS dashboard, or Enterprise-owner API

Some internal field names still contain `tenant_` because they came from an earlier multi-tenant build. In this standalone edition they simply mean company-level email, SMS, and USSD settings.

## Main Modules

- `apps/company`: company profile, branding, public website content, channel integrations, database backup/export
- `apps/loans`: borrowers, loans, payments, statements, reports, imports, repayment collection workflow
- `apps/accounts`: agents/workforce, login helpers, payroll, statutory deductions, workforce imports
- `apps/accounting`: ledger accounts, journals, bank transactions, invoices, bills, budgets, operational accounting sync
- `apps/assets`: asset register, maintenance, depreciation, disposals, asset imports, accounting postings
- `apps/communication`: management SMS, marketing campaigns, website leads/popups, USSD callbacks
- `apps/borrower_portal`: borrower dashboard, loan detail, password change, payment initiation
- `apps/core`: approvals, audit logging, role helpers, standalone creation limits, pagination, backup helpers, checks
- `apps/notifications`: in-app notifications and optional email delivery

## Tech Stack

- Python 3.12+
- Django 6.0
- SQLite by default for local/standalone use
- OpenPyXL
- WeasyPrint
- Pillow
- `python-dotenv`
- Requests

## URL Map

- `/` public company website
- `/login/` staff, agent, and borrower login
- `/redirect/` role-based post-login redirect
- `/dashboard/` loan dashboard
- `/borrowers/` borrower management
- `/loans/` loan management
- `/agents/` workforce and payroll
- `/accounting/` accounting hub
- `/assets/` asset register
- `/communication/management/messages/` management message center
- `/communication/management/marketing/` marketing hub
- `/notifications/inbox/` notifications
- `/my-account/` borrower portal
- `/settings/` company settings
- `/setup/` first-run company setup

## Local Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create `.env`

Copy `.env.example` and edit the values you need:

```bash
cp .env.example .env
```

Useful settings:

```env
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=change-me-in-production
TIME_ZONE=Africa/Accra
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=no-reply@microcredit.local
ARKESEL_API_KEY=
ARKESEL_SENDER_ID=MicroCredit
PAYMENT_WEBHOOK_SECRET=
ALLOW_INSECURE_PAYMENT_WEBHOOKS=True
ALLOW_INSECURE_USSD_CALLBACKS=True
```

### 4. Apply migrations

```bash
python manage.py migrate
```

### 5. Create an admin user

```bash
python manage.py createsuperuser
```

### 6. Run the server

```bash
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

## Authentication and Roles

The project uses Django `User` plus profile links:

- Admin: `is_staff` or `is_superuser`, full back-office access
- Agent: linked to `Agent`, usually limited to their own portfolio
- Borrower: linked to `Borrower`, limited to `/my-account/`

All roles use `/login/`; `apps.core.roles.role_redirect_view` sends each user to the correct landing page.

## Standalone Behavior

- Borrower and agent usernames are stored as plain usernames.
- Tenant schema prefixes are not used.
- Cross-company debt checks are disabled and return a standalone message.
- Borrower and agent creation limits always allow local creation through `apps.core.limits`.
- Subscription and SaaS dashboards are not part of the active URL configuration.

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.core apps.accounts apps.loans apps.communication
```
