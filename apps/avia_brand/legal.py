"""Public installation-specific legal information; never expose account data."""

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_safe


@require_safe
def terms(request):
    return page(request, "terms")


@require_safe
def privacy(request):
    return page(request, "privacy")


def page(request, document):
    return render(
        request,
        "avia_brand/legal.html",
        {
            "document": document,
            "operator": getattr(settings, "AVIA_LEGAL_OPERATOR", ""),
            "contact": getattr(settings, "AVIA_LEGAL_CONTACT_EMAIL", ""),
            "title": "Términos de servicio" if document == "terms" else "Política de privacidad",
        },
    )
