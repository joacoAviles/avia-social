import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("url,title", [("/terms/", "Términos de servicio"), ("/privacy/", "Política de privacidad")])
@override_settings(AVIA_LEGAL_OPERATOR="Mi Empresa", AVIA_LEGAL_CONTACT_EMAIL="privacy@example.com")
def test_public_legal_pages(client, url, title):
    response = client.get(url)
    assert response.status_code == 200
    assert title in response.content.decode()
    assert b"Mi Empresa" in response.content
    assert b"privacy@example.com" in response.content
    assert client.head(url).status_code == 200
    assert client.post(url).status_code == 405


@override_settings(AVIA_LEGAL_OPERATOR="", AVIA_LEGAL_CONTACT_EMAIL="")
def test_missing_identity_is_not_invented(client):
    response = client.get("/privacy/")
    assert "pendiente de configuración" in response.content.decode()
    assert b'id="eliminacion"' in response.content
