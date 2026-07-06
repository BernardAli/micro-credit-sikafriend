# Micro Credit ERP

Multi-tenant Django micro-credit platform for running isolated lending workspaces on one SaaS codebase. It combines borrower and loan operations, workforce and payroll, accounting, assets, communications, a borrower self-service portal, and a public marketing/subscription layer.

## Overview

This repository now runs as a `django-tenants` application with:

- A public SaaS schema for marketing pages, pricing, signup, subscription plans, and subscription management
- Separate tenant schemas for each onboarded company
- Tenant-specific company settings, branding, messaging keys, and website content
- Borrower, loan, repayment, accounting, payroll, and asset records isolated per tenant

## Major Features

- Public SaaS website with pricing, features, signup, contact, and subscriber account pages
- Tenant onboarding that provisions a new isolated schema per company
- Company settings for branding, public website pages, integrations, and statutory configuration
- Borrower management with portal logins and KYC/profile capture
- Loan origination, repayment tracking, statements, analytics, and approval workflows
- Cross-company borrower exposure check before loan approval across onboarded companies
- Automated repayment collection flow with reconciliation queue and webhook-style processing
- Workforce management for agents, HR, finance, recovery, operations, and management
- Payroll with statutory deductions, adjustments, commissions, loan recovery, and accounting sync
- Accounting hub with ledgers, journals, receivables, payables, budgets, bank control, and reports
- Fixed asset register with maintenance, depreciation, disposals, and ledger linkage
- Communication and marketing tools, including templates, dispatch history, leads, and website popups
- Borrower self-service portal for balances, loans, password change, and payment initiation
- Enterprise-owner API with bearer-key access to tenant data
- Subscription plans with borrower/agent caps, trial periods, and tenant-access enforcement
- Comprehensive demo seeding for a tenant workspace

## Tech Stack

- Python 3.12+
- Django 6.0
- PostgreSQL
- `django-tenants`
- `psycopg2-binary`
- OpenPyXL
- WeasyPrint
- Pillow
- `python-dotenv`

## Repository Layout

```text
micro-credit/
├── apps/
│   ├── accounting/
│   ├── accounts/
│   ├── assets/
│   ├── borrower_portal/
│   ├── communication/
│   ├── company/
│   ├── core/
│   ├── loans/
│   ├── notifications/
│   └── tenants/
├── config/
├── templates/
├── media/
├── requirements.txt
└── manage.py
```

## App Summary

- `apps/tenants`
  Public SaaS pages, signup, tenant provisioning, subscription plans, payments, subscription enforcement, and Enterprise API access.

- `apps/company`
  Company profile, website configuration, branding, setup workflow, integrations, and statutory settings.

- `apps/loans`
  Borrowers, loans, payments, importers, analytics, repayment collections, and approval-linked lending workflows.

- `apps/accounts`
  Workforce directory, staff and agent login management, payroll, and workforce imports.

- `apps/accounting`
  Ledger, journals, accounts, invoices, bills, budgets, cash/bank workflows, and reporting.

- `apps/assets`
  Asset register, categories, maintenance, depreciation, assignments, and disposals.

- `apps/communication`
  Marketing templates, campaigns, dispatches, leads, and website popup content.

- `apps/notifications`
  Internal in-app notifications.

- `apps/borrower_portal`
  Borrower-facing portal pages and payment actions.

- `apps/core`
  Shared roles, approvals, audit logging, pagination, and helpers.

## Public vs Tenant URLs

Public schema examples:

- `http://127.0.0.1:8000/`
- `/pricing/`
- `/features/`
- `/signup/`
- `/dashboard/` for SaaS subscription management
- `/account/` for a tenant owner’s subscription account
- `/api/v1/enterprise/...` for Enterprise-owner API access

Tenant schema examples:

- `http://allgift.localhost:8000/login/`
- `http://allgift.localhost:8000/dashboard/`
- `http://allgift.localhost:8000/settings/`
- `http://allgift.localhost:8000/borrowers/`
- `http://allgift.localhost:8000/agents/`
- `http://allgift.localhost:8000/accounting/`
- `http://allgift.localhost:8000/assets/`
- `http://allgift.localhost:8000/communication/`
- `http://allgift.localhost:8000/my-account/` for borrower portal access

## Local Setup

### 1. Prerequisites

- Python 3.12+
- PostgreSQL 14+ recommended
- System packages required by WeasyPrint on your OS

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create a `.env`

The project loads environment variables from `.env` in the repository root.

Example:

```env
DJANGO_DEBUG=true
DJANGO_SECRET_KEY=change-me
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,.localhost

PGDATABASE=micro_credit_db
PGUSER=postgres
PGPASSWORD=your-password
PGHOST=127.0.0.1
PGPORT=5432
PGCONN_MAX_AGE=60
PGTEST_DATABASE=test_micro_credit_db

MAIN_DOMAIN=localhost
SHOW_PUBLIC_IF_NO_TENANT_FOUND=true
PORT=8000

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=no-reply@microcredit.local
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false

ARKESEL_API_KEY=
ARKESEL_SENDER_ID=SikaFriend
ARKESEL_BASE_URL=https://sms.arkesel.com/api/v2

PAYMENT_WEBHOOK_SECRET=replace-with-a-long-random-secret
ALLOW_INSECURE_PAYMENT_WEBHOOKS=true
ALLOW_INSECURE_USSD_CALLBACKS=true

SAAS_NAME=SikaFriend
SAAS_TAGLINE=Professional Micro-Credit Management Platform
SAAS_SUPPORT_EMAIL=support@sikafriend.com
```

### 5. Create the PostgreSQL database

Example:

```sql
CREATE DATABASE micro_credit_db;
```

### 6. Apply migrations

For a clean local setup, run:

```bash
python manage.py migrate_schemas --shared
python manage.py migrate_schemas
```

If you already have an initialized environment and use the standard migrate flow in your setup, make sure all tenant and public migrations are applied before using the app.

If you are updating an existing environment, rerun the shared migration flow so the Enterprise API key table is created:

```bash
python manage.py migrate_schemas --shared
```

### 7. Seed subscription plans

```bash
python manage.py seed_plans
```

This creates the default `Starter`, `Professional`, and `Enterprise` plans, including borrower caps, agent caps, trial days, and feature flags.

### 8. Create a SaaS superuser

```bash
python manage.py createsuperuser
```

### 9. Start the development server

```bash
python manage.py runserver
```

Then open the public app at:

- `http://127.0.0.1:8000/`

After signup, tenant workspaces are reachable on subdomains such as:

- `http://allgift.localhost:8000/`

## First-Time Flow

### Public SaaS side

1. Visit `/signup/`
2. Choose a plan
3. Create a company and owner account
4. Let the platform provision the tenant schema and primary domain

### Tenant workspace side

1. Sign in on the tenant domain
2. Complete `/onboarding/`
3. Review `/settings/` and company setup
4. Configure branding, website content, messaging credentials, and statutory settings
5. Add staff, borrowers, and lending data

## Enterprise API

The platform includes a public-schema Enterprise API for eligible tenant owners.

Full endpoint reference:

- `ENTERPRISE_API.md`

### Access Rules

- Only Enterprise or API-enabled tenant subscriptions can use it
- Access is scoped to the owner's own tenant workspace
- Authentication can be:
  - a tenant owner session on the public schema
  - a bearer API key created from the owner account page
- Suspended, cancelled, and expired workspaces are blocked

### How to Get an API Key

1. Sign in as the tenant owner on the public domain
2. Open `/account/`
3. Find the `Enterprise API` section
4. Enter a key name
5. Click `Create API Key`

Important:

- The raw key is shown only once
- Store it securely
- If you lose it, create a new key and revoke the old one

### Endpoints

- `GET /api/v1/enterprise/overview/`
- `GET /api/v1/enterprise/borrowers/`
- `GET /api/v1/enterprise/loans/`
- `GET /api/v1/enterprise/payments/`

### Authentication Format

```http
Authorization: Bearer sk_live_...
```

Example:

```bash
curl -H "Authorization: Bearer <YOUR_API_KEY>" \
  http://localhost:8000/api/v1/enterprise/overview/
```

### Ready-to-Use HTTP File

The repository includes:

- `enterprise_api.http`

Set `@apiKey` in that file to your real Enterprise API key and run the requests from your editor or HTTP client.

## Subscription and Tenant Enforcement

The platform now enforces plan limits and tenant access rules:

- Borrower caps are enforced on borrower creation and borrower bulk import
- Agent caps are enforced on agent creation, login-based agent registration, and agent bulk import
- Tenant borrower and agent counts are synced automatically
- Trial-expired, suspended, and cancelled tenants are blocked from normal tenant workspace access and redirected to subscription recovery/onboarding

Related implementation areas:

- `apps/tenants/enforcement.py`
- `apps/tenants/middleware.py`
- `apps/loans/signals.py`
- `apps/accounts/signals.py`

## Borrower and Staff Login Notes

- Django auth lives in the shared/public schema
- Borrower portal usernames are tenant-scoped internally, so different companies can reuse the same visible borrower username safely
- Tenant login resolves the simple visible borrower username on the correct tenant domain
- Borrower password reset supports tenant username aliases

## Cross-Company Exposure Checks

When a company tries to issue a new loan, the system can check whether a borrower already has open debt at another onboarded company by matching borrower identity fields across tenant schemas.

Current behavior:

- External debt summary is shown on loan creation screens
- Loan request submission requires acknowledgement when external exposure exists
- Loan approval execution requires a review note if exposure exists

## Automated Repayment Collection

The project includes an automated repayment collection flow for borrower-initiated repayments:

- Mobile money, bank transfer, and card-style collection initiation
- Provider callback/webhook processing
- Auto-posting to repayments where valid
- Manual reconciliation queue for exceptions

## Demo Data

You can seed a comprehensive tenant workspace dataset, including long historical lending activity.

Example:

```bash
python manage.py seed_demo_data --schema allgift
```

Or by domain:

```bash
python manage.py seed_demo_data --domain allgift.localhost
```

Current demo seeding includes:

- 1,500 borrowers
- up to 5 years of history
- borrower portal logins
- active, closed, and defaulted loans
- repayments and automated repayment collections
- accounting, payroll, assets, marketing, notifications, and approvals

## Useful Management Commands

```bash
python manage.py seed_plans
python manage.py seed_demo_data --schema allgift
python manage.py send_subscription_notifications --warning-days 3
```

## Imports

The platform supports structured bulk import flows for:

- Borrowers
- Loans
- Agents
- Assets

Supported formats:

- CSV
- Excel (`.xlsx`)
- JSON
- XML

## Public Template Currency Formatting

Public SaaS templates now use a shared currency formatter for prices, plan totals, subscriber account values, and subscription dashboard amounts.

Primary template tags:

- `public_money`
- `public_money0`
- `public_money_number`
- `public_money_number0`
- `public_currency_symbol`

These live in:

- `apps/tenants/templatetags/public_money.py`

## Verification Commands

Common checks while developing:

```bash
python manage.py check
python -m py_compile apps/tenants/enforcement.py
python manage.py test
```

## Media and Static Files

- Uploaded files live under `media/`
- `MEDIA_URL` is `/media/`
- In development, Django serves media and static files when `DEBUG=True`

## Notes

- This repository may contain a dirty working tree during active development
- Tenant provisioning, subscription enforcement, and schema-based isolation are central to the current architecture
- If you change plans, signup, or tenant access behavior, update both the public SaaS layer and the tenant workspace layer together
