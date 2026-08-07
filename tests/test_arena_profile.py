import os
import uuid

import pytest


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.test_settings")

import django
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse


django.setup()

from accounts.models import ArenaProfile


pytestmark = pytest.mark.django_db


def create_user(username="player", email="player@example.com", password="StrongPass123!"):
    return get_user_model().objects.create_user(
        username=username,
        email=email,
        password=password,
    )


def test_new_user_gets_one_arena_profile():
    user = create_user()

    profile = user.arena_profile
    assert profile.user == user
    assert profile.display_name == f"Player {user.pk}"
    assert ArenaProfile.objects.filter(user=user).count() == 1


def test_arena_profile_exposes_uuid_public_identifier():
    user = create_user()

    assert isinstance(user.arena_profile.public_id, uuid.UUID)
    assert ArenaProfile._meta.get_field("public_id").unique is True
    assert ArenaProfile._meta.get_field("public_id").editable is False


def test_arena_profile_rejects_second_profile_for_same_user():
    user = create_user()

    with pytest.raises(ValidationError):
        ArenaProfile.objects.create(user=user, display_name="Second Player")


def test_display_name_is_normalized_before_save():
    user = create_user()
    profile = user.arena_profile

    profile.display_name = "  Ace   Player  "
    profile.save()

    assert profile.display_name == "Ace Player"


@pytest.mark.parametrize(
    "display_name",
    [
        "ab",
        "-bad-name",
        "bad-name-",
        "bad@example",
        "a" * 25,
    ],
)
def test_display_name_rejects_invalid_values(display_name):
    user = create_user()
    profile = user.arena_profile
    profile.display_name = display_name

    with pytest.raises(ValidationError):
        profile.full_clean()


def test_display_name_is_unique_case_insensitively():
    first_user = create_user(username="first", email="first@example.com")
    second_user = create_user(username="second", email="second@example.com")

    first_user.arena_profile.display_name = "Table Captain"
    first_user.arena_profile.save()
    second_user.arena_profile.display_name = "table captain"

    with pytest.raises(ValidationError):
        second_user.arena_profile.save()


def test_display_name_database_constraint_blocks_concurrent_duplicates():
    first_user = create_user(username="first", email="first@example.com")
    second_user = create_user(username="second", email="second@example.com")
    ArenaProfile.objects.filter(user__in=[first_user, second_user]).delete()

    profiles = [
        ArenaProfile(user=first_user, display_name="Mirror Name"),
        ArenaProfile(user=second_user, display_name="mirror name"),
    ]

    with pytest.raises(IntegrityError), transaction.atomic():
        ArenaProfile.objects.bulk_create(profiles)


def test_arena_profile_admin_is_registered_for_safe_inspection():
    assert admin.site.is_registered(ArenaProfile)

    model_admin = admin.site._registry[ArenaProfile]
    assert "public_id" in model_admin.readonly_fields
    assert "user" in model_admin.readonly_fields
    assert "user_email" in model_admin.list_display


def test_arena_profile_admin_requires_staff_access(client):
    create_user()

    response = client.get(reverse("admin:accounts_arenaprofile_changelist"))

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_arena_profile_admin_rejects_non_staff_users(client):
    user = create_user()
    client.force_login(user)

    response = client.get(reverse("admin:accounts_arenaprofile_changelist"))

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_arena_profile_admin_allows_superuser_inspection(client):
    user = get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="StrongPass123!",
    )
    client.force_login(user)

    response = client.get(reverse("admin:accounts_arenaprofile_changelist"))

    assert response.status_code == 200
    assert user.arena_profile.display_name.encode() in response.content


def test_arena_profile_does_not_add_deferred_game_profile_fields():
    field_names = {field.name for field in ArenaProfile._meta.get_fields()}

    assert "rating" not in field_names
    assert "balance" not in field_names
    assert "game_stats" not in field_names
