"""Health check endpoints for deployment and local operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from redis import Redis

from .channel_layers import REDIS_CHANNEL_LAYER_BACKEND


OK = "ok"
UNAVAILABLE = "unavailable"
NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class ReadinessReport:
    checks: dict[str, str]

    @property
    def is_ready(self) -> bool:
        return all(status in {OK, NOT_CONFIGURED} for status in self.checks.values())


@require_GET
def liveness(request):
    return JsonResponse({"status": "ok", "checks": {"application": OK}})


@require_GET
def readiness(request):
    report = build_readiness_report()
    response_status = 200 if report.is_ready else 503
    payload_status = "ready" if report.is_ready else "not_ready"
    return JsonResponse(
        {"status": payload_status, "checks": report.checks},
        status=response_status,
    )


def build_readiness_report() -> ReadinessReport:
    checks = {
        "database": OK if check_database() else UNAVAILABLE,
        "redis": check_redis_status(),
    }
    return ReadinessReport(checks=checks)


def check_database() -> bool:
    try:
        with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return False
    return True


def check_redis_status() -> str:
    redis_urls = configured_redis_urls(settings.CHANNEL_LAYERS)
    if not redis_urls:
        return NOT_CONFIGURED

    if all(ping_redis_url(redis_url) for redis_url in redis_urls):
        return OK
    return UNAVAILABLE


def configured_redis_urls(channel_layers: dict[str, dict[str, Any]]) -> list[str]:
    default_layer = channel_layers.get("default", {})
    if default_layer.get("BACKEND") != REDIS_CHANNEL_LAYER_BACKEND:
        return []

    config = default_layer.get("CONFIG", {})
    hosts = config.get("hosts", [])
    return [host for host in hosts if isinstance(host, str) and host.strip()]


def ping_redis_url(redis_url: str) -> bool:
    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        return bool(client.ping())
    except Exception:
        return False
    finally:
        client.close()
