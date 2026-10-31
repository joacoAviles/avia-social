"""X OAuth 2.0 / PKCE and text-only publishing. No media, inbox or analytics."""

import base64
import hashlib
from urllib.parse import urlencode

import httpx

from .base import SocialProvider
from .exceptions import OAuthError, PublishError
from .types import AccountProfile, AuthType, OAuthTokens, PostType, PublishResult


class XProvider(SocialProvider):
    platform_name = "X / Twitter"
    auth_type = AuthType.OAUTH2
    max_caption_length = 280
    supported_post_types = [PostType.TEXT]
    supported_media_types = []
    required_scopes = ["tweet.read", "tweet.write", "users.read", "offline.access"]
    uses_pkce = True
    needs_local_media = False
    token_url = "https://api.x.com/2/oauth2/token"

    def get_auth_url(self, redirect_uri, state, code_verifier=None):
        if not code_verifier:
            raise OAuthError("Falta PKCE. Reinicia la conexión.", retryable=False)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
        return "https://x.com/i/oauth2/authorize?" + urlencode(
            dict(
                response_type="code",
                client_id=self.credentials["client_id"],
                redirect_uri=redirect_uri,
                state=state,
                scope=" ".join(self.required_scopes),
                code_challenge=challenge,
                code_challenge_method="S256",
            )
        )

    def _token(self, data):
        auth = base64.b64encode(
            (self.credentials["client_id"] + ":" + self.credentials["client_secret"]).encode()
        ).decode()
        response = self._request("POST", self.token_url, headers={"Authorization": "Basic " + auth}, data=data).json()
        if not response.get("access_token"):
            raise OAuthError("El proveedor no entregó un token de acceso.", retryable=False)
        return OAuthTokens(
            access_token=response["access_token"],
            refresh_token=response.get("refresh_token"),
            expires_in=response.get("expires_in"),
            scope=response.get("scope"),
        )

    def exchange_code(self, code, redirect_uri, code_verifier=None):
        if not code_verifier:
            raise OAuthError("Falta PKCE. Reinicia la conexión.", retryable=False)
        return self._token(
            dict(grant_type="authorization_code", code=code, redirect_uri=redirect_uri, code_verifier=code_verifier)
        )

    def refresh_token(self, refresh_token):
        return self._token(dict(grant_type="refresh_token", refresh_token=refresh_token))

    def get_profile(self, access_token):
        data = self._request("GET", "https://api.x.com/2/users/me", access_token=access_token).json().get("data", {})
        if not data.get("id"):
            raise OAuthError("No se pudo identificar la cuenta X.", retryable=False)
        return AccountProfile(
            platform_id=str(data["id"]), name=data.get("name") or data.get("username", ""), handle=data.get("username")
        )

    def publish_post(self, access_token, content):
        if content.media_urls or content.media_files or content.post_type != PostType.TEXT or not content.text.strip():
            raise PublishError("X admite solo texto en esta versión; no se enviaron archivos.", retryable=False)
        try:
            data = (
                self._request(
                    "POST", "https://api.x.com/2/tweets", access_token=access_token, json={"text": content.text}
                )
                .json()
                .get("data", {})
            )
        except (httpx.TransportError, ValueError):
            raise PublishError(
                "No se confirmó el envío a X. Revisa tu cuenta antes de volver a publicar.", retryable=False
            ) from None
        if not data.get("id"):
            raise PublishError(
                "X no confirmó el ID de publicación. Revisa tu cuenta antes de reintentar.", retryable=False
            )
        return PublishResult(platform_post_id=str(data["id"]), url="https://x.com/i/web/status/" + str(data["id"]))
