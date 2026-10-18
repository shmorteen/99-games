from django.urls import path

from .consumers import GameConsumer


websocket_urlpatterns = [
    path("ws/games/<uuid:session_uuid>/", GameConsumer.as_asgi()),
]
