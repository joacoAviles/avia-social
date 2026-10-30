import uuid

from django.db import models

from apps.common.managers import OrgScopedManager
from apps.common.validators import validate_hex_color


class Workspace(models.Model):
    class ApprovalWorkflowMode(models.TextChoices):
        NONE = "none", "None"
        OPTIONAL = "optional", "Optional"
        REQUIRED_INTERNAL = "required_internal", "Required (Internal)"
        REQUIRED_INTERNAL_AND_CLIENT = "required_internal_and_client", "Required (Internal + Client)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="workspaces",
    )
    name = models.CharField(max_length=100)
    icon = models.ImageField(upload_to="workspaces/icons/%Y/%m/", blank=True)
    description = models.CharField(max_length=500, blank=True, default="")
    timezone = models.CharField(max_length=63, blank=True, default="")
    primary_color = models.CharField(max_length=7, blank=True, default="", validators=[validate_hex_color])
    secondary_color = models.CharField(max_length=7, blank=True, default="", validators=[validate_hex_color])
    default_hashtags = models.JSONField(default=list, blank=True)
    default_first_comment = models.TextField(blank=True, default="")
    approval_workflow_mode = models.CharField(
        max_length=40,
        choices=ApprovalWorkflowMode.choices,
        default=ApprovalWorkflowMode.NONE,
    )
    is_archived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrgScopedManager()

    class Meta:
        db_table = "workspaces_workspace"

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            from apps.avia_brand.models import BrandSource

            source = BrandSource.objects.filter(workspace_id=self.pk).select_related("active_revision").first()
            if source:
                from apps.avia_brand.services import REPOSITORIES

                identity = source.active_revision.identity if source.active_revision_id else {}
                self.name = identity.get("brand", {}).get("name", REPOSITORIES.get(source.repository, self.name))
                colors = identity.get("visual", {}).get("colors", {}).get("values", {})
                import re

                values = (
                    [v for v in colors.values() if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v)]
                    if isinstance(colors, dict)
                    else []
                )
                self.primary_color = values[0] if values else ""
                self.secondary_color = values[1] if len(values) > 1 else ""
                self.icon = ""
                if kwargs.get("update_fields"):
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                        "name",
                        "primary_color",
                        "secondary_color",
                        "icon",
                    }
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def effective_timezone(self):
        return self.timezone or self.organization.default_timezone
