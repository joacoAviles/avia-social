"""Canonical public URLs for OAuth callbacks.

Behind Cloudflare Tunnel / Caddy the request Django sees can say ``http`` or an
internal host. Meta, TikTok and Google compare ``redirect_uri`` byte-for-byte,
so when the installation declares an HTTPS ``APP_URL`` every callback is built
from it instead of from the incoming request.
"""

from __future__ import annotations

from urllib.parse import urljoin

from django.conf import settings


def public_base_url() -> str:
    """Return the HTTPS base URL to trust for callbacks, or ``""``."""
    base = (getattr(settings, "OAUTH_PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    return base if base.startswith("https://") else ""


def public_url(request, path: str) -> str:
    """Absolute URL for ``path`` — from ``APP_URL`` when HTTPS, else the request."""
    base = public_base_url()
    if base:
        return urljoin(base + "/", path.lstrip("/"))
    return request.build_absolute_uri(path)
