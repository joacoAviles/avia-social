import hashlib
import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from .presentation import REPOSITORY, private_identity, tokens, ui_brand

# Synthetic fixture: does not contain the private corporate palette or documents.
IDENTITY = {
    "schema_version": 1,
    "brand": {"name": "Fixture"},
    "visual": {
        "colors": {"values": {"blue": "#123456", "navy": "#112233", "white": "#fafafa", "gray": "#556677"}},
        "typography": {"display": "Inter"},
    },
}


def envelope(manifest):
    raw = manifest.encode()
    return {
        "repository": REPOSITORY,
        "commit": "a" * 40,
        "manifest": manifest,
        "blob_sha": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def test_private_theme_integrity_and_wrong_repository(tmp_path):
    path = tmp_path / "theme.json"
    data = envelope(json.dumps(IDENTITY))
    path.write_text(json.dumps(data))
    with override_settings(AVIA_UI_BRAND_FILE=str(path)):
        assert private_identity() == IDENTITY
        data["manifest"] += " "
        path.write_text(json.dumps(data))
        assert private_identity() is None
        data = envelope(json.dumps(IDENTITY))
        data["repository"] = "another/source"
        path.write_text(json.dumps(data))
        assert private_identity() is None


def test_theme_rejects_yaml_aliases_and_invalid_json_shape(tmp_path):
    path = tmp_path / "theme.json"
    with override_settings(AVIA_UI_BRAND_FILE=str(path)):
        path.write_text("[]")
        assert private_identity() is None
        path.write_text(json.dumps(envelope("schema_version: 1\nx: &ref [one]\ny: *ref")))
        assert private_identity() is None


def test_css_injection_is_rejected():
    identity = json.loads(json.dumps(IDENTITY))
    identity["visual"]["colors"]["values"]["blue"] = "</style><script>alert(1)</script>"
    assert tokens(identity) == []
    identity = json.loads(json.dumps(IDENTITY))
    identity["visual"]["typography"]["display"] = "evil';url(https://example.test)"
    assert "--brand-font-display" not in dict(tokens(identity))


@pytest.mark.django_db
def test_shell_never_exposes_private_manifest():
    with patch(
        "apps.avia_brand.presentation.private_identity", return_value={**IDENTITY, "internal": "PRIVATE_MARKER"}
    ):
        response = Client().get("/accounts/login/")
    assert response.status_code == 200
    text = response.content.decode()
    assert "PRIVATE_MARKER" not in text and "brand.yaml" not in text
    assert "--brand-500: #123456" in text
    assert "brightbean-studio-logo" not in text
    assert "favicon/favicon" not in text
    assert "Derivado de BrightBean Studio" in text


@pytest.mark.django_db
def test_global_shell_does_not_modify_workspace_identity():
    from apps.accounts.models import User

    user = User.objects.create_user(email="shell-fixture@example.test")
    ws = user.workspace_memberships.first().workspace
    before = (ws.name, ws.primary_color, ws.secondary_color)
    with patch("apps.avia_brand.presentation.private_identity", return_value=IDENTITY):
        assert ui_brand(None)["avia_ui_configured"]
    ws.refresh_from_db()
    assert (ws.name, ws.primary_color, ws.secondary_color) == before
