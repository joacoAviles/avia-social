from django.urls import path

from . import welcome

app_name = "welcome"
urlpatterns = [
    path("setup/", welcome.setup, name="setup"),
    path("<uuid:workspace_id>/", welcome.journey, name="journey"),
]
