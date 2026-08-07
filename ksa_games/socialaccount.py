"""Social account provider settings for KSA Games."""
from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured


GOOGLE_OAUTH_CLIENT_ID_ENV = "KSA_GOOGLE_OAUTH_CLIENT_ID"
GOOGLE_OAUTH_CLIENT_SECRET_ENV = "KSA_GOOGLE_OAUTH_CLIENT_SECRET"


def _optional_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def build_socialaccount_providers_config() -> dict[str, dict[str, object]]:
    google_config: dict[str, object] = {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    }

    client_id = _optional_env(GOOGLE_OAUTH_CLIENT_ID_ENV)
    client_secret = _optional_env(GOOGLE_OAUTH_CLIENT_SECRET_ENV)
    if bool(client_id) != bool(client_secret):
        raise ImproperlyConfigured(
            f"{GOOGLE_OAUTH_CLIENT_ID_ENV} and "
            f"{GOOGLE_OAUTH_CLIENT_SECRET_ENV} must be set together."
        )

    if client_id and client_secret:
        google_config["APPS"] = [
            {
                "name": "Google",
                "client_id": client_id,
                "secret": client_secret,
            }
        ]

    return {"google": google_config}
