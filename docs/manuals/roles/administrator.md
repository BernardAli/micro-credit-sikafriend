# Administrator Manual

Detailed application procedures are in the [Dashboard and Application Operations Manual](../dashboard_operations.md).

## Purpose

Administrators operate the back office, maintain company data, supervise lending, manage payments, workforce and payroll, and control privileged workflows.

## Access

An administrator is a Django account with `is_staff` or `is_superuser`. Sign in at `/login/`; the system redirects administrators to `/dashboard/`.

Never share administrator credentials. Use a named account for each person so the audit trail identifies the responsible user.

## Start-of-day checklist

1. Review Dashboard totals and overdue indicators.
2. Open Loan Requests and review pending applications.
3. Open Approvals for payroll, accounting, or asset requests.
4. Review Pending Payments and reconciliation exceptions.
5. Check Notifications and failed communication attempts.
6. Confirm that the latest backup completed successfully.

## Borrowers

Use **Borrowers** to create, edit, search, import, and analyse customers. Verify identity fields and attached Ghana Card documents before lending. A borrower portal account can be created or reset from the borrower detail page.

Do not create duplicate borrowers. Search by name, phone, national ID, and Ghana Card before onboarding.

## Loan requests

Creating a loan submits a request; it does not immediately create the facility. Review requests at `/loan-requests/`.

Before approval, confirm:

- Borrower identity and contact information
- Principal, duration, frequency, and repayment amount
- Responsible agent
- Declarations and signatures
- Guarantor and collateral information where applicable
- Affordability and existing exposure
- Review note where risk requires explanation

Ordinary administrators cannot approve their own submissions. Management users and superusers are the only self-review exceptions.

## Payments

Review pending payments before confirmation. Match amount, borrower, loan, method, reference, and evidence. Use Reconciliation for online collections whose provider status and local status differ. Never force reconciliation without independent evidence.

## Workforce and payroll

Workforce records contain personal, employment, access, banking, payroll, and compliance information. Use Admin Console Access sparingly. Payroll runs should be reviewed for salary, allowances, commissions, adjustments, deductions, and statutory values before approval.

## Accounting and assets

Review journal balance and supporting references. Asset records should include category, acquisition data, custodian, carrying value, maintenance, and disposal evidence. Journal and disposal requests are handled through Approvals.

## Company settings

Company Settings controls public branding, legal details, loan defaults, statutory rules, website content, and communication credentials. Back up the database before major configuration changes.

## Security responsibilities

- Disable access promptly when employment ends.
- Never expose borrower identity documents publicly.
- Keep API keys and passwords out of notes and messages.
- Investigate failed approvals and unexpected audit events.
- Use HTTPS and secure production settings.
- Test backups by restoring them in a safe environment.

## End-of-day checklist

1. Confirm payments and collection totals.
2. Review pending or failed requests.
3. Investigate reconciliation exceptions.
4. Check overdue accounts requiring follow-up.
5. Export or verify the scheduled backup.
6. Sign out.
