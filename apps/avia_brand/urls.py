from django.urls import path

from . import template_builder, views

app_name = "avia_brand"
urlpatterns = [
    path("<uuid:workspace_id>/template/", template_builder.builder, name="template_builder"),
    path("<uuid:workspace_id>/", views.catalog, name="catalog"),
    path("<uuid:workspace_id>/sync/", views.synchronize, name="sync"),
    path("<uuid:workspace_id>/<uuid:revision_id>/review/", views.decide, name="review"),
    path("<uuid:workspace_id>/<uuid:revision_id>/asset/<str:sha>/", views.asset, name="asset"),
    path("webhooks/github/", views.webhook, name="webhook"),
]
