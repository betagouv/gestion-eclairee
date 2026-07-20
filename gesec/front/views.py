import logging

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.http import HttpRequest
from django.shortcuts import render

from .ratelimit.services import check_rate_limit_for_user


logger = logging.getLogger(__name__)


def home(request: HttpRequest):
    return render(
        request,
        "gesec/home.html",
    )


def s3_file(request: HttpRequest, path: str):
    if not request.user.is_authenticated or not request.user.is_superuser:
        return HttpResponseForbidden()

    ratelimit_result = check_rate_limit_for_user(request.user, 200, 3600 * 24)
    is_ratelimited = ratelimit_result.limited
    if is_ratelimited:
        logger.info(f"Rate limit for user {request.user.id} exceeded")
        return HttpResponseForbidden()

    if not default_storage.exists(path):
        raise Http404()

    file = default_storage.open(path)
    return FileResponse(file)
