import re

from django.urls import NoReverseMatch, URLPattern, URLResolver, reverse

import pytest
from oauth2_provider.urls import urlpatterns as oauth2_provider_urlpatterns

from gesec.front import urls as front_urls
from gesec.front.urls import OAUTH2_EXPOSED_ROUTES

REMOVED_OAUTH2_ROUTES = {
    "oauth-server-metadata",
    "oauth-server-metadata-issuer",
    "oauth-resource-metadata",
    "oauth-resource-metadata-path",
    "introspect",
    "device-authorization",
    "device",
    "device-confirm",
    "device-grant-status",
    "list",
    "register",
    "detail",
    "delete",
    "update",
    "authorized-token-list",
    "authorized-token-delete",
    "oidc-connect-discovery-info",
    "jwks-info",
    "user-info",
    "rp-initiated-logout",
    "dcr-register",
    "dcr-register-management",
}


def test_removed_oauth2_routes_exist_in_oauth2_provider_urls():
    dot_names = {pattern.name for pattern in oauth2_provider_urlpatterns if pattern.name}
    assert not REMOVED_OAUTH2_ROUTES & OAUTH2_EXPOSED_ROUTES
    assert dot_names == REMOVED_OAUTH2_ROUTES | OAUTH2_EXPOSED_ROUTES


@pytest.mark.django_db
def test_removed_oauth2_routes_are_not_mounted(client):
    for name in REMOVED_OAUTH2_ROUTES:
        with pytest.raises(NoReverseMatch):
            reverse(f"oauth2_provider:{name}")


def oauth_prefix() -> str:
    for pattern in front_urls.urlpatterns:
        if isinstance(pattern, URLResolver) and pattern.namespace == "oauth2_provider":
            return str(pattern.pattern)
    raise AssertionError("le namespace oauth2_provider n'est pas monté dans gesec.front.urls")


@pytest.mark.django_db
def test_removed_oauth2_routes_return_404_under_oauth_prefix(client):
    prefix = oauth_prefix()
    assert prefix
    for pattern in oauth2_provider_urlpatterns:
        if not isinstance(pattern, URLPattern) or pattern.name not in REMOVED_OAUTH2_ROUTES:
            continue
        route = re.sub(r"<[^>]+>", "1", str(pattern.pattern))
        response = client.get(f"/{prefix}{route}")
        assert response.status_code == 404, route
        response = client.post(f"/{prefix}{route}")
        assert response.status_code == 404, route
