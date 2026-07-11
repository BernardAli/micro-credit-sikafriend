# Micro Credit ERP Project Manual

This manual describes the current standalone codebase.

## 1. Purpose

Micro Credit ERP is a single-company Django application for managing micro-credit operations. It combines:

- company profile, branding, and public website content
- borrower onboarding and KYC
- loan origination, approvals, repayment tracking, and statements
- workforce and payroll
- accounting, journals, bank transactions, invoices, bills, and budgets
- fixed asset tracking, maintenance, depreciation, and disposals
- SMS, marketing campaigns, website leads, popups, and USSD callbacks
- borrower self-service portal
- notifications, audit logging, approvals, and database backups

The project is no longer configured as a multi-tenant SaaS app. There is no active schema routing, tenant provisioning, subscription dashboard, plan enforcement, or Enterprise-owner API.

## 2. Runtime Shape

- `config.settings` is the active settings module.
- `config.urls` is the only active URL configuration.
- SQLite is the default database in local standalone mode.
- The old `tenant_` field prefixes on `CompanyProfile` mean company-level channel configuration.

## 3. App Responsibilities

### `apps.company`

Owns `CompanyProfile`, the single-row settings record for the installation. It controls:

- company identity, logo, favicon, colors, currency, country, timezone
- repayment defaults, loan tiers, borrower languages
- statutory payroll and tax settings
- public website pages, services, team, documents, gallery, and CTAs
- email, SMS, and USSD channel settings
- database backup/export views

### `apps.loans`

Owns the core lending workflow:

- `Borrower`
- `Loan`
- `Payment`
- `RepaymentCollection`
- loan and borrower imports
- dashboard, reports, statements, analytics
- pending payment confirmation and collection reconciliation

Loan totals are computed from principal, repayment count, and payment records. Payments automatically allocate amounts between principal and ROIC, then refresh loan and borrower statuses.

### `apps.accounts`

Owns workforce and payroll:

- `Agent`
- `PayrollRun`
- `PayrollLine`
- `PayrollAdjustment`
- agent registration and reset helpers
- borrower portal login creation/reset
- payroll snapshot generation and approval flow

### `apps.accounting`

Owns accounting primitives and operational sync:

- accounting periods
- ledger accounts
- journal entries and lines
- bank accounts and transactions
- counterparties
- invoices, bills, budgets
- default chart of accounts

Accounting helpers create balanced journal entries and can sync operational loan, repayment, payroll, bank, invoice, bill, and asset activity.

### `apps.assets`

Owns fixed assets:

- asset categories
- asset items
- assignments
- maintenance records
- depreciation runs and lines
- disposals
- asset import tools
- journal posting for acquisition, maintenance, depreciation, and disposal

### `apps.communication`

Owns outreach and channel callbacks:

- management SMS center
- marketing templates and campaigns
- dispatch logs
- website leads
- website marketing popups
- Hubtel/Arkesel-style USSD routes

USSD callbacks can be protected by a company callback token or API key. In local development, insecure callbacks can be allowed with `ALLOW_INSECURE_USSD_CALLBACKS=True`.

### `apps.borrower_portal`

Owns borrower self-service:

- borrower home
- loan detail
- password change
- repayment initiation
- local collection simulation helper

### `apps.core`

Owns shared controls:

- role detection and decorators
- approval queue
- audit logging
- database backup/export helpers
- pagination
- system checks

### `apps.notifications`

Owns in-app notifications and optional email delivery through the company email helper.

## 4. Roles

The app uses one login path:

- Admin: Django staff/superuser, full operational access
- Agent: linked `Agent` profile, redirected to their own profile/portfolio
- Borrower: linked `Borrower` profile, redirected to `/my-account/`

Role helpers live in `apps.core.roles`.

## 5. Important Workflows

### First Run

1. Apply migrations.
2. Create a superuser.
3. Open `/setup/`.
4. Complete company profile, currency, branding, loan tiers, languages, and channel settings.
5. Start entering agents, borrowers, and loans.

### Borrower Creation

Borrowers can be created from the back office or imported in bulk. When creating a borrower interactively, the system can create a borrower portal login with a plain standalone username.

### Loan Creation

Loan creation collects borrower, agent, amount, duration, repayment frequency, weekly/daily payment, and application metadata. The approval system can queue loan creation before execution.

Standalone behavior:

- cross-company checks are disabled
- tenant limits do not apply
- loan categories come from `CompanyProfile.loan_tiers` when configured

### Payments

Payments can be:

- entered directly by staff
- submitted by borrowers as pending payments
- created from repayment collections after callback/reconciliation

Payment save logic:

1. Allocates principal and ROIC.
2. Saves payment.
3. Refreshes loan status.
4. Refreshes borrower status.
5. Sends notifications where configured.

### Payroll

Payroll runs calculate:

- base salary
- fixed allowances
- bonuses, overtime, commissions, other earnings
- PAYE, pension, welfare, manual statutory deductions
- loan recovery and other deductions
- gross pay, total deductions, net pay

Draft payroll runs can be submitted for approval before being marked approved.

### Accounting

The accounting module maintains a default chart of accounts and can post:

- loan disbursements
- loan repayments
- payroll obligations
- bank transactions
- invoices and bills
- asset lifecycle entries

Journal entries must balance before posting.

## 6. Configuration

Environment variables are loaded from `.env`.

Common values:

```env
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=change-me-in-production
TIME_ZONE=Africa/Accra
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=no-reply@microcredit.local
ARKESEL_API_KEY=
ARKESEL_SENDER_ID=MicroCredit
ARKESEL_BASE_URL=https://sms.arkesel.com/api/v2
PAYMENT_WEBHOOK_SECRET=
ALLOW_INSECURE_PAYMENT_WEBHOOKS=True
ALLOW_INSECURE_USSD_CALLBACKS=True
```

For production, set a strong secret key, disable debug, configure allowed hosts, configure a real database backup process, and require webhook/USSD secrets.

## 7. Verification Commands

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

For a quicker focused pass:

```bash
python manage.py test apps.core apps.accounts apps.loans apps.communication
```

## 8. Known Compatibility Notes

- Standalone creation limits live in `apps.core.limits` and always allow local borrower/agent creation.
- `CompanyProfile` still has database fields beginning with `tenant_`; treat them as company channel fields.
- Old public SaaS templates and URL configs have been removed from the active standalone project.
- Enterprise-owner API documentation and subscription workflows are retired in this edition.
