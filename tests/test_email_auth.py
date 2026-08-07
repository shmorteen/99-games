import os

import pytest


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.test_settings")

import django
from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse


django.setup()


pytestmark = pytest.mark.django_db


def signup_payload(email="player@example.com", password="StrongPass123!"):
    return {
        "email": email,
        "password1": password,
        "password2": password,
    }


def create_user_with_email(email="player@example.com", password="StrongPass123!"):
    user = get_user_model().objects.create_user(
        username=email,
        email=email,
        password=password,
    )
    EmailAddress.objects.create(
        user=user,
        email=email,
        primary=True,
        verified=True,
    )
    return user


def test_signup_creates_user_and_email_identity(client):
    response = client.post(reverse("account_signup"), signup_payload())

    assert response.status_code == 302
    user = get_user_model().objects.get(email="player@example.com")
    email_address = EmailAddress.objects.get(user=user)
    assert email_address.email == "player@example.com"
    assert email_address.primary is True


def test_duplicate_email_signup_is_rejected(client):
    create_user_with_email(email="player@example.com")

    response = client.post(reverse("account_signup"), signup_payload())

    assert response.status_code == 200
    assert get_user_model().objects.filter(email="player@example.com").count() == 1
    assert b"already" in response.content.lower()


def test_signup_rejects_invalid_email_input(client):
    response = client.post(reverse("account_signup"), signup_payload(email="not-an-email"))

    assert response.status_code == 200
    assert not get_user_model().objects.exists()
    assert response.context["form"].errors["email"]


def test_email_login_accepts_valid_credentials(client):
    create_user_with_email(
        email="player@example.com",
        password="StrongPass123!",
    )

    response = client.post(
        reverse("account_login"),
        {
            "login": "player@example.com",
            "password": "StrongPass123!",
        },
    )

    assert response.status_code == 302
    assert "_auth_user_id" in client.session


def test_email_login_rejects_invalid_credentials(client):
    create_user_with_email(
        email="player@example.com",
        password="StrongPass123!",
    )

    response = client.post(
        reverse("account_login"),
        {
            "login": "player@example.com",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert response.context["form"].errors


def test_logout_clears_authenticated_session(client):
    user = create_user_with_email()
    client.force_login(user)

    response = client.post(reverse("account_logout"))

    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


def test_auth_views_use_csrf_protection():
    client = Client(enforce_csrf_checks=True)

    response = client.post(
        reverse("account_login"),
        {
            "login": "player@example.com",
            "password": "StrongPass123!",
        },
    )

    assert response.status_code == 403


def test_signup_page_includes_csrf_token(client):
    response = client.get(reverse("account_signup"))

    assert response.status_code == 200
    assert b"csrfmiddlewaretoken" in response.content


def test_email_verification_is_documented_as_disabled_for_foundation():
    assert settings.ACCOUNT_EMAIL_VERIFICATION == "none"


def test_only_google_oauth_provider_is_added():
    provider_apps = [
        app
        for app in settings.INSTALLED_APPS
        if app.startswith("allauth.socialaccount.providers.")
    ]

    assert provider_apps == ["allauth.socialaccount.providers.google"]
