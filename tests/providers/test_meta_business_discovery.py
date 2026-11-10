"""Pages held only through a Business portfolio must still be offered."""

from unittest.mock import MagicMock

from providers.facebook import FacebookProvider
from providers.instagram import InstagramProvider


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    return r


def _router(routes):
    def _request(method, url, **kwargs):
        for suffix, payload in routes.items():
            if url.endswith(suffix):
                return _resp(payload)
        return _resp({"data": []})

    return _request


def test_facebook_finds_business_owned_page_missing_from_me_accounts():
    provider = FacebookProvider({"client_id": "a", "client_secret": "b"})
    provider._request = MagicMock(
        side_effect=_router(
            {
                "/me/accounts": {"data": []},
                "/me/businesses": {"data": [{"id": "biz-1"}]},
                "/biz-1/owned_pages": {
                    "data": [{"id": "p-9", "name": "AVIA", "access_token": "pt", "tasks": ["CREATE_CONTENT"]}]
                },
            }
        )
    )
    pages = provider.get_user_pages("user-token")
    assert [p["id"] for p in pages] == ["p-9"]
    assert pages[0]["access_token"] == "pt"
    assert pages[0]["can_publish"] is True


def test_business_discovery_failure_keeps_me_accounts_result():
    provider = InstagramProvider({"client_id": "a", "client_secret": "b"})
    provider._request = MagicMock(
        side_effect=_router(
            {
                "/me/accounts": {
                    "data": [
                        {
                            "id": "p-1",
                            "name": "Page",
                            "access_token": "pt",
                            "instagram_business_account": {"id": "ig-1", "username": "avia"},
                        }
                    ]
                },
                "/me/businesses": {"error": {"message": "Missing permission"}},
            }
        )
    )
    accounts = provider.get_user_pages("user-token")
    assert [a["id"] for a in accounts] == ["ig-1"]


def test_duplicate_page_prefers_entry_with_token():
    provider = FacebookProvider({"client_id": "a", "client_secret": "b"})
    provider._request = MagicMock(
        side_effect=_router(
            {
                "/me/accounts": {"data": [{"id": "p-1", "name": "Page"}]},
                "/me/businesses": {"data": [{"id": "biz-1"}]},
                "/biz-1/owned_pages": {"data": [{"id": "p-1", "name": "Page", "access_token": "pt"}]},
            }
        )
    )
    pages = provider.get_user_pages("user-token")
    assert len(pages) == 1 and pages[0]["access_token"] == "pt"


def test_scopes_match_postiz_for_page_and_instagram_discovery():
    fb = FacebookProvider({"client_id": "a", "client_secret": "b"}).required_scopes
    ig = InstagramProvider({"client_id": "a", "client_secret": "b"}).required_scopes
    assert {"business_management", "pages_show_list", "pages_read_engagement"} <= set(fb)
    assert {"business_management", "pages_show_list", "pages_read_engagement", "instagram_basic"} <= set(ig)
