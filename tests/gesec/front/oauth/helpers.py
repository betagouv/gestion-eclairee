import secrets
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.utils import timezone

from oauth2_provider.models import get_access_token_model, set_token_value

from gesec.common.models import OAuthApplication
from tests.factories.users import UserFactory

DATA_SCOPE = "data"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8080/callback"


def make_mcp_user(**kwargs):
    user = UserFactory.create(**kwargs)
    permission = Permission.objects.get(
        content_type__app_label="gesec", content_type__model="user", codename="api_access"
    )
    user.user_permissions.add(permission)
    return user


def make_application(user=None, **kwargs) -> OAuthApplication:
    defaults = {
        "user": user or UserFactory.create(),
        "name": "agent-test",
        "client_type": OAuthApplication.CLIENT_PUBLIC,
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "redirect_uris": DEFAULT_REDIRECT_URI,
        "registration_source": OAuthApplication.RegistrationSource.MANUAL,
    }
    defaults.update(kwargs)
    return OAuthApplication.objects.create(**defaults)


def make_access_token(
    user, application=None, scope=DATA_SCOPE, expires_in=3600, resource: list[str] | None = None
) -> str:
    access_token = get_access_token_model()(
        application=application or make_application(user=user),
        user=user,
        scope=scope,
        expires=timezone.now() + timedelta(seconds=expires_in),
        resource=resource or [],
    )
    raw_token = secrets.token_urlsafe(32)
    set_token_value(access_token, raw_token)
    access_token.save()
    return raw_token
