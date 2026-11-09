import pytest

from gesec.front.api.ratelimit import API_RATE_LIMIT, API_RATE_LIMIT_INTERVAL


@pytest.mark.django_db
def test_api_rate_limit_is_global_with_retry_after(client):
    for _ in range(API_RATE_LIMIT):
        assert client.get("/api/healthcheck").status_code != 429

    response = client.get("/api/healthcheck")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(API_RATE_LIMIT_INTERVAL)


@pytest.mark.django_db
def test_api_rate_limit_applies_to_all_api_routes(client):
    for _ in range(API_RATE_LIMIT):
        client.get("/api/healthcheck")

    assert client.get("/api/meta-budat/").status_code == 429
    assert client.get("/api/meta-budat/schema/").status_code == 429


@pytest.mark.django_db
def test_api_rate_limit_does_not_apply_outside_api(client):
    for _ in range(API_RATE_LIMIT):
        client.get("/api/healthcheck")

    assert client.get("/").status_code != 429
