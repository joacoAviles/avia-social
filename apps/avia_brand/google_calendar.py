"""Google Calendar read-only connection. Grants are private to each workspace member."""

import base64
import hashlib
import secrets
import time
from datetime import timedelta
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.members.models import WorkspaceMembership

from .models import CalendarConnection, InstallationSetup

SCOPES = [
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
]
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://www.googleapis.com/calendar/v3/"


class CalendarError(Exception):
    pass


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


def api(connection, path, params=None):
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
            response = client.get(
                API_URL + path, params=params, headers={"Authorization": "Bearer " + tokens["access_token"]}
            )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise CalendarError(
            "No pudimos consultar Google Calendar. Comprueba que la API esté habilitada y vuelve a conectar si se revocaron los permisos."
        ) from exc


@login_required
@require_POST
@never_cache
def connect(request, workspace_id):
    member(request, workspace_id)
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
    member(request, workspace_id)
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
            raise CalendarError("Faltan permisos de lectura de Calendar. Vuelve a conectar aceptando ambos permisos.")
        if not tokens.get("refresh_token"):
            raise CalendarError("Google no entregó permiso para mantener la conexión. Vuelve a autorizar Calendar.")
        tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600))
        CalendarConnection.objects.update_or_create(
            user=request.user,
            workspace_id=workspace_id,
            defaults={"tokens": tokens, "calendar_id": "", "calendar_name": ""},
        )
        messages.success(request, "Google Calendar autorizado. Elige el calendario que quieres consultar.")
    except CalendarError as exc:
        messages.error(request, str(exc))
    return redirect("welcome:calendar", workspace_id=workspace_id)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def agenda(request, workspace_id):
    membership = member(request, workspace_id)
    connection = CalendarConnection.objects.filter(user=request.user, workspace_id=workspace_id).first()
    calendars, events, error, listing = [], [], "", {}
    try:
        if connection:
            page = request.GET.get("calendars_page", "")
            listing = api(connection, "users/me/calendarList", {"maxResults": 100, "pageToken": page})
            calendars = listing.get("items", [])
            if request.method == "POST":
                selected = next((item for item in calendars if item["id"] == request.POST.get("calendar_id")), None)
                if not selected:
                    raise CalendarError("Selecciona uno de los calendarios disponibles.")
                connection.calendar_id = selected["id"]
                connection.calendar_name = selected.get("summary", selected["id"])
                connection.save(update_fields=["calendar_id", "calendar_name"])
                return redirect("welcome:calendar", workspace_id=workspace_id)
            if connection.calendar_id:
                start = timezone.now()
                result = api(
                    connection,
                    "calendars/" + quote(connection.calendar_id, safe="") + "/events",
                    {
                        "timeMin": start.isoformat(),
                        "timeMax": (start + timedelta(days=30)).isoformat(),
                        "singleEvents": "true",
                        "orderBy": "startTime",
                        "maxResults": 100,
                    },
                )
                events = result.get("items", [])
                try:
                    display_zone = ZoneInfo(membership.workspace.timezone or "UTC")
                except ZoneInfoNotFoundError:
                    display_zone = ZoneInfo("UTC")
                for event in events:
                    start_value = event.get("start", {})
                    if start_value.get("date"):
                        event["when"] = start_value["date"] + " · Todo el día"
                    else:
                        parsed = parse_datetime(start_value.get("dateTime", ""))
                        event["when"] = (
                            parsed.astimezone(display_zone).strftime("%d/%m/%Y · %H:%M %Z")
                            if parsed
                            else "Horario no disponible"
                        )
                if result.get("nextPageToken"):
                    messages.info(request, "Mostrando los primeros 100 eventos de los próximos 30 días.")
    except CalendarError as exc:
        error = str(exc)
    return render(
        request,
        "avia_brand/calendar.html",
        {
            "workspace": membership.workspace,
            "connection": connection,
            "calendars": calendars,
            "events": events,
            "error": error,
            "configured": bool(credentials()),
            "next_calendars": listing.get("nextPageToken", ""),
        },
    )


@login_required
@require_POST
@never_cache
def disconnect(request, workspace_id):
    member(request, workspace_id)
    CalendarConnection.objects.filter(user=request.user, workspace_id=workspace_id).delete()
    messages.success(request, "Conexión eliminada de AVIA. Puedes revocar el permiso también desde tu cuenta Google.")
    return redirect("welcome:calendar", workspace_id=workspace_id)
