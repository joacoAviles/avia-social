"""AVIA Social additions, 2026-10-30. AGPL-3.0. Private data stays in PostgreSQL."""

import uuid

from django.conf import settings
from django.db import models

from apps.common.encryption import EncryptedJSONField, EncryptedTextField


class BrandSource(models.Model):
    workspace = models.OneToOneField("workspaces.Workspace", on_delete=models.CASCADE, related_name="brand_source")
    repository = models.CharField(max_length=100)
    # Brand folder inside the repository ("" = repository root). One repository can hold
    # several brands (e.g. brands/avia-rockets, brands/joaco-avia); each folder is its own
    # independent source with its own revisions, catalog and approval history.
    path = models.CharField(max_length=200, blank=True, default="")
    github_token = EncryptedTextField(blank=True, default="")
    branch = models.CharField(max_length=255, default="main")
    active_revision = models.ForeignKey(
        "BrandRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["repository", "path"], name="avia_source_repository_path")]

    @property
    def root(self):
        """Prefix of every catalogued file for this brand, with trailing slash or empty."""
        return self.path.strip("/") + "/" if self.path else ""

    @property
    def label(self):
        return self.repository + (" · " + self.path if self.path else "")


class BrandRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(BrandSource, on_delete=models.CASCADE, related_name="revisions")
    commit = models.CharField(max_length=40)
    catalog = models.JSONField(default=list)
    identity = models.JSONField(default=dict)
    state = models.CharField(
        max_length=10,
        default="pending",
        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "commit"], name="avia_source_commit")]


class BrandAudit(models.Model):
    source = models.ForeignKey(BrandSource, on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    commit = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class HookReceipt(models.Model):
    delivery = models.UUIDField(unique=True)
    source = models.ForeignKey(BrandSource, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=40)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE)
    revision = models.UUIDField()
    attempts = models.PositiveIntegerField(default=0)
    delivered_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class InstallationSetup(models.Model):
    """Singleton bootstrap lock; claimed installations can never be claimed again."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    token_hash = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(null=True)
    claimed_at = models.DateTimeField(null=True)
    google_credentials = EncryptedJSONField(default=dict)
    calendar_credentials = EncryptedJSONField(default=dict)


class WelcomeProgress(models.Model):
    workspace = models.OneToOneField("workspaces.Workspace", on_delete=models.CASCADE)
    completed_at = models.DateTimeField(null=True)


class CalendarConnection(models.Model):
    """Private Google Calendar grant, scoped to a user and workspace."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE)
    tokens = EncryptedJSONField(default=dict)
    calendar_id = models.CharField(max_length=1024, blank=True)
    calendar_name = models.CharField(max_length=500, blank=True)
    managed = models.BooleanField(default=False)
    creation_started = models.BooleanField(default=False)
    last_synced_at = models.DateTimeField(null=True)
    sync_error = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "workspace"], name="avia_calendar_user_workspace")]


class CalendarMirror(models.Model):
    connection = models.ForeignKey(CalendarConnection, on_delete=models.CASCADE, related_name="mirrors")
    source_key = models.CharField(max_length=100)
    event_id = models.CharField(max_length=64, default=uuid.uuid4)
    fingerprint = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["connection", "source_key"], name="avia_calendar_mirror_source")]
