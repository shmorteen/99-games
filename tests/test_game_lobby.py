import re
import uuid

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from games.engine import BaseGameEngine, GameTransition, InvalidGameConfiguration
from games.models import GameCategory, GameDefinition
from games.registry import GameEngineRegistry
from lobbies.models import GameLobby, LobbyStatus, LobbyVisibility


pytestmark = pytest.mark.django_db


class LobbyTestEngine(BaseGameEngine):
    def validate_config(self, config):
        rounds = config.get("rounds", 1)
        if not isinstance(rounds, int) or rounds < 1:
            raise InvalidGameConfiguration("rounds must be a positive integer.")

    def create_initial_state(self, config, actors):
        return {"rounds": config.get("rounds", 1), "complete": False}

    def get_public_state(self, state):
        return {"complete": state["complete"]}

    def get_spectator_state(self, state):
        return {"complete": state["complete"]}

    def get_private_state(self, state, actor_id):
        return {"actor_id": actor_id}

    def legal_actions(self, state, actor_id):
        return [{"type": "noop"}]

    def apply_action(
        self,
        state,
        actor_id,
        action,
        *,
        idempotency_key=None,
        state_version=None,
    ):
        return GameTransition(state=dict(state), events=[])

    def handle_timeout(self, state, actor_id=None):
        return GameTransition(state=dict(state), events=[])

    def bot_action(self, state, actor_id, *, difficulty=None):
        return {"type": "noop"}

    def is_complete(self, state):
        return bool(state["complete"])

    def build_results(self, state):
        return {"complete": self.is_complete(state)}


def install_test_registry(monkeypatch):
    registry = GameEngineRegistry()
    registry.register("lobby-test-engine", "1.0", LobbyTestEngine)
    monkeypatch.setattr("games.models.game_engine_registry", registry)
    monkeypatch.setattr("lobbies.models.game_engine_registry", registry)
    return registry


def category(slug="board-games"):
    return GameCategory.objects.get(slug=slug)


def create_user(username="host"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongPass123!",
    )


def create_playable_game(monkeypatch, **overrides):
    install_test_registry(monkeypatch)
    values = {
        "category": category(),
        "name": "Lobby Test Game",
        "slug": "lobby-test-game",
        "short_description": "A playable lobby test game.",
        "engine_key": "lobby-test-engine",
        "engine_version": "1.0",
        "minimum_players": 2,
        "maximum_players": 4,
        "estimated_duration_minutes": 15,
        "supports_bots": True,
        "supports_spectators": True,
        "supports_ranked": True,
        "supports_private_lobbies": True,
        "difficulty_options": ["easy", "standard"],
        "default_configuration": {"rounds": 2},
        "is_playable": True,
        "is_active": True,
    }
    values.update(overrides)
    return GameDefinition.objects.create(**values)


def build_lobby(game, host, **overrides):
    values = {
        "game": game,
        "host": host,
        "name": "  Test   Lobby  ",
        "minimum_players": game.minimum_players,
        "maximum_players": game.maximum_players,
        "game_configuration": {"rounds": 2},
    }
    values.update(overrides)
    return GameLobby(**values)


def test_game_lobby_valid_creation_sets_required_metadata(monkeypatch):
    game = create_playable_game(monkeypatch)
    host = create_user()

    lobby = GameLobby.objects.create_for_host(host=host, game=game)

    assert isinstance(lobby.public_id, uuid.UUID)
    assert re.fullmatch(r"[A-Z0-9]{8}", lobby.lobby_code)
    assert lobby.name == "Lobby Test Game Lobby"
    assert lobby.game == game
    assert lobby.host == host
    assert lobby.visibility == LobbyVisibility.PUBLIC
    assert lobby.status == LobbyStatus.WAITING
    assert lobby.minimum_players == 2
    assert lobby.maximum_players == 4
    assert lobby.game_configuration == {"rounds": 2}
    assert str(lobby) == f"{lobby.name} ({lobby.lobby_code})"


def test_lobby_creation_rejects_unauthenticated_or_unsaved_hosts(monkeypatch):
    game = create_playable_game(monkeypatch)

    with pytest.raises(PermissionDenied):
        GameLobby.objects.create_for_host(host=AnonymousUser(), game=game)

    unsaved_user = get_user_model()(username="unsaved")
    with pytest.raises(ValidationError) as error:
        GameLobby.objects.create_for_host(host=unsaved_user, game=game)

    assert "host" in error.value.message_dict


def test_lobby_rejects_unplayable_and_inactive_games(monkeypatch):
    host = create_user()
    unplayable_game = GameDefinition.objects.create(
        category=category(),
        name="Unplayable Lobby Game",
        slug="unplayable-lobby-game",
        short_description="Not playable.",
        engine_key="future-game",
        engine_version="1.0",
        minimum_players=2,
        maximum_players=4,
        is_playable=False,
    )
    inactive_game = create_playable_game(
        monkeypatch,
        name="Inactive Lobby Game",
        slug="inactive-lobby-game",
        is_active=False,
    )

    for game in (unplayable_game, inactive_game):
        lobby = build_lobby(game, host)
        with pytest.raises(ValidationError) as error:
            lobby.full_clean()

        assert "game" in error.value.message_dict


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"minimum_players": 0}, "minimum_players"),
        ({"minimum_players": 1}, "minimum_players"),
        ({"minimum_players": 3, "maximum_players": 2}, "maximum_players"),
        ({"maximum_players": 5}, "maximum_players"),
    ],
)
def test_lobby_rejects_invalid_player_ranges(monkeypatch, overrides, field):
    game = create_playable_game(monkeypatch)
    host = create_user()
    lobby = build_lobby(game, host, **overrides)

    with pytest.raises(ValidationError) as error:
        lobby.full_clean()

    assert field in error.value.message_dict


def test_lobby_rejects_ranked_when_game_does_not_support_ranked(monkeypatch):
    game = create_playable_game(
        monkeypatch,
        name="Unranked Game",
        slug="unranked-game",
        supports_ranked=False,
    )
    lobby = build_lobby(game, create_user(), is_ranked=True)

    with pytest.raises(ValidationError) as error:
        lobby.full_clean()

    assert "is_ranked" in error.value.message_dict


def test_lobby_rejects_spectators_when_game_does_not_support_spectators(monkeypatch):
    game = create_playable_game(
        monkeypatch,
        name="No Spectators Game",
        slug="no-spectators-game",
        supports_spectators=False,
    )
    lobby = build_lobby(game, create_user(), allow_spectators=True, spectator_limit=10)

    with pytest.raises(ValidationError) as error:
        lobby.full_clean()

    assert "allow_spectators" in error.value.message_dict


def test_lobby_rejects_bots_when_game_does_not_support_bots(monkeypatch):
    game = create_playable_game(
        monkeypatch,
        name="No Bots Game",
        slug="no-bots-game",
        supports_bots=False,
    )
    lobby = build_lobby(
        game,
        create_user(),
        allow_bot_fill=True,
        bot_difficulty="standard",
    )

    with pytest.raises(ValidationError) as error:
        lobby.full_clean()

    assert "allow_bot_fill" in error.value.message_dict


def test_lobby_rejects_invalid_bot_difficulty(monkeypatch):
    game = create_playable_game(monkeypatch)
    lobby = build_lobby(
        game,
        create_user(),
        allow_bot_fill=True,
        bot_difficulty="impossible",
    )

    with pytest.raises(ValidationError) as error:
        lobby.full_clean()

    assert "bot_difficulty" in error.value.message_dict


def test_lobby_code_is_unique_at_database_level(monkeypatch):
    game = create_playable_game(monkeypatch)
    host = create_user()
    GameLobby.objects.create_for_host(
        host=host,
        game=game,
        name="First Lobby",
        lobby_code="ABC123",
    )
    duplicate = GameLobby(
        host=host,
        game=game,
        name="Duplicate Lobby",
        lobby_code="ABC123",
        minimum_players=2,
        maximum_players=4,
        game_configuration={"rounds": 2},
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        GameLobby.objects.bulk_create([duplicate])


def test_lobby_passwords_are_hashed_and_checkable(monkeypatch):
    game = create_playable_game(monkeypatch)
    lobby = build_lobby(game, create_user())

    lobby.set_password("correct horse battery staple")

    assert lobby.password_hash
    assert "correct horse battery staple" not in lobby.password_hash
    assert lobby.check_password("correct horse battery staple") is True
    assert lobby.check_password("wrong") is False


def test_lobby_rejects_plain_text_password_hash(monkeypatch):
    game = create_playable_game(monkeypatch)
    lobby = build_lobby(game, create_user(), password_hash="plain-text-password")

    with pytest.raises(ValidationError) as error:
        lobby.full_clean()

    assert "password_hash" in error.value.message_dict


def test_lobby_configuration_is_validated_by_selected_engine(monkeypatch):
    game = create_playable_game(monkeypatch)
    lobby = build_lobby(game, create_user(), game_configuration={"rounds": 0})

    with pytest.raises(ValidationError) as error:
        lobby.full_clean()

    assert "game_configuration" in error.value.message_dict


def test_lobby_rejects_invalid_json_metadata(monkeypatch):
    game = create_playable_game(monkeypatch)
    lobby = build_lobby(
        game,
        create_user(),
        game_configuration=[],
        invite_token_metadata=[],
    )

    with pytest.raises(ValidationError) as error:
        lobby.full_clean()

    assert "game_configuration" in error.value.message_dict
    assert "invite_token_metadata" in error.value.message_dict


def test_game_lobby_admin_is_registered():
    assert admin.site.is_registered(GameLobby)
