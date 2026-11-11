"""Diagnose the Meta setup from the server: callbacks, HTTPS and App ID/secret.

    docker compose exec app python manage.py avia_meta_check

Prints no secret. Exit code 1 when something blocks Meta OAuth.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.common.public_url import public_base_url
from apps.credentials.models import PlatformCredential
from apps.social_accounts.meta_connect import validate_meta_app


class Command(BaseCommand):
    help = "Comprueba HTTPS, callbacks y credenciales de Meta sin mostrar secretos."

    def add_arguments(self, parser):
        parser.add_argument("--offline", action="store_true", help="No contactar a Meta.")

    def handle(self, *args, **options):
        problems = 0
        base = public_base_url()
        if base:
            self.stdout.write(self.style.SUCCESS(f"✓ HTTPS público: {base}"))
        else:
            problems += 1
            self.stdout.write(
                self.style.ERROR(
                    f"✗ Sin HTTPS público (APP_URL={settings.APP_URL}). Define APP_URL=https://… y AVIA_HTTPS=true."
                )
            )
        origin = base or settings.APP_URL.rstrip("/")
        self.stdout.write("\nRegistra en Meta (coincidencia exacta):")
        for slug in ("facebook", "instagram", "instagram_login"):
            self.stdout.write(f"  {origin}/social-accounts/callback/{slug}/")

        for cred in PlatformCredential.objects.filter(platform__in=["facebook", "instagram", "instagram_login"]):
            c = cred.credentials or {}
            label = f"{cred.organization} · {cred.platform}"
            if not (c.get("client_id") and c.get("client_secret")):
                problems += 1
                self.stdout.write(self.style.ERROR(f"✗ {label}: faltan App ID o secreto"))
                continue
            if c.get("config_id"):
                self.stdout.write(self.style.WARNING(f"! {label}: config_id antiguo guardado (se ignora en 0.3)"))
            if cred.platform == "instagram_login" or options["offline"]:
                self.stdout.write(f"· {label}: App ID {c['client_id']} guardado")
                continue
            ok, msg = validate_meta_app(str(c["client_id"]), str(c["client_secret"]))
            problems += 0 if ok else 1
            self.stdout.write((self.style.SUCCESS if ok else self.style.ERROR)(f"{'✓' if ok else '✗'} {label}: {msg}"))

        if problems:
            self.stdout.write(self.style.ERROR(f"\n{problems} problema(s). Revisa docs/META-SETUP.md."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("\nTodo listo para conectar desde AVIA."))
