from django.core.exceptions import ValidationError

import pytest

from gesec.common.models import OAuthApplication, is_loopback_redirect_uri
from tests.factories.users import UserFactory


@pytest.mark.parametrize(
    "uri",
    [
        "http://127.0.0.1/callback",
        "http://127.0.0.1:8080/callback",
        "https://127.0.0.1/callback",
        "https://127.0.0.1:8443/cb",
        "http://[::1]/callback",
        "https://[::1]:9000/cb?x=1",
    ],
)
def test_is_loopback_redirect_uri_accepts(uri):
    assert is_loopback_redirect_uri(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost:8080/callback",
        "https://localhost/callback",
        "https://example.com/callback",
        "http://192.168.1.1/callback",
        "ftp://127.0.0.1/callback",
        "com.example.app:/oauth2redirect",
        "not a uri",
    ],
)
def test_is_loopback_redirect_uri_rejects(uri):
    assert not is_loopback_redirect_uri(uri)


def make_application(**kwargs) -> OAuthApplication:
    defaults = {
        "user": UserFactory.create(),
        "name": "agent",
        "client_type": OAuthApplication.CLIENT_PUBLIC,
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "redirect_uris": "http://127.0.0.1:8080/callback",
    }
    defaults.update(kwargs)
    return OAuthApplication(**defaults)


@pytest.mark.django_db
def test_clean_accepts_public_loopback_client():
    make_application().clean()


@pytest.mark.django_db
def test_clean_accepts_loopback_any_port_and_path():
    make_application(redirect_uris="http://127.0.0.1/ http://127.0.0.1:9999/any/path/deep").clean()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "uri",
    [
        "http://127.0.0.1:8080/callback",
        "http://127.0.0.1/callback",
        "http://127.0.0.1:19876/callback",
    ],
)
def test_redirect_uri_allowed_accepts_loopback_any_port_exact_path(uri):
    assert make_application().redirect_uri_allowed(uri)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/callback",
        "http://localhost:8080/callback",
        "http://192.168.1.1/callback",
        "http://127.0.0.1:19876/mcp/oauth/callback",
        "http://127.0.0.1:8080/autre/chemin",
        "https://127.0.0.1:8443/callback",
        "http://127.0.0.1:8080/callback#frag",
    ],
)
def test_redirect_uri_allowed_rejects_non_loopback_or_non_matching(uri):
    assert not make_application().redirect_uri_allowed(uri)


@pytest.mark.django_db
def test_clean_rejects_non_loopback_redirect_uri():
    with pytest.raises(ValidationError) as exc:
        make_application(redirect_uris="https://example.com/callback").clean()
    assert "redirect_uris" in exc.value.message_dict


@pytest.mark.django_db
def test_clean_rejects_localhost_redirect_uri():
    with pytest.raises(ValidationError) as exc:
        make_application(redirect_uris="http://localhost:8080/callback").clean()
    assert "redirect_uris" in exc.value.message_dict


@pytest.mark.django_db
def test_clean_rejects_confidential_client():
    with pytest.raises(ValidationError) as exc:
        make_application(client_type=OAuthApplication.CLIENT_CONFIDENTIAL).clean()
    assert "client_type" in exc.value.message_dict


@pytest.mark.django_db
def test_clean_rejects_non_authorization_code_grant():
    with pytest.raises(ValidationError) as exc:
        make_application(authorization_grant_type=OAuthApplication.GRANT_CLIENT_CREDENTIALS).clean()
    assert "authorization_grant_type" in exc.value.message_dict
