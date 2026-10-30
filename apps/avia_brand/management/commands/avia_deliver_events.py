import hashlib
import hmac
import json
import os

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.avia_brand.models import OutboxEvent
from apps.common.validators import is_safe_url


class Command(BaseCommand):
    help = "Deliver metadata-only events to an operator-configured HTTPS endpoint; receiver deduplicates event id."

    def handle(self, *args, **options):
        url = os.environ.get("AVIA_OUTBOUND_WEBHOOK_URL", "")
        secret = os.environ.get("AVIA_OUTBOUND_WEBHOOK_SECRET", "")
        if not url.startswith("https://") or not secret or not is_safe_url(url):
            raise CommandError("Configure an allowed public HTTPS endpoint and signing secret")
        failed = 0
        for event_id in OutboxEvent.objects.filter(delivered_at=None, attempts__lt=5).values_list("id", flat=True)[
            :100
        ]:
            with transaction.atomic():
                event = OutboxEvent.objects.select_for_update().get(pk=event_id)
                if event.delivered_at or event.attempts >= 5:
                    continue
                body = json.dumps(
                    {
                        "id": str(event.id),
                        "type": event.kind,
                        "workspace_id": str(event.workspace_id),
                        "revision_id": str(event.revision),
                    },
                    sort_keys=True,
                ).encode()
                signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
                event.attempts += 1
                try:
                    response = httpx.post(
                        url,
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Avia-Signature-256": "sha256=" + signature,
                            "Idempotency-Key": str(event.id),
                        },
                        follow_redirects=False,
                        timeout=10,
                        trust_env=False,
                    )
                    if 200 <= response.status_code < 300:
                        event.delivered_at = timezone.now()
                    else:
                        failed += 1
                except httpx.HTTPError:
                    failed += 1
                event.save(update_fields=["attempts", "delivered_at"])
        if failed:
            raise CommandError(f"{failed} delivery attempt(s) failed; details withheld to protect secrets")
