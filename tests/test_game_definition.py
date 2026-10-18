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


def category(slug="board-games"):
    return GameCategory.objects.get(slug=slug)


def create_game(**overrides):
    values = {
        "category": category(),
        "name": "Test Game",
        "slug": "test-game",
        "short_description": "A short catalog description.",
        "full_description": "A longer catalog description.",
        "engine_key": "",
        "engine_version": "",
        "minimum_players": 2,
        "maximum_players": 4,
        "estimated_duration_minutes": 20,
        "supports_bots": False,
        "supports_spectators": False,
        "supports_ranked": False,
        "supports_private_lobbies": True,
        "supports_broadcasts": False,
        "difficulty_options": ["casual"],
        "rules": {"summary": "Rules are planned."},
        "default_configuration": {"rounds": 1},
        "thumbnail": "games/test-thumb.png",
        "banner": "games/test-banner.png",
        "is_playable": False,
        "is_featured": False,
        "is_active": True,
    }
    values.update(overrides)
    return GameDefinition.objects.create(**values)


def create_superuser():
    return get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="StrongPass123!",
    )


def test_initial_game_definitions_are_seeded_as_unplayable_catalog_entries():
    expected = {
        "connect4": ("Connect4", "board-games"),
        "hangman": ("Hangman", "word-games"),
        "werewolves-vs-villagers": ("Werewolves vs Villagers", "deduction-games"),
    }

    games = {
        game.slug: game
        for game in GameDefinition.objects.filter(slug__in=expected)
        .select_related("category")
    }

    assert set(games) == set(expected)
    for slug, (name, category_slug) in expected.items():
        game = games[slug]
        assert game.name == name
        assert game.category.slug == category_slug
        assert game.is_active is True
        assert game.is_playable is False
        assert game.engine_key
        assert game.engine_version
    assert games["connect4"].supports_bots is True
    assert games["connect4"].difficulty_options == ["casual"]


def test_game_definition_creation_normalizes_name_and_slug():
    game = create_game(
        name="  Grid   Duel  ",
        slug="  Grid Duel! ",
    )

    assert game.name == "Grid Duel"
    assert game.slug == "grid-duel"
    assert isinstance(game.public_id, uuid.UUID)
    assert game.minimum_players == 2
    assert game.maximum_players == 4
    assert game.estimated_duration_minutes == 20
    assert game.supports_private_lobbies is True
    assert str(game) == "Grid Duel"


def test_game_definition_generates_slug_from_name_when_blank():
    game = create_game(name="Future Classic", slug="")

    assert game.slug == "future-classic"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minimum_players", 0),
        ("maximum_players", 1),
        ("estimated_duration_minutes", -1),
    ],
)
def test_game_definition_rejects_invalid_player_range_and_duration(field, value):
    game = GameDefinition(
        category=category(),
        name="Invalid Game",
        slug=f"invalid-{field}",
        short_description="Invalid metadata.",
        minimum_players=2,
        maximum_players=4,
        estimated_duration_minutes=10,
    )
    setattr(game, field, value)

    with pytest.raises(ValidationError) as error:
        game.full_clean()

    assert field in error.value.message_dict


def test_database_constraints_block_invalid_player_range_and_duration():
    invalid_games = [
        GameDefinition(
            category=category(),
            name="Zero Minimum",
            slug="zero-minimum",
            short_description="Invalid.",
            minimum_players=0,
            maximum_players=2,
        ),
        GameDefinition(
            category=category(),
            name="Impossible Range",
            slug="impossible-range",
            short_description="Invalid.",
            minimum_players=4,
            maximum_players=2,
        ),
        GameDefinition(
            category=category(),
            name="Negative Duration",
            slug="negative-duration",
            short_description="Invalid.",
            minimum_players=1,
            maximum_players=2,
            estimated_duration_minutes=-1,
        ),
    ]

    for game in invalid_games:
        with pytest.raises(IntegrityError), transaction.atomic():
            GameDefinition.objects.bulk_create([game])


def test_game_definition_rejects_duplicate_slugs_case_insensitively():
    create_game(name="Puzzle One", slug="puzzle-game")

    duplicate = GameDefinition(
        category=category(),
        name="Puzzle Two",
        slug="PUZZLE-GAME",
        short_description="Duplicate.",
    )

    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_database_constraint_blocks_concurrent_duplicate_slugs():
    games = [
        GameDefinition(
            category=category(),
            name="Mirror One",
            slug="mirror-game",
            short_description="Duplicate.",
        ),
        GameDefinition(
            category=category(),
            name="Mirror Two",
            slug="MIRROR-GAME",
            short_description="Duplicate.",
        ),
    ]

    with pytest.raises(IntegrityError), transaction.atomic():
        GameDefinition.objects.bulk_create(games)


def test_public_catalog_query_returns_only_active_games():
    active = create_game(name="Visible Game", slug="visible-game", is_active=True)
    inactive = create_game(name="Hidden Game", slug="hidden-game", is_active=False)

    public_games = GameDefinition.objects.public_catalog()

    assert active in public_games
    assert inactive not in public_games


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("difficulty_options", {"easy": True}),
        ("difficulty_options", ["standard", ""]),
        ("rules", []),
        ("default_configuration", []),
    ],
)
def test_game_definition_validates_json_metadata_before_save(field, value):
    values = {
        "category": category(),
        "name": f"Invalid JSON {field}",
        "slug": f"invalid-json-{field.replace('_', '-')}",
        "short_description": "Invalid JSON metadata.",
        "minimum_players": 1,
        "maximum_players": 2,
    }
    values[field] = value
    game = GameDefinition(**values)

    with pytest.raises(ValidationError) as error:
        game.full_clean()

    assert field in error.value.message_dict


def test_game_definition_blocks_playable_games_without_engine_key():
    game = GameDefinition(
        category=category(),
        name="Playable Without Engine",
        slug="playable-without-engine",
        short_description="Invalid playable metadata.",
        minimum_players=1,
        maximum_players=2,
        is_playable=True,
    )

    with pytest.raises(ValidationError) as error:
        game.full_clean()

    assert "engine_key" in error.value.message_dict


def test_database_constraint_blocks_playable_games_without_engine_key():
    game = GameDefinition(
        category=category(),
        name="DB Playable Without Engine",
        slug="db-playable-without-engine",
        short_description="Invalid playable metadata.",
        minimum_players=1,
        maximum_players=2,
        is_playable=True,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        GameDefinition.objects.bulk_create([game])


def test_game_definition_blocks_playable_games_without_registered_engine():
    game = GameDefinition(
        category=category(),
        name="Unregistered Engine",
        slug="unregistered-engine",
        short_description="Invalid playable metadata.",
        engine_key="missing-engine",
        engine_version="1.0",
        minimum_players=1,
        maximum_players=2,
        is_playable=True,
    )

    with pytest.raises(ValidationError) as error:
        game.full_clean()

    assert "is_playable" in error.value.message_dict


def test_game_definition_allows_playable_game_when_engine_is_registered(monkeypatch):
    monkeypatch.setattr(
        "games.models.is_registered_game_engine",
        lambda engine_key, engine_version: (
            engine_key == "registered-engine" and engine_version == "1.0"
        ),
    )

    game = create_game(
        name="Registered Engine",
        slug="registered-engine",
        engine_key="registered-engine",
        engine_version="1.0",
        minimum_players=1,
        maximum_players=2,
        is_playable=True,
    )

    assert game.is_playable is True


def test_initial_games_are_not_marked_playable_without_registered_engines():
    assert not GameDefinition.objects.filter(is_playable=True).exists()


def test_game_definition_admin_is_registered_for_catalog_management():
    assert admin.site.is_registered(GameDefinition)

    model_admin = admin.site._registry[GameDefinition]
    assert "category" in model_admin.list_filter
    assert "is_playable" in model_admin.list_filter
    assert "public_id" in model_admin.readonly_fields
    assert model_admin.prepopulated_fields == {"slug": ("name",)}
    assert len(model_admin.actions) == 4


def test_game_definition_admin_requires_staff_access(client):
    response = client.get(reverse("admin:games_gamedefinition_changelist"))

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_game_definition_admin_rejects_non_staff_users(client):
    user = get_user_model().objects.create_user(
        username="player",
        email="player@example.com",
        password="StrongPass123!",
    )
    client.force_login(user)

    response = client.get(reverse("admin:games_gamedefinition_changelist"))

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_game_definition_admin_allows_superuser_to_create_unimplemented_game(client):
    client.force_login(create_superuser())

    response = client.post(
        reverse("admin:games_gamedefinition_add"),
        {
            "category": str(category("party-games").pk),
            "name": "Charades",
            "slug": "",
            "short_description": "Act prompts for teammates.",
            "full_description": "A future party game.",
            "engine_key": "charades",
            "engine_version": "0.1",
            "minimum_players": "2",
            "maximum_players": "12",
            "estimated_duration_minutes": "20",
            "supports_private_lobbies": "on",
            "difficulty_options": '["standard"]',
            "rules": '{"status": "planned"}',
            "default_configuration": '{"rounds": 3}',
            "thumbnail": "",
            "banner": "",
            "is_active": "on",
            "_save": "Save",
        },
    )

    assert response.status_code == 302
    game = GameDefinition.objects.get(slug="charades")
    assert game.name == "Charades"
    assert game.is_playable is False


def test_game_definition_protects_category_deletion():
    game = create_game(name="Category Guard", slug="category-guard")

    with pytest.raises(ProtectedError):
        game.category.delete()

    assert GameCategory.objects.filter(pk=game.category_id).exists()


def test_game_definition_indexes_cover_public_catalog_queries():
    index_fields = {
        tuple(index.fields)
        for index in GameDefinition._meta.indexes
    }

    assert ("slug",) in index_fields
    assert ("category",) in index_fields
    assert ("is_active",) in index_fields
    assert ("is_playable",) in index_fields
    assert ("is_featured",) in index_fields


def test_game_definition_does_not_add_lobby_or_engine_implementations():
    field_names = {field.name for field in GameDefinition._meta.get_fields()}

    assert "lobby_code" not in field_names
    assert "state" not in field_names
    assert "player_seats" not in field_names
