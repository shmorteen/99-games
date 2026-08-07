from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from games.engine import BaseGameEngine, GameTransition, InvalidGameConfiguration
from games.models import GameCategory, GameDefinition
from games.registry import GameEngineRegistry
from ksa_games.asgi import application
from lobbies.models import (
    GameLobby,
    LobbyBan,
    LobbyMembership,
    LobbyStatus,
    MembershipConnectionStatus,
    MembershipRole,
)
from lobbies.services import begin_ready_check, join_lobby


pytestmark = pytest.mark.django_db(transaction=True)


class ConsumerTestEngine(BaseGameEngine):
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


def run(coro):
    return async_to_sync(coro)()


def install_test_registry(monkeypatch):
    registry = GameEngineRegistry()
    registry.register("consumer-test-engine", "1.0", ConsumerTestEngine)
    monkeypatch.setattr("games.models.game_engine_registry", registry)
    monkeypatch.setattr("lobbies.models.game_engine_registry", registry)
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
    install_test_registry(monkeypatch)
    values = {
        "category": category(),
        "name": f"Consumer Test Game {timezone.now().timestamp()}",
        "short_description": "A playable consumer test game.",
        "engine_key": "consumer-test-engine",
        "engine_version": "1.0",
        "minimum_players": 1,
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


async def connect_lobby(lobby, user, *, headers=None):
    communicator = WebsocketCommunicator(
        application,
        f"/ws/lobbies/{lobby.public_id}/",
        headers=headers or [],
    )
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    return communicator, connected


async def disconnect(communicator, connected=True):
    if connected:
        await communicator.disconnect()


def assert_schema(message, event_type, lobby):
    assert message["type"] == event_type
    assert message["lobby_uuid"] == str(lobby.public_id)
    assert "server_timestamp" in message
    assert "payload" in message


def test_authorized_member_connects_and_receives_initial_snapshot(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    membership = join_lobby(lobby=lobby, user=player)

    async def scenario():
        communicator, connected = await connect_lobby(lobby, player)
        snapshot = await communicator.receive_json_from()
        await disconnect(communicator, connected)
        return connected, snapshot

    connected, snapshot = run(scenario)

    assert connected is True
    assert_schema(snapshot, "LOBBY_SNAPSHOT", lobby)
    assert snapshot["payload"]["viewer"]["membership_uuid"] == str(membership.public_id)
    assert snapshot["payload"]["viewer"]["role"] == MembershipRole.PLAYER
    assert snapshot["payload"]["members"][0]["connection_status"] == (
        MembershipConnectionStatus.ONLINE
    )


def test_unauthorized_connections_are_rejected(monkeypatch):
    lobby = create_lobby(monkeypatch)
    banned = create_user("banned")
    suspended = create_user("suspended")
    missing_user = create_user("missing-lobby")
    bad_origin_user = create_user("bad-origin")
    suspended.is_active = False
    suspended.save(update_fields=["is_active"])
    LobbyBan.objects.create(lobby=lobby, user=banned, reason="blocked")

    async def scenario():
        anonymous, anonymous_connected = await connect_lobby(lobby, AnonymousUser())
        banned_socket, banned_connected = await connect_lobby(lobby, banned)
        suspended_socket, suspended_connected = await connect_lobby(lobby, suspended)
        missing = WebsocketCommunicator(
            application,
            "/ws/lobbies/00000000-0000-0000-0000-000000000000/",
        )
        missing.scope["user"] = missing_user
        missing_connected, _ = await missing.connect()
        bad_origin, bad_origin_connected = await connect_lobby(
            lobby,
            bad_origin_user,
            headers=[(b"origin", b"https://evil.example.test")],
        )
        await disconnect(anonymous, anonymous_connected)
        await disconnect(banned_socket, banned_connected)
        await disconnect(suspended_socket, suspended_connected)
        await disconnect(missing, missing_connected)
        await disconnect(bad_origin, bad_origin_connected)
        return [
            anonymous_connected,
            banned_connected,
            suspended_connected,
            missing_connected,
            bad_origin_connected,
        ]

    assert run(scenario) == [False, False, False, False, False]


def test_invalid_event_and_invalid_payload_return_structured_errors(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    join_lobby(lobby=lobby, user=player)

    async def scenario():
        communicator, connected = await connect_lobby(lobby, player)
        await communicator.receive_json_from()
        await communicator.send_json_to(
            {"type": "UNKNOWN_EVENT", "request_id": "bad-type", "payload": {}}
        )
        unknown = await communicator.receive_json_from()
        await communicator.send_json_to(
            {"type": "LOBBY_READY", "request_id": "bad-payload", "payload": []}
        )
        invalid = await communicator.receive_json_from()
        await disconnect(communicator, connected)
        return connected, unknown, invalid

    connected, unknown, invalid = run(scenario)

    assert connected is True
    assert_schema(unknown, "ERROR", lobby)
    assert unknown["request_id"] == "bad-type"
    assert unknown["payload"]["code"] == "unknown_event"
    assert_schema(invalid, "ERROR", lobby)
    assert invalid["request_id"] == "bad-payload"
    assert invalid["payload"]["code"] == "invalid_payload"


def test_ready_unready_broadcasts_and_rejects_readying_another_player(monkeypatch):
    lobby = create_lobby(monkeypatch)
    host = lobby.host
    join_lobby(lobby=lobby, user=host)
    player = create_user("player")
    other = create_user("other")
    player_membership = join_lobby(lobby=lobby, user=player)
    other_membership = join_lobby(lobby=lobby, user=other)
    begin_ready_check(lobby=lobby, user=host)

    async def scenario():
        communicator, connected = await connect_lobby(lobby, player)
        await communicator.receive_json_from()
        await communicator.send_json_to(
            {
                "type": "LOBBY_READY",
                "request_id": "ready-other",
                "payload": {"member_uuid": str(other_membership.public_id)},
            }
        )
        denied = await communicator.receive_json_from()
        await communicator.send_json_to(
            {"type": "LOBBY_READY", "request_id": "ready-self", "payload": {}}
        )
        ready = await communicator.receive_json_from()
        await communicator.send_json_to(
            {"type": "LOBBY_UNREADY", "request_id": "unready-self", "payload": {}}
        )
        unready = await communicator.receive_json_from()
        await disconnect(communicator, connected)
        return denied, ready, unready

    denied, ready, unready = run(scenario)

    assert denied["payload"]["code"] == "permission_denied"
    assert_schema(ready, "READY_STATE_CHANGED", lobby)
    assert ready["payload"]["member_uuid"] == str(player_membership.public_id)
    assert ready["payload"]["is_ready"] is True
    assert_schema(unready, "READY_STATE_CHANGED", lobby)
    assert unready["payload"]["is_ready"] is False
    player_membership.refresh_from_db()
    assert player_membership.is_ready is False


def test_spectator_connection_cannot_ready(monkeypatch):
    lobby = create_lobby(monkeypatch, allow_spectators=True, spectator_limit=2)
    host = lobby.host
    join_lobby(lobby=lobby, user=host)
    spectator = create_user("spectator")
    join_lobby(lobby=lobby, user=spectator, as_spectator=True)
    begin_ready_check(lobby=lobby, user=host)

    async def scenario():
        communicator, connected = await connect_lobby(lobby, spectator)
        await communicator.receive_json_from()
        await communicator.send_json_to(
            {"type": "LOBBY_READY", "request_id": "spectator-ready", "payload": {}}
        )
        error = await communicator.receive_json_from()
        await disconnect(communicator, connected)
        return connected, error

    connected, error = run(scenario)

    assert connected is True
    assert error["request_id"] == "spectator-ready"
    assert error["payload"]["code"] == "permission_denied"


def test_join_and_leave_events_are_routed_through_services(monkeypatch):
    lobby = create_lobby(monkeypatch, minimum_players=1, maximum_players=1)
    host = lobby.host
    join_lobby(lobby=lobby, user=host)
    player = create_user("player")

    async def scenario():
        observer, observer_connected = await connect_lobby(lobby, host)
        await observer.receive_json_from()
        player_socket, player_connected = await connect_lobby(lobby, player)
        await player_socket.receive_json_from()
        await player_socket.send_json_to(
            {"type": "LOBBY_JOIN", "request_id": "join-full", "payload": {}}
        )
        full = await player_socket.receive_json_from()
        await observer.send_json_to(
            {"type": "LOBBY_LEAVE", "request_id": "leave-host", "payload": {}}
        )
        left = await observer.receive_json_from()
        status = await observer.receive_json_from()
        await disconnect(observer, observer_connected)
        await disconnect(player_socket, player_connected)
        return full, left, status

    full, left, status = run(scenario)

    assert full["payload"]["code"] == "lobby_full"
    assert_schema(left, "LOBBY_MEMBER_LEFT", lobby)
    assert_schema(status, "LOBBY_STATUS_CHANGED", lobby)
    assert status["payload"]["status"] == LobbyStatus.CANCELLED


def test_non_member_can_join_waiting_lobby_and_broadcasts_to_group(monkeypatch):
    lobby = create_lobby(monkeypatch)
    host = lobby.host
    join_lobby(lobby=lobby, user=host)
    player = create_user("joining-player")

    async def scenario():
        host_socket, host_connected = await connect_lobby(lobby, host)
        await host_socket.receive_json_from()
        player_socket, player_connected = await connect_lobby(lobby, player)
        await player_socket.receive_json_from()
        await player_socket.send_json_to(
            {"type": "LOBBY_JOIN", "request_id": "join-player", "payload": {}}
        )
        host_event = await host_socket.receive_json_from()
        player_event = await player_socket.receive_json_from()
        await disconnect(host_socket, host_connected)
        await disconnect(player_socket, player_connected)
        return host_event, player_event

    host_event, player_event = run(scenario)

    assert_schema(host_event, "LOBBY_MEMBER_JOINED", lobby)
    assert_schema(player_event, "LOBBY_MEMBER_JOINED", lobby)
    assert host_event["request_id"] == "join-player"
    assert player_event["payload"]["member"]["role"] == MembershipRole.PLAYER


def test_host_permission_and_bot_permission_are_enforced(monkeypatch):
    lobby = create_lobby(monkeypatch, allow_bot_fill=True)
    host = lobby.host
    player = create_user("player")
    moderator = create_user("moderator")
    host_membership = join_lobby(lobby=lobby, user=host)
    player_membership = join_lobby(lobby=lobby, user=player)
    moderator_membership = LobbyMembership.objects.create(
        lobby=lobby,
        user=moderator,
        role=MembershipRole.MODERATOR,
    )

    async def scenario():
        player_socket, player_connected = await connect_lobby(lobby, player)
        await player_socket.receive_json_from()
        await player_socket.send_json_to(
            {
                "type": "HOST_TRANSFER",
                "request_id": "transfer-denied",
                "payload": {"target_member_uuid": str(player_membership.public_id)},
            }
        )
        transfer_denied = await player_socket.receive_json_from()
        await player_socket.send_json_to(
            {
                "type": "BOT_ADD",
                "request_id": "bot-denied",
                "payload": {"bot_reference": "bot-alpha"},
            }
        )
        bot_denied = await player_socket.receive_json_from()

        host_socket, host_connected = await connect_lobby(lobby, host)
        await host_socket.receive_json_from()
        await host_socket.send_json_to(
            {
                "type": "HOST_TRANSFER",
                "request_id": "moderator-transfer-denied",
                "payload": {
                    "target_member_uuid": str(moderator_membership.public_id)
                },
            }
        )
        moderator_transfer_denied = await host_socket.receive_json_from()
        await host_socket.send_json_to(
            {
                "type": "HOST_TRANSFER",
                "request_id": "transfer-ok",
                "payload": {"target_member_uuid": str(player_membership.public_id)},
            }
        )
        host_changed = await player_socket.receive_json_from()
        await player_socket.send_json_to(
            {
                "type": "BOT_ADD",
                "request_id": "bot-add",
                "payload": {"bot_reference": "bot-alpha"},
            }
        )
        bot_joined = await player_socket.receive_json_from()
        bot_uuid = bot_joined["payload"]["member"]["member_uuid"]
        await player_socket.send_json_to(
            {
                "type": "BOT_REMOVE",
                "request_id": "human-remove-denied",
                "payload": {"target_member_uuid": str(host_membership.public_id)},
            }
        )
        human_remove_denied = await player_socket.receive_json_from()
        await player_socket.send_json_to(
            {
                "type": "BOT_REMOVE",
                "request_id": "bot-remove",
                "payload": {"target_member_uuid": bot_uuid},
            }
        )
        bot_left = await player_socket.receive_json_from()
        await disconnect(host_socket, host_connected)
        await disconnect(player_socket, player_connected)
        return (
            transfer_denied,
            bot_denied,
            moderator_transfer_denied,
            host_changed,
            bot_joined,
            human_remove_denied,
            bot_left,
        )

    (
        transfer_denied,
        bot_denied,
        moderator_transfer_denied,
        host_changed,
        bot_joined,
        human_remove_denied,
        bot_left,
    ) = run(scenario)

    assert transfer_denied["payload"]["code"] == "permission_denied"
    assert bot_denied["payload"]["code"] == "permission_denied"
    assert moderator_transfer_denied["payload"]["code"] == "permission_denied"
    assert_schema(host_changed, "HOST_CHANGED", lobby)
    assert host_changed["payload"]["new_host_member_uuid"] == str(
        player_membership.public_id
    )
    player_membership.refresh_from_db()
    host_membership.refresh_from_db()
    assert player_membership.role == MembershipRole.HOST
    assert host_membership.role == MembershipRole.PLAYER
    assert_schema(bot_joined, "LOBBY_MEMBER_JOINED", lobby)
    assert human_remove_denied["payload"]["code"] == "permission_denied"
    assert_schema(bot_left, "LOBBY_MEMBER_LEFT", lobby)
    assert bot_left["payload"]["member_uuid"] == (
        bot_joined["payload"]["member"]["member_uuid"]
    )


def test_reconnect_restores_snapshot_and_presence(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    membership = join_lobby(lobby=lobby, user=player)

    async def first_connection():
        communicator, connected = await connect_lobby(lobby, player)
        await communicator.receive_json_from()
        await disconnect(communicator, connected)
        return connected

    assert run(first_connection) is True
    membership.refresh_from_db()
    assert membership.connection_status == MembershipConnectionStatus.DISCONNECTED

    async def second_connection():
        communicator, connected = await connect_lobby(lobby, player)
        snapshot = await communicator.receive_json_from()
        status = await database_sync_to_async(
            lambda: LobbyMembership.objects.get(pk=membership.pk).connection_status
        )()
        await disconnect(communicator, connected)
        return connected, snapshot, status

    connected, snapshot, status = run(second_connection)

    assert connected is True
    assert_schema(snapshot, "LOBBY_SNAPSHOT", lobby)
    assert snapshot["payload"]["viewer"]["membership_uuid"] == str(membership.public_id)
    assert status == MembershipConnectionStatus.ONLINE


def test_game_resync_returns_current_snapshot(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    join_lobby(lobby=lobby, user=player)

    async def scenario():
        communicator, connected = await connect_lobby(lobby, player)
        await communicator.receive_json_from()
        await communicator.send_json_to(
            {"type": "GAME_RESYNC", "request_id": "resync", "payload": {}}
        )
        snapshot = await communicator.receive_json_from()
        await disconnect(communicator, connected)
        return connected, snapshot

    connected, snapshot = run(scenario)

    assert connected is True
    assert_schema(snapshot, "LOBBY_SNAPSHOT", lobby)
    assert snapshot["request_id"] == "resync"
