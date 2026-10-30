import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.avia_brand.models import InstallationSetup


class Command(BaseCommand):
    help = "Issue a 30-minute first-administrator code. Refuses initialized installations."

    @transaction.atomic
    def handle(self, *args, **options):
        InstallationSetup.objects.get_or_create(pk=1)
        state = InstallationSetup.objects.select_for_update().get(pk=1)
        if state.claimed_at or get_user_model().objects.exists():
            raise CommandError("Installation already initialized; existing accounts preserved.")
        code = secrets.token_urlsafe(32)
        state.token_hash = hashlib.sha256(code.encode()).hexdigest()
        state.expires_at = timezone.now() + timedelta(minutes=30)
        state.save(update_fields=["token_hash", "expires_at"])
        self.stdout.write("Open /welcome/setup/ and enter this one-use code (expires in 30 minutes):")
        self.stdout.write(code)
