import logging

from django.urls import reverse

from oauth2_provider.contrib.rest_framework import OAuth2ProtectedResourceAuthentication

logger = logging.getLogger(__name__)


class LoggingOAuth2Authentication(OAuth2ProtectedResourceAuthentication):
    """Loggue les requêtes API : méthode, path, utilisateur et client_id — jamais le jeton."""

    def get_resource_metadata_url(self, request):
        return request.build_absolute_uri(reverse("oauth2_metadata:oauth-resource-metadata"))

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            logger.warning(f"API {request.method} {request.path}: authentification échouée")
            return None
        user, token = result
        application = getattr(token, "application", None)
        client_id = application.client_id if application is not None else None
        logger.info(f"API {request.method} {request.path}: user={user.pk} email={user.email} client_id={client_id}")
        return result
