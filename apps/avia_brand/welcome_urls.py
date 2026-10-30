from django.urls import path

from . import google_calendar, welcome

app_name = "welcome"
urlpatterns = [
    path("<uuid:workspace_id>/calendar/create/", google_calendar.create_calendar, name="calendar_create"),
    path("<uuid:workspace_id>/calendar/sync/", google_calendar.synchronize, name="calendar_sync"),
    path("<uuid:workspace_id>/calendar/", google_calendar.agenda, name="calendar"),
    path("<uuid:workspace_id>/calendar/connect/", google_calendar.connect, name="calendar_connect"),
    path("<uuid:workspace_id>/calendar/callback/", google_calendar.callback, name="calendar_callback"),
    path("<uuid:workspace_id>/calendar/disconnect/", google_calendar.disconnect, name="calendar_disconnect"),
    path("setup/", welcome.setup, name="setup"),
    path("<uuid:workspace_id>/", welcome.journey, name="journey"),
]
