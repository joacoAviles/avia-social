"""AVIA Social additions, 2026-10-30. AGPL-3.0. Private data stays in PostgreSQL."""

import uuid

from django.conf import settings
from django.db import models


class BrandSource(models.Model):
    workspace = models.OneToOneField("workspaces.Workspace", on_delete=models.CASCADE, related_name="brand_source")
    repository = models.CharField(max_length=100, unique=True)
    active_revision = models.ForeignKey(
        "BrandRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )


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
