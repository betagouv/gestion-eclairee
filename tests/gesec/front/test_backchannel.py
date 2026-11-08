import pytest
from oauth2_provider.models import get_access_token_model, get_grant_model, get_refresh_token_model

from gesec.front.auth.views import CustomOIDCBackChannelLogoutView
from tests.factories.users import UserFactory
from tests.gesec.front.oauth.helpers import make_access_token, make_application


@pytest.mark.django_db
def test_logout_revokes_dot_tokens_by_sub():
    user = UserFactory.create(sub="sub-1")
    access_token = make_access_token(user)

    view = CustomOIDCBackChannelLogoutView()
    view.logout_user_sessions("sub-1", None)

    assert access_token
    assert not get_access_token_model().objects.filter(user__sub="sub-1").exists()
    assert not get_refresh_token_model().objects.filter(user__sub="sub-1").exists()
    assert not get_grant_model().objects.filter(user__sub="sub-1").exists()


@pytest.mark.django_db
def test_logout_without_sub_does_not_revoke():
    user = UserFactory.create(sub="sub-2")
    make_access_token(user)

    view = CustomOIDCBackChannelLogoutView()
    view.logout_user_sessions(None, "sid-2")

    assert get_access_token_model().objects.filter(user__sub="sub-2").exists()


@pytest.mark.django_db
def test_logout_revokes_application_tokens():
    user = UserFactory.create(sub="sub-3")
    application = make_application(user=user)
    make_access_token(user, application=application)

    view = CustomOIDCBackChannelLogoutView()
    view.logout_user_sessions("sub-3", None)

    assert not get_access_token_model().objects.filter(application=application).exists()
