import io

from django.contrib.auth import authenticate
from django.core.files.storage import default_storage

import pytest
from freezegun import freeze_time

from gesec.front.ratelimit.models import RateLimitCount
from tests.factories.users import UserFactory


@pytest.mark.django_db
def test_home_view(client):
    """Test that home view renders correctly."""
    response = client.get("/")

    assert response.status_code == 200
    assert any(t.name == "gesec/home.html" for t in response.templates)


@pytest.mark.django_db
def test_s3_file_unauthenticated(client):
    """Test that unauthenticated users get 403."""
    response = client.get("/s3/test.txt")

    assert response.status_code == 403


@pytest.mark.django_db
def test_s3_file_not_superuser(client):
    """Test that authenticated non-superuser gets 403."""
    user = UserFactory.create(is_superuser=False)
    client.force_login(user)

    response = client.get("/s3/test.txt")

    assert response.status_code == 403


@pytest.mark.django_db
def test_s3_file_rate_limited(client):
    """Test that rate limited superuser gets 403."""
    user = UserFactory.create(is_superuser=True)
    client.force_login(user)

    with freeze_time("2025-10-08T10:00:00+00:00"):
        RateLimitCount.objects.create(
            key=str(user.pk),
            interval=3600 * 24,
            count=201,
            expiry="2025-10-09T10:00:00+00:00",
        )
        response = client.get("/s3/test.txt")

    assert response.status_code == 403


@pytest.mark.django_db
def test_s3_file_not_found(admin_client):
    """Test that 404 is raised when file doesn't exist."""

    response = admin_client.get("/s3/nonexistent.txt")

    assert response.status_code == 404


@pytest.mark.django_db
def test_s3_file_success(admin_client):
    """Test that file is served correctly when all conditions are met."""

    test_content = b"test file content"
    default_storage.save("test.txt", io.BytesIO(test_content))

    response = admin_client.get("/s3/test.txt")

    assert response.status_code == 200
    assert b"test file content" in b"".join(response.streaming_content)

    default_storage.delete("test.txt")


@pytest.mark.django_db
def test_password_authentication_disabled():
    """ModelBackend retiré : authenticate() avec un mot de passe renvoie None."""
    user = UserFactory.create(admin_email="staff@test.local")
    user.set_password("secret-password")
    user.save()

    assert authenticate(username="staff@test.local", password="secret-password") is None


@pytest.mark.django_db
def test_admin_login_redirects_to_oidc_login(client):
    """La page de login admin n'affiche pas de formulaire mdp : redirection vers /login (OIDC)."""
    response = client.get("/admintest/login/")

    assert response.status_code == 302
    assert response.url.startswith("/login?next=")


@pytest.mark.django_db
def test_admin_accessible_with_authenticated_staff(admin_client):
    """Un utilisateur staff authentifié (session OIDC) accède à l'admin."""
    response = admin_client.get("/admintest/")

    assert response.status_code == 200
