from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.api.limits import enforce_http_rate_limits
from apps.api.middleware import log_audit_entry
from apps.members.decorators import require_permission

from .models import BrandSource

router = Router(tags=["avia-brand"])


@router.get("/", summary="Approved private identity for this key's workspace")
@require_permission("manage_workspace_settings")
def identity(request):
    enforce_http_rate_limits(request, is_write=False)
    source = get_object_or_404(BrandSource, workspace=request.workspace)
    revision = source.active_revision
    response = JsonResponse(
        {
            "workspace_id": str(source.workspace_id),
            "commit": revision.commit if revision else None,
            "identity": revision.identity if revision else None,
            "catalog": revision.catalog if revision else [],
        }
    )
    response["Cache-Control"] = "private, no-store"
    log_audit_entry(request, action="brand.read", target_id=None, status_code=200)
    return response
