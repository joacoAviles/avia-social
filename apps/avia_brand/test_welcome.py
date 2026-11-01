import hashlib
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.adapters import SocialAccountAdapter
from apps.accounts.models import User
from apps.credentials.models import PlatformCredential
from apps.members.models import WorkspaceMembership

from .models import BrandSource, InstallationSetup, WelcomeProgress
from .services import GitHubReader, SyncError

pytestmark = pytest.mark.django_db


def setup_payload():
    return {
        "code": "synthetic-setup-code",
        "name": "Demo owner",
        "email": "owner@example.test",
        "password": "Strong-example-setup-902!",
        "confirm": "Strong-example-setup-902!",
        "acknowledge": "on",
    }


def prepare_code(expired=False):
    InstallationSetup.objects.update_or_create(
        pk=1,
        defaults={
            "claimed_at": None,
            "token_hash": hashlib.sha256(b"synthetic-setup-code").hexdigest(),
            "expires_at": timezone.now() + timedelta(minutes=-1 if expired else 30),
        },
    )


@pytest.fixture
def owner():
    return User.objects.create_superuser(
        email="owner@example.test", password="test-only", tos_accepted_at=timezone.now()
    )


@pytest.fixture
def session(owner):
    client = Client()
    client.force_login(owner)
    ws = owner.workspace_memberships.first().workspace
    return client, ws, reverse("welcome:journey", args=[ws.id])


def test_empty_root_goes_to_setup(client):
    assert client.get("/").url == reverse("welcome:setup")


def test_first_owner_claimed_once(client):
    prepare_code()
    response = client.post(reverse("welcome:setup"), setup_payload(), secure=True)
    assert response.status_code == 302
    user = User.objects.get(email="owner@example.test")
    assert user.is_superuser and user.check_password(setup_payload()["password"])
    assert WelcomeProgress.objects.filter(workspace_id=user.last_workspace_id).exists()
    state = InstallationSetup.objects.get(pk=1)
    assert state.claimed_at and not state.token_hash
    assert client.post(reverse("welcome:setup"), setup_payload(), secure=True).status_code == 302
    assert User.objects.count() == 1
    assert client.get("/").url == reverse("welcome:journey", args=[user.last_workspace_id])


@pytest.mark.parametrize("expired,code", [(True, "synthetic-setup-code"), (False, "invalid-onboarding-code-long")])
def test_expired_or_wrong_code_cannot_claim(client, expired, code):
    prepare_code(expired)
    payload = setup_payload()
    payload["code"] = code
    response = client.post(reverse("welcome:setup"), payload, secure=True)
    assert response.status_code == 200 and not User.objects.exists()
    assert code.encode() not in response.content


def test_claim_cannot_reopen_after_owner_deleted(client):
    InstallationSetup.objects.update_or_create(pk=1, defaults={"claimed_at": timezone.now()})
    assert client.get(reverse("welcome:setup")).status_code == 302
    with pytest.raises(CommandError):
        call_command("avia_setup_code", stdout=StringIO())


def test_existing_installation_is_not_claimable(owner, client):
    assert client.get(reverse("welcome:setup")).status_code == 302
    with pytest.raises(CommandError):
        call_command("avia_setup_code", stdout=StringIO())


def test_setup_code_is_hash_only():
    output = StringIO()
    call_command("avia_setup_code", stdout=output)
    code = output.getvalue().strip().splitlines()[-1]
    state = InstallationSetup.objects.get(pk=1)
    assert state.token_hash == hashlib.sha256(code.encode()).hexdigest()
    assert code not in state.token_hash and state.expires_at > timezone.now()


def test_setup_requires_csrf_and_secure_transport():
    prepare_code()
    client = Client(enforce_csrf_checks=True)
    assert client.post(reverse("welcome:setup"), setup_payload(), secure=True).status_code == 403
    assert Client().post(reverse("welcome:setup"), setup_payload()).status_code == 400
    assert not User.objects.exists()


def test_brand_save_and_resume_finish(session):
    client, ws, url = session
    assert client.post(url, {"action": "brand", "name": "Mi marca", "timezone": "America/Santiago"}).status_code == 302
    ws.refresh_from_db()
    assert ws.name == "Mi marca" and ws.timezone == "America/Santiago"
    assert client.get("/").url == url
    for step in ["brand", "connections", "ready"]:
        assert client.get(url + "?step=" + step).status_code == 200
    assert client.post(url, {"action": "finish"}).status_code == 302
    assert WelcomeProgress.objects.get(workspace=ws).completed_at
    assert client.get("/").url == reverse("calendar:calendar", args=[ws.id])


def test_connections_are_optional_and_no_fake_success(session):
    client, ws, url = session
    response = client.get(url + "?step=connections")
    assert "Sin configurar" in response.content.decode()
    assert "Cuenta vinculada" not in response.content.decode()
    assert not ws.social_accounts.exists()
    assert client.post(url, {"action": "finish"}).status_code == 302


def test_cross_workspace_and_viewer_forbidden(session):
    client, ws, url = session
    outsider = User.objects.create_user(email="outside@example.test", tos_accepted_at=timezone.now())
    client.force_login(outsider)
    assert client.get(url).status_code == 403
    WorkspaceMembership.objects.create(user=outsider, workspace=ws, workspace_role="viewer")
    assert client.post(url, {"action": "brand", "name": "attack", "timezone": "UTC"}).status_code == 403


@pytest.mark.parametrize(
    "platform,key",
    [("youtube", "client_id"), ("tiktok", "client_key"), ("instagram_login", "client_id"), ("facebook", "client_id")],
)
def test_provider_credentials_encrypted_not_echoed(session, platform, key):
    client, ws, url = session
    response = client.post(
        url,
        {
            "action": "credentials",
            "platform": platform,
            "meta_flow": {"instagram_login": "instagram_legacy", "facebook": "facebook_user"}.get(platform, ""),
            "client_id": "synthetic-id",
            "client_secret": "synthetic-private-value",
        },
        secure=True,
    )
    assert response.status_code == 302
    credential = PlatformCredential.objects.get(organization=ws.organization, platform=platform)
    assert credential.credentials[key] == "synthetic-id" and credential.is_configured
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT credentials FROM credentials_platform_credential WHERE id = %s", [credential.pk])
        assert "synthetic-private-value" not in cursor.fetchone()[0]
    content = client.get(url + "?step=connections").content.decode()
    assert "synthetic-private-value" not in content and "Falta autorizar" in content
    assert not ws.social_accounts.exists()


def test_google_instance_configuration_and_adapter(session):
    client, ws, url = session
    assert (
        client.post(
            url,
            {
                "action": "credentials",
                "platform": "google_login",
                "client_id": "google-synthetic",
                "client_secret": "secret-synthetic",
            },
            secure=True,
        ).status_code
        == 302
    )
    app = SocialAccountAdapter().get_app(None, "google")
    assert app.client_id == "google-synthetic" and app.secret == "secret-synthetic"
    response = client.get(url + "?step=connections")
    assert response.status_code == 200 and b"secret-synthetic" not in response.content
    assert b"Google Calendar" in response.content
    assert b"Continuar con Google" not in response.content


def test_org_owner_cannot_change_global_google(session, owner):
    client, ws, url = session
    owner.is_superuser = False
    owner.save(update_fields=["is_superuser"])
    assert (
        client.post(
            url,
            {"action": "credentials", "platform": "google_login", "client_id": "id", "client_secret": "secret"},
            secure=True,
        ).status_code
        == 403
    )


def test_github_verified_then_saved_and_not_echoed(session):
    client, ws, url = session
    with patch.object(
        GitHubReader, "get", return_value={"full_name": "example/identity", "default_branch": "brand/main"}
    ) as get:
        response = client.post(
            url,
            {
                "action": "github",
                "repository": "example/identity",
                "token": "synthetic-private-token",
                "readonly": "on",
            },
            secure=True,
        )
    assert response.status_code == 302 and get.call_args.args == ("",)
    source = BrandSource.objects.get(workspace=ws)
    assert source.github_token == "synthetic-private-token" and source.branch == "brand/main"
    assert b"synthetic-private-token" not in client.get(url + "?step=connections").content
    assert not source.revisions.exists()


def test_github_failure_does_not_save(session):
    client, ws, url = session
    with patch.object(GitHubReader, "get", side_effect=SyncError("failed")):
        response = client.post(
            url,
            {"action": "github", "repository": "example/identity", "token": "secret-synthetic", "readonly": "on"},
            secure=True,
        )
    assert response.status_code == 200 and not BrandSource.objects.filter(workspace=ws).exists()
    assert b"secret-synthetic" not in response.content


def test_github_cannot_reassign_history(session):
    client, ws, url = session
    BrandSource.objects.create(workspace=ws, repository="example/first")
    with patch.object(GitHubReader, "get", return_value={"full_name": "example/second", "default_branch": "main"}):
        client.post(
            url, {"action": "github", "repository": "example/second", "token": "secret", "readonly": "on"}, secure=True
        )
    assert BrandSource.objects.get(workspace=ws).repository == "example/first"


@pytest.mark.parametrize(
    "repo", ["https://evil.example/a", "../secret", "example/repo?x=y", "example/repo/../../secret"]
)
def test_github_rejects_url_injection(repo):
    with pytest.raises(SyncError):
        GitHubReader(repo, "synthetic")


def test_empty_google_button_not_shown(client):
    with override_settings(GOOGLE_AUTH_CLIENT_ID="", GOOGLE_AUTH_CLIENT_SECRET=""):
        assert b"Continuar con Google" not in client.get(reverse("accounts:account_login")).content


def test_google_authorization_uses_instance_client(session):
    client, ws, url = session
    InstallationSetup.objects.update_or_create(
        pk=1, defaults={"google_credentials": {"client_id": "our-client.example", "client_secret": "synthetic"}}
    )
    response = client.post("/accounts/google/login/?process=connect", secure=True)
    assert response.status_code == 302
    assert response.url.startswith("https://accounts.google.com/")
    assert "our-client.example" in response.url
    assert "synthetic" not in response.url


@pytest.mark.django_db(transaction=True)
def test_concurrent_setup_only_creates_one_owner():
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    prepare_code()

    def claim():
        try:
            return Client().post(reverse("welcome:setup"), setup_payload(), secure=True).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert all(status in {200, 302} for status in results)
    assert User.objects.count() == 1
    assert InstallationSetup.objects.get(pk=1).claimed_at


@pytest.mark.django_db(transaction=True)
def test_upgrade_preserves_existing_brand_and_closes_bootstrap():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    old_target = [("avia_brand", "0002_site_identity")]
    new_target = [("avia_brand", "0005_calendarconnection_creation_started_and_more")]
    executor = MigrationExecutor(connection)
    old_target = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "avia_brand"] + old_target
    executor.migrate(old_target)
    try:
        old = executor.loader.project_state(old_target).apps
        user = old.get_model("accounts", "User").objects.create(
            email="existing@example.test", password="unchanged-hash"
        )
        org = old.get_model("organizations", "Organization").objects.create(name="Existing org")
        ws = old.get_model("workspaces", "Workspace").objects.create(organization=org, name="Existing brand")
        source = old.get_model("avia_brand", "BrandSource").objects.create(
            workspace=ws, repository="joacoAviles/avia-rockets-brand"
        )
        MigrationExecutor(connection).migrate(new_target)
        assert User.objects.get(pk=user.pk).password == "unchanged-hash"
        restored = BrandSource.objects.get(pk=source.pk)
        assert restored.workspace_id == ws.pk and restored.branch == "main" and restored.github_token == ""
        assert InstallationSetup.objects.get(pk=1).claimed_at
        with pytest.raises(CommandError):
            call_command("avia_setup_code", stdout=StringIO())
    finally:
        MigrationExecutor(connection).migrate(new_target)


def test_connection_screen_offers_journey_and_calendar(session):
    client, ws, journey_url = session
    response = client.get(reverse("social_accounts:connect", args=[ws.id]))
    assert response.status_code == 200
    html = response.content.decode()
    assert f"{journey_url}?step=connections" in html
    assert "Abrir guía de configuración y continuar" in html
    assert reverse("calendar:calendar", args=[ws.id]) in html
    assert "Prepara tus conexiones" in html


def test_guides_explain_repository_token_and_tiktok_https(session):
    client, ws, url = session
    response = client.get(url + "?step=connections&configure=github")
    html = response.content.decode()
    assert response.status_code == 200
    assert "Only select repositories" in html
    assert "examples/brand-starter" in html
    html = client.get(url + "?step=connections&configure=tiktok").content.decode()
    assert "Falta HTTPS para conectar TikTok" in html
    assert "Manage apps" in html
    assert "No copies tokens de usuario manualmente" in html
    secure_html = client.get(url + "?step=connections&configure=tiktok", secure=True).content.decode()
    assert "Falta HTTPS para conectar TikTok" not in secure_html


def test_instagram_direct_can_start_without_facebook(session):
    client, ws, url = session
    client.post(
        url,
        {
            "action": "credentials",
            "platform": "instagram_login",
            "meta_flow": "instagram_legacy",
            "client_id": "synthetic-ig-id",
            "client_secret": "synthetic-ig-secret",
        },
        HTTP_HOST="localhost",
    )
    assert not PlatformCredential.objects.filter(organization=ws.organization, platform="facebook").exists()
    response = client.get(url + "?step=connections")
    cards = {card["platform"]: card for card in response.context["cards"]}
    assert cards["instagram_login"]["configured"]
    assert not cards["facebook"]["configured"]
    assert "Conectar Instagram directo" in response.content.decode()
    assert "Habilitar Facebook" in response.content.decode()


def test_connections_hide_admin_forms_and_offer_existing_oauth(session):
    client, ws, url = session
    PlatformCredential.objects.create(
        organization=ws.organization,
        platform="instagram_login",
        credentials={"client_id": "synthetic", "client_secret": "synthetic"},
    )
    html = client.get(url + "?step=connections").content.decode()
    assert 'name="client_secret"' not in html
    assert 'name="token"' not in html
    assert "Conectar Instagram directo" in html
    assert reverse("social_accounts:connect", args=[ws.id]) in html
    admin = client.get(url + "?step=connections&configure=instagram_login").content.decode()
    assert 'name="client_secret"' in admin
    assert "Prepara Instagram directo" in admin
    assert "Prepara Facebook" not in admin


def test_meta_unified_refused_without_overwriting_existing(session):
    client, ws, url = session
    original = PlatformCredential.objects.create(
        organization=ws.organization,
        platform="instagram_login",
        credentials={"client_id": "old", "client_secret": "old-secret"},
    )
    response = client.post(
        url + "?step=connections&configure=instagram_login",
        {
            "action": "credentials",
            "platform": "instagram_login",
            "meta_flow": "unified_suat",
            "client_id": "new",
            "client_secret": "new-secret",
        },
        secure=True,
    )
    assert response.status_code == 200
    assert "Para SUAT usa Instagram Unified Login" in response.content.decode()
    original.refresh_from_db()
    assert original.credentials["client_id"] == "old"


def test_facebook_business_config_id_drives_login(session):
    from urllib.parse import parse_qs, urlparse

    from providers.facebook import FacebookProvider

    client, ws, url = session
    response = client.post(
        url,
        {
            "action": "credentials",
            "platform": "facebook",
            "meta_flow": "facebook_user",
            "config_id": "12345678",
            "client_id": "app",
            "client_secret": "secret",
        },
        secure=True,
    )
    assert response.status_code == 302
    credential = PlatformCredential.objects.get(organization=ws.organization, platform="facebook")
    query = parse_qs(
        urlparse(FacebookProvider(credential.credentials).get_auth_url("https://example.test/callback/", "state")).query
    )
    assert query["config_id"] == ["12345678"]
    assert "scope" not in query
    assert query["response_type"] == ["code"]


def test_connected_channels_are_compact_and_identified(session):
    from apps.social_accounts.models import SocialAccount

    client, ws, url = session
    SocialAccount.objects.create(
        workspace=ws,
        platform="youtube",
        account_platform_id="channel-demo-one",
        account_name="Canal ejemplo",
        connection_status="connected",
    )
    response = client.get(url + "?step=connections")
    html = response.content.decode()
    assert "connect-row-ok" in html
    assert "channel-demo-one" in html
    assert "¿Por qué aparecen varios nombres?" in html
    assert "Administración · credenciales, dominio y ayuda" in html
    assert " · connected" not in html
    SocialAccount.objects.filter(workspace=ws).update(connection_status="error")
    response = client.get(url + "?step=connections")
    card = next(c for c in response.context["cards"] if c["platform"] == "youtube")
    assert card["needs_attention"]
    assert "Revisar conexión" in response.content.decode()


def test_calendar_guide_explains_actual_google_fields(session):
    client, ws, url = session
    html = client.get(url + "?step=connections&configure=google_calendar", secure=True).content.decode()
    assert "Agrega permisos manualmente" in html
    assert "URI de redireccionamiento autorizados" in html
    assert "Orígenes autorizados de JavaScript" in html
    assert "No borres las credenciales" in html
    assert "mantén abierto SSH" not in html


def test_tiktok_review_help_does_not_claim_approval(session):
    client, ws, url = session
    html = client.get(url + "?step=connections&configure=tiktok", secure=True).content.decode()
    assert "https://testserver/terms/" in html
    assert "https://testserver/privacy/" in html
    assert "AVIA no consulta ese estado automáticamente" in html
