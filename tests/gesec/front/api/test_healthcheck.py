import pytest

from tests.gesec.front.oauth.helpers import make_access_token, make_application, make_mcp_user


@pytest.mark.django_db
def test_healthcheck_success(client):
    user = make_mcp_user(email="agent@example.com")
    access_token = make_access_token(user)

    response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "username": "agent@example.com"}


@pytest.mark.django_db
def test_healthcheck_does_not_check_scope(client):
    user = make_mcp_user()
    access_token = make_access_token(user, scope="read")

    response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200


@pytest.mark.django_db
def test_healthcheck_requires_authorization(client):
    response = client.get("/api/healthcheck")

    assert response.status_code == 401
    assert "resource_metadata" in response.headers["WWW-Authenticate"]


@pytest.mark.django_db
def test_healthcheck_rejects_unknown_token(client):
    response = client.get("/api/healthcheck", headers={"Authorization": "Bearer unknown-token"})

    assert response.status_code == 401


@pytest.mark.django_db
def test_healthcheck_rejects_inactive_user(client):
    user = make_mcp_user(is_active=False)
    access_token = make_access_token(user)

    response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 401


@pytest.mark.django_db
def test_healthcheck_rejects_expired_token(client):
    user = make_mcp_user()
    access_token = make_access_token(user, expires_in=-10)

    response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 401


@pytest.mark.django_db
def test_healthcheck_rejects_revoked_token(client):
    user = make_mcp_user()
    application = make_application(user=user)
    access_token = make_access_token(user, application=application)
    client.post("/oauth/revoke_token/", {"token": access_token, "client_id": application.client_id})

    response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 401
