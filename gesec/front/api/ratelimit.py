from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from gesec.front.ratelimit.services import check_rate_limit

API_RATE_LIMIT = 200
API_RATE_LIMIT_INTERVAL = 3600 * 24


class ApiRateLimitMiddleware:
    """Rate limiting global des routes API (/api/...) : 200 requêtes par jour."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/api/"):
            if check_rate_limit("api", API_RATE_LIMIT, API_RATE_LIMIT_INTERVAL).limited:
                return HttpResponse(status=429, headers={"Retry-After": str(API_RATE_LIMIT_INTERVAL)})
        return self.get_response(request)
