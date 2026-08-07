import os
import uuid

import pytest


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.test_settings")

import django
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse


django.setup()

from games.models import GameCategory, GameDefinition


pytestmark = pytest.mark.django_db


def create_superuser():
    return get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="StrongPass123!",
    )


def test_initial_game_categories_are_seeded():
    expected = {
        "board-games": "Board Games",
        "word-games": "Word Games",
        "deduction-games": "Deduction Games",
        "trivia-games": "Trivia Games",
        "party-games": "Party Games",
    }

    categories = {
        category.slug: category
        for category in GameCategory.objects.filter(slug__in=expected)
    }

    assert set(categories) == set(expected)
    for slug, name in expected.items():
        assert categories[slug].name == name
        assert categories[slug].is_active is True


def test_game_category_creation_normalizes_name_and_generates_slug():
    category = GameCategory.objects.create(
        name="  Classic   Strategy  ",
        description="Turn based classics.",
        display_order=15,
    )

    assert category.name == "Classic Strategy"
    assert category.slug == "classic-strategy"
    assert isinstance(category.public_id, uuid.UUID)
    assert category.is_active is True
    assert category.description == "Turn based classics."
    assert category.created_at is not None
    assert str(category) == "Classic Strategy"


def test_game_category_normalizes_explicit_slug():
    category = GameCategory.objects.create(
        name="Arcade Games",
        slug="  Arcade Classics! ",
    )

    assert category.slug == "arcade-classics"


def test_game_category_rejects_blank_name_and_slug():
    category = GameCategory(name=" !!! ")

    with pytest.raises(ValidationError) as error:
        category.full_clean()

    assert "slug" in error.value.message_dict or "__all__" in error.value.message_dict


def test_game_category_rejects_duplicate_names_case_insensitively():
    GameCategory.objects.create(name="Strategy Games")

    duplicate = GameCategory(name="strategy games")

    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_game_category_database_constraint_blocks_concurrent_duplicate_names():
    categories = [
        GameCategory(name="Mirror Category", slug="mirror-category-one"),
        GameCategory(name="mirror category", slug="mirror-category-two"),
    ]

    with pytest.raises(IntegrityError), transaction.atomic():
        GameCategory.objects.bulk_create(categories)


def test_game_category_rejects_duplicate_slugs_case_insensitively():
    GameCategory.objects.create(name="Puzzle Games", slug="brain-games")

    duplicate = GameCategory(name="Brain Games", slug="BRAIN-GAMES")

    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_game_category_database_constraint_blocks_concurrent_duplicate_slugs():
    categories = [
        GameCategory(name="Fast Games", slug="quick-games"),
        GameCategory(name="Quick Games", slug="QUICK-GAMES"),
    ]

    with pytest.raises(IntegrityError), transaction.atomic():
        GameCategory.objects.bulk_create(categories)


def test_public_catalog_query_returns_only_active_categories():
    active = GameCategory.objects.create(name="Active Games", display_order=1)
    inactive = GameCategory.objects.create(
        name="Hidden Games",
        display_order=2,
        is_active=False,
    )

    public_categories = GameCategory.objects.public_catalog()

    assert active in public_categories
    assert inactive not in public_categories


def test_game_category_admin_is_registered_for_catalog_management():
    assert admin.site.is_registered(GameCategory)

    model_admin = admin.site._registry[GameCategory]
    assert "display_order" in model_admin.list_editable
    assert "is_active" in model_admin.list_editable
    assert "public_id" in model_admin.readonly_fields
    assert model_admin.prepopulated_fields == {"slug": ("name",)}
    assert len(model_admin.actions) == 2


def test_game_category_admin_requires_staff_access(client):
    response = client.get(reverse("admin:games_gamecategory_changelist"))

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_game_category_admin_rejects_non_staff_users(client):
    user = get_user_model().objects.create_user(
        username="player",
        email="player@example.com",
        password="StrongPass123!",
    )
    client.force_login(user)

    response = client.get(reverse("admin:games_gamecategory_changelist"))

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_game_category_admin_can_create_edit_reorder_and_deactivate(client):
    client.force_login(create_superuser())

    add_response = client.post(
        reverse("admin:games_gamecategory_add"),
        {
            "name": "Family Games",
            "slug": "",
            "description": "Friendly group games.",
            "icon": "users",
            "display_order": "60",
            "is_active": "on",
            "_save": "Save",
        },
    )

    assert add_response.status_code == 302
    category = GameCategory.objects.get(slug="family-games")
    assert category.is_active is True

    change_response = client.post(
        reverse("admin:games_gamecategory_change", args=[category.pk]),
        {
            "name": "Family Table Games",
            "slug": "family-table-games",
            "description": "Friendly table games.",
            "icon": "users-round",
            "display_order": "5",
            "_save": "Save",
        },
    )

    assert change_response.status_code == 302
    category.refresh_from_db()
    assert category.name == "Family Table Games"
    assert category.display_order == 5
    assert category.is_active is False


def test_game_category_delete_is_blocked_when_related_games_exist():
    category = GameCategory.objects.create(name="Protected Category")
    GameDefinition.objects.create(
        category=category,
        name="Protected Game",
        slug="protected-game",
        short_description="A protected game.",
        minimum_players=1,
        maximum_players=2,
    )

    with pytest.raises(ProtectedError):
        category.delete()

    assert GameCategory.objects.filter(pk=category.pk).exists()


def test_game_category_delete_allows_empty_categories():
    category = GameCategory.objects.create(name="Empty Category")
    pk = category.pk

    category.delete()

    assert not GameCategory.objects.filter(pk=pk).exists()


def test_game_category_does_not_add_deferred_game_definition_fields():
    field_names = {field.name for field in GameCategory._meta.get_fields()}

    assert "engine_key" not in field_names
    assert "minimum_players" not in field_names
    assert "maximum_players" not in field_names
    assert "is_playable" not in field_names
