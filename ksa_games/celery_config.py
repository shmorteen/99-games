"""Celery configuration helpers for KSA Games settings."""
from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured


DEFAULT_CELERY_BROKER_URL = "redis://localhost:6379/1"
DEFAULT_CELERY_RESULT_BACKEND = "redis://localhost:6379/2"
DEFAULT_CELERY_TASK_DEFAULT_QUEUE = "ksa-games"


def build_celery_config() -> dict[str, object]:
    """Build Celery settings from environment variables."""
    broker_url = non_blank_env(
        "KSA_CELERY_BROKER_URL",
        DEFAULT_CELERY_BROKER_URL,
    )
    result_backend = non_blank_env(
        "KSA_CELERY_RESULT_BACKEND",
        DEFAULT_CELERY_RESULT_BACKEND,
    )
    task_default_queue = non_blank_env(
        "KSA_CELERY_TASK_DEFAULT_QUEUE",
        DEFAULT_CELERY_TASK_DEFAULT_QUEUE,
    )

    config: dict[str, object] = {
        "CELERY_BROKER_URL": broker_url,
        "CELERY_RESULT_BACKEND": result_backend,
        "CELERY_TASK_DEFAULT_QUEUE": task_default_queue,
        "CELERY_TASK_IGNORE_RESULT": False,
        "CELERY_TASK_TRACK_STARTED": True,
        "CELERY_TASK_SERIALIZER": "json",
        "CELERY_RESULT_SERIALIZER": "json",
        "CELERY_ACCEPT_CONTENT": ["json"],
        "CELERY_TIMEZONE": "UTC",
    }

    broker_connection_retry_on_startup = os.environ.get(
        "KSA_CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP"
    )
    if broker_connection_retry_on_startup is not None:
        config["CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP"] = parse_bool(
            "KSA_CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP",
            broker_connection_retry_on_startup,
        )

    return config


def non_blank_env(name: str, default: str) -> str:
    """Read an environment value and reject blank explicit values."""
    value = os.environ.get(name, default).strip()
    if not value:
        raise ImproperlyConfigured(f"{name} cannot be blank.")
    return value


def parse_bool(name: str, value: str) -> bool:
    """Parse a boolean Celery environment value."""
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean value.")
