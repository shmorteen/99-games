import importlib
import os
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.settings")

import django
from django.conf import settings
from django.test import Client

from ksa_games.env import env_bool, env_int, env_list, env_secret_key


django.setup()


def test_manage_py_exists():
    assert Path("manage.py").is_file()


def test_entrypoints_import_without_side_effects():
    for module_name in ("ksa_games.urls", "ksa_games.asgi", "ksa_games.wsgi"):
        module = importlib.import_module(module_name)
        assert module is not None


def test_root_endpoint_returns_project_shell_status():
    response = Client().get("/")

    assert response.status_code == 200
    assert response.json() == {"service": "KSA Games", "status": "project-shell"}


def test_root_endpoint_rejects_unsupported_methods():
    response = Client().post("/")

    assert response.status_code == 405


def test_unknown_route_returns_not_found():
    response = Client(HTTP_HOST="localhost").get("/missing/")

    assert response.status_code == 404


def test_project_shell_adds_only_google_oauth_provider():
    provider_apps = [
        app
        for app in settings.INSTALLED_APPS
        if app.startswith("allauth.socialaccount.providers.")
    ]

    assert provider_apps == ["allauth.socialaccount.providers.google"]


def test_env_bool_accepts_documented_values(monkeypatch):
    monkeypatch.setenv("KSA_DEBUG", "off")

    assert env_bool("KSA_DEBUG", True) is False


def test_env_bool_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("KSA_DEBUG", "sometimes")

    with pytest.raises(ImproperlyConfigured, match="KSA_DEBUG must be one of"):
        env_bool("KSA_DEBUG", True)


def test_env_list_trims_empty_items(monkeypatch):
    monkeypatch.setenv("KSA_ALLOWED_HOSTS", "example.com, localhost, ,127.0.0.1")

    assert env_list("KSA_ALLOWED_HOSTS", []) == [
        "example.com",
        "localhost",
        "127.0.0.1",
    ]


def test_env_int_accepts_positive_integer(monkeypatch):
    monkeypatch.setenv("KSA_READY_CHECK_TIMEOUT_SECONDS", "45")

    assert env_int("KSA_READY_CHECK_TIMEOUT_SECONDS", 30) == 45


def test_env_int_rejects_non_positive_integer(monkeypatch):
    monkeypatch.setenv("KSA_READY_CHECK_TIMEOUT_SECONDS", "0")

    with pytest.raises(ImproperlyConfigured, match="positive integer"):
        env_int("KSA_READY_CHECK_TIMEOUT_SECONDS", 30)


def test_secret_key_is_required_when_debug_is_disabled(monkeypatch):
    monkeypatch.delenv("KSA_SECRET_KEY", raising=False)

    with pytest.raises(ImproperlyConfigured, match="KSA_SECRET_KEY must be set"):
        env_secret_key("KSA_SECRET_KEY", debug=False)
