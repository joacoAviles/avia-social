"""AVIA 0.3 Meta connection diagnostics.

Turns the silent failures of the Meta OAuth flow into actionable Spanish
messages, the way Postiz checks ``/me/permissions`` right after the code
exchange. Nothing here logs or returns tokens, secrets or raw responses.
"""

from __future__ import annotations

import logging
import re

from providers.exceptions import ProviderError

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v25.0"

# Permissions without which the connection cannot work at all. Missing ones
# here stop the flow with an exact list instead of an empty picker.
ESSENTIAL_SCOPES: dict[str, tuple[str, ...]] = {
    "facebook": ("pages_show_list", "pages_manage_posts"),
    "instagram": ("instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement"),
}

META_PLATFORMS = frozenset({"facebook", "instagram"})


def user_token_permissions(provider, user_token: str) -> tuple[set[str], set[str]] | None:
    """Return ``(granted, declined)`` from ``/me/permissions`` for a *user* token."""
    try:
        data = provider._request("GET", f"{GRAPH}/me/permissions", access_token=user_token).json()
    except Exception:  # noqa: BLE001 - diagnostics must never break the connect flow
        logger.warning("Meta /me/permissions unavailable for %s", getattr(provider, "platform_name", "?"))
        return None
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return None  # unknown — never block a connection on a missing answer
    granted: set[str] = set()
    declined: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("permission")
        if not name:
            continue
        (granted if row.get("status") == "granted" else declined).add(name)
    return granted, declined


def missing_essentials(platform: str, granted: set[str]) -> list[str]:
    return [s for s in ESSENTIAL_SCOPES.get(platform, ()) if s not in granted]


def missing_permissions_message(platform: str, missing: list[str], declined: set[str]) -> str:
    names = ", ".join(missing)
    if any(m in declined for m in missing):
        return (
            f"Meta no concedió: {names}. En el diálogo se desmarcó algún permiso. "
            "Vuelve a pulsar Conectar y deja todos los permisos activados; si Meta no muestra el diálogo, "
            "elimina la app en Facebook → Configuración → Integraciones comerciales y repite."
        )
    return (
        f"Meta no concedió: {names}. Tu app de Meta no tiene esos permisos disponibles: en developers.facebook.com → "
        "tu app → Casos de uso, agrega «Administrar todo en tu página»"
        + (
            " y «Administrar mensajes y contenido en Instagram → Configuración de la API con inicio de sesión de Facebook»"
            if platform == "instagram"
            else ""
        )
        + " y pulsa «Agregar» en cada permiso. Luego vuelve a conectar."
    )


def empty_discovery_message(platform: str, granted: set[str] | None) -> str:
    if platform == "instagram":
        return (
            "Meta autorizó, pero ninguna página compartida tiene una cuenta de Instagram profesional vinculada. "
            "Revisa: 1) Instagram → Configuración → Tipo de cuenta: Empresa o Creador; "
            "2) Instagram está vinculado a una página de Facebook que tú administras (Meta Business Suite → Configuración → Cuentas de Instagram); "
            "3) en el diálogo de Meta, «Editar acceso» incluye esa página y esa cuenta. "
            "Alternativa sin página: usa «Instagram directo»."
        )
    hint = ""
    if granted is not None and "business_management" not in granted:
        hint = " Si la página pertenece a un portafolio comercial, concede también business_management."
    return (
        "Meta autorizó, pero no compartiste ninguna página. Vuelve a Conectar Facebook, pulsa «Editar acceso» "
        "y marca la página. Solo aparecen páginas donde tienes control total o tarea «Crear contenido»." + hint
    )


_HINTS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"redirect_uri|URL blocked|redirect URI", re.I),
        "La dirección de retorno no coincide. Copia exactamente el callback que muestra AVIA (https y barra final) en "
        "Meta → Inicio de sesión con Facebook para empresas → Configuración → URI de redireccionamiento de OAuth válidos.",
    ),
    (
        re.compile(r"client secret|Error validating client|Invalid client_secret|app secret", re.I),
        "El App Secret no corresponde al App ID. Cópialo de nuevo desde Meta → Configuración de la app → Básica.",
    ),
    (
        re.compile(r"Invalid platform app|Invalid app ID|invalid client_id", re.I),
        "El ID de app es incorrecto. Para «Instagram directo» usa el ID de app de Instagram (Casos de uso → Instagram → "
        "Configuración de la API con inicio de sesión de Instagram), no el App ID de Meta.",
    ),
    (
        re.compile(
            r"Insufficient developer role|not a test user|app is in development|not available|isn't available", re.I
        ),
        "La app está en modo desarrollo y esta cuenta no tiene rol. Agrégala en Meta → Roles de la app (Administrador, "
        "Desarrollador o Tester; para Instagram directo, «Instagram Tester») y acepta la invitación.",
    ),
    (
        re.compile(r"code has been used|authorization code has expired|code was already redeemed", re.I),
        "El código de autorización ya se usó o venció. Pulsa Conectar otra vez sin recargar la página de retorno.",
    ),
    (
        re.compile(r"Invalid Scopes?|invalid_scope", re.I),
        "La app no tiene habilitado alguno de los permisos pedidos. Agrega el caso de uso correspondiente en Meta o "
        "desactiva «Bandeja de mensajes» en la configuración Meta de AVIA.",
    ),
]


def explain_error(exc_or_text) -> str:
    """Spanish, actionable explanation for an OAuth/provider failure."""
    text = str(exc_or_text or "")
    raw = getattr(exc_or_text, "raw_response", None)
    if isinstance(raw, dict):
        err = raw.get("error")
        if isinstance(err, dict):
            text = f"{text} {err.get('message', '')} {err.get('error_user_msg', '')}"
        elif isinstance(err, str):
            text = f"{text} {err} {raw.get('error_description', '')}"
    for pattern, hint in _HINTS:
        if pattern.search(text):
            return hint
    detail = _safe_detail(text)
    return f"El proveedor rechazó la conexión: {detail}" if detail else "No se pudo conectar la cuenta."


def _safe_detail(text: str) -> str:
    text = re.sub(r"(access_token|code|client_secret)=[^&\s]+", r"\1=***", text)
    text = re.sub(r"\b[A-Za-z0-9_\-|]{60,}\b", "***", text)
    return " ".join(text.split())[:300]


def is_provider_error(exc: Exception) -> bool:
    return isinstance(exc, ProviderError)


def validate_meta_app(client_id: str, client_secret: str, *, http=None) -> tuple[bool, str]:
    """Check an App ID / App Secret pair with an app access token (no user involved)."""
    import httpx

    http = http or httpx
    try:
        resp = http.get(
            f"{GRAPH}/{client_id}",
            params={"fields": "id,name", "access_token": f"{client_id}|{client_secret}"},
            timeout=10,
        )
        data = resp.json()
    except Exception:  # noqa: BLE001
        return False, "No se pudo contactar a Meta. Revisa la salida a internet del contenedor."
    if "error" in data:
        return False, explain_error(data["error"].get("message", ""))
    if str(data.get("id")) != str(client_id):
        return False, "Meta respondió con otra app. Revisa el App ID."
    return True, f"Credenciales válidas para la app «{data.get('name', client_id)}»."
