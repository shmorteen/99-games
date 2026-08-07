"""Environment parsing helpers for project settings."""
from __future__ import annotations

import os
from collections.abc import Iterable

from django.core.exceptions import ImproperlyConfigured


LOCAL_DEV_SECRET_KEY = "django-insecure-ksa-games-local-dev"

TRUE_VALUES = frozenset({"1", "true", "t", "yes", "y", "on"})
FALSE_VALUES = frozenset({"0", "false", "f", "no", "n", "off"})


def env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable with strict accepted values."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False

    accepted = sorted(TRUE_VALUES | FALSE_VALUES)
    raise ImproperlyConfigured(
        f"{name} must be one of: {', '.join(accepted)}."
    )


def env_list(name: str, default: Iterable[str]) -> list[str]:
    """Read a comma-separated environment variable into a clean string list."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return list(default)

    return [item.strip() for item in raw_value.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    """Read a positive integer environment variable."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    try:
        parsed_value = int(raw_value.strip())
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from exc
    if parsed_value <= 0:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")
    return parsed_value


def env_secret_key(name: str, *, debug: bool) -> str:
    """Read the Django secret key and forbid the local key outside debug mode."""
    secret_key = os.environ.get(name, LOCAL_DEV_SECRET_KEY)
    if not debug and secret_key == LOCAL_DEV_SECRET_KEY:
        raise ImproperlyConfigured(f"{name} must be set when KSA_DEBUG is false.")
    return secret_key
