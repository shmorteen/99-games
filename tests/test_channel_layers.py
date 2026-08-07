import importlib
import os

import pytest
from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.settings")

import django
from channels.layers import channel_layers, get_channel_layer
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.sessions import CookieMiddleware

from ksa_games.channel_layers import (
    DEFAULT_CHANNEL_PREFIX,
    DEFAULT_REDIS_URL,
    IN_MEMORY_CHANNEL_LAYER_BACKEND,
    REDIS_CHANNEL_LAYER_BACKEND,
    build_channel_layers_config,
    build_in_memory_channel_layers_config,
)


django.setup()


def reset_channel_layer_cache():
    channel_layers.backends = {}


def test_default_channel_layer_uses_redis(monkeypatch):
    monkeypatch.delenv("KSA_REDIS_URL", raising=False)
    monkeypatch.delenv("KSA_CHANNEL_PREFIX", raising=False)

    config = build_channel_layers_config()

    assert config == {
        "default": {
            "BACKEND": REDIS_CHANNEL_LAYER_BACKEND,
            "CONFIG": {
                "hosts": [DEFAULT_REDIS_URL],
                "prefix": DEFAULT_CHANNEL_PREFIX,
            },
        }
    }


def test_redis_channel_layer_uses_environment_values(monkeypatch):
    monkeypatch.setenv("KSA_REDIS_URL", "redis://cache.example.com:6380/2")
    monkeypatch.setenv("KSA_CHANNEL_PREFIX", "ksa-test")
    monkeypatch.setenv("KSA_CHANNEL_CAPACITY", "200")
    monkeypatch.setenv("KSA_CHANNEL_EXPIRY", "30")
    monkeypatch.setenv("KSA_CHANNEL_GROUP_EXPIRY", "120")

    config = build_channel_layers_config()

    assert config == {
        "default": {
            "BACKEND": REDIS_CHANNEL_LAYER_BACKEND,
            "CONFIG": {
                "hosts": ["redis://cache.example.com:6380/2"],
                "prefix": "ksa-test",
                "capacity": 200,
                "expiry": 30,
                "group_expiry": 120,
            },
        }
    }


def test_in_memory_channel_layer_config_is_available_for_tests():
    assert build_in_memory_channel_layers_config() == {
        "default": {
            "BACKEND": IN_MEMORY_CHANNEL_LAYER_BACKEND,
        }
    }


def test_blank_redis_url_is_rejected(monkeypatch):
    monkeypatch.setenv("KSA_REDIS_URL", " ")

    with pytest.raises(ImproperlyConfigured, match="KSA_REDIS_URL"):
        build_channel_layers_config()


def test_channel_capacity_must_be_positive(monkeypatch):
    monkeypatch.setenv("KSA_CHANNEL_CAPACITY", "0")

    with pytest.raises(ImproperlyConfigured, match="KSA_CHANNEL_CAPACITY"):
        build_channel_layers_config()


@override_settings(CHANNEL_LAYERS=build_in_memory_channel_layers_config())
def test_in_memory_channel_layer_can_be_loaded():
    reset_channel_layer_cache()

    layer = get_channel_layer()
    async_to_sync(layer.send)(
        "test-channel",
        {"type": "test.message", "payload": "ok"},
    )
    message = async_to_sync(layer.receive)("test-channel")

    assert message == {"type": "test.message", "payload": "ok"}
    reset_channel_layer_cache()


def test_test_settings_use_isolated_in_memory_channel_layer():
    test_settings = importlib.import_module("ksa_games.test_settings")

    assert test_settings.CHANNEL_LAYERS == {
        "default": {
            "BACKEND": IN_MEMORY_CHANNEL_LAYER_BACKEND,
        }
    }


def test_asgi_application_routes_http_and_websocket():
    asgi_module = importlib.import_module("ksa_games.asgi")

    assert isinstance(asgi_module.application, ProtocolTypeRouter)
    assert "http" in asgi_module.application.application_mapping
    assert "websocket" in asgi_module.application.application_mapping
    assert isinstance(asgi_module.application.application_mapping["websocket"], CookieMiddleware)


def test_lobby_websocket_consumer_is_registered():
    routing = importlib.import_module("ksa_games.routing")

    assert routing.websocket_urlpatterns
    assert any("ws/lobbies/" in str(pattern.pattern) for pattern in routing.websocket_urlpatterns)
