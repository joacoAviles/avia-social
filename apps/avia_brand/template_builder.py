"""Generate a portable brand starter without writing to GitHub or storing secrets."""

import io
import json
import zipfile
from zoneinfo import available_timezones

import yaml
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.members.models import WorkspaceMembership


class TemplateForm(forms.Form):
    name = forms.CharField(label="Nombre de marca", max_length=100)
    tagline = forms.CharField(label="Frase de marca", max_length=200, required=False)
    description = forms.CharField(label="Qué hace tu marca", max_length=2000, widget=forms.Textarea)
    website = forms.URLField(label="Sitio web (opcional)", required=False, assume_scheme="https")
    language = forms.ChoiceField(label="Idioma", choices=[("es", "Español"), ("en", "English"), ("pt", "Português")])
    timezone = forms.ChoiceField(label="Zona horaria", choices=[(x, x) for x in sorted(available_timezones())])
    primary = forms.RegexField(r"\A#[0-9a-fA-F]{6}\Z", label="Color principal (#RRGGBB)")
    secondary = forms.RegexField(r"\A#[0-9a-fA-F]{6}\Z", label="Color secundario (#RRGGBB)")
    heading_font = forms.CharField(label="Tipografía de títulos", max_length=100)
    body_font = forms.CharField(label="Tipografía de textos", max_length=100)
    audience = forms.CharField(label="A quién te diriges", max_length=1500, widget=forms.Textarea)
    voice = forms.CharField(label="Cómo habla la marca", max_length=1500, widget=forms.Textarea)
    avoid = forms.CharField(label="Qué debe evitar", max_length=1500, required=False, widget=forms.Textarea)
    pillars = forms.CharField(label="Temas de contenido (uno por línea)", max_length=2000, widget=forms.Textarea)


def package(data):
    identity = {
        "schema_version": 1,
        "brand": {
            "name": data["name"],
            "tagline": data["tagline"],
            "description": data["description"],
            "website": data["website"],
            "language": data["language"],
            "timezone": data["timezone"],
        },
        "visual": {
            "colors": {"values": {"primary": data["primary"], "secondary": data["secondary"]}},
            "typography": {"heading": data["heading_font"], "body": data["body_font"]},
        },
        "voice": {"tone": data["voice"], "avoid": data["avoid"]},
        "audience": data["audience"],
        "content": {"pillars": [line.strip() for line in data["pillars"].splitlines() if line.strip()]},
        "assets": [],
    }
    manifest = yaml.safe_dump(identity, allow_unicode=True, sort_keys=False)
    files = {
        "brand/brand.yaml": manifest,
        "brand/content-templates.yaml": yaml.safe_dump(
            {
                "schema_version": 1,
                "templates": [
                    {
                        "name": "Presentación",
                        "text": "Conoce nuestra propuesta: [beneficio]. Más información: [enlace].",
                    },
                    {"name": "Educativo", "text": "[Consejo útil para nuestra audiencia]. [Ejemplo concreto]."},
                    {"name": "Novedad", "text": "Presentamos [novedad]. [Qué cambia para ti]. [Próximo paso]."},
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        "assets/README.md": "# Recursos oficiales\n\nAñade aquí logos, imágenes y tipografías con licencia. No se han generado ni copiado logos oficiales. Declara sus rutas y licencias en brand/brand.yaml si deseas documentarlas. No subas secretos ni archivos .env.\n",
        "README.md": "# " + data["name"] + "\n\nFuente de identidad para AVIA Social.\n\n"
        "1. Descomprime este paquete.\n2. Abre tu repositorio privado en GitHub → Code → Add file → Upload files.\n"
        "3. Sube las carpetas brand y assets a la raíz: debe quedar brand/brand.yaml, sin una carpeta contenedora extra.\n"
        "4. Revisa los cambios antes de confirmar el commit; si ya existe una identidad, compara y conserva sus recursos.\n"
        "5. En AVIA verifica el repositorio, sincroniza y aprueba la versión.\n\n"
        "El nombre y colores se aplican al espacio al aprobar. Tipografías, tono, audiencia y plantillas se guardan en el catálogo; no implican aplicación automática al editor o generación de contenido. No incluyen archivos de fuentes ni licencias.\n",
        ".gitignore": ".env\n.env.*\nsecrets/\n*.pem\n*.key\n.DS_Store\n",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return manifest, output.getvalue(), json.dumps(identity, ensure_ascii=False, indent=2)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def builder(request, workspace_id):
    membership = get_object_or_404(
        WorkspaceMembership.objects.select_related("workspace"),
        user=request.user,
        workspace_id=workspace_id,
        workspace__is_archived=False,
    )
    if not membership.effective_permissions.get("manage_workspace_settings"):
        raise PermissionDenied
    workspace = membership.workspace
    form = TemplateForm(
        request.POST if request.method == "POST" else None,
        initial={
            "name": workspace.name,
            "language": "es",
            "timezone": workspace.timezone or "UTC",
            "primary": workspace.primary_color or "#334155",
            "secondary": workspace.secondary_color or "#64748B",
            "heading_font": "Inter",
            "body_font": "Inter",
        },
    )
    preview = ""
    if request.method == "POST" and form.is_valid():
        preview, archive, _ = package(form.cleaned_data)
        if request.POST.get("action") == "download":
            response = HttpResponse(archive, content_type="application/zip")
            response["Content-Disposition"] = 'attachment; filename="avia-brand-template.zip"'
            response["X-Content-Type-Options"] = "nosniff"
            return response
    return render(
        request, "avia_brand/template_builder.html", {"workspace": workspace, "form": form, "preview": preview}
    )
