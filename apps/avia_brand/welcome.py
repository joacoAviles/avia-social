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
    step = request.GET.get("step", "brand")
    if step not in {"brand", "connections", "ready"}:
        step = "brand"
    form = BrandForm(initial={"name": workspace.name, "timezone": workspace.timezone or "UTC"})
    credential_form = CredentialForm()
    github_form = GitHubForm()
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
                if platform not in {
                    "youtube",
                    "tiktok",
                    "instagram_login",
                    "facebook",
                    "google_login",
                    "google_calendar",
                }:
                    return HttpResponse(status=400)
                if platform in {"google_login", "google_calendar"} and not request.user.is_superuser:
                    raise PermissionDenied
                credential_form = CredentialForm(request.POST)
                if platform in {"instagram_login", "facebook"}:
                    credential_form.is_valid()
                    flow = request.POST.get("meta_flow", "")
                    expected = "instagram_legacy" if platform == "instagram_login" else "facebook_user"
                    if flow != expected:
                        credential_form.add_error(
                            "meta_flow",
                            "Esta versión no admite Unified Login/SUAT. No guardamos ni reemplazamos tus credenciales. Selecciona el flujo compatible solo si coincide con la configuración real de Meta.",
                        )
                if credential_form.is_valid():
                    values = dict(credential_form.cleaned_data)
                    config_id = values.pop("config_id", "")
                    values.pop("meta_flow", None)
                    if platform == "facebook" and config_id:
                        values["config_id"] = config_id
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
                    return redirect(reverse("welcome:journey", args=[workspace.id]) + "?step=connections")
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
            "instagram_login",
            "Instagram directo",
            "Conecta una cuenta profesional de Instagram sin vincular Facebook.",
            "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/",
        ),
        (
            "facebook",
            "Facebook",
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
        accounts = list(workspace.social_accounts.filter(platform=platform).values("account_name", "connection_status"))
        stored_credential = PlatformCredential.objects.filter(
            organization=workspace.organization, platform=platform
        ).first()
        cards.append(
            {
                "platform": platform,
                "config_id": (
                    stored_credential.credentials.get("config_id", "")
                    if stored_credential and platform == "facebook"
                    else ""
                ),
                "title": title,
                "description": description,
                "guide": guide,
                "configured": platform in configured,
                "accounts": accounts,
                "callback": request.build_absolute_uri(
                    reverse("social_accounts:oauth_callback", kwargs={"platform": to_url_slug(platform)})
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
            "error": error,
            "workspace": workspace,
            "cards": cards,
            "google_configured": google_configured,
            "calendar_configured": bool(state and state.calendar_credentials),
            "calendar_connection": CalendarConnection.objects.filter(user=request.user, workspace=workspace).first(),
            "calendar_callback": callback_url(request, workspace.id),
            "google_connected": SocialAccount.objects.filter(user=request.user, provider="google").exists(),
            "google_callback": request.build_absolute_uri("/accounts/google/login/callback/"),
            "github_source": BrandSource.objects.filter(workspace=workspace).first(),
            "publishing_enabled": getattr(settings, "AVIA_PUBLISH_ENABLED", False),
        },
    )
