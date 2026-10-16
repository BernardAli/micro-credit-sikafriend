# Deploy SikaFriend on PythonAnywhere with MySQL

This guide deploys the standalone Django application using PythonAnywhere MySQL, a virtual environment, WSGI, and platform static/media mappings.

Apply the [latest security and performance release instructions](SECURITY_PERFORMANCE_UPDATE.md), including independent MFA encryption keys, staff enrollment, new migrations and hosted verification.

## Account requirement

PythonAnywhere's current official documentation states that MySQL works for paid accounts and for qualifying older free accounts. New free accounts created after the January 2026 cutoff may not have MySQL. Confirm the **Databases/MySQL** tab is available before deployment.

## 1. Create the MySQL database

1. Sign in to PythonAnywhere.
2. Open the **Databases** or **MySQL** tab.
3. Set a MySQL password.
4. Create a database named `sikafriend`.
5. Record the displayed username and MySQL hostname.

PythonAnywhere names the database `YOUR_USERNAME$sikafriend`. The dollar sign is part of the database name.

## 2. Upload or clone the project

Open a Bash console:

```bash
cd ~
git clone <YOUR_REPOSITORY_URL> micro-credit-standalone
cd micro-credit-standalone
```

If uploading a ZIP instead, extract it under `/home/YOUR_USERNAME/` and confirm `manage.py` is in the project root.

## 3. Create the virtual environment

Choose a Python version supported by your PythonAnywhere account and compatible with the project:

```bash
python3.12 -m venv ~/.virtualenvs/sikafriend
source ~/.virtualenvs/sikafriend/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

The Web tab must use the same Python major/minor version as this virtual environment.

## 4. Create the production `.env`

Create `/home/YOUR_USERNAME/micro-credit-standalone/.env`:

```env
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=REPLACE_WITH_A_LONG_RANDOM_SECRET
DJANGO_ALLOWED_HOSTS=YOUR_USERNAME.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://YOUR_USERNAME.pythonanywhere.com
TIME_ZONE=Africa/Accra

DB_ENGINE=mysql
DB_NAME=YOUR_USERNAME$sikafriend
DB_USER=YOUR_USERNAME
DB_PASSWORD=YOUR_MYSQL_PASSWORD
DB_HOST=YOUR_MYSQL_HOSTNAME_FROM_THE_DATABASES_TAB
DB_PORT=3306
DB_CONN_MAX_AGE=60

DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False
DJANGO_TRUST_PROXY_HTTPS=True

PAYMENT_WEBHOOK_SECRET=REPLACE_WITH_A_STRONG_SECRET
ALLOW_INSECURE_PAYMENT_WEBHOOKS=False
ALLOW_INSECURE_USSD_CALLBACKS=False
```

Use the actual hostname displayed on the Databases tab. EU accounts have different service hostnames.

Protect the file:

```bash
chmod 600 .env
```

Generate a Django secret with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 5. Validate MySQL and migrate

```bash
source ~/.virtualenvs/sikafriend/bin/activate
cd ~/micro-credit-standalone
python manage.py check
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

Do not copy `db.sqlite3` and expect MySQL to contain the same data. See the migration section below when existing SQLite data must be transferred.

## 6. Create the web application

1. Open the PythonAnywhere **Web** tab.
2. Select **Add a new web app**.
3. Select **Manual configuration**.
4. Select the same Python version as the virtual environment.
5. Set the virtualenv path to `/home/YOUR_USERNAME/.virtualenvs/sikafriend`.

## 7. Configure WSGI

Open the WSGI file linked from the Web tab. Replace its content with the equivalent of `deployment/pythonanywhere_wsgi.py.example`, using the real project path:

```python
import os
import sys

project_home = "/home/YOUR_USERNAME/micro-credit-standalone"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

## 8. Configure static and uploaded media

The project collects static files into `staticfiles/` and stores uploads in `media/`.

On the Web tab, add:

| URL | Directory |
| --- | --- |
| `/static/` | `/home/YOUR_USERNAME/micro-credit-standalone/staticfiles` |
| `/media/company/` | `/home/YOUR_USERNAME/micro-credit-standalone/media/company` |

Customer/workforce images use authenticated `/private-media/` URLs and are stored in `private-media/`. Do not map `/media/`, `/private-media/`, `/media/borrowers/`, or `/media/agents/` directly to disk. Preview moving existing uploads with `python manage.py secure_private_uploads`, then run it with `--apply`. Include `private-media/` in secure backups. See [the security update instructions](SECURITY_UPDATE.md) for credential rotation and historical data checks.

Run `collectstatic` again whenever static assets change.

## 9. Reload and verify

Select **Reload** on the Web tab, then verify:

1. Public home page and logo
2. `/login/`
3. Administrator dashboard
4. Borrower creation
5. Loan request submission and approval
6. Static CSS/images and uploaded media
7. Database backup/export
8. Email/SMS/webhook configuration

Review the PythonAnywhere error log if an HTTP 500 occurs.

## 10. Move existing SQLite data to MySQL

Back up both databases before migration. On the existing SQLite configuration:

```bash
DB_ENGINE=sqlite python manage.py dumpdata \
  --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission \
  --indent 2 > data-export.json
```

Switch `.env` to MySQL, create schema, and load:

```bash
python manage.py migrate
python manage.py loaddata data-export.json
```

Then verify user counts, company settings, borrowers, loans, payments, workforce, payroll, journals, and assets. Keep the original SQLite database until reconciliation is complete.

Large or complex production migrations should be rehearsed in a separate MySQL database first.

## 11. Updates

For the SikaFriend portfolio and permanent Customer ID release, use [the portfolio update guide](PORTFOLIO_UPDATE.md). It includes the database-preserving migration, management review, confirmed-ID CSV transfer, source ZIP deployment, and rollback steps.

```bash
cd ~/micro-credit-standalone
git pull
source ~/.virtualenvs/sikafriend/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

Reload the web app from the Web tab after every deployment.

## 12. MySQL test database

PythonAnywhere MySQL users may not have permission for Django to create test databases automatically. Create `YOUR_USERNAME$test_sikafriend` from the Databases tab and set:

```env
DB_TEST_NAME=YOUR_USERNAME$test_sikafriend
```

Never run tests against the production database name.

## 13. Troubleshooting

### `ModuleNotFoundError: MySQLdb`

Activate the web app virtual environment and install `mysqlclient` from `requirements.txt`, then reload.

### `Access denied for user`

Confirm `DB_USER`, password, hostname, and the complete database name including `USERNAME$`.

### Static files return 404

Run `collectstatic`, confirm Web-tab mappings use absolute paths, and reload.

### Application still shows old code

Reload the PythonAnywhere web app. Console processes and web workers are separate.

### Redirect loop behind HTTPS

Confirm `DJANGO_TRUST_PROXY_HTTPS=True` and use the PythonAnywhere HTTPS site. Do not trust proxy headers on an untrusted proxy deployment.

## Official references

- PythonAnywhere: Deploying an existing Django project
- PythonAnywhere: Using MySQL
- PythonAnywhere: Django static files
- PythonAnywhere: Environment variables
