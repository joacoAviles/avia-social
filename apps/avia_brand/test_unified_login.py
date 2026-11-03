from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from providers.exceptions import OAuthError
from providers.instagram_unified import GRAPH, InstagramUnifiedProvider
from providers.types import PublishContent


def provider():
    return InstagramUnifiedProvider({"client_id": "demo", "client_secret": "synthetic", "config_id": "1234"})


def test_unified_dialog_uses_config_not_legacy_scopes():
    q = parse_qs(urlsplit(provider().get_auth_url("https://example.com/callback/", "nonce")).query)
    assert q["state"] == ["nonce"]
    assert q["prompt"] == ["login"]
    assert q["config_id"] == ["1234"]
    assert "scope" not in q
    with pytest.raises(OAuthError):
        provider().get_auth_url("http://example.com/callback/", "nonce")


def test_discovers_every_authorized_account_with_business_context():
    p = provider()
    replies = [
        {"client_business_id": "42"},
        {"data": [{"id": "1", "username": "one"}], "paging": {"next": "ignored", "cursors": {"after": "c1"}}},
        {"data": [{"id": "2", "username": "two"}]},
    ]
    with patch.object(p, "_request", side_effect=[Mock(json=lambda r=r: r) for r in replies]) as call:
        accounts = p.get_user_pages("synthetic-token")
    assert [a["id"] for a in accounts] == ["1", "2"]
    assert all(a["meta_oauth_context"] == {"client_business_id": "42", "config_id": "1234"} for a in accounts)
    assert call.call_args_list[1].args[1] == GRAPH + "/me/assigned_instagram_accounts"
    assert call.call_args_list[2].kwargs["params"]["after"] == "c1"


def test_publish_never_guesses_first_instagram_account():
    p = provider()
    with pytest.raises(OAuthError):
        p.publish_post("token", PublishContent(media_urls=["https://example.com/image.jpg"]))
    p.credentials["ig_user_id"] = "selected-2"
    with patch.object(p, "_publish_single") as send:
        p.publish_post(
            "token", PublishContent(media_urls=["https://example.com/image.jpg"], extra={"ig_user_id": "wrong-brand"})
        )
    assert send.call_args.args[1] == "selected-2"


def test_suat_is_not_refreshed_as_a_user_token():
    with pytest.raises(OAuthError):
        provider().refresh_token("token")


def test_code_exchange_keeps_suat_expiration_without_legacy_refresh():
    p = provider()
    with patch.object(
        p, "_request", return_value=Mock(json=lambda: {"access_token": "test-suat", "expires_in": 3600})
    ) as call:
        tokens = p.exchange_code("one-use-code", "https://example.com/callback/")
    assert tokens.access_token == "test-suat"
    assert tokens.expires_in == 3600
    assert tokens.refresh_token is None
    assert call.call_args.args == ("GET", GRAPH + "/oauth/access_token")
    assert call.call_args.kwargs["params"]["redirect_uri"] == "https://example.com/callback/"


def test_unified_does_not_advertise_unimplemented_inbox():
    from apps.social_accounts.webhooks import supports_webhooks
    from providers.base import SocialProvider

    p = provider()
    assert not supports_webhooks(p)
    assert type(p).get_messages is SocialProvider.get_messages


def test_empty_assigned_edge_recovers_only_token_authorized_ig():
    p = provider()
    replies = [
        {"client_business_id": "42"},
        {"data": []},
        {
            "data": {
                "app_id": "demo",
                "is_valid": True,
                "scopes": ["instagram_basic"],
                "granular_scopes": [{"scope": "instagram_basic", "target_ids": ["12"]}],
            }
        },
        {"id": "12", "username": "authorized"},
    ]
    with patch.object(p, "_request", side_effect=[Mock(json=lambda r=r: r) for r in replies]) as req:
        accounts = p.get_user_pages("customer-grant")
    assert [a["id"] for a in accounts] == ["12"]
    assert req.call_args_list[-1].kwargs["access_token"] == "customer-grant"
    assert accounts[0]["meta_oauth_context"]["client_business_id"] == "42"


@pytest.mark.parametrize(
    "data",
    [
        {"app_id": "other", "is_valid": True, "scopes": ["instagram_basic"]},
        {"app_id": "demo", "is_valid": False, "scopes": ["instagram_basic"]},
        {"app_id": "demo", "is_valid": True, "scopes": []},
    ],
)
def test_empty_edge_rejects_invalid_or_wrong_app_grants(data):
    p = provider()
    with patch.object(p, "_request", return_value=Mock(json=lambda: {"data": data})), pytest.raises(OAuthError):
        p._discover_granted_accounts("grant")


def test_empty_edge_does_not_invent_or_lookup_ungranted_accounts():
    p = provider()
    data = {"app_id": "demo", "is_valid": True, "scopes": ["instagram_basic"], "granular_scopes": []}
    with patch.object(p, "_request", return_value=Mock(json=lambda: {"data": data})) as req:
        assert p._discover_granted_accounts("grant") == []
        assert req.call_count == 1


def test_empty_edge_rejects_response_identity_mismatch():
    p = provider()
    replies = [
        {
            "data": {
                "app_id": "demo",
                "is_valid": True,
                "scopes": ["instagram_basic"],
                "granular_scopes": [{"scope": "instagram_basic", "target_ids": ["12"]}],
            }
        },
        {"id": "99", "username": "unrelated"},
    ]
    with patch.object(p, "_request", side_effect=[Mock(json=lambda r=r: r) for r in replies]):
        assert p._discover_granted_accounts("grant") == []


def test_granted_page_can_resolve_linked_instagram_with_customer_token():
    p = provider()
    replies = [
        {
            "data": {
                "app_id": "demo",
                "is_valid": True,
                "scopes": ["instagram_basic"],
                "granular_scopes": [{"scope": "pages_show_list", "target_ids": ["22"]}],
            }
        },
        {"id": "22", "instagram_business_account": {"id": "12", "username": "authorized"}},
    ]
    with patch.object(p, "_request", side_effect=[Mock(json=lambda r=r: r) for r in replies]) as req:
        assert p._discover_granted_accounts("customer-grant")[0]["id"] == "12"
    assert req.call_args.kwargs["access_token"] == "customer-grant"
