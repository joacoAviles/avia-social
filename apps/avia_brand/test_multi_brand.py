"""One repository (Avia-Brands) holding several independent brands, one folder each."""

import hashlib
from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.test import Client

from apps.accounts.models import User
from apps.workspaces.models import Workspace

from .models import BrandAudit, BrandSource
from .presentation import tokens, ui_brand
from .services import SyncError, clean_path, list_brands, review, sync

pytestmark = pytest.mark.django_db

REPO = "joacoAviles/Avia-Brands"


def blob(content):
    return content, hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


ROCKETS, ROCKETS_SHA = blob(
    b'{"schema_version":1,"brand":{"name":"Avia Rockets"},"visual":{"colors":{"values":'
    b'{"blue":"#0A6CFF","navy":"#071426","white":"#FFFFFF","gray":"#8A95A6"},"primary":"blue","secondary":"navy"},'
    b'"typography":{"display":"Space Grotesk"}}}'
)
JOACO, JOACO_SHA = blob(b'{"schema_version":1,"brand":{"name":"Joaco Avia"}}')
INDEX, INDEX_SHA = blob(
    b'{"schema_version":1,"brands":[{"path":"brands/avia-rockets","name":"Avia Rockets"},'
    b'{"path":"brands/joaco-avia","name":"Joaco Avia"},{"path":"brands/../x","name":"bad"},'
    b'{"path":"brands/empty","name":"Sin manifiesto"}]}'
)


def item(path, sha, size=10):
    return {"type": "blob", "mode": "100644", "path": path, "sha": sha, "size": size}


TREE = {
    "tree": [
        item("brands.yaml", INDEX_SHA, len(INDEX)),
        item("brands/avia-rockets/brand/brand.yaml", ROCKETS_SHA, len(ROCKETS)),
        item("brands/avia-rockets/assets/favicon/favicon.svg", "1" * 40),
        item("brands/joaco-avia/brand/brand.yaml", JOACO_SHA, len(JOACO)),
        item("brands/joaco-avia/assets/logo/logo.svg", "2" * 40),
        item("brands/empty/README.md", "3" * 40),
        item("brand/brand.yaml", "4" * 40),
    ]
}
BLOBS = {ROCKETS_SHA: ROCKETS, JOACO_SHA: JOACO, INDEX_SHA: INDEX}


@pytest.fixture
def org():
    owner = User.objects.create_user(email="owner@example.test", password="pass")
    ws = owner.workspace_memberships.first().workspace
    second = Workspace.objects.create(organization=ws.organization, name="Segunda")
    return owner, ws, second


def fake_reader(reader):
    reader.return_value.get.side_effect = lambda path: {"sha": "c" * 40} if path.startswith("/commits/") else TREE
    reader.return_value.blob.side_effect = lambda sha, limit=0: BLOBS[sha]


def test_each_brand_only_catalogs_its_own_folder(org):
    owner, ws, second = org
    rockets = BrandSource.objects.create(workspace=ws, repository=REPO, path="brands/avia-rockets", github_token="t")
    joaco = BrandSource.objects.create(workspace=second, repository=REPO, path="brands/joaco-avia", github_token="t")
    with patch("apps.avia_brand.services.GitHubReader") as reader:
        fake_reader(reader)
        r1 = sync(rockets, owner)
        r2 = sync(joaco, owner)
    assert r1.identity["brand"]["name"] == "Avia Rockets"
    assert r2.identity["brand"]["name"] == "Joaco Avia"
    assert {c["path"] for c in r1.catalog} == {
        "brands/avia-rockets/brand/brand.yaml",
        "brands/avia-rockets/assets/favicon/favicon.svg",
    }
    assert all(c["path"].startswith("brands/joaco-avia/") for c in r2.catalog)
    review(rockets, r1.id, owner, True)
    review(joaco, r2.id, owner, True)
    ws.refresh_from_db()
    second.refresh_from_db()
    assert (ws.name, ws.primary_color, ws.secondary_color) == ("Avia Rockets", "#0A6CFF", "#071426")
    assert second.name == "Joaco Avia" and second.primary_color == ""


def test_same_folder_cannot_back_two_workspaces(org):
    _, ws, second = org
    BrandSource.objects.create(workspace=ws, repository=REPO, path="brands/avia-rockets")
    with pytest.raises(IntegrityError):
        BrandSource.objects.create(workspace=second, repository=REPO, path="brands/avia-rockets")


def test_missing_manifest_in_folder_fails(org):
    _, ws, _ = org
    source = BrandSource.objects.create(workspace=ws, repository=REPO, path="brands/empty", github_token="t")
    with patch("apps.avia_brand.services.GitHubReader") as reader:
        fake_reader(reader)
        with pytest.raises(SyncError, match="brands/empty/brand/brand.yaml"):
            sync(source)


@pytest.mark.parametrize("bad", ["../x", "brands/../x", "a b", "Brands/Upper", "a/b/c/d/e", "brands/.hidden"])
def test_folder_traversal_rejected(bad):
    with pytest.raises(SyncError):
        clean_path(bad)


def test_index_lists_only_valid_folders_with_manifest():
    with patch("apps.avia_brand.services.GitHubReader") as reader:
        fake_reader(reader)
        with pytest.raises(SyncError):
            list_brands(reader.return_value, "main")  # traversal entry makes the whole index invalid


def test_index_lists_brands():
    clean, sha = blob(
        b'{"schema_version":1,"brands":[{"path":"brands/avia-rockets","name":"Avia Rockets"},'
        b'{"path":"brands/joaco-avia","name":"Joaco Avia"},{"path":"brands/empty","name":"x"}]}'
    )
    tree = {"tree": [item("brands.yaml", sha, len(clean)), *TREE["tree"][1:]]}
    with patch("apps.avia_brand.services.GitHubReader") as reader:
        reader.return_value.get.side_effect = lambda p: {"sha": "c" * 40} if p.startswith("/commits/") else tree
        reader.return_value.blob.side_effect = lambda s, limit=0: {sha: clean, **BLOBS}[s]
        assert list_brands(reader.return_value, "main") == [
            {"path": "brands/avia-rockets", "name": "Avia Rockets"},
            {"path": "brands/joaco-avia", "name": "Joaco Avia"},
        ]


def test_link_requires_folder_when_repo_has_several_brands(org):
    owner, ws, _ = org
    clean, sha = blob(b'{"schema_version":1,"brands":[{"path":"brands/avia-rockets","name":"Avia Rockets"}]}')
    tree = {"tree": [item("brands.yaml", sha, len(clean)), *TREE["tree"][1:]]}
    c = Client()
    owner.tos_accepted_at = __import__("django.utils.timezone", fromlist=["now"]).now()
    owner.save()
    c.force_login(owner)

    def get(path):
        if path == "":
            return {"default_branch": "main", "full_name": REPO}
        return {"sha": "c" * 40} if path.startswith("/commits/") else tree

    post = {"action": "github", "repository": REPO, "token": "t", "readonly": "on"}
    from django.urls import reverse

    url = reverse("welcome:journey", args=[ws.id])
    with patch("apps.avia_brand.welcome.GitHubReader") as reader:
        reader.return_value.get.side_effect = get
        reader.return_value.blob.side_effect = lambda s, limit=0: {sha: clean}[s]
        response = c.post(url, post, secure=True)
        assert "brands/avia-rockets (Avia Rockets)" in response.content.decode()
        assert not BrandSource.objects.filter(workspace=ws).exists()
        response = c.post(url, {**post, "path": "brands/avia-rockets"}, secure=True)
    assert response.status_code == 302
    source = BrandSource.objects.get(workspace=ws)
    assert (source.repository, source.path, source.label) == (
        REPO,
        "brands/avia-rockets",
        REPO + " · brands/avia-rockets",
    )


def test_ui_theme_uses_avia_rockets_folder(org, rf):
    owner, ws, second = org
    source = BrandSource.objects.create(workspace=ws, repository=REPO, path="brands/avia-rockets", github_token="t")
    BrandSource.objects.create(workspace=second, repository=REPO, path="brands/joaco-avia", github_token="t")
    with patch("apps.avia_brand.services.GitHubReader") as reader:
        fake_reader(reader)
        revision = sync(source, owner)
    review(source, revision.id, owner, True)
    values = dict(ui_brand(rf.get("/"))["avia_ui_tokens"])
    assert values["--brand-500"] == "#0A6CFF" and values["--brand-900"] == "#071426"
    assert values["--brand-font-display"].startswith("'Space Grotesk'")


def test_push_webhook_requests_sync_for_every_brand_in_repo(org, settings):
    import hmac
    import json
    import uuid

    from django.urls import reverse

    _, ws, second = org
    BrandSource.objects.create(workspace=ws, repository=REPO, path="brands/avia-rockets")
    BrandSource.objects.create(workspace=second, repository=REPO, path="brands/joaco-avia")
    settings.AVIA_GITHUB_WEBHOOK_SECRET = "s"
    body = json.dumps({"ref": "refs/heads/main", "repository": {"full_name": REPO}}).encode()
    signature = "sha256=" + hmac.new(b"s", body, "sha256").hexdigest()
    response = Client().post(
        reverse("avia_brand:webhook"),
        body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
        HTTP_X_GITHUB_EVENT="push",
        HTTP_X_GITHUB_DELIVERY=str(uuid.uuid4()),
    )
    assert response.status_code == 202
    assert BrandAudit.objects.filter(action="sync_requested").count() == 2


def test_tokens_ignore_structured_typography():
    assert tokens({"visual": {"colors": {"values": {}}, "typography": {"display": {"family": "x"}}}}) == []


@pytest.mark.parametrize(
    "colors, expected",
    [
        (
            {"values": {"blue": "#0A6CFF", "navy": "#071426"}, "primary": "blue", "secondary": "navy"},
            ("#0A6CFF", "#071426"),
        ),
        ({"values": {"x": "#111111"}, "primary": "#222222", "secondary": "#333333"}, ("#222222", "#333333")),
        ({"values": {"secondary": "#64748B", "primary": "#334155"}}, ("#334155", "#64748B")),
        ({"values": {"one": "#123456"}}, ("#123456", "")),
        ({"values": {"blue": "nope"}, "primary": "blue"}, ("", "")),
    ],
)
def test_workspace_colors_prefers_explicit_roles(colors, expected):
    from .services import workspace_colors

    assert workspace_colors({"visual": {"colors": colors}}) == expected
