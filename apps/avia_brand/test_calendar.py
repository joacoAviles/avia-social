import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User

from .google_calendar import SCOPES, CalendarError, api
from .models import CalendarConnection, InstallationSetup

pytestmark = pytest.mark.django_db


@pytest.fixture
def calendar_session():
    user = User.objects.create_superuser(email="calendar@example.test", password="test", tos_accepted_at=timezone.now())
    ws = user.workspace_memberships.first().workspace
    client = Client()
    client.force_login(user)
    InstallationSetup.objects.update_or_create(
        pk=1, defaults={"calendar_credentials": {"client_id": "calendar-client", "client_secret": "synthetic-secret"}}
    )
    return client, user, ws


def url(name, ws):
    return reverse("welcome:calendar" + name, args=[ws.id])


def test_authorization_is_app_created_only_and_uses_pkce(calendar_session):
    client, user, ws = calendar_session
    response = client.post(url("_connect", ws), HTTP_HOST="localhost:8091")
    query = parse_qs(urlparse(response.url).query)
    assert query["scope"] == ["https://www.googleapis.com/auth/calendar.app.created"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://localhost:8091" + url("_callback", ws)]
    assert "client_secret" not in response.url
    assert client.get(url("_connect", ws)).status_code == 405


def test_callback_is_single_use_and_bad_state_never_exchanged(calendar_session):
    client, user, ws = calendar_session
    client.post(url("_connect", ws), HTTP_HOST="localhost")
    with patch("apps.avia_brand.google_calendar.exchange") as exchange:
        client.get(url("_callback", ws), {"state": "wrong", "code": "fake"})
        exchange.assert_not_called()
    assert not CalendarConnection.objects.exists()


def test_grant_stored_encrypted_and_selects_calendar(calendar_session):
    client, user, ws = calendar_session
    client.post(url("_connect", ws), HTTP_HOST="localhost")
    state = client.session["calendar_oauth"]["state"]
    with patch(
        "apps.avia_brand.google_calendar.exchange",
        return_value={
            "access_token": "private-access",
            "refresh_token": "private-refresh",
            "scope": " ".join(SCOPES),
            "expires_in": 3600,
        },
    ):
        client.get(url("_callback", ws), {"state": state, "code": "synthetic"})
    connection = CalendarConnection.objects.get(user=user, workspace=ws)
    from django.db import connection as db

    with db.cursor() as cursor:
        cursor.execute("SELECT tokens FROM avia_brand_calendarconnection WHERE id=%s", [connection.pk])
        assert "private-access" not in str(cursor.fetchone())
    with patch("apps.avia_brand.google_calendar.api", return_value={"id": "avia-calendar"}) as google:
        response = client.post(url("_create", ws))
        assert response.status_code == 302
        assert google.call_args.args[1] == "calendars"
        assert google.call_args.kwargs["method"] == "POST"
        client.post(url("_create", ws))
        assert google.call_count == 1
    connection.refresh_from_db()
    assert connection.calendar_id == "avia-calendar" and connection.managed
    with patch("apps.avia_brand.google_calendar.api") as google:
        response = client.get(url("", ws))
        google.assert_not_called()
        assert "private-access" not in response.content.decode()
        assert "Abrir Google Calendar" in response.content.decode()


def test_other_user_cannot_read_grant_and_disconnect_is_post(calendar_session):
    client, user, ws = calendar_session
    CalendarConnection.objects.create(user=user, workspace=ws, tokens={"access_token": "secret"})
    outsider = User.objects.create_user(email="other@example.test", password="test", tos_accepted_at=timezone.now())
    client.force_login(outsider)
    assert client.get(url("", ws)).status_code == 403
    client.force_login(user)
    assert client.get(url("_disconnect", ws)).status_code == 405
    client.post(url("_disconnect", ws))
    assert not CalendarConnection.objects.exists()


def test_expired_token_refresh_failure_is_actionable(calendar_session):
    client, user, ws = calendar_session
    connection = CalendarConnection.objects.create(
        user=user,
        workspace=ws,
        tokens={"access_token": "secret", "refresh_token": "refresh", "expires_at": time.time() - 10},
    )
    with patch("apps.avia_brand.google_calendar.exchange", side_effect=CalendarError("Vuelve a conectar")):
        with pytest.raises(CalendarError):
            api(connection, "calendars/avia-calendar/events")
        response = client.get(url("", ws))
        assert response.status_code == 200
        assert "Volver a autorizar" in response.content.decode()


def test_calendar_settings_do_not_replace_google_login_or_youtube(calendar_session):
    client, user, ws = calendar_session
    state = InstallationSetup.objects.get(pk=1)
    state.google_credentials = {"client_id": "login-original", "client_secret": "login-secret"}
    state.save()
    response = client.post(
        reverse("welcome:journey", args=[ws.id]),
        {
            "action": "credentials",
            "platform": "google_calendar",
            "client_id": "calendar-new",
            "client_secret": "calendar-new-secret",
        },
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    state.refresh_from_db()
    assert state.google_credentials["client_id"] == "login-original"
    assert state.calendar_credentials["client_id"] == "calendar-new"
    html = client.get(reverse("welcome:journey", args=[ws.id]) + "?step=connections").content.decode()
    assert "Conectar Google Calendar" in html
    assert "Usa tu cuenta Google para entrar" not in html


def test_missing_scopes_preserves_previous_grant(calendar_session):
    client, user, ws = calendar_session
    previous = CalendarConnection.objects.create(
        user=user, workspace=ws, tokens={"access_token": "previous"}, calendar_id="original"
    )
    client.post(url("_connect", ws), HTTP_HOST="localhost")
    state = client.session["calendar_oauth"]["state"]
    with patch(
        "apps.avia_brand.google_calendar.exchange",
        return_value={"access_token": "new", "refresh_token": "new", "scope": ""},
    ):
        client.get(url("_callback", ws), {"state": state, "code": "fake"})
    previous.refresh_from_db()
    assert previous.tokens["access_token"] == "previous"
    assert previous.calendar_id == "original"


def test_expired_or_replayed_callback_rejected(calendar_session):
    client, user, ws = calendar_session
    client.post(url("_connect", ws), HTTP_HOST="localhost")
    session = client.session
    pending = session["calendar_oauth"]
    pending["created"] = time.time() - 601
    session["calendar_oauth"] = pending
    session.save()
    with patch("apps.avia_brand.google_calendar.exchange") as exchange:
        for _ in range(2):
            client.get(url("_callback", ws), {"state": pending["state"], "code": "fake"})
        exchange.assert_not_called()


def test_calendar_post_requires_csrf(calendar_session):
    client, user, ws = calendar_session
    checked = Client(enforce_csrf_checks=True)
    checked.force_login(user)
    assert checked.post(url("_connect", ws)).status_code == 403
    assert checked.post(url("_disconnect", ws)).status_code == 403


def test_calendar_admin_credentials_require_superuser(calendar_session):
    client, user, ws = calendar_session
    user.is_superuser = False
    user.save(update_fields=["is_superuser"])
    response = client.post(
        reverse("welcome:journey", args=[ws.id]),
        {"action": "credentials", "platform": "google_calendar", "client_id": "bad", "client_secret": "bad"},
        HTTP_HOST="localhost",
    )
    assert response.status_code == 403


def test_uncertain_calendar_creation_never_retries_automatically(calendar_session):
    client, user, ws = calendar_session
    connection = CalendarConnection.objects.create(user=user, workspace=ws, tokens={"scope": " ".join(SCOPES)})
    with patch("apps.avia_brand.google_calendar.api", side_effect=CalendarError("Resultado incierto")) as google:
        client.post(url("_create", ws))
        client.post(url("_create", ws))
        assert google.call_count == 1
    connection.refresh_from_db()
    assert connection.creation_started and not connection.managed


def test_sync_creates_edits_moves_deletes_without_reading_google(calendar_session):
    from datetime import date

    from apps.calendar.models import CustomCalendarEvent

    from .calendar_sync import sync_connection
    from .models import CalendarMirror

    client, user, ws = calendar_session
    connection = CalendarConnection.objects.create(user=user, workspace=ws, managed=True, calendar_id="avia-only")
    event = CustomCalendarEvent.objects.create(
        workspace=ws, title="Lanzamiento", start_date=date(2026, 11, 1), end_date=date(2026, 11, 1)
    )
    with patch("apps.avia_brand.calendar_sync.api", return_value={}) as google:
        sync_connection(connection.pk)
        assert google.call_count == 1
        assert google.call_args.kwargs["method"] == "POST"
        event_id = google.call_args.kwargs["body"]["id"]
        sync_connection(connection.pk)
        assert google.call_count == 1
        event.title = "Lanzamiento nuevo"
        event.start_date = event.end_date = date(2026, 11, 3)
        event.save()
        sync_connection(connection.pk)
        assert google.call_args.kwargs["method"] == "PATCH"
        assert google.call_args.args[1].endswith(event_id)
        assert google.call_args.kwargs["body"]["start"] == {"date": "2026-11-03"}
        event.delete()
        sync_connection(connection.pk)
        assert google.call_args.kwargs["method"] == "DELETE"
        assert all("avia-only" in call.args[1] for call in google.call_args_list)
        assert all(call.kwargs["method"] != "GET" for call in google.call_args_list)
    assert CalendarMirror.objects.get(connection=connection).fingerprint == ""


def test_sync_lost_response_reuses_event_id(calendar_session):
    from datetime import date

    from apps.calendar.models import CustomCalendarEvent

    from .calendar_sync import sync_connection

    client, user, ws = calendar_session
    connection = CalendarConnection.objects.create(user=user, workspace=ws, managed=True, calendar_id="avia-only")
    CustomCalendarEvent.objects.create(
        workspace=ws, title="Demo", start_date=date(2026, 11, 1), end_date=date(2026, 11, 1)
    )
    with patch("apps.avia_brand.calendar_sync.api", side_effect=CalendarError("Timeout")) as google:
        with pytest.raises(CalendarError):
            sync_connection(connection.pk)
        event_id = google.call_args.kwargs["body"]["id"]
    with patch("apps.avia_brand.calendar_sync.api", side_effect=[CalendarError("Already exists", 409), {}]) as google:
        sync_connection(connection.pk)
        assert google.call_args_list[0].kwargs["body"]["id"] == event_id
        assert google.call_args_list[1].kwargs["method"] == "PATCH"


def test_existing_personal_calendar_cannot_be_synced(calendar_session):
    from .calendar_sync import sync_connection

    client, user, ws = calendar_session
    connection = CalendarConnection.objects.create(user=user, workspace=ws, calendar_id="primary", managed=False)
    with patch("apps.avia_brand.calendar_sync.api") as google:
        with pytest.raises(CalendarError):
            sync_connection(connection.pk)
        google.assert_not_called()
    assert client.post(url("_sync", ws)).status_code == 404


def test_dated_drafts_are_mirrored(calendar_session):
    from apps.composer.models import Post

    from .calendar_sync import desired_events

    client, user, ws = calendar_session
    post = Post.objects.create(workspace=ws, author=user, title="Demo", proposed_publish_at=timezone.now())
    assert desired_events(ws.pk)["draft:" + str(post.pk)]["summary"] == "Demo"


def test_sync_stops_when_workspace_permission_is_removed(calendar_session):
    from apps.members.models import WorkspaceMembership

    from .calendar_sync import sync_connection

    client, user, ws = calendar_session
    connection = CalendarConnection.objects.create(user=user, workspace=ws, managed=True, calendar_id="avia-only")
    WorkspaceMembership.objects.filter(user=user, workspace=ws).delete()
    with patch("apps.avia_brand.calendar_sync.api") as google:
        with pytest.raises(CalendarError):
            sync_connection(connection.pk)
        google.assert_not_called()


def test_reauthorization_preserves_managed_calendar(calendar_session):
    client, user, ws = calendar_session
    connection = CalendarConnection.objects.create(
        user=user, workspace=ws, managed=True, calendar_id="avia-only", tokens={"access_token": "old"}
    )
    client.post(url("_connect", ws), HTTP_HOST="localhost")
    state = client.session["calendar_oauth"]["state"]
    with patch(
        "apps.avia_brand.google_calendar.exchange",
        return_value={"access_token": "new", "refresh_token": "new", "scope": " ".join(SCOPES)},
    ):
        client.get(url("_callback", ws), {"state": state, "code": "synthetic"})
    connection.refresh_from_db()
    assert connection.managed and connection.calendar_id == "avia-only"
    assert connection.tokens["access_token"] == "new"
