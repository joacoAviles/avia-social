# ruff: noqa: F811
"""AVIA 0.3 Meta connection diagnostics."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from apps.social_accounts import meta_connect
from apps.social_accounts.tests.test_views import authenticated_client, manager_setup, workspace  # noqa: F401,F811
from apps.social_accounts.views import OAUTH_SESSION_KEY, _sign_state
from providers.exceptions import APIError, OAuthError
from providers.types import OAuthTokens


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    return r


@pytest.mark.parametrize(
    "text,needle",
    [
        ("Can't load URL: The domain of this URL isn't included / redirect_uri mismatch", "dirección de retorno"),
        ("Error validating client secret.", "App Secret"),
        ("Invalid platform app", "ID de app de Instagram"),
        ("Insufficient developer role", "modo desarrollo"),
        ("This authorization code has been used.", "ya se usó"),
        ("Invalid Scopes: pages_messaging", "Bandeja de mensajes"),
    ],
)
def test_explain_error_maps_common_meta_failures(text, needle):
    assert needle in meta_connect.explain_error(OAuthError(text))


def test_explain_error_reads_raw_graph_error_and_redacts_tokens():
    exc = APIError("Failed", raw_response={"error": {"message": "Weird thing access_token=EAAB123secret"}})
    msg = meta_connect.explain_error(exc)
    assert "EAAB123secret" not in msg and "access_token=***" in msg


def test_user_token_permissions_splits_granted_and_declined():
    provider = MagicMock()
    provider._request.return_value = _resp(
        {
            "data": [
                {"permission": "pages_show_list", "status": "granted"},
                {"permission": "pages_manage_posts", "status": "declined"},
            ]
        }
    )
    granted, declined = meta_connect.user_token_permissions(provider, "t")
    assert granted == {"pages_show_list"} and declined == {"pages_manage_posts"}
    assert meta_connect.missing_essentials("facebook", granted) == ["pages_manage_posts"]


def test_user_token_permissions_unknown_never_blocks():
    provider = MagicMock()
    provider._request.side_effect = RuntimeError("boom")
    assert meta_connect.user_token_permissions(provider, "t") is None
    provider._request.side_effect = None
    provider._request.return_value = _resp({"data": []})
    assert meta_connect.user_token_permissions(provider, "t") is None


def test_validate_meta_app_ok_and_bad_secret():
    http = MagicMock()
    http.get.return_value = _resp({"id": "123", "name": "AVIA Social"})
    assert meta_connect.validate_meta_app("123", "s", http=http) == (
        True,
        "Credenciales válidas para la app «AVIA Social».",
    )
    http.get.return_value = _resp({"error": {"message": "Error validating client secret."}})
    ok, msg = meta_connect.validate_meta_app("123", "bad", http=http)
    assert not ok and "App Secret" in msg


@pytest.mark.django_db
def test_callback_stops_with_exact_missing_permissions(authenticated_client, workspace, user):
    state = _sign_state(workspace.id, "facebook", user.id, "n")
    session = authenticated_client.session
    session[OAUTH_SESSION_KEY] = {"nonce": "n"}
    session.save()
    provider = MagicMock()
    provider.exchange_code.return_value = OAuthTokens(access_token="user-token")
    provider.refresh_token.return_value = OAuthTokens(access_token="long", expires_in=100)
    provider._request.return_value = _resp(
        {
            "data": [
                {"permission": "pages_show_list", "status": "granted"},
                {"permission": "pages_manage_posts", "status": "declined"},
            ]
        }
    )
    url = reverse("social_accounts:oauth_callback", kwargs={"platform": "facebook"})
    with patch("apps.social_accounts.views._get_provider_for_platform", return_value=provider):
        response = authenticated_client.get(url, {"code": "c", "state": state})
    assert response.status_code == 302
    provider.get_user_pages.assert_not_called()
    text = " ".join(str(m) for m in get_messages(response.wsgi_request))
    assert "pages_manage_posts" in text and "desmarcó" in text


@pytest.mark.django_db
def test_callback_shows_provider_reason_instead_of_generic_error(authenticated_client, workspace, user):
    state = _sign_state(workspace.id, "instagram_login", user.id, "n")
    session = authenticated_client.session
    session[OAUTH_SESSION_KEY] = {"nonce": "n"}
    session.save()
    provider = MagicMock()
    provider.exchange_code.side_effect = OAuthError("Invalid platform app")
    url = reverse("social_accounts:oauth_callback", kwargs={"platform": "instagram_login"})
    with patch("apps.social_accounts.views._get_provider_for_platform", return_value=provider):
        response = authenticated_client.get(url, {"code": "c", "state": state})
    text = " ".join(str(m) for m in get_messages(response.wsgi_request))
    assert "ID de app de Instagram" in text


@pytest.mark.django_db
def test_callback_user_denied_message(authenticated_client, workspace):
    url = reverse("social_accounts:oauth_callback", kwargs={"platform": "facebook"})
    response = authenticated_client.get(url, {"error": "access_denied", "error_reason": "user_denied"})
    text = " ".join(str(m) for m in get_messages(response.wsgi_request))
    assert "Cancelaste la autorización" in text


def test_public_url_prefers_https_app_url(settings, rf):
    from apps.common.public_url import public_url

    request = rf.get("/x", HTTP_HOST="internal:8000")
    settings.OAUTH_PUBLIC_BASE_URL = ""
    assert public_url(request, "/cb/") == "http://internal:8000/cb/"
    settings.OAUTH_PUBLIC_BASE_URL = "https://social.example.cl/"
    assert public_url(request, "/cb/") == "https://social.example.cl/cb/"
    settings.OAUTH_PUBLIC_BASE_URL = "http://not-trusted"
    assert public_url(request, "/cb/") == "http://internal:8000/cb/"


def test_csp_allows_regional_facebook_hosts(settings):
    # Chile is redirected to web.facebook.com; form-action covers redirects.
    assert "https://*.facebook.com" in settings.CSP_FORM_ACTION
    assert "https://*.instagram.com" in settings.CSP_FORM_ACTION


def test_inbox_sync_reads_do_not_need_publish_switch(settings):
    # 0.3.2: with AVIA_PUBLISH_ENABLED off the inbox poll raised for every account.
    import inspect

    from apps.inbox import tasks

    assert "_resolve_publish_credentials(account, read_only=True)" in inspect.getsource(
        tasks.InboxSyncEngine._sync_account
    )


@pytest.mark.django_db
def test_paused_notice_is_admin_only_and_has_no_backend_details(authenticated_client, workspace, settings):
    from django.contrib.auth import get_user_model

    url = reverse("inbox:feed", kwargs={"workspace_id": workspace.id})
    settings.AVIA_PUBLISH_ENABLED = False
    html = authenticated_client.get(url).content.decode()
    assert "en pausa en esta instalación" not in html and "AVIA_PUBLISH_ENABLED" not in html
    get_user_model().objects.update(is_superuser=True)
    html = authenticated_client.get(url).content.decode()
    assert "en pausa en esta instalación" in html and "AVIA_PUBLISH_ENABLED" not in html
    settings.AVIA_PUBLISH_ENABLED = True
    assert "en pausa en esta instalación" not in authenticated_client.get(url).content.decode()
