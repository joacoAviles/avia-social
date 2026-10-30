import io
import zipfile

import pytest
import yaml
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User

from .template_builder import TemplateForm


@pytest.fixture
def session():
    user = User.objects.create_superuser(
        email="builder@example.test", password="test-only", tos_accepted_at=timezone.now()
    )
    client = Client()
    client.force_login(user)
    return client, user.workspace_memberships.first().workspace, ""


pytestmark = pytest.mark.django_db


def payload():
    return {
        "name": "Mi marca",
        "tagline": "Una idea",
        "description": "Descripción",
        "website": "https://example.test",
        "language": "es",
        "timezone": "America/Santiago",
        "primary": "#123456",
        "secondary": "#ABCDEF",
        "heading_font": "Inter",
        "body_font": "Inter",
        "audience": "Clientes",
        "voice": "Claro y directo",
        "avoid": "Promesas sin evidencia",
        "pillars": "Educación\nNovedades",
        "action": "download",
    }


def test_download_roundtrip_has_real_schema_and_fixed_paths(session):
    client, ws, _ = session
    response = client.post(reverse("avia_brand:template_builder", args=[ws.id]), payload())
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert "no-store" in response["Cache-Control"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "README.md",
            ".gitignore",
            "brand/brand.yaml",
            "brand/content-templates.yaml",
            "assets/README.md",
        }
        identity = yaml.safe_load(archive.read("brand/brand.yaml"))
        assert identity["schema_version"] == 1
        assert identity["brand"]["name"] == "Mi marca"
        assert identity["visual"]["colors"]["values"]["primary"] == "#123456"
        assert identity["assets"] == []
        assert identity["content"]["pillars"] == ["Educación", "Novedades"]
    ws.refresh_from_db()
    assert ws.name != "Mi marca"


def test_builder_rejects_invalid_colors_and_escapes_preview(session):
    data = payload()
    data["primary"] = "red; background:url(evil)"
    assert not TemplateForm(data).is_valid()
    client, ws, _ = session
    data = payload()
    data.update(action="preview", name="<script>alert(1)</script>")
    response = client.post(reverse("avia_brand:template_builder", args=[ws.id]), data)
    assert b"<script>alert(1)</script>" not in response.content
    assert b"&lt;script&gt;" in response.content


def test_builder_requires_login_and_csrf(session):
    from django.test import Client

    client, ws, _ = session
    endpoint = reverse("avia_brand:template_builder", args=[ws.id])
    assert Client().get(endpoint).status_code == 302
    checked = Client(enforce_csrf_checks=True)
    # A signed-in session still cannot POST a download without a CSRF token.
    checked.cookies = client.cookies
    assert checked.post(endpoint, payload()).status_code == 403
