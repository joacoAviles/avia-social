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


def _meta(client, url, **data):
    return client.post(url + "?step=connections&configure=meta", {"action": "meta", **data}, secure=True)


def test_meta_wizard_saves_one_app_for_facebook_and_instagram(session):
    client, ws, url = session
    response = _meta(client, url, meta_app_id="111111", meta_app_secret="synthetic-secret")
    assert response.status_code == 302 and response.url.endswith("configure=meta")
    for platform in ("facebook", "instagram"):
        cred = PlatformCredential.objects.get(organization=ws.organization, platform=platform)
        assert cred.credentials["client_id"] == "111111" and cred.is_configured
        assert "config_id" not in cred.credentials
    assert not PlatformCredential.objects.filter(organization=ws.organization, platform="instagram_login").exists()
    html = client.get(url + "?step=connections&configure=meta", secure=True).content.decode()
    assert "synthetic-secret" not in html
    assert "/social-accounts/callback/facebook/" in html and "/social-accounts/callback/instagram/" in html
    assert "Conectar Facebook Pages" in html and "Conectar Instagram vía Facebook" in html


def test_meta_wizard_drops_legacy_config_id(session):
    client, ws, url = session
    PlatformCredential.objects.create(
        organization=ws.organization,
        platform="facebook",
        credentials={"client_id": "111111", "client_secret": "old", "config_id": "999"},
    )
    html = client.get(url + "?step=connections&configure=facebook", secure=True).content.decode()
    assert "Configuración anterior detectada" in html
    _meta(client, url, meta_app_id="111111", meta_app_secret="new-secret")
    cred = PlatformCredential.objects.get(organization=ws.organization, platform="facebook")
    assert "config_id" not in cred.credentials and cred.credentials["client_secret"] == "new-secret"


def test_meta_wizard_keeps_secret_when_left_blank(session):
    client, ws, url = session
    _meta(client, url, meta_app_id="111111", meta_app_secret="keep-me")
    _meta(client, url, meta_app_id="111111", meta_app_secret="", inbox_scopes_enabled="on")
    cred = PlatformCredential.objects.get(organization=ws.organization, platform="facebook")
    assert cred.credentials["client_secret"] == "keep-me"
    assert cred.credentials["inbox_scopes_enabled"] is True
    assert (
        PlatformCredential.objects.get(organization=ws.organization, platform="instagram").credentials[
            "dm_oauth_scopes_enabled"
        ]
        is True
    )


def test_meta_wizard_rejects_instagram_id_equal_to_meta_id(session):
    client, ws, url = session
    response = _meta(
        client,
        url,
        meta_app_id="111111",
        meta_app_secret="a",
        instagram_app_id="111111",
        instagram_app_secret="b",
    )
    assert response.status_code == 200
    assert "Es el mismo número que el Meta App ID" in response.content.decode()
    assert not PlatformCredential.objects.filter(organization=ws.organization).exists()


def test_meta_wizard_requires_some_credentials(session):
    client, ws, url = session
    response = _meta(client, url)
    assert response.status_code == 200
    assert "Ingresa al menos la app de Meta" in response.content.decode()


def test_meta_test_button_validates_pair(session):
    client, ws, url = session
    _meta(client, url, meta_app_id="111111", meta_app_secret="s")
    with patch(
        "apps.social_accounts.meta_connect.validate_meta_app",
        return_value=(True, "Credenciales válidas para la app «AVIA»."),
    ) as check:
        response = client.post(url + "?step=connections&configure=meta", {"action": "meta_test"}, secure=True)
    check.assert_called_once_with("111111", "s")
    assert "Credenciales válidas para la app «AVIA»" in response.content.decode()


def test_meta_wizard_forbidden_for_non_admin(session):
    client, ws, url = session
    WorkspaceMembership.objects.filter(workspace=ws).update(workspace_role="editor")
    from apps.members.models import OrgMembership

    OrgMembership.objects.filter(organization=ws.organization).update(org_role="member")
    response = _meta(client, url, meta_app_id="111111", meta_app_secret="s")
    assert response.status_code == 403
    assert not PlatformCredential.objects.filter(organization=ws.organization).exists()
