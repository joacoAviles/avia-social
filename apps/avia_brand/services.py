"""Strict GET-only GitHub client. No cloning, execution, redirects or arbitrary URLs."""

import base64
import hashlib
import json
import re
from pathlib import Path

import httpx
import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import BrandAudit, BrandRevision, BrandSource, OutboxEvent

REPOSITORIES = {
    "joacoAviles/joaco-avia-brand": "Joaco Avia",
    "joacoAviles/avia-rockets-brand": "Avia Rockets",
    "joacoAviles/acelerados-brand": "Acelerados",
}
MAX_BYTES = 5 * 1024 * 1024


class SyncError(Exception):
    pass


class GitHubReader:
    def __init__(self, repository):
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


def sync(source, actor=None):
    reader = GitHubReader(source.repository)
    commit = reader.get("/commits/main")["sha"]
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
        and item["path"].startswith(("brand/", "assets/"))
        and item.get("size", MAX_BYTES + 1) <= MAX_BYTES
        and not any(part.startswith(".") for part in item["path"].split("/"))
    ]
    manifest = next((x for x in catalog if x["path"] == "brand/brand.yaml"), None)
    if not manifest:
        raise SyncError("Missing brand/brand.yaml")
    try:
        raw = reader.blob(manifest["sha"], 65536)
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(raw)):
            raise ValueError()
        identity = yaml.safe_load(raw)
        # Reject recursive YAML, dates/non-JSON values and excessive expansion.
        serialized = json.dumps(identity)
        if len(serialized) > 131072 or not isinstance(identity, dict) or identity.get("schema_version") != 1:
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
