"""Shared ``/me/accounts`` enumeration for the Facebook-hosted Meta providers.

``FacebookProvider`` and ``InstagramProvider`` both read the same Graph edge —
one for the Pages themselves, one for the Instagram Business accounts linked to
them — so the cursor walking, the time budget and the CREATE_CONTENT rule live
here rather than being copied into each.

``InstagramLoginProvider`` drives Instagram's own API and deliberately uses none
of this.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .base import REQUEST_TIMEOUT
from .exceptions import APIError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .base import SocialProvider

logger = logging.getLogger(__name__)

# /me/accounts is paginated. A single response is commonly enough for an
# individual creator, but agencies and Business Manager users can administer
# hundreds of Pages, so we follow cursors rather than silently showing only the
# first response.
META_ACCOUNTS_PAGE_SIZE = 100
META_ACCOUNTS_MAX_PAGES = 100

# This runs inside the OAuth callback the user is waiting on, and each request
# carries the provider's full REQUEST_TIMEOUT. Without a wall-clock budget a
# slow Graph turns "you have a lot of Pages" into a platform request timeout
# with nothing connected and no partial progress saved. Stop early and work
# with what we have instead — well under the 30s most PaaS routers allow.
META_ACCOUNTS_MAX_SECONDS = 20.0

# Never hand httpx a zero or negative timeout when the budget is already spent:
# the first request always has to be allowed to happen, or the caller gets an
# empty list where a slow answer would have done.
META_ACCOUNTS_MIN_REQUEST_SECONDS = 1.0


def fetch_me_accounts(
    provider: SocialProvider,
    *,
    access_token: str,
    base_url: str,
    fields: str,
    error_message: str,
    max_seconds: float = META_ACCOUNTS_MAX_SECONDS,
    edge: str = "accounts",
) -> list[dict]:
    """Walk every page of ``/me/accounts`` and return the raw entries.

    Stops early — and says so — when the cursor chain ends, when the page cap is
    reached, or when the time budget runs out. Truncation is always logged: the
    whole point of following cursors is that a caller should never silently see
    a partial list, and a cap that quietly hides the remainder would put that
    bug back at a higher bound.
    """
    raw_pages: list[dict] = []
    after: str | None = None
    seen_cursors: set[str] = set()
    started = time.monotonic()
    truncated_reason: str | None = None

    for attempt in range(META_ACCOUNTS_MAX_PAGES):
        remaining = max_seconds - (time.monotonic() - started)
        if attempt and remaining <= 0:
            truncated_reason = f"time budget of {max_seconds:.0f}s exhausted"
            break

        params: dict = {"fields": fields, "limit": META_ACCOUNTS_PAGE_SIZE}
        if after:
            params["after"] = after
        data = provider._request(
            "GET",
            f"{base_url}/me/{edge}",
            access_token=access_token,
            params=params,
            # The budget has to bound each request, not just the gaps between
            # them. A page that answers after 19 of 20 seconds would otherwise
            # start another call carrying the provider's full timeout and blow
            # straight past the router limit the budget exists to stay under.
            timeout=min(REQUEST_TIMEOUT, max(remaining, META_ACCOUNTS_MIN_REQUEST_SECONDS)),
        ).json()
        if "error" in data:
            logger.error("%s /me/accounts error: %s", provider.platform_name, data["error"])
            raise APIError(
                f"{error_message}: {data['error'].get('message', 'Unknown error')}",
                platform=provider.platform_name,
                raw_response=data,
            )

        raw_pages.extend(data.get("data", []))
        paging = data.get("paging") or {}
        next_cursor = (paging.get("cursors") or {}).get("after")
        if not paging.get("next") or not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        after = next_cursor
    else:
        truncated_reason = f"page cap of {META_ACCOUNTS_MAX_PAGES} reached"

    if truncated_reason:
        logger.warning(
            "%s /me/accounts truncated after %d entries: %s. Some accounts will not be offered.",
            provider.platform_name,
            len(raw_pages),
            truncated_reason,
        )
    else:
        logger.debug("%s /me/accounts returned %d entries", provider.platform_name, len(raw_pages))
    return raw_pages


def fetch_pages_with_business_fallback(
    provider: SocialProvider,
    *,
    access_token: str,
    base_url: str,
    fields: str,
    error_message: str,
    max_seconds: float = META_ACCOUNTS_MAX_SECONDS,
) -> list[dict]:
    """``/me/accounts`` plus Pages reachable through the user's Business portfolios.

    Pages owned by a Business portfolio are often missing from ``/me/accounts``
    when the person did not tick them in the Login dialog, or when they hold the
    Page only through Business Manager. Postiz handles this by also walking
    ``/me/businesses`` -> ``owned_pages`` / ``client_pages`` (requires
    ``business_management``). Entries are de-duplicated by Page id, preferring
    the one that carries a Page access token. Business-edge failures never
    break onboarding: they are logged with counts only.
    """
    started = time.monotonic()
    pages = fetch_me_accounts(
        provider,
        access_token=access_token,
        base_url=base_url,
        fields=fields,
        error_message=error_message,
        max_seconds=max_seconds,
    )
    by_id: dict[str, dict] = {str(p.get("id")): p for p in pages if p.get("id")}

    def _remaining() -> float:
        return max_seconds - (time.monotonic() - started)

    def _walk(url: str, params: dict) -> list[dict]:
        out: list[dict] = []
        for _ in range(META_ACCOUNTS_MAX_PAGES):
            if _remaining() <= 0:
                break
            data = provider._request(
                "GET",
                url,
                access_token=access_token,
                params=params,
                timeout=min(REQUEST_TIMEOUT, max(_remaining(), META_ACCOUNTS_MIN_REQUEST_SECONDS)),
            ).json()
            if "error" in data:
                raise APIError(error_message, platform=provider.platform_name, raw_response=data)
            out.extend(data.get("data", []))
            after = ((data.get("paging") or {}).get("cursors") or {}).get("after")
            if not (data.get("paging") or {}).get("next") or not after:
                break
            params = {**params, "after": after}
        return out

    added = 0
    try:
        businesses = _walk(f"{base_url}/me/businesses", {"fields": "id", "limit": META_ACCOUNTS_PAGE_SIZE})
    except Exception:  # noqa: BLE001 - optional edge, never fatal
        logger.warning("%s business discovery unavailable (business_management missing?)", provider.platform_name)
        businesses = []
    for business in businesses:
        for edge in ("owned_pages", "client_pages"):
            try:
                found = _walk(
                    f"{base_url}/{business['id']}/{edge}",
                    {"fields": fields, "limit": META_ACCOUNTS_PAGE_SIZE},
                )
            except Exception:  # noqa: BLE001
                continue
            for page in found:
                pid = str(page.get("id") or "")
                if not pid:
                    continue
                current = by_id.get(pid)
                if current is None:
                    by_id[pid] = page
                    added += 1
                elif not current.get("access_token") and page.get("access_token"):
                    by_id[pid] = page
    logger.warning(
        "%s Meta discovery: me_accounts=%d businesses=%d business_only_pages=%d",
        provider.platform_name,
        len(pages),
        len(businesses),
        added,
    )
    return list(by_id.values())


def page_can_publish(page: dict) -> bool:
    """Whether the grant lets us create content on this Page.

    Meta reports the caller's per-Page permissions as a ``tasks`` list. A Page
    without ``CREATE_CONTENT`` accepts a connection and then fails every publish,
    so it must be rejected at onboarding rather than discovered later.

    An *omitted* ``tasks`` field is a Graph response that predates the field —
    unknown, not empty — and keeps the historical "assume publishable" behavior.
    An explicitly empty list is Meta telling us there are no tasks at all.
    """
    if "tasks" not in page:
        return True
    return "CREATE_CONTENT" in (page.get("tasks") or [])
