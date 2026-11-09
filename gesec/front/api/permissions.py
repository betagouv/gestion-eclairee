from rest_framework import viewsets
from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class ApiAccessPermission(BasePermission):
    def has_permission(self, request: Request, view: viewsets.ViewSet) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("gesec.api_access"))
