from django.urls import path

from apps.avia_brand.welcome import entry

urlpatterns = [
    path("", entry, name="dashboard"),
]
