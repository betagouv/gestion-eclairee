from django.urls import path

from gesec.front.api import views as api_views

urlpatterns = [
    path("healthcheck", api_views.HealthcheckView.as_view(), name="api_healthcheck"),
    path("meta-budat/", api_views.MetaBudatViewSet.as_view({"get": "list"}), name="meta_budat_list"),
    path("meta-budat/schema/", api_views.MetaBudatViewSet.as_view({"get": "schema"}), name="meta_budat_schema"),
]
