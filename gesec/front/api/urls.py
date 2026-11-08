from django.urls import path

from gesec.front.api import views as api_views

urlpatterns = [
    path("healthcheck", api_views.HealthcheckView.as_view(), name="api_healthcheck"),
]
