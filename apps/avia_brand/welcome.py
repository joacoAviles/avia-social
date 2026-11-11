"""Self-hosted first-run journey. No external write or live publish is performed here."""

import hashlib
import hmac
from zoneinfo import available_timezones

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.common.public_url import public_base_url, public_url
from apps.credentials.models import PlatformCredential
from apps.members.models import WorkspaceMembership
from apps.social_accounts.oauth_aliases import to_url_slug
from apps.social_accounts.views import _get_configured_platforms

from .models import BrandSource, InstallationSetup, WelcomeProgress
from .services import GitHubReader, SyncError


class SetupForm(forms.Form):
    code = forms.CharField(label="Código de instalación", widget=forms.PasswordInput, max_length=100)
    name = forms.CharField(label="Tu nombre", max_length=100)
    email = forms.EmailField(label="Correo electrónico")
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput, max_length=128)
    confirm = forms.CharField(label="Repite la contraseña", widget=forms.PasswordInput, max_length=128)
    acknowledge = forms.BooleanField(label="Entiendo que esta instancia y sus datos están bajo mi administración.")

    def clean(self):
        data = super().clean()
        if data.get("password") != data.get("confirm"):
            self.add_error("confirm", "Las contraseñas no coinciden.")
        if data.get("password"):
            validate_password(
                data["password"], get_user_model()(email=data.get("email", ""), name=data.get("name", ""))
            )
        return data


class BrandForm(forms.Form):
    name = forms.CharField(label="Nombre de tu marca", max_length=100)
    timezone = forms.ChoiceField(label="Zona horaria", choices=[(x, x) for x in sorted(available_timezones())])


class CredentialForm(forms.Form):
    subreddit = forms.RegexField(r"\A[A-Za-z0-9_]{2,30}\Z", required=False, max_length=30)
    reddit_username = forms.RegexField(r"\A[A-Za-z0-9_-]{3,30}\Z", required=False, max_length=30)
    client_id = forms.CharField(label="Client ID / Client key", max_length=500)
    client_secret = forms.CharField(label="Client secret", widget=forms.PasswordInput, max_length=2000)
    config_id = forms.RegexField(r"\A[0-9]{1,100}\Z", label="Configuration ID (config_id)", required=False)
    meta_flow = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Selecciona el flujo"),
            ("instagram_legacy", "Instagram Login anterior"),
            ("facebook_user", "Facebook Pages · token de usuario"),
            ("unified_suat", "Unified Login · token de usuario del sistema"),
        ],
    )


class MetaAppForm(forms.Form):
    """AVIA 0.3: one Meta app powers Facebook Pages and Instagram vía Facebook;
    the optional Instagram app (same Meta app, Instagram-login use case) powers
    Instagram directo. Classic login only — no config_id, no Unified/SUAT."""

    meta_app_id = forms.RegexField(r"\A[0-9]{5,30}\Z", label="Meta App ID", required=False)
    meta_app_secret = forms.CharField(
        label="Meta App Secret", widget=forms.PasswordInput, max_length=200, required=False
    )
    instagram_app_id = forms.RegexField(r"\A[0-9]{5,30}\Z", label="Instagram App ID", required=False)
    instagram_app_secret = forms.CharField(
        label="Instagram App Secret", widget=forms.PasswordInput, max_length=200, required=False
    )
    inbox_scopes_enabled = forms.BooleanField(label="Pedir permisos de bandeja de mensajes", required=False)

    def __init__(self, *args, stored=None, **kwargs):
        # ``stored`` = {"meta": (id, secret), "ig": (id, secret)} so an admin can
        # change the inbox toggle without retyping a secret Meta never shows twice.
        self.stored = stored or {}
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        for prefix, key in (("meta_app", "meta"), ("instagram_app", "ig")):
            stored_id, stored_secret = self.stored.get(key, ("", ""))
            if data.get(f"{prefix}_id") and not data.get(f"{prefix}_secret") and str(stored_id) == data[f"{prefix}_id"]:
                data[f"{prefix}_secret"] = stored_secret
        meta = (data.get("meta_app_id"), data.get("meta_app_secret"))
        ig = (data.get("instagram_app_id"), data.get("instagram_app_secret"))
        if any(meta) and not all(meta):
            self.add_error("meta_app_secret" if meta[0] else "meta_app_id", "Completa el par App ID / App Secret.")
        if any(ig) and not all(ig):
            self.add_error(
                "instagram_app_secret" if ig[0] else "instagram_app_id", "Completa el par Instagram App ID / Secret."
            )
        if not any(meta) and not any(ig):
            raise forms.ValidationError("Ingresa al menos la app de Meta o la app de Instagram.")
        if all(meta) and all(ig) and meta[0] == ig[0]:
            self.add_error(
                "instagram_app_id",
                "Es el mismo número que el Meta App ID. El Instagram App ID está en Casos de uso → Instagram → "
                "Configuración de la API con inicio de sesión de Instagram.",
            )
        return data


META_PLATFORMS = {"facebook", "instagram", "instagram_login", "instagram_unified"}


def save_meta_credentials(organization, data) -> list[str]:
    """Persist the Meta wizard. Existing secrets are replaced only for the pairs submitted."""
    saved = []
    if data.get("meta_app_id") and data.get("meta_app_secret"):
        for platform in ("facebook", "instagram"):
            existing = PlatformCredential.objects.filter(organization=organization, platform=platform).first()
            creds = dict(existing.credentials) if existing else {}
            creds.pop("config_id", None)
            creds.update(
                client_id=data["meta_app_id"],
                client_secret=data["meta_app_secret"],
                inbox_scopes_enabled=bool(data.get("inbox_scopes_enabled")),
            )
            if platform == "instagram":
                creds["dm_oauth_scopes_enabled"] = bool(data.get("inbox_scopes_enabled"))
            PlatformCredential.objects.update_or_create(
                organization=organization, platform=platform, defaults={"credentials": creds}
            )
            saved.append(platform)
    if data.get("instagram_app_id") and data.get("instagram_app_secret"):
        existing = PlatformCredential.objects.filter(organization=organization, platform="instagram_login").first()
        creds = dict(existing.credentials) if existing else {}
        creds.update(client_id=data["instagram_app_id"], client_secret=data["instagram_app_secret"])
        PlatformCredential.objects.update_or_create(
            organization=organization, platform="instagram_login", defaults={"credentials": creds}
        )
        saved.append("instagram_login")
    return saved


class GitHubForm(forms.Form):
    repository = forms.RegexField(
        r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,59}\Z",
        label="Repositorio (propietario/nombre)",
        max_length=100,
    )
    token = forms.CharField(label="Token de lectura", widget=forms.PasswordInput, max_length=2000)
    readonly = forms.BooleanField(label="He limitado este token a lectura del repositorio indicado.")


def local_or_secure(request):
    return request.is_secure() or request.get_host().split(":")[0] in {"localhost", "127.0.0.1", "[::1]"}


def entry(request):
    state = InstallationSetup.objects.filter(pk=1).first()
    if not get_user_model().objects.exists() and not (state and state.claimed_at):
        return redirect("welcome:setup")
    from apps.accounts.views import dashboard

    return dashboard(request)


@never_cache
@sensitive_post_parameters()
@ratelimit(key="ip", rate="10/m", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def setup(request):
    state = InstallationSetup.objects.filter(pk=1).first()
    if get_user_model().objects.exists() or (state and state.claimed_at):
        return redirect("accounts:account_login")
    form = SetupForm(request.POST or None)
    if request.method == "POST" and not local_or_secure(request):
        return HttpResponse("Usa HTTPS o localhost para configurar la instalación.", status=400)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            state = InstallationSetup.objects.select_for_update().filter(pk=1).first()
            if (
                state
                and not state.claimed_at
                and not get_user_model().objects.exists()
                and state.expires_at
                and state.expires_at > timezone.now()
                and hmac.compare_digest(
                    state.token_hash, hashlib.sha256(form.cleaned_data["code"].encode()).hexdigest()
                )
            ):
                user = get_user_model().objects.create_superuser(
                    email=form.cleaned_data["email"],
                    name=form.cleaned_data["name"],
                    password=form.cleaned_data["password"],
                    tos_accepted_at=timezone.now(),
                )
                state.claimed_at = timezone.now()
                state.token_hash = ""
                state.expires_at = None
                state.save(update_fields=["claimed_at", "token_hash", "expires_at"])
                WelcomeProgress.objects.create(workspace_id=user.last_workspace_id)
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                return redirect("welcome:journey", workspace_id=user.last_workspace_id)
        form.add_error("code", "Código inválido, vencido o ya utilizado. Genera otro desde tu Docker.")
    return render(request, "avia_brand/setup.html", {"form": form})


@login_required
@ratelimit(key="user", rate="20/m", method="POST", block=True)
@never_cache
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def journey(request, workspace_id):
    membership = get_object_or_404(
        WorkspaceMembership.objects.select_related("workspace__organization"),
        user=request.user,
        workspace_id=workspace_id,
        workspace__is_archived=False,
    )
    if not membership.effective_permissions.get("manage_workspace_settings"):
        raise PermissionDenied
    workspace = membership.workspace
    can_configure = bool(
        request.org_membership
        and request.org_membership.org_role in {"owner", "admin"}
        and membership.effective_permissions.get("manage_social_accounts")
    )
    setup_provider = request.GET.get("configure", "")
    if setup_provider and (
        not can_configure or (setup_provider in {"google_login", "google_calendar"} and not request.user.is_superuser)
    ):
        raise PermissionDenied
    if setup_provider in META_PLATFORMS:
        setup_provider = "meta"
    step = request.GET.get("step", "brand")
    if step not in {"brand", "connections", "ready"}:
        step = "brand"
    form = BrandForm(initial={"name": workspace.name, "timezone": workspace.timezone or "UTC"})
    credential_form = CredentialForm()
    github_form = GitHubForm()
    meta_form = MetaAppForm()
    meta_test_result = None
    error = ""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "brand":
            form = BrandForm(request.POST)
            if form.is_valid():
                workspace.name = form.cleaned_data["name"]
                workspace.timezone = form.cleaned_data["timezone"]
                workspace.save(update_fields=["name", "timezone"])
                WelcomeProgress.objects.get_or_create(workspace=workspace)
                return redirect(reverse("welcome:journey", args=[workspace.id]) + "?step=connections")
        elif action in {"meta", "meta_test"}:
            if not local_or_secure(request):
                return HttpResponse("Usa HTTPS o localhost para guardar credenciales.", status=400)
            if not can_configure:
                raise PermissionDenied
            step, setup_provider = "connections", "meta"
            if action == "meta_test":
                from apps.social_accounts.meta_connect import validate_meta_app

                stored = PlatformCredential.objects.filter(
                    organization=workspace.organization, platform="facebook"
                ).first()
                creds = stored.credentials if stored else {}
                if creds.get("client_id") and creds.get("client_secret"):
                    meta_test_result = validate_meta_app(str(creds["client_id"]), str(creds["client_secret"]))
                else:
                    meta_test_result = (False, "Primero guarda el Meta App ID y su secreto.")
            else:
                stored = {
                    key: (c.credentials.get("client_id", ""), c.credentials.get("client_secret", ""))
                    for key, c in (
                        (
                            "meta",
                            PlatformCredential.objects.filter(
                                organization=workspace.organization, platform="facebook"
                            ).first(),
                        ),
                        (
                            "ig",
                            PlatformCredential.objects.filter(
                                organization=workspace.organization, platform="instagram_login"
                            ).first(),
                        ),
                    )
                    if c
                }
                meta_form = MetaAppForm(request.POST, stored=stored)
                if meta_form.is_valid():
                    saved = save_meta_credentials(workspace.organization, meta_form.cleaned_data)
                    messages.success(
                        request,
                        "Meta configurado ("
                        + ", ".join(saved)
                        + "). Pulsa «Probar credenciales» y luego Conectar en cada canal.",
                    )
                    return redirect(
                        reverse("welcome:journey", args=[workspace.id]) + "?step=connections&configure=meta"
                    )
        elif action in {"credentials", "github"}:
            if not local_or_secure(request):
                return HttpResponse("Usa HTTPS o localhost para guardar credenciales.", status=400)
            if (
                not request.org_membership
                or request.org_membership.org_role not in {"owner", "admin"}
                or not membership.effective_permissions.get("manage_social_accounts")
            ):
                raise PermissionDenied
            if action == "credentials":
                platform = request.POST.get("platform")
                # A form submitted without its query string must still show its errors.
                step = "connections"
                setup_provider = platform
                if platform not in {
                    "linkedin_personal",
                    "linkedin_company",
                    "x",
                    "reddit",
                    "youtube",
                    "tiktok",
                    "google_login",
                    "google_calendar",
                }:
                    return HttpResponse(status=400)
                if platform in {"google_login", "google_calendar"} and not request.user.is_superuser:
                    raise PermissionDenied
                credential_form = CredentialForm(request.POST)
                if platform == "reddit":
                    credential_form.is_valid()
                    for field in ("subreddit", "reddit_username"):
                        if not credential_form.cleaned_data.get(field):
                            credential_form.add_error(field, "Obligatorio para configurar Reddit.")
                if credential_form.is_valid():
                    values = dict(credential_form.cleaned_data)
                    subreddit = values.pop("subreddit", "")
                    reddit_username = values.pop("reddit_username", "")
                    if platform == "reddit":
                        values.update(subreddit=subreddit, user_agent=f"web:avia-social:0.1 (by /u/{reddit_username})")
                    values.pop("config_id", None)
                    values.pop("meta_flow", None)
                    if platform in {"google_login", "google_calendar"}:
                        state, _ = InstallationSetup.objects.get_or_create(pk=1)
                        field = "calendar_credentials" if platform == "google_calendar" else "google_credentials"
                        setattr(state, field, values)
                        state.save(update_fields=[field])
                    else:
                        if platform == "tiktok":
                            values["client_key"] = values.pop("client_id")
                        PlatformCredential.objects.update_or_create(
                            organization=workspace.organization, platform=platform, defaults={"credentials": values}
                        )
                    messages.success(request, "Credenciales guardadas. Falta autorizar la conexión con el proveedor.")
                    return redirect(
                        reverse("welcome:journey", args=[workspace.id])
                        + "?step=connections&configure="
                        + platform
                        + "&saved=1"
                    )
            else:
                github_form = GitHubForm(request.POST)
                if github_form.is_valid():
                    data = github_form.cleaned_data
                    try:
                        metadata = GitHubReader(data["repository"], data["token"]).get("")
                        branch = metadata.get("default_branch")
                        if (
                            not isinstance(branch, str)
                            or not 1 <= len(branch) <= 255
                            or metadata.get("full_name", "").lower() != data["repository"].lower()
                        ):
                            raise SyncError("Respuesta de repositorio no válida")
                        with transaction.atomic():
                            # Never reassign reviewed history to a different repository.
                            source = BrandSource.objects.select_for_update().filter(workspace=workspace).first()
                            if source and source.repository.lower() != data["repository"].lower():
                                raise SyncError(
                                    "Esta marca ya tiene otra fuente. Conserva su historial; crea otra marca para otra fuente."
                                )
                            BrandSource.objects.update_or_create(
                                workspace=workspace,
                                defaults={
                                    "repository": metadata["full_name"],
                                    "github_token": data["token"],
                                    "branch": branch,
                                },
                            )
                        messages.success(
                            request,
                            "Acceso a GitHub verificado. Sincroniza el catálogo y aprueba la identidad cuando esté lista.",
                        )
                        return redirect(reverse("welcome:journey", args=[workspace.id]) + "?step=connections")
                    except (SyncError, IntegrityError):
                        error = "No se pudo vincular el repositorio. Revisa el nombre, el acceso de lectura y que no esté asignado a otra marca."
            step = "connections"
            setup_provider = request.POST.get("platform", "github")
        elif action == "finish":
            WelcomeProgress.objects.update_or_create(workspace=workspace, defaults={"completed_at": timezone.now()})
            return redirect("calendar:calendar", workspace_id=workspace.id)
        else:
            return HttpResponse(status=400)
    configured = _get_configured_platforms(workspace.organization_id)
    cards = []
    for platform, title, description, guide in [
        (
            "linkedin_personal",
            "LinkedIn Personal",
            "Publica en tu perfil profesional.",
            "https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin",
        ),
        (
            "linkedin_company",
            "LinkedIn Company Page",
            "Conecta las páginas de empresa que administras.",
            "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview",
        ),
        (
            "x",
            "X / Twitter",
            "Conecta tu cuenta. Esta versión admite publicaciones de texto.",
            "https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code",
        ),
        (
            "reddit",
            "Reddit",
            "Texto en la comunidad configurada; requiere acceso aprobado a Data API.",
            "https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data",
        ),
        (
            "instagram_login",
            "Instagram directo",
            "Conecta una cuenta profesional de Instagram sin vincular Facebook.",
            "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/",
        ),
        (
            "instagram",
            "Instagram vía Facebook",
            "Publica, responde comentarios y lee métricas de cuentas profesionales vinculadas a tus páginas.",
            "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/",
        ),
        (
            "facebook",
            "Facebook Pages",
            "Conecta las páginas que administras. No requiere conectar Instagram.",
            "https://developers.facebook.com/docs/pages-api/getting-started/",
        ),
        (
            "youtube",
            "YouTube",
            "Conecta tu canal para preparar videos y publicaciones.",
            "https://developers.google.com/youtube/v3/guides/auth/server-side-web-apps",
        ),
        (
            "tiktok",
            "TikTok",
            "Autoriza la cuenta que usarás para tus videos.",
            "https://developers.tiktok.com/doc/login-kit-web/",
        ),
    ]:
        accounts = list(
            workspace.social_accounts.filter(platform=platform).values(
                "account_name", "account_handle", "account_platform_id", "connection_status"
            )
        )
        cards.append(
            {
                "platform": platform,
                "title": title,
                "description": description,
                "guide": guide,
                "configured": platform in configured,
                "accounts": accounts,
                "needs_attention": any(a["connection_status"] != "connected" for a in accounts),
                "callback": public_url(
                    request, reverse("social_accounts:oauth_callback", kwargs={"platform": to_url_slug(platform)})
                ),
            }
        )
    state = InstallationSetup.objects.filter(pk=1).first()
    google_configured = bool(
        (state and state.google_credentials) or (settings.GOOGLE_AUTH_CLIENT_ID and settings.GOOGLE_AUTH_CLIENT_SECRET)
    )
    from allauth.socialaccount.models import SocialAccount

    from .google_calendar import callback_url
    from .models import CalendarConnection

    return render(
        request,
        "avia_brand/welcome.html",
        {
            "step": step,
            "can_configure": can_configure,
            "setup_provider": setup_provider,
            "welcome_active": True,
            "form": form,
            "credential_form": credential_form,
            "github_form": github_form,
            "meta_form": meta_form,
            "meta_test_result": meta_test_result,
            "meta": _meta_context(request, workspace),
            "error": error,
            "workspace": workspace,
            "cards": cards,
            "has_social_accounts": any(card["accounts"] for card in cards),
            "has_available_channels": any(not card["accounts"] for card in cards),
            "google_configured": google_configured,
            "calendar_configured": bool(state and state.calendar_credentials),
            "calendar_connection": CalendarConnection.objects.filter(user=request.user, workspace=workspace).first(),
            "calendar_callback": callback_url(request, workspace.id),
            "public_origin": public_url(request, "/").rstrip("/"),
            "google_connected": SocialAccount.objects.filter(user=request.user, provider="google").exists(),
            "google_callback": request.build_absolute_uri("/accounts/google/login/callback/"),
            "github_source": BrandSource.objects.filter(workspace=workspace).first(),
            "publishing_enabled": getattr(settings, "AVIA_PUBLISH_ENABLED", False),
        },
    )


def _meta_context(request, workspace):
    """Everything the Meta wizard shows: exact callbacks and what is configured."""
    creds = {
        c.platform: c.credentials
        for c in PlatformCredential.objects.filter(
            organization=workspace.organization, platform__in=["facebook", "instagram", "instagram_login"]
        )
    }

    def cb(platform):
        return public_url(
            request, reverse("social_accounts:oauth_callback", kwargs={"platform": to_url_slug(platform)})
        )

    fb = creds.get("facebook", {})
    return {
        "callbacks": {
            "facebook": cb("facebook"),
            "instagram": cb("instagram"),
            "instagram_login": cb("instagram_login"),
        },
        "origin": public_url(request, "/").rstrip("/"),
        "https_ok": bool(public_base_url()) or request.is_secure(),
        "meta_app_id": str(fb.get("client_id", "")),
        "meta_configured": bool(fb.get("client_id") and fb.get("client_secret")),
        "instagram_configured": bool(creds.get("instagram_login", {}).get("client_id")),
        "instagram_app_id": str(creds.get("instagram_login", {}).get("client_id", "")),
        "inbox_enabled": bool(fb.get("inbox_scopes_enabled")),
        "has_legacy_config_id": any(c.get("config_id") for c in creds.values()),
    }
