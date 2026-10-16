from decimal import Decimal, ROUND_HALF_UP
import re

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction, router
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Agent
from apps.core.private_media import private_upload_storage
from apps.core.models import ReversibleTransaction


class Portfolio(models.Model):
    number = models.CharField(max_length=2, unique=True, validators=[RegexValidator(r"^(0[1-9]|[1-9][0-9])$", "Use a portfolio number from 01 to 99.")])
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    next_customer_number = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["number"]
        constraints = [models.CheckConstraint(condition=models.Q(next_customer_number__gte=1, next_customer_number__lte=1001), name="portfolio_customer_capacity")]

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            if self.pk:
                original = type(self).objects.using(using).select_for_update().get(pk=self.pk)
                if self.number != original.number:
                    raise ValidationError("A portfolio number is permanent.")
                self.next_customer_number = original.next_customer_number
            self.full_clean()
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} — {self.name}"


class PortfolioAssignment(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="assignments")
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="portfolio_assignments")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-started_at", "-pk"]

    def __str__(self):
        return f"{self.portfolio} / {self.agent.name}"


class CustomerIdentity(models.Model):
    """Permanent issuance register: deleting a customer never releases their number."""
    customer_id = models.CharField(max_length=8, primary_key=True)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="issued_ids")
    number = models.PositiveIntegerField()
    borrower = models.OneToOneField("Borrower", on_delete=models.SET_NULL, null=True, blank=True, related_name="identity")
    issued_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["portfolio", "number"], name="unique_portfolio_customer_number"),
            models.CheckConstraint(condition=models.Q(number__gte=1, number__lte=1000), name="customer_number_range"),
        ]

    def __str__(self):
        return self.customer_id


class Borrower(models.Model):
    @staticmethod
    def get_language_choices():
        try:
            from apps.company.models import CompanyProfile
            langs = CompanyProfile.get_solo().languages_for_template
            return tuple((lang, lang) for lang in langs)
        except Exception:
            return (("Twi","Twi"),("Ewe","Ewe"),("Ga","Ga"),("Hausa","Hausa"))

    LANGUAGE_CHOICES = (
        ("Twi", "Twi"),
        ("Ewe", "Ewe"),
        ("Ga", "Ga"),
        ("Hausa", "Hausa"),
    )

    STATUS_CHOICES = (
        ("ACTIVE", "Active"),
        ("CLOSED", "Closed"),
        ("BAD", "Bad"),
    )

    GENDER_CHOICES = (
        ("MALE", "Male"),
        ("FEMALE", "Female"),
    )

    BORROWER_TYPE_CHOICES = (
        ("NEW", "New Borrower"),
        ("EXISTING", "Existing Borrower (New Loan)"),
    )

    RESIDENCE_STATUS_CHOICES = (
        ("OWNED", "Owned"),
        ("RENTED", "Rented"),
        ("FAMILY_HOUSE", "Family House"),
        ("OTHER", "Other"),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="borrower_profile",
        help_text="Login account for this borrower.",
    )

    borrower_id = models.CharField("Customer ID", max_length=50, unique=True, blank=True)
    legacy_borrower_id = models.CharField(max_length=50, blank=True, editable=False, db_index=True)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, null=True, blank=True, related_name="borrowers")

    full_name = models.CharField(max_length=160)
    national_id = models.CharField(max_length=80, unique=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    borrower_type = models.CharField(max_length=12, choices=BORROWER_TYPE_CHOICES, default="NEW")
    phone = models.CharField(max_length=20)
    alternative_phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    location = models.CharField(max_length=150)
    digital_address = models.CharField(max_length=150, blank=True)
    nearest_landmark = models.CharField(max_length=150, blank=True)
    residence_directions = models.TextField(blank=True)
    years_at_residence = models.CharField(max_length=80, blank=True)
    residence_status = models.CharField(max_length=20, choices=RESIDENCE_STATUS_CHOICES, blank=True)
    residence_status_other = models.CharField(max_length=80, blank=True)

    photo = models.ImageField(upload_to="borrowers/photos/", storage=private_upload_storage)
    ghana_card_front = models.ImageField(upload_to="borrowers/ghana_cards/front/", storage=private_upload_storage)
    ghana_card_back = models.ImageField(upload_to="borrowers/ghana_cards/back/", storage=private_upload_storage)

    ghana_card_number = models.CharField(max_length=30, unique=True)
    group_name = models.CharField(max_length=150)
    preferred_language = models.CharField(max_length=20, choices=LANGUAGE_CHOICES)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="CLOSED")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            original = type(self).objects.using(using).select_for_update().filter(pk=self.pk).first() if self.pk else None
            if original and self.borrower_id != original.borrower_id:
                raise ValidationError({"borrower_id": "Customer IDs cannot be changed. Use portfolio assignment to issue an ID to a legacy customer."})
            identity = CustomerIdentity.objects.using(using).filter(borrower_id=self.pk).first() if self.pk else None
            if identity and self.borrower_id != identity.customer_id:
                raise ValidationError({"borrower_id": "This customer's permanent ID cannot be changed."})
            if identity and not self.portfolio_id:
                raise ValidationError({"portfolio": "A customer must belong to a portfolio."})
            if not original and not self.portfolio_id and not getattr(self, "_legacy_import", False):
                raise ValidationError({"portfolio": "Select a portfolio before registering a customer."})
            issuing = self.portfolio_id and not identity
            if issuing:
                portfolio = Portfolio.objects.using(using).select_for_update().get(pk=self.portfolio_id)
                if not portfolio.is_active:
                    raise ValidationError({"portfolio": "This portfolio is inactive."})
                requested = self.borrower_id if re.fullmatch(r"SF\d{6}", self.borrower_id or "") else ""
                number = int(requested[4:]) if requested else portfolio.next_customer_number
                if number < 1 or number > 1000:
                    raise ValidationError({"portfolio": "This portfolio has issued all 1,000 Customer IDs."})
                if requested and requested[2:4] != portfolio.number:
                    raise ValidationError({"borrower_id": "Customer ID must match the issuing portfolio."})
                customer_id = f"SF{portfolio.number}{number:04d}"
                if CustomerIdentity.objects.using(using).filter(customer_id=customer_id).exists() or type(self).objects.using(using).exclude(pk=self.pk).filter(borrower_id=customer_id).exists():
                    raise ValidationError({"borrower_id": "This Customer ID has already been issued and cannot be reused."})
                if not requested:
                    self.legacy_borrower_id = self.borrower_id or self.legacy_borrower_id
                self.borrower_id = customer_id
                Portfolio.objects.using(using).filter(pk=portfolio.pk).update(next_customer_number=max(portfolio.next_customer_number, number + 1))
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"borrower_id", "legacy_borrower_id", "portfolio"}
            super().save(*args, **kwargs)
            if issuing:
                CustomerIdentity.objects.using(using).create(customer_id=self.borrower_id, portfolio=portfolio, number=number, borrower=self)
            if original and original.portfolio_id != self.portfolio_id:
                Loan.objects.using(using).filter(borrower_id=self.pk).update(portfolio_id=self.portfolio_id)
            self.sync_login_email()

    def sync_login_email(self):
        if not self.user_id:
            return
        email = (self.email or "").strip().lower()
        if (self.user.email or "").strip().lower() != email:
            self.user.email = email
            self.user.save(update_fields=["email"])

    def compute_status(self) -> str:
        """
        Borrower status rules:
        - BAD: any related loan is DEFAULT or overdue by > 6 weeks
        - ACTIVE: has any ACTIVE loan with outstanding balance
        - CLOSED: no bad/active exposure remains
        """
        loans = list(self.loans.all())

        if not loans:
            return "CLOSED"

        has_bad = any(
            loan.status == "DEFAULT" or loan.is_overdue_more_than_6_weeks
            for loan in loans
        )
        if has_bad:
            return "BAD"

        has_active = any(
            loan.status == "ACTIVE" and loan.balance_amount > Decimal("0.00")
            for loan in loans
        )
        if has_active:
            return "ACTIVE"

        return "CLOSED"

    def refresh_status(self, save: bool = True) -> str:
        new_status = self.compute_status()

        if self.status != new_status:
            self.status = new_status
            if save and self.pk:
                Borrower.objects.filter(pk=self.pk).update(status=new_status)

        return new_status

    def __str__(self):
        return f"{self.full_name} ({self.borrower_id})"

    @property
    def customer_credit_balance(self):
        return Payment.objects.filter(loan__borrower=self, is_void=False, is_pending=False).aggregate(total=Sum("customer_credit"))["total"] or Decimal("0.00")


class Loan(models.Model):
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("CLOSED", "Closed"),
        ("DEFAULT", "Default"),
    ]

    LOAN_CATEGORY_CHOICES = [
        ("BRONZE", "Bronze"),
        ("SILVER", "Silver"),
        ("GOLD", "Gold"),
        ("PLATINUM", "Platinum"),
        ("DIAMOND", "Diamond"),
        ("EXECUTIVE", "Executive"),
    ]

    REPAYMENT_FREQUENCY_CHOICES = [
        ("DAILY", "Daily"),
        ("WEEKLY", "Weekly"),
    ]

    SECTOR_CHOICES = [
        ("AGRIC_FISHING_FORESTRY", "Agric / Fishing / Forestry"),
        ("EDUCATION", "Education"),
        ("SERVICES", "Services"),
        ("MANUFACTURING_AGRO_PROCESSING", "Manufacturing / Agro-processing"),
        ("RELIGIOUS_ENTERPRISE", "Church / Religious Enterprise"),
        ("CONSTRUCTION", "Construction"),
        ("COMMERCE_TRADING", "Commerce / Trading"),
        ("TRANSPORT_COMMUNICATION", "Transport / Communication"),
        ("HOUSEHOLD_CONSUMPTION", "Household Consumption"),
        ("MORTGAGE_HOUSING_HOME_IMPROVEMENT", "Mortgage / Housing / Home Improvement"),
        ("OTHER", "Other"),
    ]

    borrower = models.ForeignKey("Borrower", on_delete=models.PROTECT, related_name="loans")
    agent_name = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="loans")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, null=True, blank=True, related_name="loans")

    amount = models.DecimalField(max_digits=12, decimal_places=2)  # principal
    loan_category = models.CharField(
        max_length=20,
        choices=LOAN_CATEGORY_CHOICES,
        editable=False,
        blank=True,
    )
    duration_months = models.PositiveIntegerField(default=0)
    duration_weeks = models.PositiveIntegerField(default=0)
    repayment_frequency = models.CharField(max_length=10, choices=REPAYMENT_FREQUENCY_CHOICES, default="WEEKLY")
    sector = models.CharField(max_length=50, choices=SECTOR_CHOICES, blank=True)
    sector_other = models.CharField(max_length=120, blank=True)
    loan_acquisition_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(default=timezone.localdate)
    weekly_payment = models.DecimalField(max_digits=12, decimal_places=2)
    borrower_declaration_accepted = models.BooleanField(default=False)
    borrower_signature_name = models.CharField(max_length=160, blank=True)
    borrower_signed_date = models.DateField(null=True, blank=True)
    guarantor_name = models.CharField(max_length=160, blank=True)
    guarantor_id_number = models.CharField(max_length=80, blank=True)
    guarantor_signature_name = models.CharField(max_length=160, blank=True)
    guarantor_signed_date = models.DateField(null=True, blank=True)
    collateral_type = models.CharField(max_length=120, blank=True)
    collateral_details = models.CharField(max_length=255, blank=True)
    collateral_estimated_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    collateral_location = models.CharField(max_length=180, blank=True)
    collateral_borrower_consent_accepted = models.BooleanField(default=False)
    collateral_borrower_signed_date = models.DateField(null=True, blank=True)
    collateral_guarantor_signature_name = models.CharField(max_length=160, blank=True)
    collateral_guarantor_signed_date = models.DateField(null=True, blank=True)
    application_received_by = models.CharField(max_length=160, blank=True)
    application_received_date = models.DateField(null=True, blank=True)
    approved_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    approved_repayment_plan = models.CharField(max_length=160, blank=True)
    loan_officer_signature_name = models.CharField(max_length=160, blank=True)
    approval_manager_signature_name = models.CharField(max_length=160, blank=True)
    approval_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="ACTIVE")
    disbursed_at = models.DateField(
        null=True,
        blank=True,
        help_text="Set automatically when the required security deposit has been approved and collected.",
    )
    security_deposit_applied_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"], name="loan_status_created_idx")]

    def get_loan_category(self) -> str:
        amount = Decimal(self.amount or Decimal("0.00"))
        try:
            from apps.company.models import CompanyProfile
            tiers = CompanyProfile.get_solo().tiers_for_template
            for tier in tiers:
                if amount <= Decimal(str(tier["max"])):
                    return tier["code"]
            # Return code of last tier if above all maxes
            return tiers[-1]["code"] if tiers else "EXECUTIVE"
        except Exception:
            pass
        # Fallback to hardcoded defaults
        if amount <= Decimal("3000.00"):
            return "BRONZE"
        elif amount <= Decimal("5000.00"):
            return "SILVER"
        elif amount <= Decimal("10000.00"):
            return "GOLD"
        elif amount <= Decimal("15000.00"):
            return "PLATINUM"
        elif amount <= Decimal("20000.00"):
            return "DIAMOND"
        return "EXECUTIVE"

    @property
    def expected_payments_count(self) -> int:
        weeks = int(self.duration_weeks or 0)
        months = int(self.duration_months or 0)
        if self.repayment_frequency == "DAILY":
            return (months * 30) + (weeks * 7)
        return (months * 4) + weeks

    @property
    def actual_payments_count(self) -> int:
        if hasattr(self, "_settled_payment_count"):
            return self._settled_payment_count
        cached = self._cached_settled_payments()
        if cached is not None:
            return len(cached)
        return self.payments.filter(is_void=False, is_pending=False).count()

    def _cached_settled_payments(self):
        """Return settled payments when this loan was prefetched, else None."""
        cache = getattr(self, "_prefetched_objects_cache", None)
        if cache is None or "payments" not in cache:
            return None
        return [
            payment
            for payment in cache["payments"]
            if not payment.is_void and not payment.is_pending
        ]

    def _settled_payment_total(self, field: str) -> Decimal:
        total_attribute = f"_settled_total_{field}"
        if hasattr(self, total_attribute):
            return Decimal(getattr(self, total_attribute)).quantize(Decimal("0.01"))
        cached = self._cached_settled_payments()
        if cached is not None:
            return sum(
                (Decimal(getattr(payment, field) or Decimal("0.00")) for payment in cached),
                Decimal("0.00"),
            ).quantize(Decimal("0.01"))
        agg = self.payments.filter(is_void=False, is_pending=False).aggregate(s=Sum(field))["s"] or Decimal("0.00")
        return Decimal(agg).quantize(Decimal("0.01"))

    @property
    def paid_installments_count(self) -> int:
        if self.weekly_payment <= 0:
            return 0
        return min(self.expected_payments_count, int((self.total_paid_amount + self.security_deposit_applied_amount) // self.weekly_payment))

    @property
    def outstanding_payments_count(self) -> int:
        remaining = self.expected_payments_count - self.paid_installments_count
        return max(0, int(remaining))

    @property
    def total_expected_amount(self) -> Decimal:
        return (
            Decimal(self.expected_payments_count) * Decimal(self.weekly_payment)
        ).quantize(Decimal("0.01"))

    @property
    def roic_amount(self) -> Decimal:
        """
        ROIC = total expected repayment - principal
        """
        roic = self.total_expected_amount - Decimal(self.amount)
        return max(roic, Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def principal_amount(self) -> Decimal:
        return Decimal(self.amount).quantize(Decimal("0.01"))

    @property
    def principal_per_installment(self) -> Decimal:
        if self.expected_payments_count <= 0:
            return Decimal("0.00")
        return (
            self.principal_amount / Decimal(self.expected_payments_count)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def roic_per_installment(self) -> Decimal:
        if self.expected_payments_count <= 0:
            return Decimal("0.00")
        return (
            self.roic_amount / Decimal(self.expected_payments_count)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def total_paid_amount(self) -> Decimal:
        return self.total_cash_received - self.total_customer_credit

    @property
    def total_cash_received(self) -> Decimal:
        return self._settled_payment_total("amount")

    @property
    def total_customer_credit(self) -> Decimal:
        return self._settled_payment_total("customer_credit")

    @property
    def total_principal_paid(self) -> Decimal:
        return self._settled_payment_total("principal_paid")

    @property
    def total_roic_paid(self) -> Decimal:
        return self._settled_payment_total("roic_paid")

    @property
    def principal_outstanding(self) -> Decimal:
        bal = self.principal_amount - self.total_principal_paid - self.security_deposit_applied_amount
        return max(bal, Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def security_deposit_applied_amount(self) -> Decimal:
        return Decimal(self.security_deposit_applied_total or Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def roic_outstanding(self) -> Decimal:
        bal = self.roic_amount - self.total_roic_paid
        return max(bal, Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def balance_amount(self) -> Decimal:
        bal = self.total_expected_amount - self.total_paid_amount - self.security_deposit_applied_amount
        return max(Decimal(bal), Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def weeks_since_start(self) -> int:
        """
        Whole weeks elapsed since start date.
        """
        today = timezone.localdate()
        if not self.start_date:
            return 0
        delta_days = (today - self.start_date).days
        return max(0, delta_days // 7)

    @property
    def expected_payments_due_by_now(self) -> int:
        """
        Repayments expected by now, capped at total duration.
        """
        if not self.is_ready_for_disbursement:
            return 0
        if self.repayment_frequency == "DAILY":
            today = timezone.localdate()
            elapsed = max(0, (today - self.start_date).days) if self.start_date else 0
            return min(self.expected_payments_count, elapsed)
        return min(self.expected_payments_count, self.weeks_since_start)

    @property
    def overdue_weeks(self) -> int:
        """
        Number of weekly payments borrower is behind.
        """
        overdue = self.expected_payments_due_by_now - self.paid_installments_count
        return max(0, overdue)

    @property
    def is_overdue_more_than_6_weeks(self) -> bool:
        try:
            from apps.company.models import CompanyProfile
            grace = CompanyProfile.get_solo().overdue_grace_periods
        except Exception:
            grace = 6
        return self.balance_amount > Decimal("0.00") and self.overdue_weeks > grace

    def compute_status(self) -> str:
        """
        Loan status rules:
        - CLOSED: fully paid
        - DEFAULT: overdue by more than 6 weeks
        - ACTIVE: otherwise
        """
        if self.balance_amount <= Decimal("0.00"):
            return "CLOSED"
        if self.is_overdue_more_than_6_weeks:
            return "DEFAULT"
        return "ACTIVE"

    def refresh_status(self, save: bool = True) -> str:
        new_status = self.compute_status()

        if self.status != new_status:
            self.status = new_status
            if save and self.pk:
                Loan.objects.filter(pk=self.pk).update(status=new_status)

        return new_status

    @property
    def is_ready_for_disbursement(self) -> bool:
        """Legacy loans remain operational; new loans require a fully secured deposit."""
        if hasattr(self, "_disbursement_ready"):
            return self._disbursement_ready
        try:
            deposit = self.security_deposit
            return bool(self.disbursed_at or not deposit.enforce_before_disbursement or deposit.is_secured)
        except SecurityDeposit.DoesNotExist:
            return True

    def save(self, *args, **kwargs):
        if not self.pk:
            if not self.borrower.portfolio_id and not getattr(self, "_legacy_import", False):
                raise ValidationError("Assign the customer to a portfolio before issuing a loan.")
            self.portfolio_id = self.borrower.portfolio_id
        terms = ("amount", "duration_months", "duration_weeks", "weekly_payment", "repayment_frequency")
        original = type(self).objects.filter(pk=self.pk).values(*terms).first() if self.pk else None
        if not getattr(self, "_legacy_import", False) and (original is None or any(original[field] != getattr(self, field) for field in terms)):
            self.clean()
        self.loan_category = self.get_loan_category()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.amount is None or self.weekly_payment is None:
            return
        if Decimal(self.amount) <= 0 or Decimal(self.weekly_payment) <= 0 or self.total_expected_amount < self.principal_amount:
            raise ValidationError("A loan needs positive principal and installments, with an agreed repayment schedule covering its principal.")

    def __str__(self):
        return f"Loan #{self.id} - {self.borrower.full_name} - GHS {self.amount} ({self.loan_category})"


class Payment(ReversibleTransaction):
    PAYMENT_METHOD_CHOICES = [
        ("CASH",         "Cash"),
        ("MOBILE_MONEY", "Mobile Money (MoMo)"),
        ("BANK",         "Bank Transfer"),
        ("CARD",         "Card / Online"),
        ("CHEQUE",       "Cheque"),
        ("OTHER",        "Other"),
    ]

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="payments")
    payment_date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    principal_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    roic_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    customer_credit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), editable=False)

    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, default="CASH",
    )
    reference = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=255, blank=True)
    is_void = models.BooleanField(default=False)
    is_pending = models.BooleanField(
        default=False,
        help_text="Submitted by borrower; awaiting staff confirmation.",
    )
    submitted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="submitted_payments",
    )
    collected_by = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.PROTECT, related_name="collected_payments")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["payment_date", "id"]
        indexes = [
            models.Index(fields=["loan", "is_void", "is_pending"], name="pay_loan_settled_idx"),
            models.Index(fields=["is_void", "is_pending", "payment_date"], name="pay_settled_date_idx"),
            models.Index(fields=["is_void", "is_pending", "created_at"], name="pay_settled_created_idx"),
        ]

    @property
    def loan_applied_amount(self):
        return self.amount - self.customer_credit

    def allocate_components(self):
        from .payment_allocations import allocate_receipt
        zero = Decimal("0.00")
        self.customer_credit = zero
        if not self.loan_id or self.is_void or self.is_pending:
            self.principal_paid = self.roic_paid = zero
            return
        totals = self.loan.payments.filter(is_void=False, is_pending=False).exclude(pk=self.pk).aggregate(
            principal=Sum("principal_paid"), roic=Sum("roic_paid"))
        principal_remaining = max(self.loan.principal_amount - self.loan.security_deposit_applied_amount - (totals["principal"] or zero), zero)
        roic_remaining = max(self.loan.roic_amount - (totals["roic"] or zero), zero)
        if self.loan.total_expected_amount <= zero or self.loan.total_expected_amount < self.loan.principal_amount:
            raise ValidationError("The loan repayment schedule must cover its principal before allocating receipts.")
        self.principal_paid, self.roic_paid, self.customer_credit = allocate_receipt(
            Decimal(self.amount), principal=self.loan.principal_amount, expected=self.loan.total_expected_amount,
            principal_remaining=principal_remaining, roic_remaining=roic_remaining)

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            # All repayment paths lock the loan before reading its available balance.
            loan = Loan.objects.using(using).select_for_update().get(pk=self.loan_id)
            original = type(self).objects.using(using).select_for_update().filter(pk=self.pk).first() if self.pk else None
            if original and original.loan_id != self.loan_id:
                raise ValidationError({"loan": "A recorded repayment cannot be moved to another loan."})
            if original and original.reversal_id:
                raise ValidationError("An approved reversal is permanent. Record a new receipt for any correction.")
            if original and not original.is_void and not original.is_pending and self.is_void:
                raise ValidationError("Settled repayments require an approved transaction reversal.")
            if original and not original.is_void and not original.is_pending and not getattr(self, "_legacy_import", False):
                if self.is_pending or any(getattr(self, name) != getattr(original, name) for name in ("amount", "payment_date", "payment_method")):
                    raise ValidationError("Settled receipt amounts, dates, methods and status require an approved reversal before correction.")
            self.loan = loan
            amount = Decimal(self.amount or "0")
            if not amount.is_finite() or amount <= 0 or amount >= Decimal("10000000000") or amount != amount.quantize(Decimal("0.01")):
                raise ValidationError({"amount": "Enter a positive amount with at most two decimal places and ten whole digits."})
            if not self.is_void:
                totals = loan.payments.filter(is_void=False, is_pending=False).exclude(pk=self.pk).aggregate(total=Sum("amount"), credit=Sum("customer_credit"))
                existing_paid = (totals["total"] or Decimal("0.00")) - (totals["credit"] or Decimal("0.00"))
                available = max(loan.total_expected_amount - existing_paid - loan.security_deposit_applied_amount, Decimal("0.00"))
                unchanged_credit_receipt = original and original.customer_credit > 0 and not original.is_void and not original.is_pending and not self.is_pending and amount == original.amount and self.payment_date == original.payment_date
                if amount > available and not getattr(self, "_legacy_import", False) and not unchanged_credit_receipt:
                    raise ValidationError({"amount": f"Payment cannot exceed the outstanding balance of {available:,.2f}."})
                if not loan.is_ready_for_disbursement:
                    raise ValidationError("Collect and approve the security deposit before accepting repayments.")
            if not self.pk and not self.collected_by_id and self.submitted_by_id:
                self.collected_by = Agent.objects.filter(user_id=self.submitted_by_id).first()
            if original and original.customer_credit > 0 and not self.is_void and (amount != original.amount or self.payment_date != original.payment_date):
                raise ValidationError("A receipt holding customer credit needs reconciliation before changing its amount or date.")
            if not self.is_void and not self.is_pending and original and not original.is_void and not original.is_pending and amount == original.amount and self.payment_date == original.payment_date:
                self.principal_paid, self.roic_paid, self.customer_credit = original.principal_paid, original.roic_paid, original.customer_credit
            else:
                self.allocate_components()
            if self.customer_credit > 0 and not getattr(self, "_legacy_import", False) and not (original and original.customer_credit > 0):
                raise ValidationError("Review this loan's historical allocations before accepting further repayments.")
            if not self.is_void and not self.is_pending and self.principal_paid + self.roic_paid + self.customer_credit != amount:
                raise ValidationError("Repayment components do not match the received amount. Review this loan's existing allocations.")
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"principal_paid", "roic_paid", "customer_credit"}
            super().save(*args, **kwargs)
            loan.refresh_status(save=True)
            loan.borrower.refresh_status(save=True)

    def __str__(self):
        return f"Payment #{self.id or 'new'} - Loan #{self.loan_id} - GHS {self.amount}"

    def delete(self, *args, **kwargs):
        raise ValidationError("Receipt evidence cannot be deleted. Request an approved reversal for a settled payment.")


class RepaymentCollection(models.Model):
    PROVIDER_CHOICES = [
        ("INTERNAL", "Internal Gateway"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending Provider Confirmation"),
        ("PROCESSING", "Processing"),
        ("SUCCEEDED", "Succeeded"),
        ("RECONCILED", "Reconciled"),
        ("FAILED", "Failed"),
        ("MANUAL_REVIEW", "Manual Review"),
        ("CANCELLED", "Cancelled"),
    ]

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="repayment_collections")
    borrower = models.ForeignKey(Borrower, on_delete=models.CASCADE, related_name="repayment_collections")
    payment = models.OneToOneField(
        Payment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="repayment_collection",
    )
    submitted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="repayment_collections",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency_code = models.CharField(max_length=6, default="GHS")
    payment_method = models.CharField(
        max_length=20,
        choices=Payment.PAYMENT_METHOD_CHOICES,
        default="MOBILE_MONEY",
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="INTERNAL")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    client_reference = models.CharField(max_length=40, unique=True)
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    submitted_reference = models.CharField(max_length=120, blank=True)
    payer_phone = models.CharField(max_length=30, blank=True)
    payer_name = models.CharField(max_length=160, blank=True)
    note = models.CharField(max_length=255, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    reconciliation_notes = models.TextField(blank=True)
    gateway_checkout_url = models.URLField(blank=True)
    gateway_payload = models.JSONField(default=dict, blank=True)
    callback_payload = models.JSONField(default=dict, blank=True)
    initiated_at = models.DateTimeField(auto_now_add=True)
    provider_confirmed_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-initiated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "initiated_at"]),
            models.Index(fields=["loan", "status"]),
            models.Index(fields=["provider", "provider_reference"]),
        ]

    @property
    def display_reference(self) -> str:
        return self.provider_reference or self.submitted_reference or self.client_reference

    @property
    def is_reconciled(self) -> bool:
        return self.status == "RECONCILED" and self.payment_id is not None

    def __str__(self):
        return f"Collection {self.client_reference} - Loan #{self.loan_id} - GHS {self.amount}"


class RepaymentReceipt(models.Model):
    """Reserve each provider receipt once, even across concurrent loans."""
    collection = models.OneToOneField(RepaymentCollection, on_delete=models.PROTECT, related_name="receipt")
    provider = models.CharField(max_length=20)
    provider_reference = models.CharField(max_length=120)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "provider_reference"], name="unique_provider_repayment_receipt")]


class SecurityDeposit(models.Model):
    """Customer funds held separately as security for one approved loan."""

    STATUS_CHOICES = [
        ("REQUIRED", "Deposit Required"),
        ("SECURED", "Fully Secured"),
        ("REFUNDED", "Refunded"),
        ("APPLIED", "Applied Against Default"),
    ]

    borrower = models.ForeignKey(Borrower, on_delete=models.PROTECT, related_name="security_deposits")
    loan = models.OneToOneField(Loan, on_delete=models.PROTECT, related_name="security_deposit")
    required_amount = models.DecimalField(max_digits=12, decimal_places=2)
    enforce_before_disbursement = models.BooleanField(default=True, help_text="Disabled for deposits recorded against loans already issued before this workflow.")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="REQUIRED")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def collected_amount(self):
        if not self.pk:
            return Decimal("0.00")
        return self.transactions.filter(action="COLLECTION", reversal__isnull=True).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def refunded_amount(self):
        if not self.pk:
            return Decimal("0.00")
        return self.transactions.filter(action="REFUND", reversal__isnull=True).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def applied_amount(self):
        if not self.pk:
            return Decimal("0.00")
        return self.transactions.filter(action="DEFAULT_APPLICATION", reversal__isnull=True).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def transferred_in_amount(self):
        if not self.pk:
            return Decimal("0.00")
        return self.incoming_transfers.filter(reversal__isnull=True).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def transferred_out_amount(self):
        if not self.pk:
            return Decimal("0.00")
        return self.outgoing_transfers.filter(reversal__isnull=True).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def held_amount(self):
        return max(Decimal("0.00"), self.collected_amount + self.transferred_in_amount - self.refunded_amount - self.applied_amount - self.transferred_out_amount).quantize(Decimal("0.01"))

    @property
    def amount_due(self):
        return max(Decimal("0.00"), Decimal(self.required_amount) - self.held_amount).quantize(Decimal("0.01"))

    @property
    def is_secured(self):
        return self.held_amount >= Decimal(self.required_amount)

    def refresh_status(self, save=True):
        if self.held_amount <= Decimal("0.00") and self.refunded_amount > 0:
            status = "REFUNDED"
        elif self.held_amount <= Decimal("0.00") and self.applied_amount > 0:
            status = "APPLIED"
        elif self.is_secured:
            status = "SECURED"
        else:
            status = "REQUIRED"
        if self.status != status:
            self.status = status
            if save and self.pk:
                SecurityDeposit.objects.filter(pk=self.pk).update(status=status)
        return status

    def __str__(self):
        return f"Security deposit — Loan #{self.loan_id}"


class SecurityDepositTransaction(ReversibleTransaction):
    ACTION_CHOICES = [
        ("COLLECTION", "Deposit Collection"),
        ("REFUND", "Deposit Refund"),
        ("DEFAULT_APPLICATION", "Apply Against Default"),
    ]

    deposit = models.ForeignKey(SecurityDeposit, on_delete=models.PROTECT, related_name="transactions")
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_date = models.DateField(default=timezone.localdate)
    payment_method = models.CharField(max_length=20, choices=Payment.PAYMENT_METHOD_CHOICES, default="CASH")
    reference = models.CharField(max_length=120)
    notes = models.TextField(blank=True)
    customer_verification = models.JSONField(default=dict, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="approved_security_deposit_transactions")
    approval_request = models.OneToOneField("core.ApprovalRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="security_deposit_transaction")
    accounting_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="security_deposit_transactions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transaction_date", "-pk"]

    def __str__(self):
        return f"{self.get_action_display()} — Loan #{self.deposit.loan_id}"


class SecurityDepositTransfer(ReversibleTransaction):
    """An approved, customer-authorised deposit carry-forward between loan cycles."""

    source = models.ForeignKey(SecurityDeposit, on_delete=models.PROTECT, related_name="outgoing_transfers")
    target = models.ForeignKey(SecurityDeposit, on_delete=models.PROTECT, related_name="incoming_transfers")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=120)
    customer_verification = models.JSONField(default=dict, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="approved_security_deposit_transfers")
    approval_request = models.OneToOneField("core.ApprovalRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="security_deposit_transfer")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=~models.Q(source=models.F("target")), name="security_deposit_transfer_distinct_deposits")]

    def __str__(self):
        return f"GHS {self.amount} carried from Loan #{self.source.loan_id} to Loan #{self.target.loan_id}"
