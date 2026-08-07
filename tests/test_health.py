import os

import pytest
from django.test import override_settings
from django.urls import reverse


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.test_settings")

import django

from ksa_games.channel_layers import IN_MEMORY_CHANNEL_LAYER_BACKEND
from ksa_games.health import (
    NOT_CONFIGURED,
    OK,
    REDIS_CHANNEL_LAYER_BACKEND,
    UNAVAILABLE,
    configured_redis_urls,
)


django.setup()


pytestmark = pytest.mark.django_db


REDIS_CHANNEL_LAYERS = {
    "default": {
        "BACKEND": REDIS_CHANNEL_LAYER_BACKEND,
        "CONFIG": {
            "hosts": ["redis://:secret-password@localhost:6379/0"],
        },
    }
}


def test_liveness_endpoint_returns_success(client):
    response = client.get(reverse("health-live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"application": OK}}


def test_health_endpoints_reject_post(client):
    live_response = client.post(reverse("health-live"))
    ready_response = client.post(reverse("health-ready"))

    assert live_response.status_code == 405
    assert ready_response.status_code == 405


def test_readiness_endpoint_checks_database_and_skips_unconfigured_redis(client):
    response = client.get(reverse("health-ready"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": OK,
            "redis": NOT_CONFIGURED,
        },
    }


def test_readiness_endpoint_reports_database_failure_without_details(client, monkeypatch):
    monkeypatch.setattr("ksa_games.health.check_database", lambda: False)

    response = client.get(reverse("health-ready"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "database": UNAVAILABLE,
            "redis": NOT_CONFIGURED,
        },
    }
    assert b"OperationalError" not in response.content
    assert b"Traceback" not in response.content


@override_settings(CHANNEL_LAYERS=REDIS_CHANNEL_LAYERS)
def test_readiness_endpoint_checks_configured_redis(client, monkeypatch):
    checked_urls = []

    def fake_ping(redis_url):
        checked_urls.append(redis_url)
        return True

    monkeypatch.setattr("ksa_games.health.ping_redis_url", fake_ping)

    response = client.get(reverse("health-ready"))

    assert response.status_code == 200
    assert response.json()["checks"]["redis"] == OK
    assert checked_urls == ["redis://:secret-password@localhost:6379/0"]


@override_settings(CHANNEL_LAYERS=REDIS_CHANNEL_LAYERS)
def test_readiness_endpoint_reports_redis_failure_without_leaking_url(
    client,
    monkeypatch,
):
    monkeypatch.setattr("ksa_games.health.ping_redis_url", lambda redis_url: False)

    response = client.get(reverse("health-ready"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "database": OK,
            "redis": UNAVAILABLE,
        },
    }
    assert b"redis://" not in response.content
    assert b"secret-password" not in response.content
    assert b"localhost:6379" not in response.content
    assert b"Traceback" not in response.content


def test_configured_redis_urls_ignores_non_redis_channel_layers():
    channel_layers = {
        "default": {
            "BACKEND": IN_MEMORY_CHANNEL_LAYER_BACKEND,
        }
    }

    assert configured_redis_urls(channel_layers) == []
