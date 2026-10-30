"""One-way, idempotent AVIA -> dedicated Google calendar projection."""

import hashlib
import json
from datetime import timedelta
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from apps.members.models import WorkspaceMembership

from .google_calendar import CalendarError, api
from .models import CalendarConnection, CalendarMirror


def desired_events(workspace_id):
    from apps.calendar.models import CustomCalendarEvent
    from apps.composer.models import PlatformPost, Post

    result = {}
    for event in CustomCalendarEvent.objects.filter(workspace_id=workspace_id):
        result["event:" + str(event.pk)] = {
            "summary": event.title,
            "description": event.description,
            "start": {"date": event.start_date.isoformat()},
            "end": {"date": (event.end_date + timedelta(days=1)).isoformat()},
        }
    for child in PlatformPost.objects.filter(post__workspace_id=workspace_id).select_related("post", "social_account"):
        when = child.scheduled_at or child.post.scheduled_at or child.post.proposed_publish_at
        if not when:
            continue
        result["post:" + str(child.pk)] = {
            "summary": (child.post.title or child.post.caption[:100] or "Publicación")
            + " · "
            + child.social_account.platform,
            "description": "Estado en AVIA: " + child.status + "\n" + child.post.caption,
            "start": {"dateTime": when.isoformat()},
            "end": {"dateTime": (when + timedelta(minutes=30)).isoformat()},
        }
    for post in Post.objects.filter(workspace_id=workspace_id, platform_posts__isnull=True):
        when = post.scheduled_at or post.proposed_publish_at
        if when:
            result["draft:" + str(post.pk)] = {
                "summary": post.title or post.caption[:100] or "Borrador AVIA",
                "description": post.caption,
                "start": {"dateTime": when.isoformat()},
                "end": {"dateTime": (when + timedelta(minutes=30)).isoformat()},
            }
    return result


@transaction.atomic
def sync_connection(connection_id):
    connection = CalendarConnection.objects.select_for_update().get(pk=connection_id)
    membership = WorkspaceMembership.objects.filter(
        user=connection.user, workspace=connection.workspace, workspace__is_archived=False
    ).first()
    if not membership or not membership.effective_permissions.get("manage_workspace_settings"):
        raise CalendarError("La sincronización está detenida: falta permiso para administrar esta marca.")
    if not connection.managed or not connection.calendar_id:
        raise CalendarError("Primero crea el calendario exclusivo de AVIA.")
    base = "calendars/" + quote(connection.calendar_id, safe="") + "/events"
    desired = desired_events(connection.workspace_id)
    for key, payload in desired.items():
        payload["extendedProperties"] = {"private": {"avia_source": key}}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        mirror, _ = CalendarMirror.objects.get_or_create(
            connection=connection,
            source_key=key,
            defaults={"event_id": hashlib.sha256((str(connection.pk) + ":" + key).encode()).hexdigest()},
        )
        if mirror.fingerprint == fingerprint:
            continue
        path = base + "/" + quote(mirror.event_id, safe="")
        if mirror.fingerprint:
            api(connection, path, method="PATCH", body=payload)
        else:
            try:
                api(connection, base, method="POST", body={**payload, "id": mirror.event_id})
            except CalendarError as exc:
                if exc.status != 409:
                    raise
                api(connection, path, method="PATCH", body=payload)
        mirror.fingerprint = fingerprint
        mirror.save(update_fields=["fingerprint"])
    for mirror in connection.mirrors.exclude(source_key__in=desired).exclude(fingerprint=""):
        try:
            api(connection, base + "/" + quote(mirror.event_id, safe=""), method="DELETE")
        except CalendarError as exc:
            if exc.status not in {404, 410}:
                raise
        mirror.event_id = hashlib.sha256((mirror.event_id + ":next").encode()).hexdigest()
        mirror.fingerprint = ""
        mirror.save(update_fields=["event_id", "fingerprint"])
    connection.last_synced_at = timezone.now()
    connection.sync_error = ""
    connection.save(update_fields=["last_synced_at", "sync_error"])
