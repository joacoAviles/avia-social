"""Instagram Unified Login (Meta documentation, 2026-10-27).

Separate platform identity keeps existing Instagram grants on their original
host and token lifecycle. A SUAT is never exchanged as a Facebook user token.
"""

import logging
import time
from dataclasses import replace
from urllib.parse import urlencode

from .base import SocialProvider
from .exceptions import OAuthError, ProviderError
from .instagram import BASE_URL as LEGACY_BASE
from .instagram import InstagramProvider
from .meta_accounts import fetch_me_accounts
from .types import OAuthTokens

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v26.0"


class InstagramUnifiedProvider(InstagramProvider):
    platform_name = "instagram_unified"
    # Inbox routing and metrics need their own verified integration contract.
    subscribe_webhooks = SocialProvider.subscribe_webhooks
    unsubscribe_webhooks = SocialProvider.unsubscribe_webhooks
    get_messages = SocialProvider.get_messages
    reply_to_message = SocialProvider.reply_to_message
    reply_to_comment = SocialProvider.reply_to_comment
    get_account_metrics = SocialProvider.get_account_metrics
    get_post_metrics = SocialProvider.get_post_metrics

    @property
    def required_scopes(self):
        return ["instagram_basic", "instagram_content_publish"]

    def _request(self, method, url, **kwargs):
        if url.startswith(LEGACY_BASE + "/"):
            url = GRAPH + url[len(LEGACY_BASE) :]
        return super()._request(method, url, **kwargs)

    def get_auth_url(self, redirect_uri, state, code_verifier=None):
        if not redirect_uri.startswith("https://") or not self.credentials.get("config_id"):
            raise OAuthError("Unified Login necesita HTTPS y Configuration ID.", platform=self.platform_name)
        return "https://www.facebook.com/dialog/oauth?" + urlencode(
            {
                "client_id": self.credentials["client_id"],
                "config_id": self.credentials["config_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "state": state,
                "prompt": "login",
            }
        )

    def exchange_code(self, code, redirect_uri, code_verifier=None):
        body = self._request(
            "GET",
            f"{GRAPH}/oauth/access_token",
            params={
                "client_id": self.credentials["client_id"],
                "client_secret": self.credentials["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
            },
        ).json()
        if not body.get("access_token"):
            raise OAuthError("Meta no devolvió un token empresarial.", platform=self.platform_name)
        return OAuthTokens(access_token=body["access_token"], expires_in=body.get("expires_in"))

    def refresh_token(self, refresh_token):
        raise OAuthError("Vuelve a autorizar el portfolio en Meta.", platform=self.platform_name)

    def get_user_pages(self, access_token):
        business = (
            self._request("GET", f"{GRAPH}/me", access_token=access_token, params={"fields": "client_business_id"})
            .json()
            .get("client_business_id")
        )
        if not business:
            raise OAuthError("Meta no devolvió el portfolio autorizado.", platform=self.platform_name)
        accounts = fetch_me_accounts(
            self,
            access_token=access_token,
            base_url=GRAPH,
            fields="id,username",
            error_message="No se pudieron consultar las cuentas autorizadas",
            edge="assigned_instagram_accounts",
        )
        if not accounts:
            accounts = self._discover_granted_accounts(access_token)
        logger.warning(
            "Meta discovery: edge=assigned_instagram_accounts returned=%d usable=%d business_present=%s",
            len(accounts),
            sum(bool(a.get("id")) for a in accounts),
            bool(business),
        )
        return [
            {
                "id": str(a["id"]),
                "name": a.get("username") or str(a["id"]),
                "handle": a.get("username", ""),
                "access_token": access_token,
                "meta_oauth_context": {
                    "client_business_id": str(business),
                    "config_id": str(self.credentials["config_id"]),
                },
                "can_message": False,
            }
            for a in accounts
            if a.get("id")
        ]

    def _discover_granted_accounts(self, access_token):
        """Recover only assets explicitly named by Meta's token introspection.

        Never enumerate a business's owned assets with an app token. Each
        candidate is read with the customer grant and must resolve as Instagram.
        """
        deadline = time.monotonic() + 8
        data = (
            self._request(
                "GET",
                f"{GRAPH}/debug_token",
                access_token=f"{self.credentials['client_id']}|{self.credentials['client_secret']}",
                params={"input_token": access_token},
                timeout=3,
            )
            .json()
            .get("data", {})
        )
        if data.get("is_valid") is not True or str(data.get("app_id")) != str(self.credentials["client_id"]):
            raise OAuthError("Meta devolvió un token inválido o de otra aplicación.", platform=self.platform_name)
        scopes = data.get("scopes", [])
        if "instagram_basic" not in scopes:
            raise OAuthError(
                "El token autorizado no incluye instagram_basic; la configuración guardada no equivale al permiso concedido.",
                platform=self.platform_name,
            )
        targets = set()
        pages = set()
        for grant in data.get("granular_scopes", []):
            if not isinstance(grant, dict):
                continue
            destination = (
                targets
                if grant.get("scope") == "instagram_basic"
                else pages
                if grant.get("scope") == "pages_show_list"
                else None
            )
            if destination is not None:
                destination.update(str(i) for i in (grant.get("target_ids") or []) if str(i).isdigit())
        self.discovery_diagnostic = {
            "assigned_count": 0,
            "valid": True,
            "app_matches": True,
            "instagram_targets": len(targets),
            "page_targets": len(pages),
            "instagram_basic": True,
        }
        found = {}
        # Bound callback work; an administrator can authorize smaller batches.
        for target in sorted(targets)[:20]:
            if time.monotonic() >= deadline:
                break
            try:
                account = self._request(
                    "GET", f"{GRAPH}/{target}", access_token=access_token, params={"fields": "id,username"}, timeout=3
                ).json()
            except ProviderError:
                continue
            if str(account.get("id")) == target and account.get("username"):
                found[target] = account
        if not found:
            for page_id in sorted(pages)[:10]:
                if time.monotonic() >= deadline:
                    break
                try:
                    page = self._request(
                        "GET",
                        f"{GRAPH}/{page_id}",
                        access_token=access_token,
                        params={"fields": "id,instagram_business_account{id,username}"},
                        timeout=3,
                    ).json()
                except ProviderError:
                    continue
                account = page.get("instagram_business_account") or {}
                if str(page.get("id")) == page_id and account.get("id") and account.get("username"):
                    found[str(account["id"])] = account
        self.discovery_diagnostic["resolved_count"] = len(found)
        logger.warning("Meta empty-edge diagnostic: %s", self.discovery_diagnostic)
        return list(found.values())

    def publish_post(self, access_token, content):
        # A SUAT may cover several brands; only the selected account is a destination.
        account_id = self._get_ig_user_id(access_token)
        content = replace(content, extra={**content.extra, "ig_user_id": account_id})
        return super().publish_post(access_token, content)

    def _get_ig_user_id(self, access_token):
        account_id = self.credentials.get("ig_user_id")
        if not account_id:
            raise OAuthError("Falta el identificador de la cuenta seleccionada.", platform=self.platform_name)
        return account_id
