from django.urls import path

from . import views


app_name = "lobbies"

urlpatterns = [
    path("create/<slug:game_slug>/", views.create_lobby, name="create"),
    path("<uuid:lobby_uuid>/", views.lobby_detail, name="detail"),
    path("<uuid:lobby_uuid>/join/", views.join_public_lobby, name="join"),
]
