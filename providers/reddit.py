"""Reddit approved Data API apps: OAuth and explicit subreddit text posts."""

from urllib.parse import urlencode

import httpx

from .exceptions import OAuthError, PublishError
from .types import AccountProfile, PostType, PublishResult
from .x import XProvider


class RedditProvider(XProvider):
    platform_name = "Reddit"
    max_caption_length = 40000
    required_scopes = ["identity", "submit"]
    uses_pkce = False
    token_url = "https://www.reddit.com/api/v1/access_token"

    def _request(self, method, url, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["User-Agent"] = self.credentials.get("user_agent", "AVIA-Social/0.1 (self-hosted)")
        return super()._request(method, url, headers=headers, **kwargs)

    def get_auth_url(self, redirect_uri, state, code_verifier=None):
        return "https://www.reddit.com/api/v1/authorize?" + urlencode(
            dict(
                client_id=self.credentials["client_id"],
                response_type="code",
                state=state,
                redirect_uri=redirect_uri,
                duration="permanent",
                scope=" ".join(self.required_scopes),
            )
        )

    def exchange_code(self, code, redirect_uri, code_verifier=None):
        return self._token(dict(grant_type="authorization_code", code=code, redirect_uri=redirect_uri))

    def get_profile(self, access_token):
        data = self._request("GET", "https://oauth.reddit.com/api/v1/me", access_token=access_token).json()
        if not data.get("id") or not data.get("name"):
            raise OAuthError("Reddit no confirmó la identidad de la cuenta.", retryable=False)
        return AccountProfile(platform_id=str(data["id"]), name=data["name"], handle=data["name"])

    def publish_post(self, access_token, content):
        subreddit = self.credentials.get("subreddit", "")
        title = (content.title or content.text.split("\n", 1)[0]).strip()
        if (
            not subreddit
            or not title
            or len(title) > 300
            or content.media_urls
            or content.media_files
            or content.post_type != PostType.TEXT
        ):
            raise PublishError(
                "Reddit requiere comunidad configurada, título de hasta 300 caracteres y contenido de texto sin archivos.",
                retryable=False,
            )
        try:
            response = (
                self._request(
                    "POST",
                    "https://oauth.reddit.com/api/submit",
                    access_token=access_token,
                    data=dict(
                        api_type="json", sr=subreddit, kind="self", title=title, text=content.text, resubmit="false"
                    ),
                )
                .json()
                .get("json", {})
            )
        except (httpx.TransportError, ValueError):
            raise PublishError(
                "No se confirmó el envío a Reddit. Revisa la comunidad antes de volver a publicar.", retryable=False
            ) from None
        if response.get("errors"):
            raise PublishError("Reddit rechazó el envío. Revisa permisos y reglas de la comunidad.", retryable=False)
        data = response.get("data", {})
        if not data.get("id"):
            raise PublishError("Reddit no confirmó el ID. Comprueba la comunidad antes de reintentar.", retryable=False)
        return PublishResult(platform_post_id=str(data["id"]), url="https://www.reddit.com/comments/" + str(data["id"]))
