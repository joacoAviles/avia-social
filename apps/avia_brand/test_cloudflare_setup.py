"""Regression tests for optional tunnel setup and trusted proxy handling."""

import importlib.util
from pathlib import Path

import pytest
from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, override_settings

spec = importlib.util.spec_from_file_location(
    "cloudflare_setup", Path(__file__).resolve().parents[2] / "scripts/cloudflare_setup.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.mark.parametrize(
    "value",
    [
        "localhost",
        "http://social.example.com",
        "127.0.0.1",
        "social.example.com:443",
        "x.test",
        "x.com/path",
        "*.example.com",
        "x.com\nBAD=1",
    ],
)
def test_rejects_invalid_hostname(value):
    with pytest.raises(ValueError):
        setup.hostname(value)


def test_setup_preserves_credentials_profiles_and_backup(tmp_path):
    original = "SECRET_KEY=keep\nENCRYPTION_KEY_SALT=keep-too\nPOSTGRES_PASSWORD=unchanged\nCOMPOSE_PROFILES=n8n\nAPP_URL=http://localhost:8088\n"
    (tmp_path / ".env").write_text(original)
    token = "synthetic" * 10
    setup.configure(tmp_path, "https://social.example.com/", token)
    result = (tmp_path / ".env").read_text()
    for line in original.splitlines()[:3]:
        assert line + "\n" in result
    assert "COMPOSE_PROFILES=n8n,cloudflare\n" in result
    assert "APP_URL=https://social.example.com\n" in result
    assert token not in result
    assert (tmp_path / ".cloudflare/tunnel.token").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    setup.configure(tmp_path, "social.example.com", token)
    assert (tmp_path / ".cloudflare/env.before-tunnel").read_text() == original
    assert (tmp_path / ".env").read_text() == result


def test_invalid_token_does_not_mutate(tmp_path):
    (tmp_path / ".env").write_text("SECRET_KEY=keep\n")
    with pytest.raises(ValueError):
        setup.configure(tmp_path, "social.example.com", "docker run --token wrong")
    assert not (tmp_path / ".cloudflare").exists()
    assert (tmp_path / ".env").read_text() == "SECRET_KEY=keep\n"


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_SSL_HOST="social.example.com",
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    ALLOWED_HOSTS=["social.example.com", "localhost"],
    SECURE_REDIRECT_EXEMPT=[r"^health/$"],
)
def test_https_proxy_redirect_and_health():
    middleware = SecurityMiddleware(lambda request: HttpResponse("ok"))
    factory = RequestFactory()
    assert middleware(factory.get("/welcome/", HTTP_HOST="localhost")).url == "https://social.example.com/welcome/"
    request = factory.get("/welcome/", HTTP_HOST="social.example.com", HTTP_X_FORWARDED_PROTO="https")
    assert middleware(request).status_code == 200
    assert (
        request.build_absolute_uri("/social-accounts/callback/facebook/")
        == "https://social.example.com/social-accounts/callback/facebook/"
    )
    assert middleware(factory.get("/health/", HTTP_HOST="localhost")).status_code == 200
