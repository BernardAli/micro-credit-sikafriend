from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.checks import run_checks

from apps.core.pdf import LocalPDFResources
from apps.loans.borrower_imports import parse_borrower_import
from apps.loans.loan_imports import parse_loan_import
from apps.accounts.agent_imports import parse_agent_import
from apps.assets.asset_imports import parse_asset_import
from django.contrib.auth.models import User
from django.test import RequestFactory
from apps.core.export_limits import export_limit_response


class SecurityControlTests(TestCase):
    @override_settings(EXPORTS_PER_MINUTE=1)
    def test_expensive_exports_share_a_per_account_budget(self):
        request = RequestFactory().get('/report.pdf')
        request.user = User.objects.create_user('export-budget-user')
        self.assertIsNone(export_limit_response(request))
        response = export_limit_response(request)
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)

    def test_all_xml_imports_reject_entities_before_reading_external_files(self):
        for parser in (parse_borrower_import, parse_loan_import, parse_agent_import, parse_asset_import):
            malicious = b'<!DOCTYPE data [<!ENTITY secret SYSTEM "file:///etc/passwd">]><data><name>&secret;</name></data>'
            with self.subTest(parser=parser.__name__), self.assertRaisesRegex(ValueError, 'DTD'):
                parser(SimpleUploadedFile('unsafe.xml', malicious), 'xml')

    @override_settings(IMPORT_MAX_ROWS=2)
    def test_csv_imports_reject_excess_rows(self):
        for parser in (parse_borrower_import, parse_loan_import, parse_agent_import, parse_asset_import):
            with self.subTest(parser=parser.__name__), self.assertRaisesRegex(ValueError, 'at most'):
                parser(SimpleUploadedFile('rows.csv', b'name\nOne\nTwo\nThree\n'), 'csv')

    @override_settings(IMPORT_MAX_BYTES=20, IMPORT_MAX_EXPANDED_BYTES=100)
    def test_import_size_and_spreadsheet_expansion_are_bounded(self):
        with self.assertRaisesRegex(ValueError, 'size'):
            parse_borrower_import(SimpleUploadedFile('big.csv', b'a' * 21), 'csv')
        stream = BytesIO()
        with ZipFile(stream, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('xl/worksheets/sheet1.xml', 'a' * 1000)
        with override_settings(IMPORT_MAX_BYTES=10000), self.assertRaisesRegex(ValueError, 'expands'):
            parse_borrower_import(SimpleUploadedFile('bomb.xlsx', stream.getvalue()), 'excel')

    def test_deeply_nested_json_is_rejected_before_decoding(self):
        with self.assertRaisesRegex(ValueError, 'deeply nested'):
            parse_borrower_import(SimpleUploadedFile('nested.json', ('[' * 25 + '0' + ']' * 25).encode()), 'json')

    def test_pdf_resources_cannot_read_credentials_or_make_network_requests(self):
        fetcher = LocalPDFResources()
        for uri in ('https://example.invalid/image.png', 'http://127.0.0.1/', Path('.env').resolve().as_uri(), 'file:///etc/passwd'):
            with self.subTest(uri=uri.split('://', 1)[0]), self.assertRaises(ValueError):
                fetcher(uri)

    @override_settings(HEALTHCHECK_TOKEN='unit-test-monitor-token')
    def test_monitoring_requires_token_and_returns_no_backend_details(self):
        url = reverse('health')
        self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.get(url, HTTP_AUTHORIZATION='Bearer unit-test-monitor-token')
        self.assertEqual(response.json(), {'status':'ok'})
        self.assertIn('no-store', response['Cache-Control'])
        with patch('apps.core.health.connection.cursor', side_effect=DatabaseError('private backend details')):
            response = self.client.get(url, HTTP_AUTHORIZATION='Bearer unit-test-monitor-token')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status':'unavailable'})
        self.assertNotContains(response, 'private backend', status_code=503)

    @override_settings(MFA_ENABLED=False, STAFF_MFA_REQUIRED=False, MFA_ENCRYPTION_KEYS=[],
                       ALLOW_INSECURE_PAYMENT_WEBHOOKS=True, ALLOW_INSECURE_USSD_CALLBACKS=True)
    def test_deployment_checks_refuse_missing_security_controls(self):
        ids = {item.id for item in run_checks(include_deployment_checks=True)}
        self.assertTrue({'core.E003', 'core.E004', 'core.E006'}.issubset(ids))

    @override_settings(TRUSTED_PROXY_CIDRS=['0.0.0.0/0'])
    def test_unrestricted_proxy_trust_is_rejected(self):
        self.assertIn('core.E002', {item.id for item in run_checks()})
