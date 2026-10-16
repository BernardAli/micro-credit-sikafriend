"""Database-paginated receipt, pipeline and permanent-ID registers."""
from django.db.models import Q, CharField
from django.db.models.functions import Cast
from .models import Payment, RepaymentCollection, CustomerIdentity


def payment_register(portfolio, start, end, query=""):
    rows = Payment.objects.filter(loan__portfolio=portfolio, payment_date__range=(start, end)).select_related('loan__borrower', 'collected_by').only(
        'id','loan_id','payment_date','amount','principal_paid','roic_paid','customer_credit','is_void','is_pending','payment_method','reference','note','collected_by_id',
        'loan__id','loan__borrower_id','loan__borrower__id','loan__borrower__borrower_id','loan__borrower__full_name','loan__borrower__phone',
        'collected_by__id','collected_by__name','collected_by__agent_id')
    if query:
        scope = Q(loan__borrower__borrower_id__icontains=query) | Q(loan__borrower__full_name__icontains=query) | Q(loan__borrower__phone__icontains=query) | Q(reference__icontains=query)
        rows = rows.annotate(_search_pk=Cast('pk', CharField()))
        scope |= Q(_search_pk__icontains=query)
        rows = rows.filter(scope)
    return rows.order_by('-payment_date', '-pk')


def payment_row(payment):
    borrower = payment.loan.borrower
    return {'pk':payment.pk, 'loan_pk':payment.loan_id, 'date':payment.payment_date,
            'customer_id':borrower.borrower_id, 'customer':borrower.full_name, 'phone':borrower.phone,
            'amount':payment.amount, 'principal':payment.principal_paid, 'roic':payment.roic_paid,
            'customer_credit':payment.customer_credit, 'loan_applied':payment.loan_applied_amount,
            'status':'Void' if payment.is_void else 'Pending' if payment.is_pending else 'Settled',
            'method':payment.get_payment_method_display(), 'reference':payment.reference, 'note':payment.note,
            'collector':payment.collected_by.name if payment.collected_by_id else 'Staff / unrecorded collector',
            'collector_id':payment.collected_by.agent_id if payment.collected_by_id else ''}


def collection_register(portfolio, start, end):
    from datetime import datetime, time, timedelta, timezone
    unresolved = Q(payment_id__isnull=True, status__in={'PENDING','PROCESSING','SUCCEEDED','MANUAL_REVIEW'})
    activity = Q(initiated_at__gte=datetime.combine(start, time.min, tzinfo=timezone.utc),
                 initiated_at__lt=datetime.combine(end+timedelta(days=1),time.min,tzinfo=timezone.utc))
    return RepaymentCollection.objects.filter(loan__portfolio=portfolio).filter(unresolved|activity).select_related('borrower').only(
        'id','loan_id','borrower_id','amount','status','payment_method','provider_reference','client_reference','submitted_reference',
        'initiated_at','reconciled_at','failure_reason','payment_id','borrower__id','borrower__borrower_id','borrower__full_name').order_by('-initiated_at','-pk')


def collection_row(collection):
    return {'pk':collection.pk, 'loan_pk':collection.loan_id, 'customer_id':collection.borrower.borrower_id,
            'customer':collection.borrower.full_name, 'amount':collection.amount, 'status':collection.get_status_display(),
            'status_code':collection.status, 'method':collection.get_payment_method_display(), 'reference':collection.display_reference,
            'initiated':collection.initiated_at, 'reconciled':collection.reconciled_at, 'reason':collection.failure_reason,
            'unresolved':collection.payment_id is None and collection.status in {'PENDING','PROCESSING','SUCCEEDED','MANUAL_REVIEW'}}


def identity_register(portfolio):
    return CustomerIdentity.objects.filter(portfolio=portfolio).select_related('borrower__portfolio').order_by('number')


def identity_row(identity, *, private_history):
    borrower = identity.borrower
    current = borrower and borrower.portfolio_id == identity.portfolio_id
    visible = borrower and (current or private_history)
    return {'customer_id':identity.customer_id, 'number':identity.number, 'issued':identity.issued_at,
            'customer':borrower.full_name if visible else 'Former customer' if borrower else 'Deleted customer — ID reserved',
            'current_portfolio':str(borrower.portfolio) if visible and borrower.portfolio_id else 'Transferred out' if borrower else '',
            'state':'Current' if current else 'Transferred out' if borrower else 'Reserved after deletion'}
