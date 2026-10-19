import os

import pytest


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.test_settings")

import django
from django.urls import reverse


django.setup()

from games.models import GameCategory, GameDefinition


pytestmark = pytest.mark.django_db


def category(slug="board-games"):
    return GameCategory.objects.get(slug=slug)


def create_game(**overrides):
    values = {
        "category": category(),
        "name": "Catalog Test Game",
        "slug": "catalog-test-game",
        "short_description": "A visible catalog test game.",
        "full_description": "A complete description for the catalog detail page.",
        "engine_key": "catalog-test-game",
        "engine_version": "0.1",
        "minimum_players": 2,
        "maximum_players": 4,
        "estimated_duration_minutes": 20,
        "supports_bots": False,
        "supports_spectators": False,
        "supports_ranked": False,
        "supports_private_lobbies": True,
        "supports_broadcasts": False,
        "difficulty_options": ["casual"],
        "rules": {"summary": "Capture the center."},
        "default_configuration": {"rounds": 1},
        "thumbnail": "games/catalog-test-thumb.png",
        "banner": "games/catalog-test-banner.png",
        "is_playable": False,
        "is_featured": False,
        "is_active": True,
    }
    values.update(overrides)
    return GameDefinition.objects.create(**values)


def assert_contains(response, text):
    assert text.encode() in response.content


def assert_not_contains(response, text):
    assert text.encode() not in response.content


def test_catalog_page_loads_for_anonymous_users_and_lists_seeded_games(client):
    response = client.get(reverse("games:catalog"))

    assert response.status_code == 200
    assert_contains(response, "Game Catalog")
    assert_contains(response, "Connect4")
    assert_contains(response, "Hangman")
    assert_contains(response, "Werewolves vs Villagers")
    assert_contains(response, "Coming Soon")


def test_catalog_cards_show_required_game_metadata(client):
    game = create_game(
        name="Feature Matrix",
        slug="feature-matrix",
        supports_bots=True,
        supports_spectators=True,
        supports_ranked=True,
        is_featured=True,
    )

    response = client.get(reverse("games:catalog"))

    assert response.status_code == 200
    for text in (
        game.name,
        game.category.name,
        game.thumbnail,
        game.short_description,
        "2-4 players",
        "20 min",
        "Bots",
        "Spectators",
        "Ranked",
        "Coming Soon",
    ):
        assert_contains(response, text)


def test_search_filter_matches_name_and_description(client):
    create_game(name="Orbital Tactics", slug="orbital-tactics")
    create_game(
        name="Quiet Cards",
        slug="quiet-cards",
        short_description="A matching nebula clue.",
    )

    response = client.get(reverse("games:catalog"), {"q": "nebula"})

    assert response.status_code == 200
    assert_contains(response, "Quiet Cards")
    assert_not_contains(response, "Orbital Tactics")


def test_category_filter_on_catalog_page(client):
    create_game(name="Board Filter", slug="board-filter", category=category("board-games"))
    create_game(name="Word Filter", slug="word-filter", category=category("word-games"))

    response = client.get(reverse("games:catalog"), {"category": "word-games"})

    assert response.status_code == 200
    assert_contains(response, "Word Filter")
    assert_not_contains(response, "Board Filter")


def test_player_duration_bot_and_playable_filters(client, monkeypatch):
    monkeypatch.setattr("games.models.is_registered_game_engine", lambda *args: True)
    create_game(
        name="Playable Bot Sprint",
        slug="playable-bot-sprint",
        minimum_players=2,
        maximum_players=6,
        estimated_duration_minutes=15,
        supports_bots=True,
        is_playable=True,
        engine_key="playable-bot-sprint",
        engine_version="1.0",
    )
    create_game(
        name="Slow Human Only",
        slug="slow-human-only",
        minimum_players=2,
        maximum_players=4,
        estimated_duration_minutes=90,
        supports_bots=False,
    )

    response = client.get(
        reverse("games:catalog"),
        {
            "min_players": "5",
            "max_duration": "30",
            "bots": "1",
            "playable": "1",
        },
    )

    assert response.status_code == 200
    assert_contains(response, "Playable Bot Sprint")
    assert_not_contains(response, "Slow Human Only")


def test_invalid_filter_values_do_not_raise_server_errors(client):
    response = client.get(
        reverse("games:catalog"),
        {
            "category": "missing-category",
            "min_players": "nope",
            "max_duration": "-5",
            "page": "not-a-page",
        },
    )

    assert response.status_code == 200
    assert_contains(response, "Game Catalog")


def test_inactive_games_and_inactive_category_games_are_hidden(client):
    inactive_category = GameCategory.objects.create(
        name="Dormant Category",
        slug="dormant-category",
        is_active=False,
    )
    create_game(name="Hidden Game", slug="hidden-game", is_active=False)
    create_game(
        name="Inactive Category Game",
        slug="inactive-category-game",
        category=inactive_category,
        is_active=True,
    )

    response = client.get(reverse("games:catalog"))

    assert response.status_code == 200
    assert_not_contains(response, "Hidden Game")
    assert_not_contains(response, "Inactive Category Game")
    assert_not_contains(response, "Dormant Category")


def test_coming_soon_games_do_not_display_lobby_creation_actions(client):
    create_game(name="Future Table", slug="future-table", is_playable=False)

    response = client.get(reverse("games:detail", args=["future-table"]))

    assert response.status_code == 200
    assert_contains(response, "Coming Soon")
    assert_contains(response, "Lobby actions unlock when this game becomes playable.")
    assert_not_contains(response, "Create Lobby")
    assert_not_contains(response, "Quick Match")


def test_playable_games_display_expected_actions(client, monkeypatch):
    monkeypatch.setattr("games.models.is_registered_game_engine", lambda *args: True)
    create_game(
        name="Playable Actions",
        slug="playable-actions",
        engine_key="playable-actions",
        engine_version="1.0",
        is_playable=True,
    )

    response = client.get(reverse("games:detail", args=["playable-actions"]))

    assert response.status_code == 200
    assert_contains(response, "Create Lobby")
    assert_contains(response, reverse("lobbies:create", args=["playable-actions"]))
    assert_not_contains(response, "Find Lobby")
    assert_not_contains(response, "Quick Match")
    assert_contains(response, "View Rules")


def test_game_detail_page_displays_rules_configuration_and_features(client):
    create_game(
        name="Detail Arena",
        slug="detail-arena",
        full_description="A full detail description.",
        rules={"objective": "Hold the arena", "turns": 5},
        default_configuration={"rounds": 3, "timer_seconds": 60},
        difficulty_options=["casual", "ranked"],
        supports_bots=True,
        supports_spectators=True,
        supports_ranked=True,
        supports_broadcasts=True,
    )

    response = client.get(reverse("games:detail", args=["detail-arena"]))

    assert response.status_code == 200
    for text in (
        "A full detail description.",
        "Hold the arena",
        "rounds",
        "3",
        "Open public lobbies",
        "0",
        "2-4 players",
        "Bot Support",
        "Spectator Support",
        "Ranked",
        "Broadcast",
    ):
        assert_contains(response, text)


def test_missing_and_inactive_game_detail_pages_return_404(client):
    inactive = create_game(name="Inactive Detail", slug="inactive-detail", is_active=False)

    missing_response = client.get(reverse("games:detail", args=["missing-game"]))
    inactive_response = client.get(reverse("games:detail", args=[inactive.slug]))

    assert missing_response.status_code == 404
    assert inactive_response.status_code == 404


def test_category_page_lists_only_games_for_active_category(client):
    create_game(name="Board Category Page", slug="board-category-page", category=category("board-games"))
    create_game(name="Word Category Page", slug="word-category-page", category=category("word-games"))

    response = client.get(reverse("games:category", args=["board-games"]))

    assert response.status_code == 200
    assert_contains(response, "Board Games")
    assert_contains(response, "Board Category Page")
    assert_not_contains(response, "Word Category Page")


def test_missing_and_inactive_category_pages_return_404(client):
    inactive = GameCategory.objects.create(
        name="Inactive Public Category",
        slug="inactive-public-category",
        is_active=False,
    )

    missing_response = client.get(reverse("games:category", args=["missing-category"]))
    inactive_response = client.get(reverse("games:category", args=[inactive.slug]))

    assert missing_response.status_code == 404
    assert inactive_response.status_code == 404


def test_catalog_pagination_limits_large_result_sets(client):
    for index in range(14):
        create_game(
            name=f"Paged Game {index:02d}",
            slug=f"paged-game-{index:02d}",
            is_featured=index == 0,
        )

    first_page = client.get(reverse("games:catalog"))
    second_page = client.get(reverse("games:catalog"), {"page": "2"})

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert len(first_page.context["page_obj"].object_list) == 12
    assert second_page.context["page_obj"].number == 2
    assert_contains(first_page, "Next")


def test_catalog_pagination_preserves_active_filters(client):
    for index in range(14):
        create_game(
            name=f"Filtered Paged Game {index:02d}",
            slug=f"filtered-paged-game-{index:02d}",
            supports_bots=True,
        )

    response = client.get(
        reverse("games:catalog"),
        {"q": "Filtered", "bots": "1"},
    )

    assert response.status_code == 200
    assert_contains(response, "q=Filtered&amp;bots=1&amp;page=2")


def test_catalog_templates_include_responsive_viewport_and_layout(client):
    response = client.get(reverse("games:catalog"))

    assert response.status_code == 200
    assert_contains(response, '<meta name="viewport" content="width=device-width, initial-scale=1">')
    assert_contains(response, "catalog-grid")
    assert_contains(response, "@media")
