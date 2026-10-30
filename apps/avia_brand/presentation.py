"""Display-only brand tokens. Private source data is never copied into static assets."""

import hashlib
import json
import re
from pathlib import Path

import yaml
from django.conf import settings

REPOSITORY = "joacoAviles/avia-rockets-brand"
HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")


def private_identity():
    path = Path(getattr(settings, "AVIA_UI_BRAND_FILE", "/run/secrets/avia/ui-brand.json"))
    try:
        if path.stat().st_size > 131072:
            return None
        data = json.loads(path.read_text())
        if data.get("repository") != REPOSITORY or not re.fullmatch(r"[0-9a-f]{40}", data.get("commit", "")):
            return None
        raw = data["manifest"].encode()
        if (
            len(raw) > 65536
            or hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != data["blob_sha"]
        ):
            return None
        if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(raw)):
            return None
        identity = yaml.safe_load(raw)
        if not isinstance(identity, dict) or identity.get("schema_version") != 1:
            return None
        return identity
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, yaml.YAMLError):
        return None


def color(value):
    return value if isinstance(value, str) and HEX.fullmatch(value) else None


def mix(hex_color, target, amount):
    a = [int(hex_color[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(target[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * (1 - amount) + y * amount):02x}" for x, y in zip(a, b, strict=True))


def tokens(identity):
    try:
        palette = identity["visual"]["colors"]["values"]
        accent, navy, white, gray = [color(palette.get(k)) for k in ("blue", "navy", "white", "gray")]
        if not all((accent, navy, white, gray)):
            return []
        values = {
            "--brand-500": accent,
            "--brand-600": mix(accent, navy, 0.22),
            "--brand-700": mix(accent, navy, 0.42),
            "--brand-800": mix(accent, navy, 0.62),
            "--brand-900": navy,
            "--avia-navy": navy,
            "--avia-muted": gray,
            "--surface-0": white,
            "--brand-font-body": "'Inter', system-ui, sans-serif",
        }
        for level, amount in [(50, 0.96), (100, 0.91), (200, 0.8), (300, 0.6), (400, 0.3)]:
            values[f"--brand-{level}"] = mix(accent, white, amount)
        font = identity["visual"].get("typography", {}).get("display", "")
        if font in {"Orbitron", "Orbitron Bold"}:
            values["--brand-font-display"] = "'Orbitron', 'Inter', sans-serif"
        return list(values.items())
    except (KeyError, TypeError, AttributeError):
        return []


def ui_brand(request):
    identity = None
    # Reviewed database revisions take precedence. No workspace identity is mutated.
    from django.db import OperationalError, ProgrammingError

    from .models import BrandSource

    try:
        source = BrandSource.objects.filter(repository=REPOSITORY).select_related("active_revision").first()
        if source and source.active_revision_id and source.active_revision.state == "approved":
            identity = source.active_revision.identity
    except (OperationalError, ProgrammingError):
        pass  # collectstatic / migrations before the schema exists
    values = tokens(identity or private_identity() or {})
    from .models import InstallationSetup

    google_configured = bool(settings.GOOGLE_AUTH_CLIENT_ID and settings.GOOGLE_AUTH_CLIENT_SECRET)
    try:
        state = InstallationSetup.objects.filter(pk=1).first()
        google_configured = google_configured or bool(state and state.google_credentials)
    except (OperationalError, ProgrammingError):
        pass
    return {"avia_ui_tokens": values, "avia_ui_configured": bool(values), "avia_google_configured": google_configured}
