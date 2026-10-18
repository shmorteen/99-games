from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from games.engine import BaseGameEngine, GameTransition, InvalidGameConfiguration
from games.models import GameCategory, GameDefinition
from games.registry import GameEngineRegistry
from ksa_games.asgi import application
from lobbies.models import (
    GameLobby,
    LobbyAuditEvent,
    LobbyAuditEventType,
    LobbyMembership,
    LobbyStatus,
    MembershipRole,
)
from lobbies.locks import LobbyStartLockUnavailable
from lobbies.services import (
    LobbyAccessDenied,
    LobbyNotJoinable,
    LobbyStartConflict,
    LobbyStartError,
    begin_ready_check,
    expire_ready_check,
    join_lobby,
    set_membership_ready,
    start_game,
)
from play.models import GameSession, GameSessionParticipant


pytestmark = pytest.mark.django_db(transaction=True)


class ReadyCheckEngine(BaseGameEngine):
    def validate_config(self, config):
        rounds = config.get("rounds", 1)
        if not isinstance(rounds, int) or rounds < 1:
            raise InvalidGameConfiguration("rounds must be a positive integer.")

    def create_initial_state(self, config, actors):
        return {
            "rounds": config.get("rounds", 1),
            "actors": [actor["actor_id"] for actor in actors],
            "private_by_actor": {
                actor["actor_id"]: f"secret-{actor['seat_number']}"
                for actor in actors
            },
        }

    def get_public_state(self, state):
        return {"actors": state["actors"], "rounds": state["rounds"]}

    def get_spectator_state(self, state):
        return {"actors": state["actors"]}

    def get_private_state(self, state, actor_id):
        return {"secret": state["private_by_actor"][actor_id]}

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
        return False

    def build_results(self, state):
        return {"complete": False}


class FailingInitialStateEngine(ReadyCheckEngine):
    def create_initial_state(self, config, actors):
        raise RuntimeError("engine exploded")


class EmptyPrivateStateEngine(ReadyCheckEngine):
    def get_private_state(self, state, actor_id):
        return {}


@contextmanager
def recording_lock(calls):
    calls.append("acquired")
    yield
    calls.append("released")


def run(coro):
    return async_to_sync(coro)()


def install_test_registry(monkeypatch, engine_class=ReadyCheckEngine):
    registry = GameEngineRegistry()
    registry.register("ready-check-test-engine", "1.0", engine_class)
    monkeypatch.setattr("games.models.game_engine_registry", registry)
    monkeypatch.setattr("lobbies.models.game_engine_registry", registry)
    monkeypatch.setattr("lobbies.services.game_engine_registry", registry)
    return registry


def category(slug="board-games"):
    category, _ = GameCategory.objects.get_or_create(
        slug=slug,
        defaults={
            "name": "Board Games",
            "description": "Tabletop-inspired strategy and grid games.",
            "display_order": 10,
            "is_active": True,
        },
    )
    return category


def create_user(username):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongPass123!",
    )


def create_playable_game(monkeypatch, **overrides):
    install_test_registry(monkeypatch, overrides.pop("engine_class", ReadyCheckEngine))
    values = {
        "category": category(),
        "name": f"Ready Check Test Game {timezone.now().timestamp()}",
        "short_description": "A playable ready-check test game.",
        "engine_key": "ready-check-test-engine",
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
    game = create_playable_game(monkeypatch, **overrides.pop("game_overrides", {}))
    host = host or create_user("host")
    values = {"game_configuration": {"rounds": 2}}
    values.update(overrides)
    return GameLobby.objects.create_for_host(host=host, game=game, **values)


def prepare_ready_lobby(
    monkeypatch,
    *,
    include_bot=False,
    include_spectator=False,
    **lobby_overrides,
):
    host = create_user("host")
    lobby = create_lobby(monkeypatch, host=host, **lobby_overrides)
    host_membership = join_lobby(lobby=lobby, user=host)
    player = create_user("player")
    player_membership = join_lobby(lobby=lobby, user=player)
    bot_membership = None
    spectator_membership = None
    if include_spectator:
        lobby.allow_spectators = True
        lobby.spectator_limit = 4
        lobby.save(update_fields=["allow_spectators", "spectator_limit", "updated_at"])
    if include_bot:
        bot_membership = LobbyMembership.objects.create(
            lobby=lobby,
            role=MembershipRole.BOT,
            bot_reference="bot-alpha",
            seat_number=3,
            is_ready=False,
        )
    if include_spectator:
        spectator = create_user("spectator")
        spectator_membership = join_lobby(
            lobby=lobby,
            user=spectator,
            as_spectator=True,
        )
    return (
        lobby,
        host,
        host_membership,
        player,
        player_membership,
        bot_membership,
        spectator_membership,
    )


def test_ready_check_sets_status_resets_humans_and_marks_bots_ready(monkeypatch):
    lobby, host, host_membership, _, player_membership, bot_membership, _ = (
        prepare_ready_lobby(monkeypatch, include_bot=True)
    )
    host_membership.is_ready = True
    host_membership.save(update_fields=["is_ready", "updated_at"])

    result = begin_ready_check(
        lobby=lobby,
        user=host,
        idempotency_key="ready-check",
        timeout_seconds=15,
    )

    result.refresh_from_db()
    host_membership.refresh_from_db()
    player_membership.refresh_from_db()
    bot_membership.refresh_from_db()
    assert result.status == LobbyStatus.READY_CHECK
    assert result.ready_check_started_at is not None
    assert result.ready_check_expires_at == result.ready_check_started_at + timedelta(
        seconds=15
    )
    assert host_membership.is_ready is False
    assert player_membership.is_ready is False
    assert bot_membership.is_ready is True
    assert LobbyAuditEvent.objects.filter(
        event_type=LobbyAuditEventType.READY_CHECK_STARTED,
        idempotency_key="ready-check",
    ).exists()


def test_players_can_ready_during_ready_check_but_spectators_cannot(monkeypatch):
    (
        lobby,
        host,
        host_membership,
        player,
        player_membership,
        _,
        spectator_membership,
    ) = prepare_ready_lobby(monkeypatch, include_spectator=True)
    begin_ready_check(lobby=lobby, user=host)

    set_membership_ready(lobby=lobby, user=player, is_ready=True)
    set_membership_ready(lobby=lobby, user=player, is_ready=False)

    player_membership.refresh_from_db()
    assert player_membership.is_ready is False
    assert host_membership.can_be_ready is True
    with pytest.raises(LobbyAccessDenied):
        set_membership_ready(
            lobby=lobby,
            user=spectator_membership.user,
            is_ready=True,
        )


def test_start_game_requires_authorized_ready_lobby(monkeypatch):
    lobby, host, _, player, _, _, _ = prepare_ready_lobby(monkeypatch)
    with pytest.raises(LobbyAccessDenied):
        start_game(lobby=lobby, user=player, idempotency_key="not-host")

    with pytest.raises(LobbyNotJoinable):
        start_game(lobby=lobby, user=host, idempotency_key="not-ready-check")

    begin_ready_check(lobby=lobby, user=host)
    set_membership_ready(lobby=lobby, user=host, is_ready=True)
    with pytest.raises(LobbyAccessDenied):
        start_game(lobby=lobby, user=host, idempotency_key="unready-player")


def test_successful_start_creates_one_session_and_participants(monkeypatch):
    lobby, host, host_membership, player, player_membership, _, _ = (
        prepare_ready_lobby(monkeypatch)
    )
    begin_ready_check(lobby=lobby, user=host)
    set_membership_ready(lobby=lobby, user=host, is_ready=True)
    set_membership_ready(lobby=lobby, user=player, is_ready=True)
    lock_calls = []

    result = start_game(
        lobby=lobby,
        user=host,
        idempotency_key="start-once",
        lock_context=lambda public_id: recording_lock(lock_calls),
    )

    lobby.refresh_from_db()
    assert lock_calls == ["acquired", "released"]
    assert lobby.status == LobbyStatus.ACTIVE
    assert lobby.started_at is not None
    assert result.session.engine_version == "1.0"
    assert result.session.state_version == 1
    assert result.session.initial_state["actors"] == [
        str(host_membership.public_id),
        str(player_membership.public_id),
    ]
    assert result.public_state == {"actors": result.session.initial_state["actors"], "rounds": 2}
    assert GameSession.objects.filter(lobby=lobby).count() == 1
    assert GameSessionParticipant.objects.filter(session=result.session).count() == 2
    host_participant = GameSessionParticipant.objects.get(
        session=result.session,
        lobby_membership=host_membership,
    )
    assert host_participant.private_state == {"secret": "secret-1"}
    assert LobbyAuditEvent.objects.filter(
        event_type=LobbyAuditEventType.GAME_STARTED,
        idempotency_key="start-once",
    ).exists()


def test_start_game_is_idempotent_for_same_key(monkeypatch):
    lobby, host, _, player, _, _, _ = prepare_ready_lobby(monkeypatch)
    begin_ready_check(lobby=lobby, user=host)
    set_membership_ready(lobby=lobby, user=host, is_ready=True)
    set_membership_ready(lobby=lobby, user=player, is_ready=True)

    first = start_game(lobby=lobby, user=host, idempotency_key="same-start")
    second = start_game(lobby=lobby, user=host, idempotency_key="same-start")

    assert first.session.pk == second.session.pk
    assert GameSession.objects.filter(lobby=lobby).count() == 1


def test_start_game_lock_contention_blocks_duplicate_session(monkeypatch):
    lobby, host, _, player, _, _, _ = prepare_ready_lobby(monkeypatch)
    begin_ready_check(lobby=lobby, user=host)
    set_membership_ready(lobby=lobby, user=host, is_ready=True)
    set_membership_ready(lobby=lobby, user=player, is_ready=True)

    def unavailable_lock(public_id):
        raise LobbyStartLockUnavailable("locked")

    with pytest.raises(LobbyStartConflict):
        start_game(
            lobby=lobby,
            user=host,
            idempotency_key="lock-conflict",
            lock_context=unavailable_lock,
        )

    assert GameSession.objects.filter(lobby=lobby).count() == 0


def test_engine_failure_rolls_back_session_and_lobby_status(monkeypatch, caplog):
    lobby, host, _, player, _, _, _ = prepare_ready_lobby(
        monkeypatch,
        game_overrides={"engine_class": FailingInitialStateEngine},
    )
    begin_ready_check(lobby=lobby, user=host)
    set_membership_ready(lobby=lobby, user=host, is_ready=True)
    set_membership_ready(lobby=lobby, user=player, is_ready=True)

    with pytest.raises(LobbyStartError):
        start_game(lobby=lobby, user=host, idempotency_key="engine-fails")

    lobby.refresh_from_db()
    assert lobby.status == LobbyStatus.READY_CHECK
    assert GameSession.objects.filter(lobby=lobby).count() == 0
    assert "Could not start game for lobby" in caplog.text


def test_start_keeps_player_delivery_when_private_state_is_empty(monkeypatch):
    lobby, host, _, player, _, _, _ = prepare_ready_lobby(
        monkeypatch,
        game_overrides={"engine_class": EmptyPrivateStateEngine},
    )
    begin_ready_check(lobby=lobby, user=host)
    set_membership_ready(lobby=lobby, user=host, is_ready=True)
    set_membership_ready(lobby=lobby, user=player, is_ready=True)

    result = start_game(
        lobby=lobby,
        user=host,
        idempotency_key="empty-private-state",
        lock_context=lambda _lobby_id: recording_lock([]),
    )

    assert set(result.private_states_by_user_id) == {str(host.pk), str(player.pk)}
    assert all(
        delivery["private_state"] == {}
        for delivery in result.private_states_by_user_id.values()
    )
    retried = start_game(
        lobby=lobby,
        user=host,
        idempotency_key="empty-private-state",
        lock_context=lambda _lobby_id: recording_lock([]),
    )
    assert retried.private_states_by_user_id == result.private_states_by_user_id


def test_ready_check_timeout_returns_lobby_to_waiting(monkeypatch):
    lobby, host, host_membership, _, _, _, _ = prepare_ready_lobby(monkeypatch)
    begin_ready_check(lobby=lobby, user=host, timeout_seconds=10)
    set_membership_ready(lobby=lobby, user=host, is_ready=True)

    expired = expire_ready_check(
        lobby=lobby,
        now=timezone.now() + timedelta(seconds=11),
    )

    expired.refresh_from_db()
    host_membership.refresh_from_db()
    assert expired.status == LobbyStatus.WAITING
    assert expired.ready_check_started_at is None
    assert expired.ready_check_expires_at is None
    assert host_membership.is_ready is False
    assert LobbyAuditEvent.objects.filter(
        event_type=LobbyAuditEventType.READY_CHECK_EXPIRED,
    ).exists()


async def connect_lobby(lobby, user):
    communicator = WebsocketCommunicator(application, f"/ws/lobbies/{lobby.public_id}/")
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    return communicator, connected


def assert_schema(message, event_type, lobby):
    assert message["type"] == event_type
    assert message["lobby_uuid"] == str(lobby.public_id)
    assert "server_timestamp" in message
    assert "payload" in message


def test_websocket_ready_check_and_game_start_broadcasts_public_and_private(monkeypatch):
    lobby, host, _, player, _, _, spectator_membership = prepare_ready_lobby(
        monkeypatch,
        include_spectator=True,
    )
    outsider = create_user("outsider")

    async def scenario():
        host_socket, host_connected = await connect_lobby(lobby, host)
        await host_socket.receive_json_from()
        player_socket, player_connected = await connect_lobby(lobby, player)
        await player_socket.receive_json_from()
        spectator_socket, spectator_connected = await connect_lobby(
            lobby,
            spectator_membership.user,
        )
        await spectator_socket.receive_json_from()
        outsider_socket, outsider_connected = await connect_lobby(
            lobby, outsider
        )
        await outsider_socket.receive_json_from()

        await host_socket.send_json_to(
            {
                "type": "READY_CHECK_START",
                "request_id": "ready-start",
                "payload": {"timeout_seconds": 30},
            }
        )
        ready_started = await player_socket.receive_json_from()
        await host_socket.receive_json_from()
        await spectator_socket.receive_json_from()
        await outsider_socket.receive_json_from()

        await host_socket.send_json_to(
            {"type": "LOBBY_READY", "request_id": "host-ready", "payload": {}}
        )
        await host_socket.receive_json_from()
        await player_socket.receive_json_from()
        await spectator_socket.receive_json_from()
        await outsider_socket.receive_json_from()
        await player_socket.send_json_to(
            {"type": "LOBBY_READY", "request_id": "player-ready", "payload": {}}
        )
        await host_socket.receive_json_from()
        await player_socket.receive_json_from()
        await spectator_socket.receive_json_from()
        await outsider_socket.receive_json_from()

        await host_socket.send_json_to(
            {"type": "GAME_START", "request_id": "start-game", "payload": {}}
        )
        host_public = await host_socket.receive_json_from()
        player_public = await player_socket.receive_json_from()
        spectator_public = await spectator_socket.receive_json_from()
        host_private = await host_socket.receive_json_from()
        player_private = await player_socket.receive_json_from()
        outsider_received_nothing = await outsider_socket.receive_nothing(timeout=0.2)

        await host_socket.disconnect()
        await player_socket.disconnect()
        await spectator_socket.disconnect()
        await outsider_socket.disconnect()
        return (
            host_connected,
            player_connected,
            spectator_connected,
            outsider_connected,
            outsider_received_nothing,
            ready_started,
            host_public,
            player_public,
            spectator_public,
            host_private,
            player_private,
        )

    (
        host_connected,
        player_connected,
        spectator_connected,
        outsider_connected,
        outsider_received_nothing,
        ready_started,
        host_public,
        player_public,
        spectator_public,
        host_private,
        player_private,
    ) = run(scenario)

    assert host_connected is True
    assert player_connected is True
    assert spectator_connected is True
    assert outsider_connected is True
    assert outsider_received_nothing is True
    assert_schema(ready_started, "READY_CHECK_STARTED", lobby)
    assert_schema(host_public, "GAME_STARTED", lobby)
    assert_schema(player_public, "GAME_STARTED", lobby)
    assert_schema(spectator_public, "GAME_STARTED", lobby)
    assert spectator_public["payload"]["spectator_state"] == {
        "actors": [str(host_private["payload"]["actor_id"]), str(player_private["payload"]["actor_id"])]
    }
    assert "public_state" not in spectator_public["payload"]
    assert "rounds" not in str(spectator_public["payload"])
    assert host_private["payload"]["public_state"]["rounds"] == 2
    assert player_private["payload"]["public_state"]["rounds"] == 2
    assert "private_state" not in spectator_public["payload"]
    assert_schema(host_private, "GAME_STARTED_PRIVATE", lobby)
    assert_schema(player_private, "GAME_STARTED_PRIVATE", lobby)
    assert host_private["payload"]["private_state"] != player_private["payload"][
        "private_state"
    ]
