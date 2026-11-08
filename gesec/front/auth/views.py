from lasuite.oidc_login.views import OIDCBackChannelLogoutView as LaSuiteBackChannelLogoutView
from mozilla_django_oidc.views import OIDCAuthenticationCallbackView
from oauth2_provider.models import get_access_token_model, get_grant_model, get_refresh_token_model


class CustomOIDCAuthenticationCallbackView(OIDCAuthenticationCallbackView):
    pass


class CustomOIDCBackChannelLogoutView(LaSuiteBackChannelLogoutView):
    def logout_user_sessions(self, sub, sid=None):
        success = super().logout_user_sessions(sub, sid)
        if sub is not None:
            get_access_token_model().objects.filter(user__sub=sub).delete()
            get_refresh_token_model().objects.filter(user__sub=sub).delete()
            get_grant_model().objects.filter(user__sub=sub).delete()
        return success
