from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from oauth2_provider.oauth2_validators import OAuth2Validator, validate_resource_as_url_prefix

from gesec.common.models import User
from gesec.front.ratelimit.services import check_rate_limit

OAUTH_RATE_LIMIT = 100
OAUTH_RATE_LIMIT_INTERVAL = 3600 * 24


def validate_token_resource(request_uri: str, audiences: list[str]) -> bool:
    """Valide l'audience RFC 8707 d'un jeton présenté à l'API.

    L'API Django (`PUBLIC_BASE_URL`) est le back-end de la ressource protégée MCP
    (`MCP_PUBLIC_URL`) : elle accepte les jetons émis pour cette ressource, ainsi
    que les jetons non restreints. Toute autre ressource suit la validation par
    préfixe d'URL (comportement DOT par défaut).
    """
    public_base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    if request_uri == public_base_url or request_uri.startswith(public_base_url + "/"):
        return not audiences or settings.MCP_PUBLIC_URL in audiences
    return validate_resource_as_url_prefix(request_uri, audiences)


class GesecOAuth2Validator(OAuth2Validator):
    """Rejette à la validation Bearer les jetons d'utilisateurs inactifs
    (DOT ne vérifie que l'expiration et les scopes dans `is_valid`)."""

    def validate_bearer_token(self, token: str, scopes: list[str] | None, request: Any) -> bool:
        if not super().validate_bearer_token(token, scopes, request):
            return False
        user = getattr(request, "user", None)
        return not isinstance(user, User) or user.is_active


class OAuthRateLimitMiddleware:
    """Rate limiting global des endpoints OAuth (/oauth/...) : 100 requêtes par jour."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/oauth/"):
            if check_rate_limit("oauth", OAUTH_RATE_LIMIT, OAUTH_RATE_LIMIT_INTERVAL).limited:
                return HttpResponse(status=429, headers={"Retry-After": str(OAUTH_RATE_LIMIT_INTERVAL)})
        return self.get_response(request)
