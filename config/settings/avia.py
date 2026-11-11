"""AVIA Social self-host settings. Local Compose by default; TLS opt-in behind trusted proxy."""

from urllib.parse import urlsplit

from .production import *  # noqa: F401,F403

AVIA_GITHUB_TOKEN_DIR = env("AVIA_GITHUB_TOKEN_DIR", default="/run/secrets/avia")  # noqa: F405
AVIA_GITHUB_WEBHOOK_SECRET = env("AVIA_GITHUB_WEBHOOK_SECRET", default="")  # noqa: F405
AVIA_PUBLISH_ENABLED = env.bool("AVIA_PUBLISH_ENABLED", default=False)  # noqa: F405
SIGNUP_MODE = env("SIGNUP_MODE", default="closed")  # noqa: F405
SECURE_SSL_REDIRECT = env.bool("AVIA_HTTPS", default=False)  # noqa: F405
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SECURE_HSTS_SECONDS = 31536000 if SECURE_SSL_REDIRECT else 0
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if SECURE_SSL_REDIRECT else None
INTELLIGENCE_ENABLED = False
EMAIL_SENDING_ENABLED = False

# Redirect local HTTP entry points to the canonical public host when HTTPS is enabled.
# OAuth callbacks are built from APP_URL once HTTPS is on (proxy-proof redirect_uri).
OAUTH_PUBLIC_BASE_URL = APP_URL.rstrip("/") if SECURE_SSL_REDIRECT else ""  # noqa: F405
SECURE_SSL_HOST = urlsplit(APP_URL).netloc if SECURE_SSL_REDIRECT else None  # noqa: F405
# Only this installation's origin; no wildcard cross-origin trust.
CSRF_TRUSTED_ORIGINS = [APP_URL.rstrip("/")] if SECURE_SSL_REDIRECT else []  # noqa: F405
# Do not impose HSTS on unrelated subdomains of a self-hosted installation.
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

AVIA_LEGAL_OPERATOR = env("AVIA_LEGAL_OPERATOR", default="")  # noqa: F405
AVIA_LEGAL_CONTACT_EMAIL = env("AVIA_LEGAL_CONTACT_EMAIL", default="")  # noqa: F405
