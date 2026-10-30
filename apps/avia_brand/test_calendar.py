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


def test_authorization_is_readonly_and_uses_pkce(calendar_session):
    client, user, ws = calendar_session
    response = client.post(url("_connect", ws), HTTP_HOST="localhost:8091")
    query = parse_qs(urlparse(response.url).query)
    assert query["scope"] == [" ".join(SCOPES)]
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
    with patch(
        "apps.avia_brand.google_calendar.api", return_value={"items": [{"id": "primary-id", "summary": "Mi agenda"}]}
    ):
        response = client.post(url("", ws), {"calendar_id": "primary-id"})
        assert response.status_code == 302
    connection.refresh_from_db()
    assert connection.calendar_id == "primary-id"
    with patch(
        "apps.avia_brand.google_calendar.api",
        side_effect=[
            {"items": []},
            {"items": [{"summary": "Reunión", "start": {"date": "2026-10-31"}, "end": {"date": "2026-11-01"}}]},
        ],
    ):
        response = client.get(url("", ws))
        assert "Reunión" in response.content.decode()
        assert "private-access" not in response.content.decode()


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
            api(connection, "users/me/calendarList")
        response = client.get(url("", ws))
        assert response.status_code == 200
        assert "Vuelve a conectar" in response.content.decode()


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
