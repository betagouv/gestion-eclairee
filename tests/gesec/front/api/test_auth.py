import logging

import pytest

from tests.gesec.front.oauth.helpers import make_access_token, make_application, make_mcp_user


@pytest.mark.django_db
def test_api_request_and_user_are_logged(client, caplog):
    user = make_mcp_user(email="agent@example.com")
    application = make_application(user=user)
    access_token = make_access_token(user, application=application)

    with caplog.at_level(logging.INFO, logger="gesec.front.api.auth"):
        response = client.get("/api/healthcheck", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    records = [r for r in caplog.records if r.name == "gesec.front.api.auth" and r.levelno == logging.INFO]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "GET /api/healthcheck" in message
    assert f"user={user.pk}" in message
    assert "agent@example.com" in message
    assert application.client_id in message
    assert access_token not in caplog.text


@pytest.mark.django_db
def test_api_failed_auth_is_logged(client, caplog):
    with caplog.at_level(logging.WARNING, logger="gesec.front.api.auth"):
        response = client.get("/api/healthcheck", headers={"Authorization": "Bearer unknown-token"})

    assert response.status_code == 401
    records = [r for r in caplog.records if r.name == "gesec.front.api.auth" and r.levelno == logging.WARNING]
    assert len(records) == 1
    assert "GET /api/healthcheck" in records[0].getMessage()
