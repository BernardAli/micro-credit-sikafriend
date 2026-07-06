# Micro Credit ERP Project Manual

This manual reflects the current codebase in this repository as inspected on 2026-05-23. It is intended to be both a technical guide for developers and an operating guide for admins working on the platform.

## 1. What This Project Is

This repository is a multi-tenant Django micro-credit ERP and SaaS platform.

It combines two products in one codebase:

1. A public SaaS layer
   - Marketing website
   - Pricing and feature pages
   - Tenant signup
   - Subscription dashboard
   - Promo codes and referral tracking

2. A tenant workspace layer
   - Borrower management
   - Loan issuance and repayment tracking
   - Workforce and payroll
   - Accounting and journals
   - Asset management
   - Internal notifications
   - Marketing and outbound messaging
   - Borrower self-service portal
   - Tenant-configurable public website

The project uses `django-tenants`, so each customer company gets its own PostgreSQL schema for operational data while the SaaS/public records live in the `public` schema.

## 2. Core Architecture

### 2.1 Multi-tenancy model

- Public schema:
  - Subscription plans
  - Tenants and domains
  - Promo codes
  - Tenant payments
  - Tenant API keys
  - SaaS signup and pricing pages

- Tenant schemas:
  - Company profile and branding
  - Borrowers, loans, payments, collections
  - Agents and payroll
  - Accounting data
  - Assets
  - Notifications
  - Communication and marketing records

### 2.2 URL split

- Public routes are served by `config.urls_public`.
- Tenant routes are served by `config.urls_tenant`.
- `TenantMainMiddleware` resolves the current hostname to a tenant schema.
- In development, `SHOW_PUBLIC_IF_NO_TENANT_FOUND = True`, so unknown hosts fall back to the public schema instead of throwing a tenant 404.

### 2.3 Authentication model

There are three effective user types:

- Admin
  - Django `is_staff` or `is_superuser`
  - Full access to tenant modules

- Agent
  - Linked to `apps.accounts.models.Agent`
  - Restricted to their own portfolio in many views

- Borrower
  - Linked to `apps.loans.models.Borrower`
  - Restricted to the borrower portal only

All tenant users log in through the same tenant login URL and are redirected by role after login.

## 3. Repository Map

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

### 3.1 App responsibilities

- `apps.tenants`
  - Public SaaS pages, subscription plans, tenant provisioning, referrals, promo codes, payments, subscription enforcement, tenant onboarding, Enterprise API access

- `apps.company`
  - Tenant company profile, branding, messaging integration overrides, public website content, database backup/export

- `apps.loans`
  - Borrowers, loans, repayments, statements, analytics, cross-company debt checks, repayment collection workflow, import tools

- `apps.accounts`
  - Agents/workforce directory, admin access flags, payroll runs, payroll adjustments, staff account helpers, agent import tools

- `apps.accounting`
  - Ledger accounts, journal entries, periods, bank accounts, bank transactions, invoices, bills, budgets, operational sync into accounting

- `apps.assets`
  - Asset register, categories, assignments, maintenance, depreciation, disposals, asset import tools, accounting postings

- `apps.communication`
  - Management SMS center, marketing templates and campaigns, website leads, website popup content, USSD endpoints

- `apps.notifications`
  - Internal in-app notifications, optionally emailed through tenant/company SMTP settings

- `apps.borrower_portal`
  - Borrower dashboard, payment initiation, password change, loan self-service

- `apps.core`
  - Approval queue, activity logs, role helpers, pagination, backup/export helpers, system checks

## 4. Runtime Stack

- Python 3.12+
- Django 6.0.2
- PostgreSQL via `django_tenants.postgresql_backend`
- `django-tenants`
- `psycopg2-binary`
- `openpyxl`
- `weasyprint`
- `pillow`
- `python-dotenv`

Important note:

- The repository contains `db.sqlite3`, but the active settings use PostgreSQL, not SQLite.
- Treat PostgreSQL as the real runtime database.

## 5. Configuration

### 5.1 Environment variables

The app reads `.env` from the repository root.

Required or commonly used settings:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `PGDATABASE`
- `PGUSER`
- `PGPASSWORD`
- `PGHOST`
- `PGPORT`
- `PGTEST_DATABASE`
- `PGCONN_MAX_AGE`
- `MAIN_DOMAIN`
- `SHOW_PUBLIC_IF_NO_TENANT_FOUND`
- `EMAIL_BACKEND`
- `DEFAULT_FROM_EMAIL`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`
- `EMAIL_USE_SSL`
- `ARKESEL_API_KEY`
- `ARKESEL_SENDER_ID`
- `ARKESEL_BASE_URL`
- `PAYMENT_WEBHOOK_SECRET`
- `ALLOW_INSECURE_PAYMENT_WEBHOOKS`
- `ALLOW_INSECURE_USSD_CALLBACKS`
- `SAAS_NAME`
- `SAAS_TAGLINE`
- `SAAS_SUPPORT_EMAIL`

Useful behavior notes:

- `MAIN_DOMAIN=localhost` supports local tenant URLs like `tenant.localhost:8000`.
- `TIME_ZONE` is currently set to `Africa/Accra`.
- `DJANGO_DEBUG=true` is intended for local development. In production, set it to `false`, provide `DJANGO_SECRET_KEY`, set `DJANGO_ALLOWED_HOSTS`, and disable insecure callback fallbacks.

### 5.2 Shared vs tenant apps

Shared/public apps:

- `django_tenants`
- Django auth/admin/session/static apps
- `apps.tenants`

Tenant apps:

- `apps.accounts`
- `apps.loans`
- `apps.notifications`
- `apps.core`
- `apps.communication`
- `apps.company`
- `apps.borrower_portal`
- `apps.accounting`
- `apps.assets`

## 6. Local Setup and First Boot

### 6.1 Prerequisites

- Python 3.12+
- PostgreSQL
- System libraries required by WeasyPrint

### 6.2 Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` based on `.env.example`.

Create the PostgreSQL database:

```sql
CREATE DATABASE micro_credit_db;
```

### 6.3 Migrations and public tenant bootstrap

Run schema migrations:

```bash
python manage.py migrate_schemas --shared
python manage.py migrate_schemas
```

Create the public tenant and map development hosts:

```bash
python manage.py create_public_tenant --domain localhost 127.0.0.1
```

If you are updating an existing environment after pulling the Enterprise API changes, rerun the shared migrations so the API key table is created:

```bash
python manage.py migrate_schemas --shared
```

Seed the default subscription plans:

```bash
python manage.py seed_plans
```

Create a superuser for the public/admin layer:

```bash
python manage.py createsuperuser
```

Run the server:

```bash
python manage.py runserver
```

### 6.4 Local URLs

Public:

- `http://127.0.0.1:8000/`
- `http://localhost:8000/`
- `http://localhost:8000/api/v1/enterprise/overview/`

Tenant examples:

- `http://allgift.localhost:8000/login/`
- `http://allgift.localhost:8000/dashboard/`
- `http://allgift.localhost:8000/my-account/`

## 7. First-Time Operating Flow

### 7.1 SaaS/public flow

1. Visit `/signup/`
2. Select a subscription plan
3. Enter company name, owner details, subdomain, and password
4. The system creates:
   - a `Tenant`
   - a primary `Domain`
   - a public-schema owner `User`
   - a tenant schema
5. The system bootstraps:
   - tenant `CompanyProfile`
   - default chart of accounts
6. The owner is logged into the public schema account flow and shown the tenant onboarding link

### 7.2 Tenant workspace flow

1. Open the tenant subdomain
2. Log in
3. Complete `/onboarding/`
4. Review `/settings/`
5. Configure company profile, repayment defaults, payroll tax settings, and website content
6. Start creating agents, borrowers, loans, and supporting records

## 8. Public SaaS Layer

### 8.1 Public pages

Routes include:

- `/`
- `/features/`
- `/pricing/`
- `/about/`
- `/contact/`
- `/terms/`
- `/privacy/`
- `/signup/`

### 8.2 Plans

Default plans are seeded by `seed_plans`:

- Starter
  - Monthly: `250.00`
  - Yearly: `2500.00`
  - Borrowers: 50
  - Agents: 2
  - Admins: 1
  - Features: public website only

- Professional
  - Monthly: `650.00`
  - Yearly: `6500.00`
  - Borrowers: 200
  - Agents: 10
  - Admins: 3
  - Features: website, accounting, assets, marketing, payroll

- Enterprise
  - Monthly: `1500.00`
  - Yearly: `15000.00`
  - Unlimited caps
  - Features include API, white-label, and custom domain flags

### 8.3 Subscription dashboard

The public subscription dashboard supports:

- Tenant search and filtering
- Plan CRUD
- Tenant subscription status changes
- Tenant payment review
- Promo code management
- Referral tracking
- SaaS KPI charts and revenue summaries

### 8.4 Promo codes and referrals

The public layer supports:

- Fixed or percentage promo codes
- Tier-restricted promo codes
- Trial bonus days
- Usage limits
- Tenant referral codes
- Referral conversion tracking after confirmed payment

### 8.5 Payment behavior

Current implementation note:

- Tenant owner payments created from `/payment/` are immediately stored as `CONFIRMED` and then activate the subscription in code.
- This is effectively an internal/manual confirmation flow, not a live external billing integration yet.

### 8.6 Enterprise API

The public schema now exposes an Enterprise-owner API for tenant data access.

Detailed reference:

- `ENTERPRISE_API.md`

Access rules:

- Only Enterprise or API-enabled tenant subscriptions can use it
- Access is tenant-scoped to the owner’s own workspace
- Authentication can be:
  - a tenant owner session on the public schema
  - a bearer API key created from the owner account page
- Suspended, cancelled, and expired tenant workspaces are blocked from API access

How owners get a key:

1. Sign in on the public domain as the tenant owner
2. Open `/account/`
3. Go to the `Enterprise API` section
4. Enter a key name
5. Click `Create API Key`
6. Copy the raw key immediately because it is shown only once

Available endpoints:

- `GET /api/v1/enterprise/overview/`
- `GET /api/v1/enterprise/borrowers/`
- `GET /api/v1/enterprise/loans/`
- `GET /api/v1/enterprise/payments/`

Authentication format:

```http
Authorization: Bearer sk_live_...
```

Repository helper:

- `enterprise_api.http` contains ready-to-run requests for all current Enterprise API endpoints

## 9. Tenant Access Control and Subscription Enforcement

Subscription enforcement middleware blocks authenticated tenant users from normal workspace routes when:

- the tenant is `SUSPENDED`
- the tenant is `CANCELLED`
- the trial has expired
- the tenant is otherwise not active

Allowed routes during a blocked state include:

- login/logout
- password reset
- onboarding
- pricing/account/payment
- public info pages

The block redirects users to tenant onboarding with an explanatory message.

The platform also enforces plan limits for:

- borrower creation
- agent creation

The tenant record keeps cached `borrower_count` and `agent_count`, synchronized from tenant schema data.

## 10. Roles and Permissions

### 10.1 Admin

- Full tenant access
- Approves workflows
- Can manage payroll, accounting, assets, company settings, communications, and borrowers
- Can access Django admin

### 10.2 Agent

- Usually limited to own borrowers and loans
- Can create borrowers
- Can submit loan creation requests
- Can record payments on assigned loans
- Can see own portfolio analytics

### 10.3 Borrower

- Accesses borrower portal only
- Can view their loans and payment history
- Can change password
- Can initiate payment requests

## 11. Company Setup and Branding

`apps.company` centers on a single-row `CompanyProfile` per tenant schema.

Major configuration areas:

- Identity
  - company name, tagline, description, logo, favicon

- Contact
  - phone, email, address, website

- Locale
  - currency code and symbol
  - country
  - timezone

- Lending defaults
  - repayment cycle
  - default loan duration
  - overdue grace periods

- Statutory/payroll config
  - payroll tax switches
  - employee/employer pension rates
  - welfare deduction rules
  - payroll tax brackets
  - payable/expense ledger account codes
  - VAT/NHIL/GETFund/withholding/corporate tax reference rates

- Public website content
  - hero content and carousel
  - mission, vision, goals, values
  - services
  - testimonials
  - FAQs
  - team/management
  - gallery
  - branches
  - partners/certifications/awards
  - colors and font choices
  - SEO fields

- Messaging overrides
  - tenant SMTP transport
  - tenant SMS config
  - tenant USSD config

### 11.1 Tenant website

The tenant website is multi-page:

- `/`
- `/about/`
- `/services/`
- `/services/<slug>/`
- `/team/`
- `/contact/`
- `/privacy-policy/`

This website is data-driven from `CompanyProfile`.

### 11.2 Database backup/export

Tenant admins can use the company settings area to export database backups in:

- JSON
- XML
- CSV ZIP bundle
- Excel workbook
- SQL dump

These exports come from application-level serializers and table walkers in `apps.core.db_backups`.

## 12. Borrower Management

### 12.1 Borrower data captured

Each borrower stores:

- borrower ID
- full name
- national ID
- phone and email
- location
- photo
- Ghana card images
- Ghana card number
- group name
- preferred language
- linked portal user
- computed status

### 12.2 Borrower statuses

- `ACTIVE`
  - has active loan exposure with outstanding balance

- `CLOSED`
  - no active or bad exposure remains

- `BAD`
  - has defaulted exposure or severe overdue exposure

### 12.3 Borrower creation flow

When a borrower is created:

1. The system checks the tenant borrower limit
2. A portal username is captured
3. The actual Django username is tenant-scoped as `<schema>__<visible_username>`
4. A random temporary password is generated
5. A borrower login user is created
6. SMS is sent to the borrower
7. If an agent created the borrower, that agent also gets a credential notification SMS

### 12.4 Borrower bulk import

Admins can bulk import borrowers from:

- CSV
- Excel
- JSON
- XML

Sample import files can be downloaded from the borrower import page.

## 13. Loan Management

### 13.1 Loan data

Key fields include:

- borrower
- agent
- principal amount
- loan category
- duration in weeks
- start date
- periodic payment amount
- status

Derived values include:

- total expected repayment
- ROIC amount
- principal outstanding
- ROIC outstanding
- total paid
- overdue weeks
- number of expected vs actual installments

### 13.2 Loan categories

Categories default to:

- Bronze
- Silver
- Gold
- Platinum
- Diamond
- Executive

But categorization is actually driven by tenant `CompanyProfile.loan_tiers`.

### 13.3 Loan approval workflow

Loan creation does not directly issue the loan.

Instead:

1. Admin or agent submits a loan request
2. The system creates an `ApprovalRequest`
3. A different admin must approve it
4. Approval execution creates the actual `Loan`
5. Borrower status is refreshed
6. SMS notifications are sent
7. A statement notification is generated

### 13.4 Cross-company debt check

Before loan creation, the system can check other onboarded companies for borrower exposure using:

- national ID
- Ghana card number

If external debt is found:

- the request can still proceed
- but the UI requires acknowledgement
- and the approver may need to add an approval note

This is one of the most important risk-control features in the platform.

### 13.5 Loan views and analytics

Tenant users can access:

- dashboard
- all loans list
- active loans list
- borrower analytics
- borrower status analytics
- loan analytics
- monthly loan analytics
- loan detail page with charts
- statement page
- statement PDF
- business state PDF report

## 14. Payment and Collection Workflows

### 14.1 Manual staff-recorded payments

Staff can record payments directly against a loan. When saved:

- principal/ROIC allocation is stored
- loan and borrower status are refreshed
- SMS notifications are sent
- activity is logged

### 14.2 Borrower-submitted pending payments

Borrowers can submit payments through the portal in non-auto mode.

These create `Payment` records with:

- `is_pending=True`

Staff then:

- confirm the payment, which posts it
- or reject it, which voids it

The borrower gets an in-app notification either way.

### 14.3 Repayment collection flow

For auto-collection methods:

- `MOBILE_MONEY`
- `BANK`
- `CARD`

the portal creates a `RepaymentCollection` instead of a pending manual payment.

Collection statuses include:

- `PENDING`
- `PROCESSING`
- `SUCCEEDED`
- `MANUAL_REVIEW`
- `FAILED`
- `RECONCILED`

### 14.4 Reconciliation logic

On success callbacks:

1. the collection is marked successful
2. the system attempts reconciliation
3. if valid, it creates a posted `Payment`
4. if ambiguous, it moves to manual review

Reasons for manual review include:

- amount exceeds outstanding balance
- loan already settled
- duplicate provider reference
- duplicate submitted payment reference

### 14.5 Reconciliation queue

Staff have a queue for:

- in-flight collections
- review-needed collections
- recently reconciled collections

Staff actions include:

- mark success
- force reconcile
- mark failed

### 14.6 Webhooks and simulation

The project exposes a webhook endpoint:

- `/payments/collections/webhook/<provider>/`

Gateway callbacks must include `PAYMENT_WEBHOOK_SECRET` in one of these headers:

- `Authorization: Bearer <secret>`
- `X-Webhook-Secret: <secret>`
- `X-Webhook-Token: <secret>`
- `X-Payment-Webhook-Secret: <secret>`

For local development, borrowers can simulate gateway callbacks from the portal using:

- `success`
- `failed`

Current implementation note:

- The collection provider is currently internal/mock-style and intended for workflow development.

## 15. Borrower Portal

Borrower portal routes:

- `/my-account/`
- `/my-account/loan/<id>/`
- `/my-account/change-password/`
- `/my-account/loan/<id>/pay/`

Portal features:

- account summary
- all borrower loans
- recent payments
- collection rate
- outstanding balance visibility
- password change
- payment initiation

## 16. Workforce and Payroll

### 16.1 Agent/workforce model

The `Agent` model acts as the broader workforce record, not just field agents.

Supported roles include:

- AGENT
- HR
- STAFF
- FINANCE
- OPERATIONS
- RECOVERY
- MANAGEMENT

An agent can optionally:

- hold admin access
- have a linked user account
- be configured for payroll
- hold bank or mobile money payout settings
- track commission rate

### 16.2 Payroll components

Payroll supports:

- base salary
- fixed allowances
- bonuses
- overtime
- commissions
- manual earnings
- tax deductions
- employee pension
- employer pension
- welfare deductions
- loan recovery deductions
- other deductions

### 16.3 Payroll workflow

1. Create payroll run
2. System builds payroll lines from employee records plus adjustments
3. Run remains in `DRAFT`
4. Approval request is submitted
5. Different admin approves run
6. Run can later be marked paid
7. Paid runs can sync into accounting

### 16.4 Payroll analytics and exports

The workforce area provides:

- workforce directory
- role totals
- payroll hub
- payroll run detail
- agent analytics
- individual and date-range analysis
- payroll Excel export

## 17. Accounting

### 17.1 Scope

The accounting app is an operational accounting hub, not just a ledger table.

It includes:

- accounting periods
- chart of accounts
- journal entries and lines
- counterparties
- bank accounts
- bank transactions
- invoices
- bills
- budgets
- journal approvals
- trial balance
- income statement data
- balance sheet data
- cashbook summary
- receivables/payables aging
- budget vs actual reporting

### 17.2 Default chart of accounts

The platform seeds a default chart including:

- cash and bank accounts
- mobile money wallet
- receivables
- loan portfolio principal
- fixed assets
- accumulated depreciation
- payables
- payroll/statutory liabilities
- owner capital
- retained earnings
- loan ROIC income
- processing and penalty income
- salary, commission, depreciation, maintenance, and operating expenses

### 17.3 Operational sync into accounting

The `sync_operations` action can generate journal entries for:

- loan disbursements
- loan repayments
- paid payroll runs

This is one of the key bridges between the operational modules and the finance module.

### 17.4 Manual journals

Manual journals are not posted immediately.

Instead:

1. User enters journal header and lines
2. System creates an approval request
3. Different admin approves it
4. Approval execution posts the real `JournalEntry`

### 17.5 Other posting flows

The accounting hub posts entries for:

- bank transactions
- invoices
- bills

directly at creation time.

## 18. Asset Management

### 18.1 Asset scope

The assets module covers:

- asset categories
- individual assets
- assignments
- maintenance records
- depreciation runs
- disposals

### 18.2 Accounting linkage

Assets are tightly integrated with accounting through:

- capitalization entries on acquisition
- maintenance expense postings
- depreciation journal entries
- disposal postings with gain/loss recognition

### 18.3 Asset lifecycle

1. Create category with default accounts and useful life
2. Create asset
3. Optionally auto-post capitalization
4. Assign custodian/location
5. Record maintenance
6. Run depreciation
7. Dispose or write off asset if needed

### 18.4 Depreciation

Supported methods:

- straight line
- reducing balance

Depreciation runs:

- calculate due depreciation for eligible assets
- create a journal entry
- create `DepreciationLine` rows
- mark the run `POSTED`

### 18.5 Asset disposals

Asset disposals are approval-backed through the core workflow engine and post:

- reversal of asset cost
- reversal of accumulated depreciation
- proceeds
- selling costs
- gain or loss entry

## 19. Communication, Marketing, and USSD

### 19.1 Management messaging

The message center sends one-to-many SMS to groups such as:

- all users
- staff users
- all agents
- active/default-risk agent groups
- all borrowers
- borrower segments by status, category, agent, location, group, language
- manual numbers

### 19.2 Marketing hub

The marketing hub supports:

- reusable marketing templates
- SMS campaigns
- email campaigns
- WhatsApp copy-ready campaigns
- website leads
- website popup management
- dispatch logging

Audience examples:

- all borrowers
- active borrowers
- bad borrowers
- borrowers by agent
- all agents
- all website leads
- leads by status
- all contacts
- manual contacts

### 19.3 Campaign delivery behavior

- SMS uses the project SMS service helper
- Email uses company/tenant SMTP config when configured
- WhatsApp currently logs copy-ready dispatches rather than sending through a live provider

### 19.4 USSD

USSD endpoints exist for:

- Hubtel
- Arkesel

Supported menu behaviors:

- loan repayment info
- loan disbursement confirmation
- balance check
- referral prompt
- contact info

USSD authentication can be enforced with tenant/company tokens.

## 20. Notifications, Approvals, and Audit Trail

### 20.1 Notifications

Notifications are stored in-app and optionally emailed.

Current notification types include:

- new loan
- payment
- statement
- reminder

### 20.2 Approval workflows

Current approval workflow types:

- loan creation
- payroll run approval
- accounting journal
- asset disposal

Key rule:

- the submitting user cannot approve or reject their own request

### 20.3 Audit logging

`ActivityLog` records:

- category
- action
- actor
- affected object
- message
- metadata
- IP address where available

This is the main audit trail across the operational modules.

## 21. Management Commands

### 21.1 Essential commands

Create public tenant:

```bash
python manage.py create_public_tenant --domain localhost 127.0.0.1
```

Migrate shared and tenant schemas:

```bash
python manage.py migrate_schemas --shared
python manage.py migrate_schemas
```

Seed default plans:

```bash
python manage.py seed_plans
```

Create superuser:

```bash
python manage.py createsuperuser
```

### 21.2 Demo data

Seed comprehensive tenant demo data:

```bash
python manage.py seed_demo_data --schema <tenant_schema>
```

or:

```bash
python manage.py seed_demo_data --domain <tenant.domain>
```

This command seeds large demo coverage for:

- company profile
- users
- agents
- borrowers
- loans and payments
- collections
- accounting
- payroll
- assets
- communications
- notifications
- approvals
- activity logs

### 21.3 Subscription notifications

Send trial/subscription warnings:

```bash
python manage.py send_subscription_notifications --warning-days 3
```

## 22. Important Routes Cheat Sheet

### 22.1 Public schema

- `/`
- `/pricing/`
- `/features/`
- `/signup/`
- `/dashboard/`
- `/account/`
- `/payment/`
- `/api/v1/enterprise/overview/`
- `/api/v1/enterprise/borrowers/`
- `/api/v1/enterprise/loans/`
- `/api/v1/enterprise/payments/`

### 22.2 Tenant schema

- `/login/`
- `/dashboard/`
- `/onboarding/`
- `/settings/`
- `/settings/database-backup/`
- `/borrowers/`
- `/loans/list/`
- `/loans/active/`
- `/payments/pending/`
- `/payments/reconciliation/`
- `/agents/`
- `/agents/payroll/`
- `/accounting/`
- `/assets/`
- `/communication/management/messages/`
- `/communication/management/marketing/`
- `/notifications/inbox/`
- `/my-account/`

## 23. Data Model Summary

### 23.1 Public schema models

- `SubscriptionPlan`
- `PromoCode`
- `Tenant`
- `Domain`
- `TenantPayment`
- `TenantReferral`
- `TenantPromoRedemption`
- `TenantAPIKey`

### 23.2 Tenant schema models

- Company:
  - `CompanyProfile`

- Loans:
  - `Borrower`
  - `Loan`
  - `Payment`
  - `RepaymentCollection`

- Workforce:
  - `Agent`
  - `PayrollAdjustment`
  - `PayrollRun`
  - `PayrollLine`

- Accounting:
  - `AccountingPeriod`
  - `LedgerAccount`
  - `Counterparty`
  - `JournalEntry`
  - `JournalLine`
  - `BankAccount`
  - `BankTransaction`
  - `Invoice`
  - `Bill`
  - `Budget`
  - `BudgetLine`

- Assets:
  - `AssetCategory`
  - `AssetItem`
  - `AssetAssignment`
  - `AssetMaintenance`
  - `DepreciationRun`
  - `DepreciationLine`
  - `AssetDisposal`

- Communication:
  - `WebsiteLead`
  - `MarketingTemplate`
  - `MarketingCampaign`
  - `MarketingDispatchLog`
  - `WebsiteMarketingPopup`

- Core:
  - `ApprovalRequest`
  - `ActivityLog`

- Notifications:
  - `Notification`

## 24. Operational Notes and Caveats

### 24.1 Development-only behaviors currently visible in code

- `DJANGO_DEBUG=true` enables local debug behavior
- unknown tenant hosts fall back to public schema only when `SHOW_PUBLIC_IF_NO_TENANT_FOUND=true`
- tenant owner subscription payments are auto-confirmed in the current view flow
- borrower auto-collection uses an internal collection provider pattern
- payment and USSD callbacks may be accepted without configured secrets only when the corresponding insecure fallback setting is enabled

### 24.2 Performance considerations

Some analytics and dashboards build large Python-side aggregations rather than using only database aggregates. This is fine for early-stage usage and demo environments, but large production datasets may eventually need optimization.

### 24.3 Deployment assumptions

The codebase assumes:

- PostgreSQL schemas per tenant
- host-based tenant routing
- proper wildcard or subdomain DNS in production
- a real mail backend for non-console email
- a production-ready SMS/provider configuration if live messaging is required

### 24.4 Restore/backups

The project includes export tooling, but full disaster recovery design still depends on PostgreSQL operational backup strategy. Treat the app-level JSON/XML/CSV/Excel/SQL exports as useful tools, not a complete infrastructure backup policy by themselves.

## 25. Recommended Developer Onboarding Path

If you are joining this project, the fastest way to understand it is:

1. Read `config/settings.py`, `config/urls_public.py`, and `config/urls_tenant.py`
2. Read `apps/tenants/views.py` to understand signup and subscription logic
3. Read `apps/company/models.py` to understand tenant configuration surface area
4. Read `apps/loans/models.py` and `apps/loans/views.py` for the lending core
5. Read `apps/core/approvals.py` for the business control model
6. Read `apps/accounting/views.py` and `apps/assets/views.py` for operational-financial integration
7. Seed a demo tenant and walk the UI end to end

## 26. Recommended Admin Operating Path

For a brand-new tenant workspace, the safest order is:

1. Complete company setup
2. Review plan limits and tenant subscription status
3. Configure repayment defaults and payroll statutory settings
4. Create agents/workforce members
5. Create borrowers or import them
6. Issue loans through the approval queue
7. Record or reconcile repayments
8. Set up accounting controls and sync operations
9. Register assets if required
10. Configure communications, lead capture, and website popup campaigns

## 27. Final Summary

This project is not just a loan tracker. It is a multi-tenant operational platform for micro-credit businesses, with a public SaaS front end and a tenant-specific ERP back office. The most important design ideas in the code are:

- per-tenant schema isolation
- approval-gated critical workflows
- strong overlap between operations and accounting
- borrower self-service alongside staff operations
- tenant-configurable branding, messaging, and website presence

If you keep those five ideas in mind, the rest of the codebase becomes much easier to navigate.
