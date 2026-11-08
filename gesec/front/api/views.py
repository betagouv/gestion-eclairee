from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from gesec.common.models import User


class HealthcheckView(APIView):
    def get(self, request: Request) -> Response:
        user = request.user
        assert isinstance(user, User)
        return Response({"ok": True, "username": user.email})
