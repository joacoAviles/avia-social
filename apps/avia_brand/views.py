import hashlib
import hmac
import json
import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import BrandAudit, BrandRevision, BrandSource, HookReceipt
from .services import GitHubReader, SyncError, review, sync


def source_for(request, workspace_id, write=False):
    from apps.members.models import WorkspaceMembership

    membership = get_object_or_404(
        WorkspaceMembership, user=request.user, workspace_id=workspace_id, workspace__is_archived=False
    )
    if write and not membership.effective_permissions.get("manage_workspace_settings", False):
        raise PermissionDenied
    return get_object_or_404(BrandSource, workspace_id=workspace_id)


@login_required
def catalog(request, workspace_id):
    source = source_for(request, workspace_id)
    response = render(
        request,
        "avia_brand/catalog.html",
        {
            "source": source,
            "revisions": source.revisions.order_by("-created_at"),
            "audit": BrandAudit.objects.filter(source=source).order_by("-created_at")[:30],
        },
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def synchronize(request, workspace_id):
    source = source_for(request, workspace_id, True)
    try:
        sync(source, request.user)
    except SyncError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("avia_brand:catalog", workspace_id=workspace_id)


@login_required
@require_POST
def decide(request, workspace_id, revision_id):
    source = source_for(request, workspace_id, True)
    if request.POST.get("decision") not in {"approve", "reject"}:
        return HttpResponseBadRequest("Invalid decision")
    get_object_or_404(BrandRevision, pk=revision_id, source=source)
    try:
        review(source, revision_id, request.user, request.POST["decision"] == "approve")
    except SyncError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("avia_brand:catalog", workspace_id=workspace_id)


@login_required
def asset(request, workspace_id, revision_id, sha):
    source = source_for(request, workspace_id)
    revision = get_object_or_404(BrandRevision, pk=revision_id, source=source, state="approved")
    item = next((x for x in revision.catalog if x["sha"] == sha), None)
    if not item:
        return HttpResponse(status=404)
    try:
        reader = (
            GitHubReader(source.repository, source.github_token)
            if source.github_token
            else GitHubReader(source.repository)
        )
        content = reader.blob(sha)
    except SyncError as exc:
        return HttpResponseBadRequest(str(exc))
    response = HttpResponse(content, content_type="application/octet-stream")
    response["Content-Disposition"] = 'attachment; filename="brand-resource"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@csrf_exempt
@require_POST
def webhook(request):
    # GitHub webhook only records a request. It does not publish or approve anything.
    secret = settings.AVIA_GITHUB_WEBHOOK_SECRET
    if not secret or len(request.body) > 65536:
        return HttpResponse(status=403)
    expected = "sha256=" + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
        return HttpResponse(status=403)
    if request.headers.get("X-GitHub-Event") != "push":
        return HttpResponse(status=204)
    try:
        payload = json.loads(request.body)
        delivery = uuid.UUID(request.headers.get("X-GitHub-Delivery", ""))
        repo = payload["repository"]["full_name"]
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest("Invalid event")
    sources = list(BrandSource.objects.filter(repository__iexact=repo).order_by("path"))
    if not sources:
        return HttpResponse(status=404)
    # One repository may hold several brands; a push requests a sync for each brand on that branch.
    sources = [s for s in sources if payload.get("ref") == "refs/heads/" + s.branch]
    if not sources:
        return HttpResponse(status=204)
    with transaction.atomic():
        receipt, created = HookReceipt.objects.get_or_create(delivery=delivery, defaults={"source": sources[0]})
        if created:
            for source in sources:
                BrandAudit.objects.create(source=source, action="sync_requested")
    return JsonResponse({"accepted": True, "duplicate": not created, "action": "sync_requested"}, status=202)
