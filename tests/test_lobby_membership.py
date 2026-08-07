from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from games.engine import BaseGameEngine, GameTransition, InvalidGameConfiguration
from games.models import GameCategory, GameDefinition
from games.registry import GameEngineRegistry
from lobbies.models import (
    GameLobby,
    LobbyMembership,
    MembershipConnectionStatus,
    MembershipRole,
)


pytestmark = pytest.mark.django_db


class MembershipTestEngine(BaseGameEngine):
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
    registry.register("membership-test-engine", "1.0", MembershipTestEngine)
    monkeypatch.setattr("games.models.game_engine_registry", registry)
    monkeypatch.setattr("lobbies.models.game_engine_registry", registry)
    return registry


def category(slug="board-games"):
    return GameCategory.objects.get(slug=slug)


def create_user(username):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongPass123!",
    )


def create_playable_game(monkeypatch, **overrides):
    install_test_registry(monkeypatch)
    values = {
        "category": category(),
        "name": "Membership Test Game",
        "slug": "membership-test-game",
        "short_description": "A playable membership test game.",
        "engine_key": "membership-test-engine",
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


def create_lobby(monkeypatch, *, host=None, **overrides):
    game = create_playable_game(monkeypatch)
    host = host or create_user("host")
    values = {"game_configuration": {"rounds": 2}}
    values.update(overrides)
    return GameLobby.objects.create_for_host(host=host, game=game, **values)


def test_player_membership_creation_sets_defaults(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")

    membership = LobbyMembership.objects.create(
        lobby=lobby,
        user=player,
        role=MembershipRole.PLAYER,
        seat_number=1,
    )

    assert membership.user == player
    assert membership.bot_reference == ""
    assert membership.role == MembershipRole.PLAYER
    assert membership.seat_number == 1
    assert membership.is_ready is False
    assert membership.connection_status == MembershipConnectionStatus.OFFLINE
    assert membership.is_active is True
    assert membership.consumes_player_seat is True
    assert membership.can_be_ready is True
    assert membership.is_human is True
    assert membership.is_bot is False
    assert membership.score == 0
    assert membership.result == {}
    assert membership.metadata == {}


def test_spectator_membership_does_not_consume_player_seat(monkeypatch):
    lobby = create_lobby(monkeypatch)
    spectator = create_user("spectator")

    membership = LobbyMembership.objects.create(
        lobby=lobby,
        user=spectator,
        role=MembershipRole.SPECTATOR,
    )

    assert membership.seat_number is None
    assert membership.is_active is True
    assert membership.consumes_player_seat is False
    assert membership.can_be_ready is False
    assert list(LobbyMembership.objects.spectators()) == [membership]


def test_duplicate_active_user_membership_is_rejected(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    LobbyMembership.objects.create(
        lobby=lobby,
        user=player,
        role=MembershipRole.PLAYER,
        seat_number=1,
    )
    duplicate = LobbyMembership(
        lobby=lobby,
        user=player,
        role=MembershipRole.PLAYER,
        seat_number=2,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        LobbyMembership.objects.bulk_create([duplicate])


def test_inactive_membership_allows_user_to_rejoin_same_lobby(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    now = timezone.now()
    LobbyMembership.objects.create(
        lobby=lobby,
        user=player,
        role=MembershipRole.PLAYER,
        seat_number=1,
        joined_at=now - timedelta(minutes=10),
        left_at=now,
    )

    replacement = LobbyMembership.objects.create(
        lobby=lobby,
        user=player,
        role=MembershipRole.PLAYER,
        seat_number=1,
    )

    assert replacement.is_active is True
    assert LobbyMembership.objects.active().filter(user=player).count() == 1


def test_duplicate_active_seat_is_rejected(monkeypatch):
    lobby = create_lobby(monkeypatch)
    first_player = create_user("first-player")
    second_player = create_user("second-player")
    LobbyMembership.objects.create(
        lobby=lobby,
        user=first_player,
        role=MembershipRole.PLAYER,
        seat_number=1,
    )
    duplicate_seat = LobbyMembership(
        lobby=lobby,
        user=second_player,
        role=MembershipRole.PLAYER,
        seat_number=1,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        LobbyMembership.objects.bulk_create([duplicate_seat])


def test_only_one_active_host_is_allowed(monkeypatch):
    host = create_user("host")
    lobby = create_lobby(monkeypatch, host=host)
    LobbyMembership.objects.create(
        lobby=lobby,
        user=host,
        role=MembershipRole.HOST,
        seat_number=1,
    )
    second_host = LobbyMembership(
        lobby=lobby,
        user=create_user("second-host"),
        role=MembershipRole.HOST,
        seat_number=2,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        LobbyMembership.objects.bulk_create([second_host])


def test_bot_membership_requires_bot_reference_and_no_user(monkeypatch):
    lobby = create_lobby(monkeypatch)

    bot = LobbyMembership.objects.create(
        lobby=lobby,
        role=MembershipRole.BOT,
        bot_reference=" bot-alpha ",
        seat_number=1,
        is_ready=True,
    )

    assert bot.user is None
    assert bot.bot_reference == "bot-alpha"
    assert bot.is_bot is True
    assert bot.is_human is False
    assert list(LobbyMembership.objects.bots()) == [bot]

    missing_reference = LobbyMembership(
        lobby=lobby,
        role=MembershipRole.BOT,
        seat_number=2,
    )
    with pytest.raises(ValidationError) as missing_error:
        missing_reference.full_clean()
    assert "bot_reference" in missing_error.value.message_dict

    bot_with_user = LobbyMembership(
        lobby=lobby,
        user=create_user("bot-user"),
        role=MembershipRole.BOT,
        bot_reference="bot-beta",
        seat_number=2,
    )
    with pytest.raises(ValidationError) as user_error:
        bot_with_user.full_clean()
    assert "user" in user_error.value.message_dict


def test_human_membership_requires_user_and_rejects_bot_reference(monkeypatch):
    lobby = create_lobby(monkeypatch)

    missing_user = LobbyMembership(
        lobby=lobby,
        role=MembershipRole.PLAYER,
        seat_number=1,
    )
    with pytest.raises(ValidationError) as missing_error:
        missing_user.full_clean()
    assert "user" in missing_error.value.message_dict

    human_with_bot_reference = LobbyMembership(
        lobby=lobby,
        user=create_user("player"),
        role=MembershipRole.PLAYER,
        bot_reference="bot-alpha",
        seat_number=1,
    )
    with pytest.raises(ValidationError) as reference_error:
        human_with_bot_reference.full_clean()
    assert "bot_reference" in reference_error.value.message_dict


def test_host_membership_must_belong_to_lobby_host(monkeypatch):
    lobby = create_lobby(monkeypatch, host=create_user("real-host"))

    membership = LobbyMembership(
        lobby=lobby,
        user=create_user("not-host"),
        role=MembershipRole.HOST,
        seat_number=1,
    )

    with pytest.raises(ValidationError) as error:
        membership.full_clean()

    assert "user" in error.value.message_dict


def test_ready_status_applies_only_to_player_roles(monkeypatch):
    lobby = create_lobby(monkeypatch)
    spectator_ready = LobbyMembership(
        lobby=lobby,
        user=create_user("spectator"),
        role=MembershipRole.SPECTATOR,
        is_ready=True,
    )

    with pytest.raises(ValidationError) as error:
        spectator_ready.full_clean()

    assert "is_ready" in error.value.message_dict

    player_ready = LobbyMembership(
        lobby=lobby,
        user=create_user("player"),
        role=MembershipRole.PLAYER,
        seat_number=1,
        is_ready=True,
    )
    player_ready.full_clean()


def test_spectators_and_moderators_cannot_have_seats(monkeypatch):
    lobby = create_lobby(monkeypatch)

    for role in (MembershipRole.SPECTATOR, MembershipRole.MODERATOR):
        membership = LobbyMembership(
            lobby=lobby,
            user=create_user(f"{role}-user"),
            role=role,
            seat_number=1,
        )
        with pytest.raises(ValidationError) as error:
            membership.full_clean()

        assert "seat_number" in error.value.message_dict


def test_player_roles_require_seats_within_lobby_capacity(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")

    missing_seat = LobbyMembership(
        lobby=lobby,
        user=player,
        role=MembershipRole.PLAYER,
    )
    with pytest.raises(ValidationError) as missing_error:
        missing_seat.full_clean()
    assert "seat_number" in missing_error.value.message_dict

    too_large = LobbyMembership(
        lobby=lobby,
        user=player,
        role=MembershipRole.PLAYER,
        seat_number=lobby.maximum_players + 1,
    )
    with pytest.raises(ValidationError) as capacity_error:
        too_large.full_clean()
    assert "seat_number" in capacity_error.value.message_dict


def test_result_and_metadata_must_be_json_objects(monkeypatch):
    lobby = create_lobby(monkeypatch)
    membership = LobbyMembership(
        lobby=lobby,
        user=create_user("player"),
        role=MembershipRole.PLAYER,
        seat_number=1,
        result=[],
        metadata=[],
    )

    with pytest.raises(ValidationError) as error:
        membership.full_clean()

    assert "result" in error.value.message_dict
    assert "metadata" in error.value.message_dict


def test_left_or_kicked_membership_is_not_active(monkeypatch):
    lobby = create_lobby(monkeypatch)
    now = timezone.now()
    active = LobbyMembership.objects.create(
        lobby=lobby,
        user=create_user("active-player"),
        role=MembershipRole.PLAYER,
        seat_number=1,
    )
    left = LobbyMembership.objects.create(
        lobby=lobby,
        user=create_user("left-player"),
        role=MembershipRole.PLAYER,
        seat_number=2,
        joined_at=now - timedelta(minutes=10),
        left_at=now,
    )
    kicked = LobbyMembership.objects.create(
        lobby=lobby,
        user=create_user("kicked-player"),
        role=MembershipRole.PLAYER,
        seat_number=3,
        joined_at=now - timedelta(minutes=10),
        kicked_at=now,
    )

    assert active.is_active is True
    assert left.is_active is False
    assert kicked.is_active is False
    assert set(LobbyMembership.objects.active()) == {active}
    assert set(LobbyMembership.objects.inactive()) == {left, kicked}


def test_lobby_membership_admin_is_registered():
    assert admin.site.is_registered(LobbyMembership)
