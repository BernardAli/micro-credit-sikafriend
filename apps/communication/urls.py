from django.urls import path
from .views import arkesel_ussd, hubtel_ussd, management_message_center, marketing_hub

app_name = "communications"

urlpatterns = [
    path("management/marketing/", marketing_hub, name="marketing_hub"),
    path("management/messages/", management_message_center, name="management_message_center"),
    path("hubtel/ussd/", hubtel_ussd, name="hubtel_ussd"),
    path("arkesel/ussd/", arkesel_ussd, name="arkesel_ussd"),
]
