# ruff: noqa: F811, SIM117
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from apps.avia_brand.test_welcome import owner, session  # noqa: F401
from apps.credentials.models import PlatformCredential
from providers import get_provider
from providers.exceptions import OAuthError, PublishError
from providers.types import PostType, PublishContent

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("platform", ["linkedin_personal", "linkedin_company", "x", "reddit"])
def test_setup_supports_new_channels_without_enabling_other_channels(session, platform):
    client, ws, url = session
    payload = dict(action="credentials", platform=platform, client_id="demo-id", client_secret="demo-secret")
    if platform == "reddit":
        payload.update(subreddit="mycommunity", reddit_username="mydeveloper")
    response = client.post(url, payload, HTTP_HOST="localhost")
    assert response.status_code == 302
    row = PlatformCredential.objects.get(organization=ws.organization, platform=platform)
    assert row.is_configured
    assert PlatformCredential.objects.filter(organization=ws.organization).count() == 1
    html = client.get(url + "?step=connections&configure=" + platform).content.decode()
    assert "demo-secret" not in html
    assert f"/social-accounts/callback/{platform}/" in html
    assert "Prepara la aplicación (administrador)" not in html  # no accidental YouTube guide


def test_reddit_requires_explicit_destination(session):
    client, ws, url = session
    response = client.post(
        url,
        dict(action="credentials", platform="reddit", client_id="demo", client_secret="demo"),
        HTTP_HOST="localhost",
    )
    assert response.status_code == 200
    assert not PlatformCredential.objects.filter(platform="reddit").exists()


def test_x_pkce_and_tokens():
    provider = get_provider("x", {"client_id": "demo", "client_secret": "synthetic"})
    with pytest.raises(OAuthError):
        provider.get_auth_url("https://example.com/callback/", "state")
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    query = parse_qs(urlsplit(provider.get_auth_url("https://example.com/callback/", "state", verifier)).query)
    assert query["code_challenge"] == ["E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"]
    assert query["code_challenge_method"] == ["S256"]
    with patch.object(
        provider, "_request", return_value=Mock(json=lambda: {"access_token": "test-token", "refresh_token": "refresh"})
    ) as call:
        assert provider.exchange_code("code", "https://example.com/callback/", verifier).refresh_token == "refresh"
        assert call.call_args.kwargs["data"]["code_verifier"] == verifier
        assert call.call_args.kwargs["headers"]["Authorization"].startswith("Basic ")
        assert provider.refresh_token("refresh").access_token == "test-token"


@pytest.mark.parametrize("platform", ["x", "reddit"])
def test_text_publish_rejects_media_before_network(platform):
    provider = get_provider(platform, {"subreddit": "example"})
    with patch.object(provider, "_request") as call:
        with pytest.raises(PublishError):
            provider.publish_post(
                "test",
                PublishContent(text="Example", post_type=PostType.IMAGE, media_urls=["https://example.com/a.jpg"]),
            )
        call.assert_not_called()


def test_x_publish_and_uncertain_send():
    provider = get_provider("x", {})
    with patch.object(provider, "_request", return_value=Mock(json=lambda: {"data": {"id": "123"}})) as call:
        assert provider.publish_post("test", PublishContent(text="Example")).platform_post_id == "123"
        assert call.call_args.kwargs["json"] == {"text": "Example"}
    with patch.object(provider, "_request", side_effect=httpx.ReadTimeout("timeout")):
        with pytest.raises(PublishError) as error:
            provider.publish_post("test", PublishContent(text="Example"))
        assert not error.value.retryable


def test_reddit_oauth_and_publish():
    provider = get_provider(
        "reddit",
        {"client_id": "demo", "client_secret": "synthetic", "subreddit": "example", "user_agent": "test-agent"},
    )
    query = parse_qs(urlsplit(provider.get_auth_url("https://example.com/callback/", "state")).query)
    assert query["duration"] == ["permanent"]
    assert query["scope"] == ["identity submit"]
    assert not provider.uses_pkce
    with patch.object(
        provider, "_request", return_value=Mock(json=lambda: {"json": {"errors": [], "data": {"id": "abc"}}})
    ) as call:
        assert provider.publish_post("test", PublishContent(text="Heading\nBody")).platform_post_id == "abc"
        assert call.call_args.kwargs["data"]["sr"] == "example"
        assert call.call_args.kwargs["data"]["title"] == "Heading"
    with patch.object(
        provider, "_request", return_value=Mock(json=lambda: {"json": {"errors": [["NO_USER", "denied"]]}})
    ):
        with pytest.raises(PublishError):
            provider.publish_post("test", PublishContent(text="Example"))


def test_whatsapp_does_not_claim_api_connection(session):
    client, ws, url = session
    html = client.get(url + "?step=connections").content.decode()
    assert "WhatsApp personal" in html and "WhatsApp Business" in html
    assert "Esta versión todavía no recibe ni envía mensajes WhatsApp" in html
    assert 'value="whatsapp"' not in html
