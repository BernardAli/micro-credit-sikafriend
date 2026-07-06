from django.contrib import admin

from .models import (
    MarketingCampaign,
    MarketingDispatchLog,
    MarketingTemplate,
    WebsiteLead,
    WebsiteMarketingPopup,
)


@admin.register(WebsiteLead)
class WebsiteLeadAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "status", "source", "created_at")
    list_filter = ("status", "source", "created_at")
    search_fields = ("name", "email", "phone", "subject", "message")


@admin.register(MarketingTemplate)
class MarketingTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "channel", "category", "is_example", "is_featured", "is_active", "updated_at")
    list_filter = ("channel", "category", "is_example", "is_featured", "is_active")
    search_fields = ("title", "objective", "audience_hint", "subject", "body")


@admin.register(MarketingCampaign)
class MarketingCampaignAdmin(admin.ModelAdmin):
    list_display = ("title", "channel", "audience_type", "status", "preview_count", "sent_count", "last_sent_at")
    list_filter = ("channel", "status", "audience_type", "created_at")
    search_fields = ("title", "objective", "subject", "message")


@admin.register(MarketingDispatchLog)
class MarketingDispatchLogAdmin(admin.ModelAdmin):
    list_display = ("recipient_name", "channel", "status", "recipient_segment", "created_at")
    list_filter = ("channel", "status", "created_at")
    search_fields = ("recipient_name", "recipient_phone", "recipient_email", "recipient_segment", "message_preview")


@admin.register(WebsiteMarketingPopup)
class WebsiteMarketingPopupAdmin(admin.ModelAdmin):
    list_display = ("name", "theme", "is_active", "show_once_per_browser", "start_at", "end_at", "updated_at")
    list_filter = ("theme", "is_active", "show_once_per_browser")
    search_fields = ("name", "badge", "headline", "body")
