# ruff: noqa: F811
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.avia_brand.test_welcome import owner, session  # noqa: F401
from apps.credentials.models import PlatformCredential
from apps.members.models import WorkspaceMembership
from apps.social_accounts.models import SocialAccount

pytestmark = pytest.mark.django_db


def prepare_picker(client, workspace, platform="instagram"):
    state = client.session
    state["oauth_page_select"] = {
        "workspace_id": str(workspace.id),
        "platform": platform,
        "user_tokens": {"access_token": "synthetic-user"},
        "pages": [{"id": str(i), "name": f"Brand {i}", "access_token": f"synthetic-{i}"} for i in range(1, 4)],
    }
    state.save()
    return reverse("social_accounts:select_account")


@pytest.mark.parametrize("platform", ["facebook", "instagram", "instagram_unified"])
def test_multiple_assets_keep_unselected_accounts(session, platform):
    client, workspace, _ = session
    existing = SocialAccount.objects.create(
        workspace=workspace,
        platform=platform,
        account_platform_id="3",
        account_name="Existing",
        oauth_access_token="unchanged",
    )
    url = prepare_picker(client, workspace, platform)
    with patch("apps.social_accounts.views.subscribe_account_webhooks_task"):
        result = client.post(url, {"selected_pages": ["1", "2"]})
    assert result.status_code == 302
    assert SocialAccount.objects.filter(workspace=workspace, platform=platform).count() == 3
    existing.refresh_from_db()
    assert existing.oauth_access_token == "unchanged"
    assert existing.account_name == "Existing"


def test_picker_rechecks_revoked_workspace_membership(session):
    client, workspace, _ = session
    url = prepare_picker(client, workspace)
    WorkspaceMembership.objects.filter(workspace=workspace, user=client.session["_auth_user_id"]).delete()
    response = client.post(url, {"selected_pages": ["1"]})
    assert response.status_code in (302, 403)
    assert not SocialAccount.objects.filter(workspace=workspace).exists()


def test_picker_rejects_ungranted_asset(session):
    client, workspace, _ = session
    url = prepare_picker(client, workspace)
    assert client.post(url, {"selected_pages": ["1", "not-authorized"]}).status_code == 403
    assert not SocialAccount.objects.filter(workspace=workspace).exists()


def test_instagram_facebook_setup_and_guide(session):
    client, workspace, url = session
    response = client.post(
        url,
        {
            "action": "credentials",
            "platform": "instagram",
            "meta_flow": "facebook_user",
            "client_id": "demo",
            "client_secret": "synthetic",
            "config_id": "1234",
        },
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    row = PlatformCredential.objects.get(organization=workspace.organization, platform="instagram")
    assert row.credentials["config_id"] == "1234"
    content = client.get(url + "?step=connections&configure=instagram").content.decode()
    assert "Elige todas tus cuentas" in content
    assert "synthetic" not in content


def test_suat_does_not_overwrite_existing_credentials(session):
    client, workspace, url = session
    row = PlatformCredential.objects.create(
        organization=workspace.organization,
        platform="instagram",
        credentials={"client_id": "existing", "client_secret": "preserved"},
    )
    response = client.post(
        url,
        {
            "action": "credentials",
            "platform": "instagram",
            "meta_flow": "unified_suat",
            "client_id": "different",
            "client_secret": "new",
            "config_id": "1234",
        },
        HTTP_HOST="localhost",
    )
    assert response.status_code == 200
    row.refresh_from_db()
    assert row.credentials["client_id"] == "existing"


def test_unified_setup_requires_config_and_preserves_legacy(session):
    client, workspace, url = session
    payload = {
        "action": "credentials",
        "platform": "instagram_unified",
        "meta_flow": "unified_suat",
        "client_id": "demo",
        "client_secret": "synthetic",
    }
    assert client.post(url, payload, HTTP_HOST="localhost").status_code == 200
    assert not PlatformCredential.objects.filter(platform="instagram_unified").exists()
    payload["config_id"] = "1234"
    assert client.post(url, payload, HTTP_HOST="localhost").status_code == 302
    assert PlatformCredential.objects.get(platform="instagram_unified").is_configured


def test_meta_invalid_form_without_query_keeps_visible_error(session):
    client, workspace, url = session
    result = client.post(
        url.split("?")[0],
        {
            "action": "credentials",
            "platform": "instagram_unified",
            "meta_flow": "unified_suat",
            "client_id": "demo",
            "client_secret": "synthetic",
        },
        HTTP_HOST="localhost",
    )
    assert result.status_code == 200
    assert result.context["step"] == "connections"
    assert result.context["setup_provider"] == "instagram_unified"
    assert b"Configuration ID es obligatorio" in result.content
    assert b'name="meta_flow" value="unified_suat"' in result.content
    assert b'value="synthetic"' not in result.content


def test_meta_saved_returns_to_login_step(session):
    client, workspace, url = session
    result = client.post(
        url,
        {
            "action": "credentials",
            "platform": "instagram_unified",
            "meta_flow": "unified_suat",
            "client_id": "demo",
            "client_secret": "synthetic",
            "config_id": "1234",
        },
        HTTP_HOST="localhost",
    )
    assert result.status_code == 302
    assert "configure=instagram_unified&saved=1" in result.url
    page = client.get(result.url)
    assert "Aplicación preparada".encode() in page.content
    assert b"Conectar Instagram" in page.content
