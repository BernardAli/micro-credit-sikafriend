from django.contrib.auth.models import User
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from decimal import Decimal



WORKFORCE_ROLE_CHOICES = [
    ("AGENT", "Field Agent"),
    ("HR", "Human Resources"),
    ("STAFF", "General Staff"),
    ("FINANCE", "Finance"),
    ("OPERATIONS", "Operations"),
    ("RECOVERY", "Recovery"),
    ("MANAGEMENT", "Management"),
]

EMPLOYMENT_TYPE_CHOICES = [
    ("FULL_TIME", "Full Time"),
    ("PART_TIME", "Part Time"),
    ("CONTRACT", "Contract"),
    ("CONSULTANT", "Consultant"),
]

EMPLOYMENT_STATUS_CHOICES = [
    ("ACTIVE", "Active"),
    ("ONBOARDING", "Onboarding"),
    ("ON_LEAVE", "On Leave"),
    ("SUSPENDED", "Suspended"),
    ("EXITED", "Exited"),
]

PAYMENT_METHOD_CHOICES = [
    ("BANK", "Bank Transfer"),
    ("MOMO", "Mobile Money"),
    ("CASH", "Cash"),
    ("MIXED", "Mixed"),
]

PAYROLL_STATUS_CHOICES = [
    ("DRAFT", "Draft"),
    ("APPROVED", "Approved"),
    ("PAID", "Paid"),
    ("CANCELLED", "Cancelled"),
]

ADJUSTMENT_TYPE_CHOICES = [
    ("EARNING", "Earning"),
    ("DEDUCTION", "Deduction"),
]

ADJUSTMENT_CATEGORY_CHOICES = [
    ("BONUS", "Bonus"),
    ("ALLOWANCE", "Allowance"),
    ("OVERTIME", "Overtime"),
    ("COMMISSION", "Commission"),
    ("TAX", "Tax"),
    ("PENSION", "Pension"),
    ("WELFARE", "Welfare"),
    ("ADVANCE_RECOVERY", "Advance Recovery"),
    ("LOAN_RECOVERY", "Loan Recovery"),
    ("PENALTY", "Penalty"),
    ("OTHER", "Other"),
]


class Agent(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="agent_profile",
        help_text="Login account for this agent.",
    )

    agent_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    location = models.CharField(max_length=150)
    workforce_role = models.CharField(max_length=20, choices=WORKFORCE_ROLE_CHOICES, default="AGENT")
    department = models.CharField(max_length=120, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default="FULL_TIME")
    employment_status = models.CharField(max_length=20, choices=EMPLOYMENT_STATUS_CHOICES, default="ACTIVE")
    hire_date = models.DateField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    residential_address = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=160, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    supervisor = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_members",
    )
    has_admin_access = models.BooleanField(default=False)
    payroll_active = models.BooleanField(default=True)
    preferred_payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, default="BANK")
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField(max_length=160, blank=True)
    bank_account_number = models.CharField(max_length=60, blank=True)
    mobile_money_name = models.CharField(max_length=160, blank=True)
    mobile_money_number = models.CharField(max_length=30, blank=True)
    tax_number = models.CharField(max_length=60, blank=True)
    social_security_number = models.CharField(max_length=60, blank=True)
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    meal_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    communication_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Commission rate as a percentage of collections for payroll calculation.",
    )
    notes = models.TextField(blank=True)

    photo = models.ImageField(upload_to="agents/photos/", blank=True, null=True)
    ghana_card_front = models.ImageField(upload_to="agents/ghana_cards/front/", blank=True, null=True)
    ghana_card_back = models.ImageField(upload_to="agents/ghana_cards/back/", blank=True, null=True)

    ghana_card_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    group_name = models.CharField(max_length=150, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        self.ghana_card_number = (self.ghana_card_number or "").strip().upper() or None
        super().save(*args, **kwargs)
        self.sync_login_email()
        self.sync_login_access()

    def sync_login_email(self):
        if not self.user_id:
            return
        email = (self.email or "").strip().lower()
        if (self.user.email or "").strip().lower() != email:
            self.user.email = email
            self.user.save(update_fields=["email"])

    def sync_login_access(self):
        if not self.user_id:
            return
        first_name = self.name.split()[0] if self.name else ""
        last_name = " ".join(self.name.split()[1:]) if self.name else ""
        changed = False
        if self.user.is_staff != self.has_admin_access:
            self.user.is_staff = self.has_admin_access
            changed = True
        if (self.user.first_name or "") != first_name:
            self.user.first_name = first_name
            changed = True
        if (self.user.last_name or "") != last_name:
            self.user.last_name = last_name
            changed = True
        if changed:
            self.user.save(update_fields=["is_staff", "first_name", "last_name"])

    @property
    def allowances_total(self):
        return (
            self.housing_allowance
            + self.transport_allowance
            + self.meal_allowance
            + self.communication_allowance
            + self.other_allowance
        ).quantize(Decimal("0.01"))

    @property
    def gross_regular_pay(self):
        return (self.base_salary + self.allowances_total).quantize(Decimal("0.01"))

    @property
    def role_label(self):
        return self.get_workforce_role_display()

    @property
    def is_field_agent(self):
        return self.workforce_role == "AGENT"

    def __str__(self):
        return f"{self.agent_id} - {self.name}"


class PayrollAdjustment(models.Model):
    employee = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="payroll_adjustments")
    adjustment_type = models.CharField(max_length=12, choices=ADJUSTMENT_TYPE_CHOICES)
    category = models.CharField(max_length=24, choices=ADJUSTMENT_CATEGORY_CHOICES, default="OTHER")
    label = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_recurring = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-created_at"]

    def __str__(self):
        return f"{self.employee.name} - {self.label}"


class PayrollRun(models.Model):
    title = models.CharField(max_length=160)
    period_start = models.DateField()
    period_end = models.DateField()
    pay_date = models.DateField()
    status = models.CharField(max_length=12, choices=PAYROLL_STATUS_CHOICES, default="DRAFT")
    include_active_only = models.BooleanField(default=True)
    include_commissions = models.BooleanField(default=True)
    include_loan_recovery = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_runs_created",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_runs_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_end", "-created_at"]

    @property
    def total_gross(self):
        total = self.lines.aggregate(total=models.Sum("gross_pay"))["total"] or Decimal("0.00")
        return total.quantize(Decimal("0.01"))

    @property
    def total_net(self):
        total = self.lines.aggregate(total=models.Sum("net_pay"))["total"] or Decimal("0.00")
        return total.quantize(Decimal("0.01"))

    @property
    def total_deductions(self):
        total = self.lines.aggregate(total=models.Sum("total_deductions"))["total"] or Decimal("0.00")
        return total.quantize(Decimal("0.01"))

    def __str__(self):
        return self.title


class PayrollLine(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="payroll_lines")
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, default="BANK")
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    fixed_allowances = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    bonus_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    commission_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    overtime_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    other_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    employee_pension_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    welfare_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    manual_statutory_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    employer_statutory_contributions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    statutory_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    loan_recovery_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    collections_tracked = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    disbursements_tracked = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["employee__name"]
        unique_together = ("run", "employee")

    def __str__(self):
        return f"{self.run.title} - {self.employee.name}"
