import os

import pytest
import requests


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.test_settings")

import django
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse


django.setup()

from allauth.socialaccount.models import SocialApp

from ksa_games.socialaccount import (
    GOOGLE_OAUTH_CLIENT_ID_ENV,
    GOOGLE_OAUTH_CLIENT_SECRET_ENV,
    build_socialaccount_providers_config,
)


pytestmark = pytest.mark.django_db

GOOGLE_TEST_PROVIDER_CONFIG = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "APPS": [
            {
                "name": "Google",
                "client_id": "test-google-client-id",
                "secret": "test-google-client-secret",
            }
        ],
    }
}


def test_google_socialaccount_provider_is_installed_without_extra_providers():
    provider_apps = [
        app
        for app in settings.INSTALLED_APPS
        if app.startswith("allauth.socialaccount.providers.")
    ]

    assert "allauth.socialaccount" in settings.INSTALLED_APPS
    assert provider_apps == ["allauth.socialaccount.providers.google"]


def test_google_socialapp_can_be_configured_in_admin():
    assert admin.site.is_registered(SocialApp)


def test_google_provider_config_omits_secret_placeholders_when_env_is_absent(monkeypatch):
    monkeypatch.delenv(GOOGLE_OAUTH_CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(GOOGLE_OAUTH_CLIENT_SECRET_ENV, raising=False)

    config = build_socialaccount_providers_config()

    assert config["google"]["SCOPE"] == ["profile", "email"]
    assert config["google"]["AUTH_PARAMS"] == {"access_type": "online"}
    assert "APPS" not in config["google"]


def test_google_provider_config_reads_credentials_from_environment(monkeypatch):
    monkeypatch.setenv(GOOGLE_OAUTH_CLIENT_ID_ENV, "env-google-client-id")
    monkeypatch.setenv(GOOGLE_OAUTH_CLIENT_SECRET_ENV, "env-google-client-secret")

    config = build_socialaccount_providers_config()

    app_config = config["google"]["APPS"][0]
    assert app_config["name"] == "Google"
    assert app_config["client_id"] == "env-google-client-id"
    assert app_config["secret"] == "env-google-client-secret"


@pytest.mark.parametrize(
    ("client_id", "client_secret"),
    [
        ("env-google-client-id", ""),
        ("", "env-google-client-secret"),
    ],
)
def test_google_provider_config_rejects_partial_environment(
    monkeypatch,
    client_id,
    client_secret,
):
    monkeypatch.setenv(GOOGLE_OAUTH_CLIENT_ID_ENV, client_id)
    monkeypatch.setenv(GOOGLE_OAUTH_CLIENT_SECRET_ENV, client_secret)

    with pytest.raises(ImproperlyConfigured, match="must be set together"):
        build_socialaccount_providers_config()


def test_login_page_hides_google_link_when_provider_is_not_configured(client):
    response = client.get(reverse("account_login"))

    assert response.status_code == 200
    assert b"Continue with Google" not in response.content
    assert reverse("google_login").encode() not in response.content


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_TEST_PROVIDER_CONFIG)
def test_login_page_exposes_google_login_path_when_configured(client):
    response = client.get(reverse("account_login"))

    assert response.status_code == 200
    assert b"Continue with Google" in response.content
    assert reverse("google_login").encode() in response.content


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_TEST_PROVIDER_CONFIG)
def test_google_login_start_renders_without_calling_google(client, monkeypatch):
    def fail_on_network(*args, **kwargs):
        raise AssertionError("Google OAuth start should not make an HTTP request")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_on_network)

    response = client.get(reverse("google_login"))

    assert response.status_code == 200
    assert b"Google" in response.content
