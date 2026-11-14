import base64
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.members.models import WorkspaceMembership

from .models import BrandAudit, BrandRevision, BrandSource, HookReceipt
from .services import GitHubReader, SyncError, review, sync

pytestmark = pytest.mark.django_db


@pytest.fixture
def data():
    owner = User.objects.create_user(email="owner@example.test", password="pass")
    other = User.objects.create_user(email="other@example.test", password="pass")
    ws = owner.workspace_memberships.first().workspace
    src = BrandSource.objects.create(workspace=ws, repository="joacoAviles/joaco-avia-brand")
    rev = BrandRevision.objects.create(
        source=src,
        commit="a" * 40,
        identity={"brand": {"name": "Synthetic Brand"}, "visual": {"colors": {"values": {"one": "#123456"}}}},
        catalog=[],
    )
    return owner, other, ws, src, rev


def login(user):
    c = Client()
    c.force_login(user)
    user.tos_accepted_at = __import__("django.utils.timezone", fromlist=["now"]).now()
    user.save()
    return c


def test_cross_brand_access_denied(data):
    owner, other, ws, src, rev = data
    c = login(other)
    assert c.get(reverse("avia_brand:catalog", args=[ws.id])).status_code == 403
    assert c.post(reverse("avia_brand:review", args=[ws.id, rev.id]), {"decision": "approve"}).status_code == 403
    assert c.get(reverse("avia_brand:asset", args=[ws.id, rev.id, "a" * 40])).status_code == 403


def test_viewer_cannot_sync_or_approve(data):
    owner, other, ws, src, rev = data
    WorkspaceMembership.objects.create(user=other, workspace=ws, workspace_role="viewer")
    c = login(other)
    assert c.get(reverse("avia_brand:catalog", args=[ws.id])).status_code == 200
    assert c.post(reverse("avia_brand:sync", args=[ws.id])).status_code == 403
    assert c.post(reverse("avia_brand:review", args=[ws.id, rev.id]), {"decision": "approve"}).status_code == 403


def test_approval_is_immutable_and_applies_identity(data):
    owner, _, ws, src, rev = data
    review(src, rev.id, owner, True)
    src.refresh_from_db()
    ws.refresh_from_db()
    assert src.active_revision_id == rev.id
    assert ws.name == "Synthetic Brand" and ws.primary_color == "#123456"
    ws.name = "Manual forbidden"
    ws.primary_color = "#000000"
    ws.save()
    ws.refresh_from_db()
    assert ws.name == "Synthetic Brand" and ws.primary_color == "#123456"
    with pytest.raises(SyncError):
        review(src, rev.id, owner, False)
    assert BrandAudit.objects.filter(action="approved").count() == 1


def test_cross_source_revision_rejected(data):
    owner, other, ws, src, rev = data
    other_ws = other.workspace_memberships.first().workspace
    BrandSource.objects.create(workspace=other_ws, repository="joacoAviles/acelerados-brand")
    c = login(other)
    assert c.post(reverse("avia_brand:review", args=[other_ws.id, rev.id]), {"decision": "approve"}).status_code == 404


def test_pending_asset_not_available(data):
    owner, _, ws, src, rev = data
    assert login(owner).get(reverse("avia_brand:asset", args=[ws.id, rev.id, "a" * 40])).status_code == 404


def test_sync_idempotent_and_no_autoapproval(data):
    owner, _, ws, src, rev = data
    manifest = b'{"schema_version":1,"brand":{"name":"Fixture"}}'
    sha = hashlib.sha1(b"blob " + str(len(manifest)).encode() + b"\0" + manifest).hexdigest()
    tree = {
        "tree": [
            {"type": "blob", "mode": "100644", "path": "brand/brand.yaml", "sha": sha, "size": len(manifest)},
            {"type": "blob", "mode": "100644", "path": ".env", "sha": "f" * 40, "size": 10},
        ]
    }
    with patch("apps.avia_brand.services.GitHubReader") as reader:
        reader.return_value.get.side_effect = [{"sha": "b" * 40}, tree, {"sha": "b" * 40}, tree]
        reader.return_value.blob.return_value = manifest
        first = sync(src, owner)
        second = sync(src, owner)
    assert first.id == second.id and first.state == "pending"
    assert len(first.catalog) == 1
    src.refresh_from_db()
    assert src.active_revision_id is None


def test_truncated_tree_fails_closed(data):
    with patch("apps.avia_brand.services.GitHubReader") as reader:
        reader.return_value.get.side_effect = [{"sha": "b" * 40}, {"truncated": True}]
        with pytest.raises(SyncError):
            sync(data[3])


def test_no_arbitrary_repository():
    with pytest.raises(SyncError):
        GitHubReader("attacker/private")


def test_blob_integrity():
    reader = object.__new__(GitHubReader)
    reader.get = lambda path: {"encoding": "base64", "content": base64.b64encode(b"bad").decode(), "size": 3}
    with pytest.raises(SyncError):
        reader.blob("a" * 40)


def test_webhook_signature_replay_and_nonmain(data):
    payload = json.dumps({"repository": {"full_name": data[3].repository}, "ref": "refs/heads/main"}).encode()
    url = reverse("avia_brand:webhook")
    c = Client()
    with override_settings(AVIA_GITHUB_WEBHOOK_SECRET="fixture"):
        assert c.post(url, data=payload, content_type="application/json").status_code == 403
        headers = {
            "HTTP_X_HUB_SIGNATURE_256": "sha256=" + hmac.new(b"fixture", payload, hashlib.sha256).hexdigest(),
            "HTTP_X_GITHUB_EVENT": "push",
            "HTTP_X_GITHUB_DELIVERY": str(uuid.uuid4()),
        }
        assert c.post(url, data=payload, content_type="application/json", **headers).status_code == 202
        assert c.post(url, data=payload, content_type="application/json", **headers).json()["duplicate"]
    assert HookReceipt.objects.count() == 1
    assert BrandAudit.objects.filter(action="sync_requested").count() == 1


def test_csrf_required(data):
    login(data[0])
    c = Client(enforce_csrf_checks=True)
    c.force_login(data[0])
    assert c.post(reverse("avia_brand:sync", args=[data[2].id])).status_code == 403


def test_publish_switch_prevents_dispatch():
    from apps.publisher.engine import PublishEngine, _resolve_publish_credentials

    with (
        override_settings(AVIA_PUBLISH_ENABLED=False),
        patch.object(PublishEngine, "_get_due_platform_posts") as dispatch,
    ):
        assert PublishEngine().poll_and_publish() == 0
        dispatch.assert_not_called()
        with pytest.raises(RuntimeError):
            _resolve_publish_credentials(None)


def test_outbox_signed_minimal_and_not_resent(data):
    import os

    from django.core.management import call_command

    from .models import OutboxEvent

    review(data[3], data[4].id, data[0], True)
    with (
        patch.dict(
            os.environ,
            {"AVIA_OUTBOUND_WEBHOOK_URL": "https://example.com/events", "AVIA_OUTBOUND_WEBHOOK_SECRET": "fixture"},
        ),
        patch("apps.avia_brand.management.commands.avia_deliver_events.is_safe_url", return_value=True),
        patch("apps.avia_brand.management.commands.avia_deliver_events.httpx.post") as post,
    ):
        post.return_value.status_code = 204
        call_command("avia_deliver_events")
        call_command("avia_deliver_events")
        assert post.call_count == 1
        payload = post.call_args.kwargs["content"]
        assert b"Synthetic" not in payload and b"joacoAviles" not in payload
        expected = "sha256=" + hmac.new(b"fixture", payload, hashlib.sha256).hexdigest()
        assert post.call_args.kwargs["headers"]["X-Avia-Signature-256"] == expected
    assert OutboxEvent.objects.get().delivered_at is not None


def test_brand_api_requires_permission_and_only_active_revision(data):
    from apps.api_keys.services import issue_api_key
    from apps.social_accounts.models import SocialAccount

    owner, other, ws, src, rev = data
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="linkedin_personal",
        account_platform_id="synthetic",
        account_name="Fixture",
        connection_status="connected",
    )
    key = issue_api_key(
        workspace=ws,
        social_accounts=[account],
        issued_by=owner,
        name="brand-test",
        permissions=["manage_workspace_settings"],
    )
    c = Client()
    headers = {"HTTP_AUTHORIZATION": "Bearer " + key.plaintext_token}
    response = c.get("/api/v1/brand/", secure=True, **headers)
    assert response.status_code == 200 and response.json()["identity"] is None
    review(src, rev.id, owner, True)
    response = c.get("/api/v1/brand/", secure=True, **headers)
    assert response.json()["identity"]["brand"]["name"] == "Synthetic Brand"
    assert response["Cache-Control"] == "private, no-store"
    limited = issue_api_key(
        workspace=ws, social_accounts=[account], issued_by=owner, name="limited", permissions=["create_posts"]
    )
    assert (
        c.get("/api/v1/brand/", secure=True, HTTP_AUTHORIZATION="Bearer " + limited.plaintext_token).status_code == 403
    )
    membership = WorkspaceMembership.objects.get(user=owner, workspace=ws)
    membership.workspace_role = "viewer"
    membership.save()
    assert c.get("/api/v1/brand/", secure=True, **headers).status_code == 403


def test_bootstrap_is_idempotent(data):
    from django.core.management import call_command

    # Existing legacy source is retained; the three Avia-Brands folders are created once,
    # without downloading anything.
    call_command("avia_bootstrap", email=data[0].email)
    call_command("avia_bootstrap", email=data[0].email)
    assert BrandSource.objects.count() == 4
    assert set(BrandSource.objects.exclude(path="").values_list("path", flat=True)) == {
        "brands/avia-rockets",
        "brands/joaco-avia",
        "brands/acelerados",
    }
    assert BrandRevision.objects.count() == 1


def test_reader_get_only_no_redirects(tmp_path):
    token_dir = tmp_path / "tokens"
    token_dir.mkdir()
    (token_dir / "joaco-avia-brand.token").write_text("synthetic-token")
    with (
        override_settings(AVIA_GITHUB_TOKEN_DIR=str(token_dir)),
        patch("apps.avia_brand.services.httpx.Client") as client,
    ):
        response = client.return_value.__enter__.return_value.stream.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_bytes.return_value = [b'{"sha":"fixture"}']
        reader = GitHubReader("joacoAviles/joaco-avia-brand")
        assert reader.get("/commits/main") == {"sha": "fixture"}
        assert client.call_args.kwargs["follow_redirects"] is False
        stream = client.return_value.__enter__.return_value.stream
        assert stream.call_args.args == (
            "GET",
            "https://api.github.com/repos/joacoAviles/joaco-avia-brand/commits/main",
        )


def test_approved_download_is_private(data):
    owner, _, ws, src, rev = data
    rev.catalog = [{"sha": "b" * 40, "path": "assets/test.png", "size": 7}]
    rev.save()
    review(src, rev.id, owner, True)
    with patch("apps.avia_brand.views.GitHubReader") as reader:
        reader.return_value.blob.return_value = b"fixture"
        response = login(owner).get(reverse("avia_brand:asset", args=[ws.id, rev.id, "b" * 40]))
    assert response.status_code == 200 and response.content == b"fixture"
    assert response["Cache-Control"] == "private, no-store"
    assert response["Content-Disposition"].startswith("attachment")


def test_approve_custom_repository_does_not_require_builtin_name(data):
    owner, other, ws, source, revision = data
    source.repository = "example/Avia-Brands"
    source.save(update_fields=["repository"])
    client = login(owner)
    response = client.post(reverse("avia_brand:review", args=[ws.id, revision.id]), {"decision": "approve"})
    assert response.status_code == 302
    ws.refresh_from_db()
    source.refresh_from_db()
    assert ws.name == "Synthetic Brand"
    assert source.active_revision_id == revision.id
