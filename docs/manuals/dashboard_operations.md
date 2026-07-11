# Dashboard and Application Operations Manual

This manual explains how each active application works and gives practical steps for common dashboard tasks. Access depends on the signed-in role.

## 1. Dashboard Navigation

After login, the top bar shows the company logo, account context, theme control, and mobile navigation. The desktop sidebar groups work into Loan Operations, Insights, Communications, and System/Governance.

To move safely through the dashboard:

1. Use the sidebar rather than the browser Back button after a form submission.
2. Read flash messages at the top of the content area.
3. On tabbed pages, select the relevant tab before entering information.
4. Correct every item in an error summary before resubmitting.
5. Confirm that a success message or updated record appears before leaving.

## 2. Company Setup and Website

### Configure the company

1. Open **Company Settings**.
2. Complete legal name, tagline, contacts, address, registration and licence details.
3. Upload the logo and favicon.
4. Configure loan defaults, repayment settings, and statutory values.
5. Configure SMTP, SMS, and USSD credentials if used.
6. Save and confirm the success message.

### Configure the public website

1. In Company Settings, open website branding/content sections.
2. Set crimson/magenta brand colors or approved company colors.
3. Complete hero, about, services, team, branches, FAQs, testimonials, and contact content.
4. Configure visibility toggles and public documents.
5. Open `/` in a signed-out browser to verify desktop and mobile presentation.

## 3. Borrower Application

### Create a borrower

1. Open **Borrowers** and select **Add Borrower**.
2. Search existing records first to prevent duplicates.
3. Enter identity, phone, email, location, occupation/business, assigned agent, group, and language.
4. Upload photo and Ghana Card images where available.
5. Enter a unique portal username when requested.
6. Submit and correct any visible validation errors.
7. Open the borrower detail page and verify the saved record.

### Edit or analyse a borrower

1. Open **Borrowers** and select the borrower.
2. Use Edit for corrections; avoid replacing historical facts without evidence.
3. Review loans, payments, status, and risk indicators on the detail page.
4. Use Borrower Analytics for portfolio-level patterns.

### Create or reset portal access

1. Open the borrower detail page.
2. Select **Create Login** if no account exists.
3. Set a unique username and secure temporary password.
4. Give credentials to the borrower through an approved channel.
5. Use **Reset Login** only after verifying the borrower's identity.

## 4. Loan Application and Approval

### Submit a loan request

1. Open **New Loan**.
2. Select the borrower and responsible agent.
3. Enter principal, duration, frequency, start/acquisition dates, and installment.
4. Complete sector and purpose information.
5. Complete borrower declaration and signature fields.
6. Add guarantor and collateral information where required.
7. Complete receiving/approval metadata supported by the application form.
8. Review calculated values and submit.
9. Confirm the message says an approval request was submitted.

The facility does not yet exist. It is now in **Loan Requests**.

### Review a loan request

1. Open **Loan Requests**.
2. Filter by Pending if necessary.
3. Open/read the borrower, amount, duration, repayment, agent, and risk description.
4. Enter a meaningful review note.
5. Select **Approve & Execute** or **Reject**.
6. Confirm the request becomes Executed or Rejected.
7. If Failed, inspect the result message and audit trail before retrying or resubmitting.

Ordinary submitters cannot review their own request. Management-linked accounts and superusers may self-review.

### View a loan and statement

1. Open **All Loans** and select the loan.
2. Review status, borrower, terms, expected total, payments, and balance.
3. Select the statement view or PDF action.
4. Verify transactions before sharing the statement.

## 5. Payments and Reconciliation

### Record a payment

1. Open the loan.
2. Select **Add Payment**.
3. Enter amount, date, method, and reference.
4. Submit and verify whether it is posted or pending confirmation.

### Confirm or reject a pending payment

1. Open **Pending Payments**.
2. Match the payment to cash, bank, mobile money, or provider evidence.
3. Select Confirm when evidence agrees.
4. Select Reject when it is invalid and record the reason.
5. Reopen the loan and verify the balance.

### Reconcile provider collections

1. Open **Payment Reconciliation**.
2. Compare client reference, provider reference, status, amount, borrower, and loan.
3. Use normal provider callback processing whenever possible.
4. Mark successful, force reconcile, or mark failed only with evidence.
5. Verify that successful reconciliation created one payment and updated the loan balance.

## 6. Workforce Application

### Create an employee

1. Open **Workforce** and select **Add Workforce Member**.
2. Complete Profile: employee code, name, role, department, supervisor, status, dates, and location.
3. Complete Contact & Compliance: phone, email, address, emergency contact, Ghana Card, tax and SSNIT.
4. Complete Payroll: salary, allowances, commission, payment method, bank/mobile money, payroll and admin-access flags.
5. Complete Documents & Notes.
6. Save. If validation fails, use the error summary; the page opens the first tab with an error.
7. Verify the employee detail Overview, Payroll, and Portfolio tabs.

### Create employee login

1. Open the workforce member.
2. Select **Create Login** or use Workforce registration.
3. Set a unique username and temporary password.
4. Enable Admin Console Access only for authorized staff.
5. Confirm the role and landing page using the new account.

## 7. Payroll Application

### Add an adjustment

1. Open **Payroll** and select **Run Setup**.
2. Choose employee, earning/deduction type, category, label, amount, dates, and recurring status.
3. Save Adjustment.
4. Verify it appears in the employee Payroll tab or payroll preview.

### Generate payroll

1. Open **Payroll > Run Setup**.
2. Enter run title, period dates, pay date, inclusion options, and notes.
3. Select **Generate Draft Payroll**.
4. Open the draft and review every line.
5. Recalculate if underlying records changed.
6. Submit/approve according to the displayed workflow.
7. After approval, mark paid only when disbursement is complete.
8. Export CSV or Excel for authorized reconciliation.

## 8. Accounting Application

### Initial setup

1. Open **Accounting > Chart & Cashbook**.
2. Create required ledger accounts.
3. Add bank and mobile money cashbooks.
4. Create counterparties under Receivables & Payables.
5. Create accounting periods and budgets under Controls & Budgets.

### Sync operations

1. Open Accounting Overview.
2. Select **Sync Loans, Repayments & Payroll Into Ledger**.
3. Review the success/error message.
4. Inspect Recent Ledger Activity and Trial Balance.
5. Investigate differences rather than running repeated blind syncs.

### Post transactions

- Cashbook: select account, date, direction, amount, reference, and description; then Post Transaction.
- Journal: complete header and balanced debit/credit lines; then Post Journal Entry.
- Invoice/Bill: select counterparty, dates, amounts, status, and account mapping.
- Budget: create header, then add lines by ledger account.

### Review reports

1. Open Accounting > Reports.
2. Set start and end dates.
3. Select Refresh Reports.
4. Review Income Statement, Balance Sheet, Trial Balance, Cashbook movement, and Budget vs Actual.

## 9. Asset Application

### Register an asset

1. Open **Assets > Register**.
2. Create the asset category if required.
3. Complete asset code/name, category, acquisition date/cost, depreciation method/life, location, and status.
4. Save Asset and verify it in Recent Assets.

### Assign or maintain an asset

1. Open **Custody & Maintenance**.
2. Select asset and workforce custodian, dates, condition, and notes; Record Assignment.
3. For maintenance, record provider, dates, cost, description, and outcome.

### Depreciate or dispose

1. Open **Depreciation & Disposal**.
2. For depreciation, set run date/period and Post Depreciation.
3. Review generated lines and accounting effect.
4. For disposal, select asset and enter date, proceeds, buyer, reason, and accounts.
5. Submit disposal; complete approval in **Approvals** where required.

## 10. Communications Application

### Send management messages

1. Open **Messages**.
2. Choose recipient group and filters.
3. Enter the message.
4. Select **Preview Recipients**.
5. Inspect count, names, and normalized numbers.
6. Return to the form and select **Send Messages** only when correct.

### Run a marketing campaign

1. Open **Marketing > Templates** and save reusable content if needed.
2. Open Campaigns and select channel, audience, filters, template/content, and schedule details.
3. Select **Preview Audience**.
4. Review recipients and content.
5. Select **Launch Campaign**.
6. Review History for dispatch outcomes.

### Manage leads and popup

1. Open **Marketing > Leads & Popup**.
2. Review website leads and update each status.
3. Configure popup name, badge, content, image, CTA, dates, and active status.
4. Save and verify on the signed-out public website.

## 11. Reports and Analytics

1. Open **Reports Center**.
2. Select report type.
3. Select period type: month, quarter, half-year, year, or custom dates.
4. Select **View Report**.
5. Review scope and totals.
6. Choose an available export format only after verifying the on-screen result.

Loan and Borrower Analytics provide interactive operational views; Reports Center provides formal period-based outputs.

## 12. Approvals and Audit

### Review non-loan approvals

1. Open **Approvals**.
2. Filter by status or workflow.
3. Review request, submitter, target, description, and supporting context.
4. Add a decision note.
5. Approve & Execute or Reject.
6. Confirm final status and result message.

### Search audit history

1. Open **Audit Trail**.
2. Enter record, action, message, or object text.
3. Choose a category if needed.
4. Search and review actor, time, action, record, and message.
5. Preserve relevant evidence when investigating discrepancies.

## 13. Database Backup

1. Open **Database Backup**.
2. Select the database scope when more than one is displayed.
3. Refresh Scope and review the overview.
4. Select the required export format.
5. Store the downloaded file in protected backup storage.
6. Record date, operator, scope, and verification result.
7. Periodically test restoration outside production.

## 14. Notifications and Borrower Portal

Administrators and agents use Notifications to review system messages and operational events. Borrowers use `/my-account/` to review their own loans, transactions, balances, statements, change password, and initiate payments.

## 15. Troubleshooting Workflow

When a dashboard action fails:

1. Read the flash message and field error summary.
2. Confirm required fields and active tab.
3. Confirm your role is allowed to perform the action.
4. Check whether the record is Pending, Executed, Rejected, or Failed.
5. Avoid duplicate submission while a request is processing.
6. Capture the route, time, record reference, and visible message.
7. Ask an administrator to check Audit Trail and server logs.
8. Never alter the database manually to hide the failure.
