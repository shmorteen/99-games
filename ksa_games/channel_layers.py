"""Channel layer configuration helpers for KSA Games settings."""
from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured


REDIS_CHANNEL_LAYER_BACKEND = "channels_redis.core.RedisChannelLayer"
IN_MEMORY_CHANNEL_LAYER_BACKEND = "channels.layers.InMemoryChannelLayer"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_CHANNEL_PREFIX = "ksa-games"


def build_channel_layers_config() -> dict[str, dict[str, object]]:
    """Build the Redis-backed Django Channels layer settings."""
    return build_redis_channel_layers_config()


def build_redis_channel_layers_config() -> dict[str, dict[str, object]]:
    """Build the Redis-backed channel layer config."""
    redis_url = os.environ.get("KSA_REDIS_URL", DEFAULT_REDIS_URL).strip()
    if not redis_url:
        raise ImproperlyConfigured("KSA_REDIS_URL cannot be blank.")

    prefix = os.environ.get("KSA_CHANNEL_PREFIX", DEFAULT_CHANNEL_PREFIX).strip()
    if not prefix:
        raise ImproperlyConfigured("KSA_CHANNEL_PREFIX cannot be blank.")

    config: dict[str, object] = {
        "hosts": [redis_url],
        "prefix": prefix,
    }

    capacity = os.environ.get("KSA_CHANNEL_CAPACITY")
    if capacity is not None:
        config["capacity"] = parse_positive_int("KSA_CHANNEL_CAPACITY", capacity)

    expiry = os.environ.get("KSA_CHANNEL_EXPIRY")
    if expiry is not None:
        config["expiry"] = parse_positive_int("KSA_CHANNEL_EXPIRY", expiry)

    group_expiry = os.environ.get("KSA_CHANNEL_GROUP_EXPIRY")
    if group_expiry is not None:
        config["group_expiry"] = parse_positive_int(
            "KSA_CHANNEL_GROUP_EXPIRY", group_expiry
        )

    return {
        "default": {
            "BACKEND": REDIS_CHANNEL_LAYER_BACKEND,
            "CONFIG": config,
        }
    }


def build_in_memory_channel_layers_config() -> dict[str, dict[str, str]]:
    """Build an isolated in-memory channel layer config for tests."""
    return {
        "default": {
            "BACKEND": IN_MEMORY_CHANNEL_LAYER_BACKEND,
        }
    }


def parse_positive_int(name: str, value: str) -> int:
    """Parse a positive integer environment value."""
    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from exc

    if parsed_value <= 0:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")

    return parsed_value
