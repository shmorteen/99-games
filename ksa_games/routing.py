"""ASGI routing for KSA Games realtime protocols."""
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

from lobbies.routing import websocket_urlpatterns as lobby_websocket_urlpatterns


websocket_urlpatterns = [
    *lobby_websocket_urlpatterns,
]


def build_asgi_application(http_application):
    """Build the ASGI protocol router for HTTP and WebSocket routes."""
    return ProtocolTypeRouter(
        {
            "http": http_application,
            "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
        }
    )
