from django.urls import path
from . import views

app_name = "borrower"

urlpatterns = [
    path("my-account/",          views.portal_home,        name="portal"),
    path("my-account/loan/<int:loan_id>/", views.portal_loan_detail, name="loan_detail"),
    path("my-account/change-password/",             views.portal_change_password, name="change_password"),
    path("my-account/loan/<int:loan_id>/pay/",       views.portal_make_payment,    name="make_payment"),
]
