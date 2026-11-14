"""Strict GET-only GitHub client. No cloning, execution, redirects or arbitrary URLs."""

import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import BrandAudit, BrandRevision, BrandSource, OutboxEvent

# Default AVIA sources: one private repository, one folder per brand.
BRANDS_REPOSITORY = "joacoAviles/Avia-Brands"
SOURCES = {
    (BRANDS_REPOSITORY, "brands/avia-rockets"): "Avia Rockets",
    (BRANDS_REPOSITORY, "brands/joaco-avia"): "Joaco Avia",
    (BRANDS_REPOSITORY, "brands/acelerados"): "Acelerados",
}
# Legacy single-brand repositories (one brand at the repository root). Still readable.
LEGACY_REPOSITORIES = {
    "joacoAviles/joaco-avia-brand": "Joaco Avia",
    "joacoAviles/avia-rockets-brand": "Avia Rockets",
    "joacoAviles/acelerados-brand": "Acelerados",
}
# Repositories whose read-only token may come from the mounted secrets directory.
REPOSITORIES = {BRANDS_REPOSITORY: "Avia Brands", **LEGACY_REPOSITORIES}
UI_SOURCES = ((BRANDS_REPOSITORY, "brands/avia-rockets"), ("joacoAviles/avia-rockets-brand", ""))
INDEX_PATH = "brands.yaml"
BRAND_PATH = re.compile(r"(?:[a-z0-9][a-z0-9_-]{0,62}/){0,3}[a-z0-9][a-z0-9_-]{0,62}")
MAX_BYTES = 5 * 1024 * 1024


def clean_path(value):
    """Normalise a brand folder; "" means the repository root. Rejects traversal and odd names."""
    value = (value or "").strip().strip("/")
    if value and not BRAND_PATH.fullmatch(value):
        raise SyncError("Invalid brand folder")
    return value


HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def workspace_colors(identity):
    """(primary, secondary) for a workspace from an approved identity.

    PostgreSQL stores identities as jsonb, which does not keep key order, so "the first two
    colors" is not reliable. Explicit choices win: visual.colors.primary / .secondary (a hex or
    the name of a key in visual.colors.values), then values.primary / values.secondary (template
    builder format), and only then the legacy first-two-valid-values fallback.
    """
    colors = identity.get("visual", {}).get("colors", {}) if isinstance(identity, dict) else {}
    colors = colors if isinstance(colors, dict) else {}
    values = colors.get("values", {})
    values = values if isinstance(values, dict) else {}

    def pick(ref):
        value = values.get(ref) if isinstance(ref, str) and ref in values else ref
        return value if isinstance(value, str) and HEX.fullmatch(value) else ""

    primary = pick(colors.get("primary")) or pick("primary")
    secondary = pick(colors.get("secondary")) or pick("secondary")
    if not primary:
        ordered = [v for v in values.values() if isinstance(v, str) and HEX.fullmatch(v)]
        primary = ordered[0] if ordered else ""
        secondary = secondary or (ordered[1] if len(ordered) > 1 else "")
    return primary, secondary


def source_name(repository, path):
    for (repo, folder), name in SOURCES.items():
        if repo.lower() == repository.lower() and folder == path:
            return name
    return LEGACY_REPOSITORIES.get(repository) if not path else None


class SyncError(Exception):
    pass


class GitHubReader:
    def __init__(self, repository, token=None):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,59}", repository):
            raise SyncError("Invalid repository")
        if token:
            self.repository = repository
            self.token = token
            return
        if repository not in REPOSITORIES:
            raise SyncError("Repository not allowed")
        self.repository = repository
        # One fine-grained token per repository, mounted read-only outside source tree.
        token_file = Path(settings.AVIA_GITHUB_TOKEN_DIR) / (repository.split("/")[1] + ".token")
        try:
            self.token = token_file.read_text().strip()
        except OSError:
            raise SyncError("Read-only GitHub credential is not configured") from None
        if not self.token:
            raise SyncError("Empty GitHub credential")

    def get(self, path):
        url = "https://api.github.com/repos/" + self.repository + path
        try:
            with (
                httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client,
                client.stream(
                    "GET",
                    url,
                    headers={
                        "Authorization": "Bearer " + self.token,
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    raise SyncError(f"GitHub read failed (status {response.status_code})")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        raise SyncError("GitHub response exceeds limit")
            return json.loads(data)
        except (httpx.HTTPError, ValueError):
            raise SyncError("GitHub unavailable or invalid response") from None

    def blob(self, sha, limit=MAX_BYTES):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise SyncError("Invalid blob reference")
        blob = self.get("/git/blobs/" + sha)
        if blob.get("encoding") != "base64" or blob.get("size", limit + 1) > limit:
            raise SyncError("Unsupported or oversized blob")
        try:
            raw = base64.b64decode(blob["content"].replace("\n", ""), validate=True)
        except (ValueError, KeyError):
            raise SyncError("Invalid blob encoding") from None
        digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if len(raw) > limit or digest != sha:
            raise SyncError("Blob integrity mismatch")
        return raw


def reader_for(source):
    if source.github_token:
        return GitHubReader(source.repository, source.github_token)
    return GitHubReader(source.repository)


def read_yaml(reader, sha, limit=65536):
    raw = reader.blob(sha, limit)
    if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(raw)):
        raise ValueError()
    data = yaml.safe_load(raw)
    # Reject recursive YAML, dates/non-JSON values and excessive expansion.
    if len(json.dumps(data)) > 131072:
        raise ValueError()
    return data


def list_brands(reader, ref):
    """Brands declared in a multi-brand repository's root brands.yaml.

    Returns [{"path", "name"}] for folders that really contain brand/brand.yaml; [] when the
    repository has a single brand at its root or no index.
    """
    commit = reader.get("/commits/" + quote(ref, safe="")).get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SyncError("Invalid commit")
    tree = reader.get("/git/trees/" + commit + "?recursive=1")
    if tree.get("truncated"):
        raise SyncError("Truncated catalog; refusing incomplete index")
    blobs = {i["path"]: i for i in tree.get("tree", []) if i.get("type") == "blob" and i.get("mode") == "100644"}
    index = blobs.get(INDEX_PATH)
    if not index:
        return []
    try:
        data = read_yaml(reader, index["sha"])
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("brands"), list):
            raise ValueError()
        found = []
        for entry in data["brands"]:
            path = clean_path(entry.get("path"))
            if path and path + "/brand/brand.yaml" in blobs:
                found.append({"path": path, "name": str(entry.get("name") or path)[:100]})
        return found
    except (ValueError, TypeError, AttributeError, RecursionError, yaml.YAMLError, SyncError):
        raise SyncError("Invalid brands.yaml index") from None


def sync(source, actor=None):
    reader = reader_for(source)
    root = clean_path(source.path)
    root = root + "/" if root else ""
    commit = reader.get("/commits/" + quote(source.branch, safe=""))["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SyncError("Invalid commit")
    tree = reader.get("/git/trees/" + commit + "?recursive=1")
    if tree.get("truncated"):
        raise SyncError("Truncated catalog; refusing incomplete revision")
    catalog = [
        {k: item[k] for k in ("path", "sha", "size")}
        for item in tree["tree"]
        if item.get("type") == "blob"
        and item.get("mode") == "100644"
        and item["path"].startswith((root + "brand/", root + "assets/"))
        and item.get("size", MAX_BYTES + 1) <= MAX_BYTES
        and not any(part.startswith(".") for part in item["path"].split("/"))
    ]
    manifest = next((x for x in catalog if x["path"] == root + "brand/brand.yaml"), None)
    if not manifest:
        raise SyncError("Missing " + root + "brand/brand.yaml")
    try:
        identity = read_yaml(reader, manifest["sha"])
        if not isinstance(identity, dict) or identity.get("schema_version") != 1:
            raise ValueError()
        if (
            not isinstance(identity.get("brand"), dict)
            or not isinstance(identity["brand"].get("name"), str)
            or not 1 <= len(identity["brand"]["name"]) <= 100
        ):
            raise ValueError()
        visual = identity.get("visual", {})
        if not isinstance(visual, dict) or not isinstance(visual.get("colors", {}), dict):
            raise ValueError()
    except (ValueError, TypeError, RecursionError, yaml.YAMLError):
        raise SyncError("Invalid brand schema v1") from None
    with transaction.atomic():
        BrandSource.objects.select_for_update().get(pk=source.pk)
        revision, created = BrandRevision.objects.get_or_create(
            source=source, commit=commit, defaults={"catalog": catalog, "identity": identity}
        )
        if created:
            BrandAudit.objects.create(source=source, actor=actor, action="synced", commit=commit)
    return revision


@transaction.atomic
def review(source, revision_id, actor, approve):
    source = BrandSource.objects.select_for_update().get(pk=source.pk)
    revision = source.revisions.select_for_update().get(pk=revision_id)
    if revision.state != "pending":
        raise SyncError("Revision already reviewed")
    revision.state = "approved" if approve else "rejected"
    revision.reviewed_by = actor
    revision.reviewed_at = timezone.now()
    revision.save(update_fields=["state", "reviewed_by", "reviewed_at"])
    if approve:
        source.active_revision = revision
        source.save(update_fields=["active_revision"])
        source.workspace.save()
    BrandAudit.objects.create(source=source, actor=actor, action=revision.state, commit=revision.commit)
    OutboxEvent.objects.create(kind="brand." + revision.state, workspace=source.workspace, revision=revision.id)
    return revision
