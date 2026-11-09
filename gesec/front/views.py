import logging
from typing import cast
from urllib.parse import urlencode

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpRequest, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse

from gesec.common.models import User

from .ratelimit.services import check_rate_limit_for_user

logger = logging.getLogger(__name__)


def admin_login_redirect(request: HttpRequest) -> HttpResponseRedirect:
    return redirect(f"{reverse('login')}?{urlencode({'next': request.get_full_path()})}")


def home(request: HttpRequest):
    return render(
        request,
        "gesec/home.html",
    )


def s3_file(request: HttpRequest, path: str):
    user = cast(User, request.user)
    if not user.is_authenticated or not user.is_superuser:
        return HttpResponseForbidden()

    ratelimit_result = check_rate_limit_for_user(user, 200, 3600 * 24)
    is_ratelimited = ratelimit_result.limited
    if is_ratelimited:
        logger.info(f"Rate limit for user {user.pk} exceeded")
        return HttpResponseForbidden()

    if not default_storage.exists(path):
        raise Http404()

    file = default_storage.open(path)
    return FileResponse(file)
