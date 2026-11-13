import importlib

from django.test import override_settings
from django.urls import clear_url_caches

import pytest

from gesec.front import urls


@pytest.fixture
def api_disabled():
    with override_settings(API_ENABLED=False):
        importlib.reload(urls)
        clear_url_caches()
        yield
    importlib.reload(urls)
    clear_url_caches()


@pytest.mark.django_db
def test_api_routes_return_404_when_disabled(client, api_disabled):
    assert client.get("/api/healthcheck").status_code == 404
    assert client.get("/api/meta-budat/").status_code == 404
    assert client.get("/api/meta-budat/schema/").status_code == 404
    assert client.get("/oauth/token/").status_code == 404
    assert client.get("/.well-known/oauth-protected-resource").status_code == 404


@pytest.mark.django_db
def test_api_routes_are_mounted_when_enabled(client):
    assert client.get("/api/healthcheck").status_code == 401
