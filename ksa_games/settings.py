"""Django settings for the KSA Games project shell."""
from __future__ import annotations

import os
from pathlib import Path

from .channel_layers import build_channel_layers_config
from .celery_config import build_celery_config
from .database import build_database_config
from .env import env_bool, env_int, env_list, env_secret_key
from .socialaccount import build_socialaccount_providers_config


BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = env_bool("KSA_DEBUG", True)
SECRET_KEY = env_secret_key("KSA_SECRET_KEY", debug=DEBUG)
ALLOWED_HOSTS = env_list("KSA_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])

ROOT_URLCONF = "ksa_games.urls"
WSGI_APPLICATION = "ksa_games.wsgi.application"
ASGI_APPLICATION = "ksa_games.asgi.application"

INSTALLED_APPS: list[str] = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sites",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "accounts",
    "games",
    "lobbies",
    "play",
]
KSA_GAME_ENGINE_MODULES = env_list("KSA_GAME_ENGINE_MODULES", [])
KSA_ALLOW_GUEST_SPECTATOR_WEBSOCKETS = env_bool(
    "KSA_ALLOW_GUEST_SPECTATOR_WEBSOCKETS",
    False,
)
KSA_READY_CHECK_TIMEOUT_SECONDS = env_int("KSA_READY_CHECK_TIMEOUT_SECONDS", 30)
KSA_READY_CHECK_TIMEOUT_BEHAVIOR = os.environ.get(
    "KSA_READY_CHECK_TIMEOUT_BEHAVIOR",
    "return_to_waiting",
).strip()
KSA_LOBBY_START_LOCK_BACKEND = os.environ.get(
    "KSA_LOBBY_START_LOCK_BACKEND",
    "redis",
).strip()
KSA_LOBBY_START_LOCK_REDIS_URL = os.environ.get(
    "KSA_LOBBY_START_LOCK_REDIS_URL",
    os.environ.get("KSA_REDIS_URL", "redis://localhost:6379/0"),
).strip()
KSA_GAME_ACTION_LOCK_BACKEND = os.environ.get(
    "KSA_GAME_ACTION_LOCK_BACKEND", "redis"
).strip()
KSA_GAME_ACTION_LOCK_REDIS_URL = os.environ.get(
    "KSA_GAME_ACTION_LOCK_REDIS_URL",
    os.environ.get("KSA_REDIS_URL", "redis://localhost:6379/0"),
).strip()
KSA_LOBBY_START_LOCK_PREFIX = os.environ.get(
    "KSA_LOBBY_START_LOCK_PREFIX",
    "ksa-games",
).strip()
KSA_LOBBY_START_LOCK_TIMEOUT_SECONDS = env_int(
    "KSA_LOBBY_START_LOCK_TIMEOUT_SECONDS",
    10,
)
KSA_LOBBY_START_LOCK_BLOCKING_TIMEOUT_SECONDS = env_int(
    "KSA_LOBBY_START_LOCK_BLOCKING_TIMEOUT_SECONDS",
    5,
)
MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
TEMPLATES: list[dict[str, object]] = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {"default": build_database_config(BASE_DIR)}
CHANNEL_LAYERS = build_channel_layers_config()
globals().update(build_celery_config())

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_SESSION_REMEMBER = None
SOCIALACCOUNT_PROVIDERS = build_socialaccount_providers_config()
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
