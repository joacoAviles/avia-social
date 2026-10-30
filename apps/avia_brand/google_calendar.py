"""Google Calendar dedicated AVIA calendar connection. Grants are private to each workspace member."""

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from apps.members.models import WorkspaceMembership

from .models import CalendarConnection, InstallationSetup

SCOPES = ["https://www.googleapis.com/auth/calendar.app.created"]
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://www.googleapis.com/calendar/v3/"


class CalendarError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def credentials():
    state = InstallationSetup.objects.filter(pk=1).first()
    return (state.calendar_credentials if state else {}) or {}


def member(request, workspace_id):
    return get_object_or_404(
        WorkspaceMembership.objects.select_related("workspace"),
        user=request.user,
        workspace_id=workspace_id,
        workspace__is_archived=False,
    )


def callback_url(request, workspace_id):
    return request.build_absolute_uri(reverse("welcome:calendar_callback", args=[workspace_id]))


def exchange(data):
    try:
        with httpx.Client(timeout=20, trust_env=False) as client:
            response = client.post(TOKEN_URL, data=data)
        response.raise_for_status()
        result = response.json()
        if not result.get("access_token"):
            raise CalendarError("Google no entregó acceso. Vuelve a conectar tu calendario.")
        return result
    except (httpx.HTTPError, ValueError) as exc:
        raise CalendarError(
            "Google no pudo renovar o autorizar el acceso. Revisa el cliente OAuth y vuelve a conectar."
        ) from exc


def api(connection, path, params=None, *, method="GET", body=None):
    tokens = dict(connection.tokens)
    if tokens.get("expires_at", 0) < time.time() + 60:
        config = credentials()
        if not tokens.get("refresh_token") or not config:
            raise CalendarError("Tu autorización venció. Vuelve a conectar Google Calendar.")
        result = exchange({**config, "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
        tokens.update(access_token=result["access_token"], expires_at=time.time() + int(result.get("expires_in", 3600)))
        connection.tokens = tokens
        connection.save(update_fields=["tokens"])
    try:
        with httpx.Client(timeout=20, trust_env=False) as client:
            response = client.request(
                method,
                API_URL + path,
                params=params,
                json=body,
                headers={"Authorization": "Bearer " + tokens["access_token"]},
            )
        response.raise_for_status()
        return {} if response.status_code == 204 else response.json()
    except httpx.HTTPStatusError as exc:
        raise CalendarError(
            "Google rechazó la operación. Revisa los permisos o vuelve a conectar la misma cuenta.",
            exc.response.status_code,
        ) from exc
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise CalendarError(
            "No pudimos completar la operación en el calendario AVIA. Comprueba que la API esté habilitada y vuelve a conectar si se revocaron los permisos."
        ) from exc


@login_required
@require_POST
@never_cache
def connect(request, workspace_id):
    membership = member(request, workspace_id)
    if not membership.effective_permissions.get("manage_workspace_settings"):
        raise PermissionDenied
    config = credentials()
    if not config:
        messages.error(request, "El administrador debe habilitar Google Calendar primero.")
        return redirect("welcome:calendar", workspace_id=workspace_id)
    from .welcome import local_or_secure

    if not local_or_secure(request):
        raise PermissionDenied
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    request.session["calendar_oauth"] = {
        "state": state,
        "verifier": verifier,
        "workspace": str(workspace_id),
        "user": str(request.user.pk),
        "created": time.time(),
        "redirect": callback_url(request, workspace_id),
    }
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return redirect(
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urlencode(
            {
                "client_id": config["client_id"],
                "redirect_uri": callback_url(request, workspace_id),
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )


@login_required
@require_GET
@never_cache
@sensitive_post_parameters()
def callback(request, workspace_id):
    membership = member(request, workspace_id)
    if not membership.effective_permissions.get("manage_workspace_settings"):
        raise PermissionDenied
    pending = request.session.pop("calendar_oauth", {})
    if (
        not pending
        or not secrets.compare_digest(pending.get("state", ""), request.GET.get("state", ""))
        or pending.get("workspace") != str(workspace_id)
        or pending.get("user") != str(request.user.pk)
        or time.time() - pending.get("created", 0) > 600
    ):
        messages.error(request, "La conexión expiró o no corresponde a esta sesión. Inicia la conexión otra vez.")
        return redirect("welcome:calendar", workspace_id=workspace_id)
    if request.GET.get("error") or not request.GET.get("code"):
        messages.error(
            request,
            "Google no autorizó el acceso. Si ves access_denied, añade tu correo en Google Auth Platform → Audience → Test users del proyecto de este cliente.",
        )
        return redirect("welcome:calendar", workspace_id=workspace_id)
    try:
        tokens = exchange(
            {
                **credentials(),
                "code": request.GET["code"],
                "grant_type": "authorization_code",
                "redirect_uri": pending["redirect"],
                "code_verifier": pending["verifier"],
            }
        )
        if not set(SCOPES).issubset(set(tokens.get("scope", "").split())):
            raise CalendarError("Falta el permiso para administrar calendarios creados por AVIA. Vuelve a conectar.")
        if not tokens.get("refresh_token"):
            raise CalendarError("Google no entregó permiso para mantener la conexión. Vuelve a autorizar Calendar.")
        tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600))
        CalendarConnection.objects.update_or_create(
            user=request.user,
            workspace_id=workspace_id,
            defaults={"tokens": tokens},
        )
        messages.success(
            request, "Google autorizado. Crea tu calendario exclusivo de AVIA o sincroniza el que ya vinculaste."
        )
    except CalendarError as exc:
        messages.error(request, str(exc))
    return redirect("welcome:calendar", workspace_id=workspace_id)


@login_required
@never_cache
@require_GET
def agenda(request, workspace_id):
    membership = member(request, workspace_id)
    connection = CalendarConnection.objects.filter(user=request.user, workspace_id=workspace_id).first()
    return render(
        request,
        "avia_brand/calendar.html",
        {
            "workspace": membership.workspace,
            "connection": connection,
            "configured": bool(credentials()),
            "can_manage": membership.effective_permissions.get("manage_workspace_settings"),
            "can_create": bool(connection and set(SCOPES).issubset(set(connection.tokens.get("scope", "").split()))),
        },
    )


@login_required
@require_POST
@never_cache
def create_calendar(request, workspace_id):
    from django.db import transaction

    membership = member(request, workspace_id)
    if not membership.effective_permissions.get("manage_workspace_settings"):
        raise PermissionDenied
    with transaction.atomic():
        connection = get_object_or_404(
            CalendarConnection.objects.select_for_update(), user=request.user, workspace_id=workspace_id
        )
        if connection.managed or connection.creation_started:
            return redirect("welcome:calendar", workspace_id=workspace_id)
        if not set(SCOPES).issubset(set(connection.tokens.get("scope", "").split())):
            messages.error(request, "Vuelve a autorizar para crear el calendario exclusivo de AVIA.")
            return redirect("welcome:calendar", workspace_id=workspace_id)
        # Commit before the external creation: a timeout must never create duplicates on retry.
        connection.creation_started = True
        connection.save(update_fields=["creation_started"])
    try:
        name = "AVIA Social · " + membership.workspace.name
        calendar = api(
            connection,
            "calendars",
            method="POST",
            body={
                "summary": name,
                "description": "Publicaciones y eventos gestionados desde AVIA Social.",
                "timeZone": membership.workspace.timezone or "UTC",
            },
        )
        if not calendar.get("id"):
            raise CalendarError("Google no confirmó el calendario. Revisa Google Calendar antes de reintentar.")
        connection.calendar_id = calendar["id"]
        connection.calendar_name = name
        connection.managed = True
        connection.sync_error = ""
        connection.save(update_fields=["calendar_id", "calendar_name", "managed", "sync_error"])
        messages.success(
            request, "Calendario AVIA creado en tu cuenta Google. La sincronización automática actualizará sus eventos."
        )
    except CalendarError as exc:
        connection.sync_error = str(exc)
        if exc.status in {400, 401, 403, 429}:
            connection.creation_started = False
        connection.save(update_fields=["sync_error", "creation_started"])
        messages.error(request, str(exc))
    return redirect("welcome:calendar", workspace_id=workspace_id)


@login_required
@require_POST
@never_cache
def synchronize(request, workspace_id):
    from .calendar_sync import sync_connection

    membership = member(request, workspace_id)
    if not membership.effective_permissions.get("manage_workspace_settings"):
        raise PermissionDenied
    connection = get_object_or_404(CalendarConnection, user=request.user, workspace_id=workspace_id, managed=True)
    try:
        sync_connection(connection.pk)
        messages.success(request, "Cambios de AVIA sincronizados con tu calendario Google.")
    except CalendarError as exc:
        CalendarConnection.objects.filter(pk=connection.pk).update(sync_error=str(exc)[:500])
        messages.error(request, str(exc))
    return redirect("welcome:calendar", workspace_id=workspace_id)


@login_required
@require_POST
@never_cache
def disconnect(request, workspace_id):
    member(request, workspace_id)
    CalendarConnection.objects.filter(user=request.user, workspace_id=workspace_id).delete()
    messages.success(request, "Conexión eliminada de AVIA. Puedes revocar el permiso también desde tu cuenta Google.")
    return redirect("welcome:calendar", workspace_id=workspace_id)
