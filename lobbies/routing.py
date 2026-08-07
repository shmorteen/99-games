from django.urls import path

from .consumers import LobbyConsumer


websocket_urlpatterns = [
    path("ws/lobbies/<uuid:lobby_uuid>/", LobbyConsumer.as_asgi()),
]
