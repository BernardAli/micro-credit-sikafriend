"""Regression coverage for authorization and financial integrity defects."""
from collections import Counter
from datetime import timedelta
from io import StringIO
import importlib
import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Agent
from apps.accounting.models import AccountingPeriod, JournalEntry, ensure_default_ledger_accounts, get_ledger_account, create_journal_entry
from apps.accounting.views import _ensure_accounting_setup, _sync_operational_entries
from apps.assets.models import AssetCategory, AssetItem, DepreciationRun, DepreciationLine
from apps.assets.views import _build_depreciation_run
from apps.company.models import CompanyProfile
from apps.core.approvals import approve_and_execute_request, reject_approval_request
from apps.core.models import ActivityLog, ApprovalRequest
from apps.core.private_media import PrivateMediaStorage
from apps.core.management.commands.import_legacy_data import Command
from apps.loans.models import Borrower, Loan, Payment, Portfolio, PortfolioAssignment, SecurityDeposit
from apps.loans.payment_gateway import initiate_repayment_collection, process_collection_callback, reconcile_collection
from apps.loans.views import _loan_approval_payload


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class HardeningRegressionTests(TestCase):
    def setUp(self):
        for target in ['apps.loans.views.safe_send_sms', 'apps.loans.views.notify_user', 'apps.loans.services_sms.safe_send_sms', 'apps.notifications.services.notify_user', 'apps.loans.signals.notify_user']:
            mock = patch(target)
            mock.start()
            self.addCleanup(mock.stop)
        self.admin = User.objects.create_user('hardening-admin', is_staff=True, is_superuser=True)
        self.reviewer = User.objects.create_user('hardening-reviewer', is_staff=True)
        self.user = User.objects.create_user('hardening-borrower')
        self.orphan = User.objects.create_user('hardening-orphan')
        self.agent = Agent.objects.create(agent_id='hardening-agent', name='Officer', phone='0200000000', location='Accra')
        self.portfolio = Portfolio.objects.get(number='01')
        PortfolioAssignment.objects.create(portfolio=self.portfolio, agent=self.agent)
        self.borrower = Borrower.objects.create(user=self.user, portfolio=self.portfolio, full_name='Customer', national_id='hardening-id', phone='0200000001', location='Accra', ghana_card_number='hardening-card', group_name='Group', preferred_language='Twi')
        CompanyProfile.get_solo()
        self.loan = Loan.objects.create(borrower=self.borrower, agent_name=self.agent, amount=Decimal('1000'), duration_weeks=10, weekly_payment=Decimal('120'), start_date=timezone.localdate() - timedelta(weeks=10))

    def test_borrower_cannot_simulate_settlement_and_submission_stays_pending(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/my-account/collections/1/simulate/success/').status_code, 404)
        response = self.client.post(reverse('borrower:make_payment', args=[self.loan.pk]), {'amount':'1200', 'payment_method':'MOBILE_MONEY'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.loan.payments.get().is_pending)
        self.assertEqual(self.loan.balance_amount, Decimal('1200'))

    def test_unprofiled_account_cannot_read_export_or_modify_backoffice_data(self):
        self.client.force_login(self.orphan)
        for name,args in [('loans:dashboard',[]), ('loans:loan_detail',[self.loan.pk]), ('loans:borrower_detail',[self.borrower.pk]), ('loans:loans_list',[]), ('loans:loan_analytics',[]), ('loans:pending_payments',[]), ('loans:payment_reconciliation',[])]:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name,args=args)).status_code,403)
        response = self.client.post(reverse('loans:loan_payment_create', args=[self.loan.pk]), {'amount':'120', 'payment_date':timezone.localdate().isoformat()})
        self.assertEqual(response.status_code,403)
        self.assertFalse(self.loan.payments.exists())

    def test_confirmation_and_rejection_require_post_and_csrf(self):
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('120'), is_pending=True, submitted_by=self.user)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for action in ['payment_confirm','payment_reject']:
            url = reverse('loans:'+action,args=[payment.pk])
            self.assertEqual(client.get(url).status_code,405)
            self.assertEqual(client.post(url).status_code,403)
        payment.refresh_from_db()
        self.assertTrue(payment.is_pending)
        self.assertFalse(payment.is_void)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('loans:payment_confirm',args=[payment.pk])).status_code,302)
        payment.refresh_from_db()
        self.assertFalse(payment.is_pending)

    def test_stale_approval_cannot_execute_or_reject_an_executed_request(self):
        approval = ApprovalRequest.objects.create(workflow_type='LOAN_CREATION', title='Approval', submitted_by=self.admin, payload=_loan_approval_payload(self.loan))
        stale = ApprovalRequest.objects.get(pk=approval.pk)
        before = Loan.objects.count()
        approve_and_execute_request(approval,self.reviewer)
        with self.assertRaisesMessage(ValueError,'Only pending'):
            approve_and_execute_request(stale,self.reviewer)
        with self.assertRaisesMessage(ValueError,'Only pending'):
            reject_approval_request(stale,self.reviewer)
        self.assertEqual(Loan.objects.count()-before,1)

    def test_failed_handler_rolls_back_its_writes_but_keeps_failure_audit(self):
        approval = ApprovalRequest.objects.create(workflow_type='ASSET_DISPOSAL', title='Failure', submitted_by=self.admin)
        def failing_handler(*args,**kwargs):
            ActivityLog.objects.create(message='Partial handler write')
            raise ValueError('Deliberate failure')
        with patch('apps.core.approvals._execute_asset_disposal',side_effect=failing_handler):
            with self.assertRaises(ValueError):
                approve_and_execute_request(approval,self.reviewer)
        approval.refresh_from_db()
        self.assertEqual(approval.status,'FAILED')
        self.assertFalse(ActivityLog.objects.filter(message='Partial handler write').exists())
        self.assertTrue(ActivityLog.objects.filter(action='failed',object_id=str(approval.pk)).exists())

    def test_tiny_partial_payments_do_not_erase_overdue_installments(self):
        for _ in range(10):
            Payment.objects.create(loan=self.loan,amount=Decimal('0.01'))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.overdue_weeks,10)
        self.assertEqual(self.loan.compute_status(),'DEFAULT')
        self.assertEqual(self.loan.balance_amount,Decimal('1199.90'))

    def test_large_payment_covers_multiple_installments(self):
        Payment.objects.create(loan=self.loan,amount=Decimal('600'))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.paid_installments_count,5)
        self.assertEqual(self.loan.outstanding_payments_count,5)

    def test_applied_deposit_is_deducted_from_remaining_principal(self):
        self.loan.security_deposit_applied_total=Decimal('100')
        self.loan.save(update_fields=['security_deposit_applied_total'])
        payment=Payment.objects.create(loan=self.loan,amount=Decimal('1100'))
        self.loan.refresh_from_db()
        self.assertEqual(payment.principal_paid,Decimal('900'))
        self.assertEqual(payment.roic_paid,Decimal('200'))
        self.assertEqual(self.loan.balance_amount,Decimal('0'))
        self.assertEqual(self.loan.principal_outstanding+self.loan.roic_outstanding,Decimal('0'))

    def test_staff_overpayment_is_rejected_by_form_and_model(self):
        self.client.force_login(self.admin)
        response=self.client.post(reverse('loans:loan_payment_create',args=[self.loan.pk]),{'amount':'1300','payment_date':timezone.localdate().isoformat()})
        self.assertEqual(response.status_code,200)
        self.assertFalse(self.loan.payments.exists())
        with self.assertRaises(ValidationError):
            Payment.objects.create(loan=self.loan,amount=Decimal('1300'))

    def test_pending_confirmation_rechecks_current_balance(self):
        pending=Payment.objects.create(loan=self.loan,amount=Decimal('1200'),is_pending=True)
        Payment.objects.create(loan=self.loan,amount=Decimal('120'))
        self.client.force_login(self.admin)
        self.client.post(reverse('loans:payment_confirm',args=[pending.pk]))
        pending.refresh_from_db()
        self.assertTrue(pending.is_pending)
        self.assertEqual(self.loan.total_paid_amount,Decimal('120'))

    def test_analytics_labels_cannot_terminate_a_script(self):
        marker='</script><script>window.hardeningMarker=1</script>'
        self.borrower.location=marker
        self.borrower.save()
        self.client.force_login(self.admin)
        response=self.client.get(reverse('loans:borrower_analytics'))
        self.assertEqual(response.status_code,200)
        self.assertNotIn(marker,response.content.decode())
        self.assertIn('\\u003C/script\\u003E',response.content.decode())

    def test_getting_legacy_deposit_page_does_not_create_or_block_a_deposit(self):
        self.client.force_login(self.admin)
        response=self.client.get(reverse('loans:security_deposit',args=[self.loan.pk]))
        self.assertEqual(response.status_code,200)
        self.assertFalse(SecurityDeposit.objects.filter(loan=self.loan).exists())
        self.assertTrue(Loan.objects.get(pk=self.loan.pk).is_ready_for_disbursement)

    def test_unsecured_new_loan_does_not_accrue_overdue_installments(self):
        SecurityDeposit.objects.create(loan=self.loan,borrower=self.borrower,required_amount=Decimal('100'))
        fresh=Loan.objects.get(pk=self.loan.pk)
        self.assertEqual(fresh.expected_payments_due_by_now,0)
        self.assertEqual(fresh.compute_status(),'ACTIVE')
        with self.assertRaises(ValidationError):
            Payment.objects.create(loan=fresh,amount=Decimal('10'))

    def test_provider_retries_and_late_failure_cannot_change_settlement(self):
        collection=initiate_repayment_collection(loan=self.loan,amount=Decimal('120'),payment_method='MOBILE_MONEY')
        process_collection_callback(collection,provider_status='success')
        process_collection_callback(collection,provider_status='success')
        process_collection_callback(collection,provider_status='failed')
        collection.refresh_from_db()
        self.assertEqual(collection.status,'RECONCILED')
        self.assertEqual(self.loan.payments.count(),1)

    def test_force_reconciliation_does_not_bypass_overpayment_check(self):
        collection=initiate_repayment_collection(loan=self.loan,amount=Decimal('1300'),payment_method='BANK')
        payment,created=reconcile_collection(collection,reviewer=self.admin,force=True)
        self.assertIsNone(payment)
        self.assertFalse(created)
        self.assertFalse(self.loan.payments.exists())

    def test_journal_cannot_post_to_closed_period(self):
        ensure_default_ledger_accounts()
        today=timezone.localdate()
        AccountingPeriod.objects.create(name='Closed period',start_date=today,end_date=today,status='CLOSED')
        with self.assertRaisesMessage(ValueError,'closed accounting period'):
            create_journal_entry(entry_date=today,memo='Closed posting',lines=[{'account':get_ledger_account('1000'),'debit':Decimal('10')},{'account':get_ledger_account('3000'),'credit':Decimal('10')}])
        self.assertFalse(JournalEntry.objects.exists())

    def test_approved_reversal_preserves_original_posting_and_is_idempotent(self):
        payment=Payment.objects.create(loan=self.loan,amount=Decimal('120'))
        _ensure_accounting_setup()
        _sync_operational_entries(self.admin)
        original=JournalEntry.objects.get(source_key=f'payment:{payment.pk}:repayment')
        from apps.core.reversals import request_reversal
        approval = request_reversal(kind='PAYMENT', source_id=payment.pk, user=self.admin, reason='Receipt recorded incorrectly; evidence checked.')
        approve_and_execute_request(approval, self.reviewer, note='Checked source evidence and approved correction.')
        _sync_operational_entries(self.admin)
        original.refresh_from_db()
        self.assertIsNotNone(original.reversed_by_id)
        self.assertEqual(original.status,'POSTED')
        self.assertEqual(get_ledger_account('1000').current_balance,Decimal('0'))
        self.assertEqual(get_ledger_account('1300').current_balance,Decimal('1000'))
        count=JournalEntry.objects.count()
        _sync_operational_entries(self.admin)
        self.assertEqual(JournalEntry.objects.count(),count)

    def test_legacy_corrected_and_deleted_payment_postings_are_reversed(self):
        payment=Payment.objects.create(loan=self.loan,amount=Decimal('120'))
        _ensure_accounting_setup()
        _sync_operational_entries(self.admin)
        payment.amount=Decimal('60')
        payment._legacy_import = True  # Trusted historical repair, outside normal receipt editing.
        payment.save()
        _sync_operational_entries(self.admin)
        self.assertEqual(get_ledger_account('1000').current_balance,Decimal('60'))
        # Simulate a missing legacy row; normal UI/model deletion is prohibited.
        Payment.objects.filter(pk=payment.pk).delete()
        _sync_operational_entries(self.admin)
        self.assertEqual(get_ledger_account('1000').current_balance,Decimal('0'))

    def test_depreciation_failure_cannot_leave_a_journal(self):
        ensure_default_ledger_accounts()
        accounts={'asset_account':get_ledger_account('1500'),'accumulated_depreciation_account':get_ledger_account('1590'),'depreciation_expense_account':get_ledger_account('5091'),'maintenance_expense_account':get_ledger_account('5092')}
        category=AssetCategory.objects.create(code='hardening',name='Assets',**accounts)
        today=timezone.localdate()
        AssetItem.objects.create(asset_code='hardening-asset',name='Asset',category=category,purchase_cost=Decimal('1200'),in_service_date=today-timedelta(days=60),**accounts)
        run=DepreciationRun.objects.create(title='Run',period_start=today.replace(day=1),period_end=today,posting_date=today)
        with patch.object(DepreciationLine.objects,'create',side_effect=ValueError('Deliberate failure')):
            with self.assertRaises(ValueError):
                _build_depreciation_run(run,self.admin)
        self.assertFalse(JournalEntry.objects.filter(source_key=f'asset:depreciation:{run.pk}').exists())
        self.assertFalse(DepreciationLine.objects.exists())

    def test_legacy_import_preserves_id_for_management_ownership_review(self):
        command=Command()
        command.counts=Counter()
        command.warnings=[]
        row={'id':999,'user_id':None,'borrower_id':'LEGACY-999','full_name':'Legacy customer','national_id':'legacy-national','phone':'0200000002','location':'Accra','photo':'','ghana_card_front':'','ghana_card_back':'','ghana_card_number':'legacy-card','group_name':'Group','preferred_language':'Twi','status':'CLOSED','created_at':timezone.now()}
        with patch.object(command,'_rows',return_value=[row]):
            borrower=command._borrowers({})[999]
        self.assertEqual(borrower.borrower_id,'LEGACY-999')
        self.assertIsNone(borrower.portfolio_id)
        self.assertTrue(command.warnings)
        with self.assertRaises(ValidationError):
            Loan.objects.create(borrower=borrower,agent_name=self.agent,amount=Decimal('100'),duration_weeks=10,weekly_payment=Decimal('12'))
        loan_row={'id':998,'agent_name_id':1,'borrower_id':999,'amount':Decimal('100'),'duration_weeks':10,'weekly_payment':Decimal('12'),'start_date':timezone.localdate(),'status':'ACTIVE','created_at':timezone.now()}
        with patch.object(command,'_rows',return_value=[loan_row]):
            loan=command._loans({1:self.agent},{999:borrower})[998]
        self.assertEqual(loan.borrower_id,borrower.pk)

    def test_private_upload_access_checks_owner_and_portfolio(self):
        self.borrower.ghana_card_front.save('card.jpg',ContentFile(b'private-image'))
        url=self.borrower.ghana_card_front.url
        legacy='/media/'+self.borrower.ghana_card_front.name
        self.assertTrue(url.startswith('/private-media/'))
        for address in [url,legacy]:
            self.assertEqual(self.client.get(address).status_code,404)
            self.client.force_login(self.orphan)
            self.assertEqual(self.client.get(address).status_code,404)
            self.client.force_login(self.user)
            response=self.client.get(address)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response['Cache-Control'],'private, no-store')
            self.assertEqual(b''.join(response.streaming_content),b'private-image')
            self.client.force_login(self.admin)
            response=self.client.get(address)
            self.assertEqual(response.status_code,200)
            self.assertEqual(b''.join(response.streaming_content),b'private-image')
            self.client.logout()
        outsider=User.objects.create_user('outside-officer')
        officer=Agent.objects.create(user=outsider,agent_id='outside',name='Other',phone='0200000003',location='Accra')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(url).status_code,404)
        PortfolioAssignment.objects.create(agent=officer,portfolio=self.portfolio)
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(b''.join(response.streaming_content),b'private-image')

    def test_private_storage_reads_legacy_files_and_avoids_name_collisions(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            legacy=root/'media'/'borrowers'/'photos'
            legacy.mkdir(parents=True)
            (legacy/'photo.jpg').write_bytes(b'old-image')
            with override_settings(MEDIA_ROOT=root/'media',PRIVATE_MEDIA_ROOT=root/'private'):
                storage=PrivateMediaStorage()
                self.assertTrue(storage.exists('borrowers/photos/photo.jpg'))
                with storage.open('borrowers/photos/photo.jpg') as stream:
                    self.assertEqual(stream.read(),b'old-image')
                name=storage.save('borrowers/photos/photo.jpg',ContentFile(b'new-image'))
                self.assertNotEqual(name,'borrowers/photos/photo.jpg')
                self.assertEqual((root/'private'/name).stat().st_mode & 0o777,0o600)

    def test_all_templates_compile(self):
        for path in Path('templates').rglob('*.html'):
            with self.subTest(template=str(path)):
                get_template(str(path.relative_to('templates')))

    def test_private_upload_move_is_dry_by_default_and_preserves_company_media(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'media'/'borrowers'/'photos'/'photo.jpg'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'private-image')
            logo=root/'media'/'company'/'logo.png'
            logo.parent.mkdir()
            logo.write_bytes(b'public-logo')
            target=root/'private'/'borrowers'/'photos'/'photo.jpg'
            with override_settings(MEDIA_ROOT=root/'media',PRIVATE_MEDIA_ROOT=root/'private'):
                call_command('secure_private_uploads',stdout=StringIO())
                self.assertTrue(source.exists())
                self.assertFalse(target.exists())
                call_command('secure_private_uploads',apply=True,stdout=StringIO())
                self.assertFalse(source.exists())
                self.assertEqual(target.read_bytes(),b'private-image')
                self.assertEqual(target.stat().st_mode & 0o777,0o600)
                self.assertEqual(logo.read_bytes(),b'public-logo')
                call_command('secure_private_uploads',apply=True,stdout=StringIO())

    def test_private_upload_move_refuses_conflicting_destination(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for folder,content in [('media',b'original'),('private',b'different')]:
                path=root/folder/'borrowers'/'photos'/'photo.jpg'
                path.parent.mkdir(parents=True)
                path.write_bytes(content)
            with override_settings(MEDIA_ROOT=root/'media',PRIVATE_MEDIA_ROOT=root/'private'):
                with self.assertRaises(CommandError):
                    call_command('secure_private_uploads',apply=True,stdout=StringIO())
            self.assertEqual((root/'media'/'borrowers'/'photos'/'photo.jpg').read_bytes(),b'original')

    def test_integrity_audit_is_read_only_and_reports_old_allocation_errors(self):
        payment=Payment.objects.create(loan=self.loan,amount=Decimal('120'))
        Payment.objects.filter(pk=payment.pk).update(principal_paid=Decimal('999'))
        with TemporaryDirectory() as directory:
            report=Path(directory)/'audit.json'
            with self.assertRaises(CommandError):
                call_command('audit_financial_integrity',report=str(report),fail=True,stdout=StringIO())
            findings=json.loads(report.read_text())
            self.assertTrue(any(row['record']=='Payment' for row in findings))
            self.assertEqual(report.stat().st_mode & 0o777,0o600)
            self.assertNotIn(self.borrower.full_name,report.read_text())
        payment.refresh_from_db()
        self.assertEqual(payment.principal_paid,Decimal('999'))

    def test_deposit_migration_preserves_loans_with_existing_repayments(self):
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        Payment.objects.create(loan=self.loan,amount=Decimal('120'))
        deposit=SecurityDeposit.objects.create(loan=self.loan,borrower=self.borrower,required_amount=Decimal('100'))
        migration=importlib.import_module('apps.loans.migrations.0018_securitydeposit_enforce_before_disbursement_and_more')
        migration.preserve_serviced_loans(apps,SimpleNamespace(connection=connection))
        deposit.refresh_from_db()
        self.assertFalse(deposit.enforce_before_disbursement)
        self.assertTrue(Loan.objects.get(pk=self.loan.pk).is_ready_for_disbursement)

    def test_application_pages_render_for_each_role(self):
        routes=[(name,[]) for name in ['loans:dashboard','loans:reports_center','loans:loan_create','loans:active_loans_list','loans:borrower_list','loans:borrower_analytics','loans:borrower_status_analytics','loans:borrower_create','loans:borrower_bulk_import','loans:loan_bulk_import','loans:pending_payments','loans:payment_reconciliation','loans:loans_list','loans:loan_analytics','loans:loan_monthly_analytics','loans:portfolio_list','loans:portfolio_customers','agent_list','agents_analytics','agents_monthly_range_analysis','agent_create','agent_bulk_import','agent_register','payroll_hub','accounting:hub','assets:hub','assets:bulk_import','communications:management_message_center','communications:marketing_hub','company:edit','company:backup','core:approvals','core:loan_requests','core:audit_trail','notifications:inbox']]
        routes += [('loans:loan_detail',[self.loan.pk]),('loans:loan_statement',[self.loan.pk]),('loans:loan_payment_create',[self.loan.pk]),('loans:borrower_detail',[self.borrower.pk]),('loans:portfolio_detail',[self.portfolio.pk]),('loans:portfolio_update',[self.portfolio.pk]),('agent_detail',[self.agent.pk]),('agent_comprehensive_analysis',[self.agent.pk]),('agent_monthly_range_analysis',[self.agent.pk])]
        self.client.force_login(self.admin)
        for name,args in routes:
            with self.subTest(route=name):
                self.assertIn(self.client.get(reverse(name,args=args)).status_code,[200,302])
        self.client.force_login(self.user)
        for name,args in [('borrower:portal',[]),('borrower:loan_detail',[self.loan.pk]),('borrower:make_payment',[self.loan.pk]),('borrower:change_password',[])]:
            self.assertEqual(self.client.get(reverse(name,args=args)).status_code,200)
        self.client.logout()
        for name in ['company:website','company:about','company:services','company:team','company:impact','company:documents','company:contact','company:privacy','login','password_reset']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200)

    def test_historical_excess_is_preserved_as_credit_and_repair_is_idempotent(self):
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('1200'), reference='ORIGINAL-RECEIPT')
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('1500'))
        with TemporaryDirectory() as directory:
            report = Path(directory) / 'repair.json'
            call_command('repair_payment_allocations', report=str(report), stdout=StringIO())
            self.assertEqual(json.loads(report.read_text())['customer_credit_change'], '300.00')
            payment.refresh_from_db()
            self.assertEqual(payment.customer_credit, Decimal('0'))
            call_command('repair_payment_allocations', apply=True, report=str(report), stdout=StringIO())
            self.assertTrue(json.loads(report.read_text())['applied'])
            call_command('repair_payment_allocations', apply=True, report=str(report), stdout=StringIO())
            self.assertEqual(json.loads(report.read_text())['changed_receipts'], 0)
        payment.refresh_from_db()
        self.assertEqual((payment.amount, payment.principal_paid, payment.roic_paid, payment.customer_credit), (Decimal('1500'), Decimal('1000'), Decimal('200'), Decimal('300')))
        self.assertEqual(payment.reference, 'ORIGINAL-RECEIPT')
        self.assertEqual(self.loan.total_cash_received, Decimal('1500'))
        self.assertEqual(self.loan.total_paid_amount, Decimal('1200'))
        self.assertEqual(self.loan.balance_amount, Decimal('0'))
        self.assertEqual(self.borrower.customer_credit_balance, Decimal('300'))
        self.assertEqual(self.loan.paid_installments_count, 10)
        payment.note = 'Receipt verified'
        payment.save(update_fields=['note'])
        with self.assertRaises(ValidationError):
            payment.amount = Decimal('1600')
            payment.save()

    def test_credit_repair_deducts_applied_deposit_from_principal(self):
        Loan.objects.filter(pk=self.loan.pk).update(security_deposit_applied_total=Decimal('100'))
        self.loan.refresh_from_db()
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('1100'))
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('1250'))
        call_command('repair_payment_allocations', apply=True, stdout=StringIO())
        payment.refresh_from_db()
        self.assertEqual((payment.principal_paid, payment.roic_paid, payment.customer_credit), (Decimal('900'), Decimal('200'), Decimal('150')))
        self.assertEqual(self.loan.principal_outstanding + self.loan.roic_outstanding, Decimal('0'))

    def test_repair_keeps_closed_journal_and_posts_credit_adjustment_today(self):
        from apps.accounting.repayments import sync_repayment_entry
        old_date = timezone.localdate() - timedelta(days=40)
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('1200'), payment_date=old_date)
        ensure_default_ledger_accounts()
        self.assertEqual(sync_repayment_entry(payment), 1)
        original = JournalEntry.objects.get(source_type='LOAN_REPAYMENT')
        AccountingPeriod.objects.create(name='Closed historical month', start_date=old_date, end_date=old_date, status='CLOSED')
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('1500'))
        call_command('repair_payment_allocations', apply=True, stdout=StringIO())
        original.refresh_from_db()
        self.assertEqual(original.status, 'POSTED')
        self.assertIsNotNone(original.reversed_by_id)
        payment.refresh_from_db()
        corrected = JournalEntry.objects.get(source_type='LOAN_REPAYMENT', reversed_by__isnull=True)
        self.assertEqual(corrected.entry_date, timezone.localdate())
        self.assertEqual(corrected.source_date, old_date)
        self.assertTrue(corrected.is_balanced)
        credit = get_ledger_account('2066')
        self.assertEqual(credit.current_balance, Decimal('300'))
        self.assertEqual(get_ledger_account('4000').current_balance, Decimal('200'))
        self.assertEqual(sync_repayment_entry(payment), 0)
        from apps.core.reversals import request_reversal
        approval = request_reversal(kind='PAYMENT', source_id=payment.pk, user=self.admin, reason='Receipt recorded incorrectly; evidence checked.')
        approve_and_execute_request(approval, self.reviewer, note='Checked source evidence and approved correction.')
        payment.refresh_from_db()
        self.assertEqual(sync_repayment_entry(payment), 0)
        self.assertEqual(credit.current_balance, Decimal('0'))
        self.assertEqual(self.borrower.customer_credit_balance, Decimal('0'))

    def test_failed_credit_adjustment_rolls_back_receipt_and_reversal(self):
        from apps.accounting.repayments import sync_repayment_entry
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('1200'))
        ensure_default_ledger_accounts()
        sync_repayment_entry(payment)
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('1500'))
        today = timezone.localdate()
        AccountingPeriod.objects.create(name='Closed current day', start_date=today, end_date=today, status='CLOSED')
        with self.assertRaisesMessage(ValueError, 'closed accounting period'):
            call_command('repair_payment_allocations', apply=True, stdout=StringIO())
        payment.refresh_from_db()
        self.assertEqual(payment.customer_credit, Decimal('0'))
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertIsNone(JournalEntry.objects.get().reversed_by_id)

    def test_credit_is_visible_in_portal_statements_and_portfolio_exports(self):
        from apps.loans.portfolio_analytics import portfolio_snapshot
        from apps.loans.portfolio_exports import make_report
        from apps.loans.services import build_loan_statement
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('1200'))
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('1500'))
        call_command('repair_payment_allocations', apply=True, stdout=StringIO())
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('borrower:portal')), 'Customer Credit Held')
        self.assertIn('Customer credit held: GHS 300.00', build_loan_statement(self.loan))
        snapshot = portfolio_snapshot(Portfolio.objects.filter(pk=self.portfolio.pk), timezone.localdate(), timezone.localdate())
        self.assertEqual(snapshot['totals']['collected'], Decimal('1200'))
        self.assertEqual(snapshot['totals']['customer_credit'], Decimal('300'))
        self.assertEqual(snapshot['totals']['period_collected'], Decimal('1200'))
        self.assertEqual(snapshot['totals']['period_customer_credit'], Decimal('300'))
        report = make_report(snapshot, book=snapshot['books'][self.portfolio.pk])
        rows = next(item for item in report['tables'] if item['key']=='payments')['rows']
        self.assertEqual(rows[0]['customer_credit'], Decimal('300'))

    def test_import_allocates_excess_to_credit_without_using_untrusted_components(self):
        payment = Payment(loan=self.loan, amount=Decimal('1500'))
        payment._legacy_import = True
        payment.save()
        self.assertEqual(payment.customer_credit, Decimal('300'))
        self.assertEqual(payment.principal_paid + payment.roic_paid, Decimal('1200'))

    def test_report_aging_uses_settled_money_and_excludes_customer_credit(self):
        from apps.loans.reports import _loan_snapshot
        for _ in range(10):
            Payment.objects.create(loan=self.loan, amount=Decimal('0.01'))
        snapshot = _loan_snapshot(self.loan, timezone.localdate())
        self.assertEqual(snapshot['overdue_units'], 10)
        self.assertEqual(snapshot['balance'], Decimal('1199.90'))
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('1199.90'))
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('1499.90'))
        call_command('repair_payment_allocations', apply=True, stdout=StringIO())
        snapshot = _loan_snapshot(self.loan, timezone.localdate())
        self.assertEqual(snapshot['paid'], Decimal('1200'))
        self.assertEqual(snapshot['customer_credit'], Decimal('300'))
        self.assertEqual(snapshot['overdue_units'], 0)

    def test_repair_invalid_schedule_rolls_back_every_receipt(self):
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('1200'))
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('1500'))
        other = Loan.objects.create(borrower=self.borrower, agent_name=self.agent, amount=Decimal('1000'), duration_weeks=10, weekly_payment=Decimal('120'))
        Payment.objects.create(loan=other, amount=Decimal('120'))
        Loan.objects.filter(pk=other.pk).update(weekly_payment=Decimal('50'))
        with self.assertRaises(CommandError):
            call_command('repair_payment_allocations', apply=True, stdout=StringIO())
        payment.refresh_from_db()
        self.assertEqual(payment.customer_credit, Decimal('0'))
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_reviewed_invalid_loan_can_be_deferred_without_blocking_valid_repairs(self):
        payment = Payment.objects.create(loan=self.loan, amount=Decimal('1200'))
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('1500'))
        other = Loan.objects.create(borrower=self.borrower, agent_name=self.agent, amount=Decimal('1000'), duration_weeks=10, weekly_payment=Decimal('120'))
        untouched = Payment.objects.create(loan=other, amount=Decimal('120'))
        Loan.objects.filter(pk=other.pk).update(weekly_payment=Decimal('50'))
        call_command('repair_payment_allocations', apply=True, exclude_loan=[other.pk], stdout=StringIO())
        payment.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(payment.customer_credit, Decimal('300'))
        self.assertEqual(untouched.amount, Decimal('120'))
        self.assertEqual(untouched.customer_credit, Decimal('0'))

    def test_new_and_amended_loan_terms_must_cover_principal(self):
        with self.assertRaisesMessage(ValidationError, 'covering its principal'):
            Loan.objects.create(borrower=self.borrower, agent_name=self.agent, amount=Decimal('1000'), duration_weeks=4, weekly_payment=Decimal('120'))
        self.loan.duration_weeks = 4
        with self.assertRaises(ValidationError):
            self.loan.save()
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.duration_weeks, 10)
