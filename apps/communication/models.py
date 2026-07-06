from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone



class WebsiteLead(models.Model):
    STATUS_CHOICES = [
        ("NEW", "New"),
        ("CONTACTED", "Contacted"),
        ("QUALIFIED", "Qualified"),
        ("CONVERTED", "Converted"),
        ("ARCHIVED", "Archived"),
    ]

    SOURCE_CHOICES = [
        ("CONTACT_FORM", "Website Contact Form"),
        ("MANUAL", "Manual Entry"),
    ]

    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    subject = models.CharField(max_length=160, blank=True)
    message = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="CONTACT_FORM")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="NEW")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.status})"


class MarketingTemplate(models.Model):
    CHANNEL_CHOICES = [
        ("SMS", "SMS"),
        ("EMAIL", "Email"),
        ("WHATSAPP", "WhatsApp Copy"),
        ("POPUP", "Website Popup"),
    ]

    CATEGORY_CHOICES = [
        ("ACQUISITION", "Customer Acquisition"),
        ("PROMOTION", "Promotional Offer"),
        ("REFERRAL", "Referral Drive"),
        ("REACTIVATION", "Dormant Client Reactivation"),
        ("LOYALTY", "Loyalty / Top-Up"),
        ("SEASONAL", "Seasonal Campaign"),
        ("AWARENESS", "Brand Awareness"),
        ("ANNOUNCEMENT", "Branch / Service Announcement"),
    ]

    title = models.CharField(max_length=160)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="PROMOTION")
    objective = models.CharField(max_length=180, blank=True)
    audience_hint = models.CharField(max_length=180, blank=True)
    subject = models.CharField(max_length=180, blank=True)
    body = models.TextField()
    cta_label = models.CharField(max_length=80, blank=True)
    cta_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    is_example = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_featured", "-is_example", "sort_order", "title"]

    def __str__(self):
        return f"{self.title} [{self.get_channel_display()}]"


class MarketingCampaign(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SENT", "Sent"),
        ("PAUSED", "Paused"),
    ]

    CHANNEL_CHOICES = MarketingTemplate.CHANNEL_CHOICES

    title = models.CharField(max_length=160)
    template = models.ForeignKey(
        MarketingTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    audience_type = models.CharField(max_length=60)
    objective = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    subject = models.CharField(max_length=180, blank=True)
    message = models.TextField()
    call_to_action_label = models.CharField(max_length=80, blank=True)
    call_to_action_url = models.URLField(blank=True)
    filters_json = models.JSONField(default=dict, blank=True)
    preview_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketing_campaigns_created",
    )
    last_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_channel_display()})"


class MarketingDispatchLog(models.Model):
    STATUS_CHOICES = [
        ("SENT", "Sent"),
        ("SKIPPED", "Skipped"),
        ("COPIED", "Copy Ready"),
    ]

    CHANNEL_CHOICES = MarketingTemplate.CHANNEL_CHOICES

    campaign = models.ForeignKey(
        MarketingCampaign,
        on_delete=models.CASCADE,
        related_name="dispatch_logs",
        null=True,
        blank=True,
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    recipient_name = models.CharField(max_length=160, blank=True)
    recipient_phone = models.CharField(max_length=30, blank=True)
    recipient_email = models.EmailField(blank=True)
    recipient_segment = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    message_preview = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketing_dispatches_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        label = self.recipient_name or self.recipient_phone or self.recipient_email or "Recipient"
        return f"{label} [{self.get_channel_display()} - {self.status}]"


class WebsiteMarketingPopup(models.Model):
    THEME_CHOICES = [
        ("GOLD", "Gold Spotlight"),
        ("FOREST", "Forest Green"),
        ("MIDNIGHT", "Midnight Dark"),
    ]

    name = models.CharField(max_length=120)
    badge = models.CharField(max_length=80, blank=True)
    headline = models.CharField(max_length=180)
    body = models.TextField()
    cta_label = models.CharField(max_length=80, blank=True)
    cta_url = models.URLField(blank=True)
    secondary_label = models.CharField(max_length=80, blank=True)
    secondary_url = models.URLField(blank=True)
    image = models.ImageField(upload_to="marketing/popups/", blank=True)
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default="GOLD")
    is_active = models.BooleanField(default=False)
    show_once_per_browser = models.BooleanField(default=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="website_marketing_popups_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name

    @property
    def storage_key(self) -> str:
        version = int(self.updated_at.timestamp()) if self.updated_at else self.pk
        return f"marketing-popup-{self.pk}-{version}"

    @classmethod
    def get_live_popup(cls):
        now = timezone.now()
        return (
            cls.objects.filter(is_active=True)
            .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
            .filter(Q(end_at__isnull=True) | Q(end_at__gte=now))
            .order_by("-updated_at")
            .first()
        )
