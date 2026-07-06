from django.urls import path

from . import views


app_name = "assets"

urlpatterns = [
    path("", views.assets_hub, name="hub"),
    path("import/", views.asset_bulk_import, name="bulk_import"),
    path("import/sample/<str:file_type>/", views.asset_bulk_import_sample, name="bulk_import_sample"),
    path("<int:pk>/", views.asset_detail, name="detail"),
]
