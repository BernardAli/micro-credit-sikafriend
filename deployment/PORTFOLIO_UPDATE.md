# SikaFriend portfolio and permanent Customer ID update

This update upgrades the existing database in place. The hosted database does not need to be replaced with the local database. Existing customer, loan, payment, user, payroll, security deposit, and accounting records keep their primary keys and relationships.

## What changes

The dashboard now includes clickable portfolio cards and an **Explore all portfolios** link. `/portfolios/` compares every visible portfolio, and `/portfolios/<id>/` opens an individual portfolio. The officer editor is now under `/portfolios/ID/edit/`.

The overview supports portfolio name/number, current officer, status, and activity-date filters. Individual portfolios include customer and loan registers, payment history, monthly cash activity, repayment aging, sector/location/group/category concentration, security deposits, collection attempts, officer history, and the permanent Customer ID register. Current assigned officers can view and export their own portfolios; management can view all portfolios and the unassigned customer/loan book.

Exports include an Excel workbook with separate registers, CSV summaries or a ZIP of all CSV registers, JSON, and a printable PDF. Each register also offers an individual CSV download. Exports contain all matching rows, beyond the current on-screen page. Search filters customer/loan/payment registers and loan status filters the loan register; financial summaries stay the full current portfolio.

**Reporting definitions:** balances reflect the current recorded book; date filters select disbursement and repayment activity. Aging measures the first scheduled repayment amount not fully covered, accounting for partial payments and approved deposit applications. PAR30 uses disbursed principal outstanding over 30 days overdue divided by all disbursed principal outstanding. Deposit funds and unreconciled collection attempts are separate from settled cash repayments. Portfolio transfers place past loan/payment records under their current owner. The screen and downloaded report explain these definitions.

The dashboard/detail enhancement adds no database migrations beyond the original `0016`/`0017` portfolio release. A hosted installation already running those migrations only needs the refreshed source and a web-app reload. The cumulative package `backups/sikafriend-portfolio-dashboard-update-20261011.zip` also contains the original portfolio migration files for installations that have not received the first update.

- The 11 numbered portfolios from the SikaFriend register are created by migrations `0016` and `0017`.
- Customers and their loans belong to a portfolio. Management can assign multiple officers to a portfolio and multiple portfolios to an officer.
- Officer changes take effect immediately for access. Assignment history is retained.
- New Customer IDs use `SF` + a two-digit issuing portfolio + a four-digit customer number, from `0001` through `1000`. For example, `SF070428` is customer 0428 originally registered in portfolio 07.
- Customer IDs are permanent. Transfers move the customer's portfolio and loans while preserving the issuing portfolio and ID. Issued numbers remain reserved after a customer is deleted.
- Existing loans retain their original officer for historical disbursement reporting. Payments retain a recorded collector for collection reporting and payroll commissions. Older payments without a recorded agent submitter retain their previous loan-officer allocation; this is historical attribution, not a claim that a particular person physically collected every old payment.
- The Reports screen includes **SikaFriend Portfolio Ownership**. Customer searches and loan imports accept retained legacy IDs.
- USSD option 6 accepts a Customer ID and checks that the incoming phone number matches the registered customer before returning their balance. Existing provider authentication still applies.

## 1. Confirm assignments locally

Start the local project and sign in as management/admin. Open **Loan Portfolios** (`/portfolios/`).

1. Confirm the officers for each portfolio using **Manage officers**. Only exact, unambiguous officer-name matches are seeded automatically. Several database names differ from the image; three records are named Mavis Boafo, and Joseph Yaw has no matching record. Management must select the intended records or create the appropriate workforce account.
2. Open **Assign customers** (`/portfolios/customers/`). Review customer names, legacy IDs, and historical loan officers before assigning a portfolio. No customer is assigned based on an inferred historical officer.
3. Select customers and their confirmed portfolio. Leave the SF ID blank to issue consecutive IDs. If an SF ID has already been issued outside the application, select that one customer and enter the exact ID.
4. Export **customer assignments** after local assignments are complete. The export contains the exact issued IDs, customer primary keys, legacy references, and names. Use this file on PythonAnywhere so both environments receive the same IDs.

Existing customers with no confirmed portfolio keep their original ID and all financial records. Agents cannot access those customers until management assigns their portfolio. Schedule the hosted rollout so these reviews and imports finish before agent operations resume.

### CSV alternative for larger customer lists

With the project's virtual environment active:

```bash
python manage.py portfolio_customers --export backups/customer-portfolios-review.csv
```

Review the CSV in a spreadsheet. Fill `portfolio_number` with a number such as `07`. Leave `customer_id` blank for automatic numbering, or enter a previously issued SF ID. Keep `borrower_pk`, `legacy_reference`, and `full_name` unchanged. Leave unreviewed rows blank in `portfolio_number`; they will be skipped.

Validate first; the default import rolls back every change, including issued numbers:

```bash
python manage.py portfolio_customers --import backups/customer-portfolios-review.csv
python manage.py portfolio_customers --import backups/customer-portfolios-review.csv --apply
python manage.py portfolio_customers --export backups/customer-portfolios-confirmed.csv
```

Upload **customer-portfolios-confirmed.csv**, not the preliminary review file, when replaying local assignments on the hosted database. The confirmed export carries explicit SF IDs, so numbering does not depend on the hosted row-processing order. Imports reject conflicting permanent IDs, previously issued numbers, duplicate rows, mismatched customer names/references, and invalid portfolios. A failed import rolls back the entire batch.

Officer assignments can be confirmed independently on each environment through the management screen. They are not contained in the customer CSV.

## 2. Back up the hosted database and files

Arrange a maintenance window and stop customer, loan, and repayment changes during the backup and upgrade. Activate the **existing hosted virtual environment**, using the path shown in the PythonAnywhere Web tab. Keep its current production `.env` and MySQL credentials.

From a PythonAnywhere Bash console, adjust the project directory if necessary:

```bash
cd ~/micro-credit-sikafriend
mkdir -p backups
umask 077

backup_file="backups/before-portfolios-$(date +%Y%m%d-%H%M%S).sql"
mysqldump \
  --host=sikafriend.mysql.pythonanywhere-services.com \
  --port=3306 \
  --user=sikafriend \
  --password \
  --single-transaction \
  --quick \
  --set-gtid-purged=OFF \
  --no-tablespaces \
  'sikafriend$sikafriend' > "$backup_file" &&
gzip "$backup_file" &&
gzip -t "$backup_file.gz"
```

Enter the hosted MySQL password at the prompt. Use the database host/user/name from the production `.env` if they differ from the values above. Download the backup before proceeding. Also keep a copy of the old source release, `.env`, and uploaded `media/` files for rollback. [PythonAnywhere MySQL backup instructions](https://help.pythonanywhere.com/pages/MySQLBackupRestore/).

## 3. Upload the source update

The latest cumulative release package is `backups/sikafriend-portfolio-dashboard-update-20261011.zip`. It contains the changed source files, migrations, templates, tests, and instructions. It contains no database export, customer assignment CSV, production credentials, or uploaded media.

Upload this ZIP through PythonAnywhere Files to the project directory, then extract it **inside the existing project**:

```bash
cd ~/micro-credit-sikafriend
unzip -o sikafriend-portfolio-dashboard-update-20261011.zip
```

This overwrites only files included in the update. Keep the hosted `.env`, database configuration, `media/`, WSGI configuration, and virtual environment. If the change is later committed and pushed to your Git repository, deployment may use `git pull --ff-only` instead of the ZIP; the current local changes must reach the remote first.

## 4. Apply the migrations and confirmed customer assignments

Run these commands in the existing hosted virtual environment:

```bash
python manage.py check
python manage.py migrate --plan
python manage.py migrate --noinput
```

The new migrations add the portfolio schema, seed the 11 portfolios, and preserve historical payment attribution. They do not automatically renumber legacy customers.

If local assignments were already confirmed, upload `customer-portfolios-confirmed.csv` to the hosted `backups/` folder and run:

```bash
python manage.py portfolio_customers --import backups/customer-portfolios-confirmed.csv
python manage.py portfolio_customers --import backups/customer-portfolios-confirmed.csv --apply
```

If the database has changed since the local backup, a reference/name mismatch stops the import. Reconcile those rows rather than replacing the live database. New hosted customers not included in the CSV remain available for management review.

Finish the update:

```bash
python manage.py collectstatic --noinput
python manage.py check
python manage.py showmigrations loans
```

No dependency changes are required for this release. Do not generate migrations on PythonAnywhere or use `--fake`; deploy the supplied migration files.

## 5. Reload and verify

Reload the web application using PythonAnywhere's **Web → Reload** button. [Official Django deployment and reload instructions](https://help.pythonanywhere.com/pages/DeployExistingDjangoProject/).

Verify:

1. Customer, loan, and payment counts agree with the pre-upgrade records.
2. The 11 portfolios appear and each intended officer is assigned.
3. Confirmed customers have the same SF IDs locally and on PythonAnywhere.
4. A reassigned officer sees the portfolio's existing customers and loans; the removed officer loses access.
5. Existing balances, payment history, borrower logins, security deposits, and accounting records remain accessible.
6. A newly registered customer receives the next available ID and an existing customer's ID remains unchanged after a transfer.
7. The portfolio ownership report, statements, repayment entry, and configured USSD callback work.
8. Dashboard portfolio cards open the overview and individual portfolios. Date filters, all detail sections, and full-register CSV/Excel/PDF/JSON downloads work.

## Rollback

Keep the pre-upgrade SQL backup and source release. If a rollback is needed, stop writes, restore the corresponding old source and full database backup, and reload the web app. Do not merely reverse the portfolio migrations after IDs have been issued: removing the issuance register would discard the record of reserved IDs. Reconcile any activity recorded after the backup before reverting financial data.
