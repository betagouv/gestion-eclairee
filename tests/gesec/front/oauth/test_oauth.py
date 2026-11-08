import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.test import Client

import pytest

from tests.gesec.front.oauth.helpers import (
    DATA_SCOPE,
    DEFAULT_REDIRECT_URI,
    make_access_token,
    make_application,
    make_mcp_user,
)


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@pytest.mark.django_db
def test_dcr_is_disabled(client):
    response = client.post(
        "/oauth/register/",
        data='{"client_name": "agent-test", "redirect_uris": ["http://127.0.0.1:8080/callback"]}',
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_authorization_server_metadata(client):
    response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    data = response.json()
    assert data["issuer"] == settings.PUBLIC_BASE_URL
    assert data["authorization_endpoint"] == f"{settings.PUBLIC_BASE_URL}/oauth/authorize/"
    assert data["token_endpoint"] == f"{settings.PUBLIC_BASE_URL}/oauth/token/"
    assert "registration_endpoint" not in data
    assert data["code_challenge_methods_supported"] == ["S256"]
    assert data["scopes_supported"] == [DATA_SCOPE]


@pytest.mark.django_db
def test_protected_resource_metadata(client):
    response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    data = response.json()
    assert data["resource"] == settings.MCP_PUBLIC_URL
    assert data["authorization_servers"] == [settings.PUBLIC_BASE_URL]


def authorize(client: Client, client_id: str, redirect_uri: str, code_challenge: str, method: str = "S256"):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": DATA_SCOPE,
        "state": "state-1",
        "code_challenge": code_challenge,
        "code_challenge_method": method,
    }
    get_response = client.get("/oauth/authorize/", params)
    post_data = {**params, "allow": "true"}
    post_response = client.post("/oauth/authorize/", post_data)
    return get_response, post_response


def exchange_code(client: Client, client_id: str, redirect_uri: str, code: str, verifier: str):
    return client.post(
        "/oauth/token/",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


@pytest.mark.django_db
def test_full_pkce_flow_grants_usable_access_token(client):
    user = make_mcp_user(email="agent@example.com")
    client.force_login(user)
    client_id = make_application(user=user).client_id
    verifier, challenge = pkce_pair()

    get_response, post_response = authorize(client, client_id, DEFAULT_REDIRECT_URI, challenge)

    assert get_response.status_code == 200
    assert post_response.status_code == 302
    assert post_response.url.startswith(DEFAULT_REDIRECT_URI)
    code = parse_qs(urlsplit(post_response.url).query)["code"][0]

    token_response = exchange_code(client, client_id, DEFAULT_REDIRECT_URI, code, verifier)

    assert token_response.status_code == 200
    access_token = token_response.json()["access_token"]
    assert token_response.json()["scope"] == DATA_SCOPE

    api_response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})
    assert api_response.status_code == 200
    assert api_response.json() == {"ok": True, "username": "agent@example.com"}


@pytest.mark.django_db
def test_agent_oauth_flow_end_to_end(client):
    """Flow théorique d'un agent MCP (type opencode), de bout en bout côté Django :
    discovery RFC 9728/8414 -> client pré-enregistré par l'admin -> authorize + PKCE
    S256 -> échange du code -> appel de l'API avec le Bearer."""
    user = make_mcp_user(email="agent@example.com")

    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == settings.MCP_PUBLIC_URL
    as_metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert as_metadata["issuer"] in prm["authorization_servers"]
    assert "registration_endpoint" not in as_metadata

    client.force_login(user)
    client_id = make_application(user=user).client_id

    verifier, challenge = pkce_pair()
    _, post_response = authorize(client, client_id, DEFAULT_REDIRECT_URI, challenge)
    code = parse_qs(urlsplit(post_response.url).query)["code"][0]

    token_response = exchange_code(client, client_id, DEFAULT_REDIRECT_URI, code, verifier)
    assert token_response.status_code == 200
    tokens = token_response.json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["scope"] == DATA_SCOPE
    assert tokens["refresh_token"]

    api_response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert api_response.status_code == 200
    assert api_response.json() == {"ok": True, "username": "agent@example.com"}


@pytest.mark.django_db
def test_authorize_requires_pkce(client):
    user = make_mcp_user()
    client.force_login(user)
    client_id = make_application(user=user).client_id

    response = client.get(
        "/oauth/authorize/",
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": DEFAULT_REDIRECT_URI,
            "scope": DATA_SCOPE,
        },
    )

    assert response.status_code == 302
    query = parse_qs(urlsplit(response.url).query)
    assert query["error"] == ["invalid_request"]
    assert "code" not in query


@pytest.mark.django_db
def test_authorize_rejects_plain_pkce(client):
    user = make_mcp_user()
    client.force_login(user)
    client_id = make_application(user=user).client_id
    verifier, _ = pkce_pair()

    _, post_response = authorize(client, client_id, DEFAULT_REDIRECT_URI, verifier, method="plain")

    assert post_response.status_code == 302
    query = parse_qs(urlsplit(post_response.url).query)
    assert query["error"] == ["invalid_request"]
    assert "code" not in query


@pytest.mark.django_db
def test_token_exchange_rejects_redirect_uri_mismatch(client):
    user = make_mcp_user()
    client.force_login(user)
    client_id = make_application(user=user).client_id
    verifier, challenge = pkce_pair()
    _, post_response = authorize(client, client_id, DEFAULT_REDIRECT_URI, challenge)
    code = parse_qs(urlsplit(post_response.url).query)["code"][0]

    response = exchange_code(client, client_id, "http://127.0.0.1:9999/other", code, verifier)

    assert response.status_code == 400
    assert response.json()["error"] in ("invalid_request", "invalid_grant")


@pytest.mark.django_db
def test_token_exchange_rejects_wrong_verifier(client):
    user = make_mcp_user()
    client.force_login(user)
    client_id = make_application(user=user).client_id
    verifier, challenge = pkce_pair()
    _, post_response = authorize(client, client_id, DEFAULT_REDIRECT_URI, challenge)
    code = parse_qs(urlsplit(post_response.url).query)["code"][0]

    response = exchange_code(client, client_id, DEFAULT_REDIRECT_URI, code, secrets.token_urlsafe(48))

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@pytest.mark.django_db
def test_api_accepts_token_bound_to_mcp_resource(client, settings):
    settings.PUBLIC_BASE_URL = "http://testserver"
    user = make_mcp_user()
    application = make_application(user=user)
    access_token = make_access_token(user, application=application, resource=[settings.MCP_PUBLIC_URL])

    response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200


@pytest.mark.django_db
def test_api_rejects_token_bound_to_other_resource(client, settings):
    settings.PUBLIC_BASE_URL = "http://testserver"
    user = make_mcp_user()
    application = make_application(user=user)
    access_token = make_access_token(user, application=application, resource=["https://autre-ressource.example"])

    response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 401


@pytest.mark.django_db
def test_rfc7009_revocation(client):
    user = make_mcp_user()
    application = make_application(user=user)
    access_token = make_access_token(user, application=application)

    assert client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"}).status_code == 200

    response = client.post("/oauth/revoke_token/", {"token": access_token, "client_id": application.client_id})

    assert response.status_code == 200
    assert client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"}).status_code == 401


@pytest.mark.django_db
def test_oauth_rate_limit_is_global_with_retry_after(client):
    from gesec.front.oauth import OAUTH_RATE_LIMIT, OAUTH_RATE_LIMIT_INTERVAL

    for _ in range(OAUTH_RATE_LIMIT):
        assert client.get("/oauth/authorize/").status_code != 429

    response = client.get("/oauth/authorize/")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(OAUTH_RATE_LIMIT_INTERVAL)
