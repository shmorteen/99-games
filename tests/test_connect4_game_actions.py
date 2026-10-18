"""KSA-024 durable Connect4 action service and game WebSocket path."""

from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from games.connect4_state import create_initial_state
from games.engine import StaleGameState, UnauthorizedGameAction
from games.models import GameCategory, GameDefinition
from ksa_games.asgi import application
from lobbies.models import GameLobby, LobbyMembership, LobbyStatus, MembershipRole
from play.locks import GameActionLockUnavailable
from play.models import GameActionReceipt, GameSession, GameSessionParticipant
from play.services import (
    GameActionConflict,
    GameActionDenied,
    submit_game_action,
)


pytestmark = pytest.mark.django_db(transaction=True)


def session_fixture(*, spectator=False, bot_second=False):
    """Materialize a session without making the catalog game playable."""

    User = get_user_model()
    first = User.objects.create_user(username=f"first-{uuid4().hex[:8]}")
    second = User.objects.create_user(username=f"second-{uuid4().hex[:8]}")
    watcher = User.objects.create_user(username=f"watch-{uuid4().hex[:8]}")
    category, _ = GameCategory.objects.get_or_create(
        slug="board-games", defaults={"name": "Board Games"}
    )
    game, _ = GameDefinition.objects.get_or_create(
        slug="connect4",
        defaults={
            "category": category, "name": "Connect4",
            "short_description": "Connect four discs.",
            "engine_key": "connect4", "engine_version": "0.1",
            "minimum_players": 2, "maximum_players": 2,
            "default_configuration": {"rows": 6, "columns": 7, "connect": 4},
            "is_playable": False,
        },
    )
    now = timezone.now()
    lobby = GameLobby(
        game=game, host=first, name="Connect4 action fixture",
        minimum_players=2, maximum_players=2, status=LobbyStatus.ACTIVE,
        game_configuration=game.default_configuration, started_at=now,
        allow_spectators=spectator, spectator_limit=1 if spectator else 0,
    )
    # The seeded game is intentionally unplayable until later roadmap tasks.
    GameLobby.objects.bulk_create([lobby])
    members = [
        LobbyMembership.objects.create(
            lobby=lobby, user=first, role=MembershipRole.HOST, seat_number=1,
        ),
        LobbyMembership.objects.create(
            lobby=lobby, user=None if bot_second else second,
            role=MembershipRole.BOT if bot_second else MembershipRole.PLAYER,
            bot_reference="test-bot" if bot_second else "", seat_number=2,
        ),
    ]
    if spectator:
        members.append(LobbyMembership.objects.create(
            lobby=lobby, user=watcher, role=MembershipRole.SPECTATOR,
        ))
    state = create_initial_state(game.default_configuration, [
        {"actor_id": str(member.public_id), "seat_number": member.seat_number}
        for member in members[:2]
    ])
    session = GameSession.objects.create(
        lobby=lobby, game=game, engine_key="connect4", engine_version="0.1",
        configuration=game.default_configuration, initial_state=state,
        authoritative_state=state, public_state=state, spectator_state=state,
        started_at=now,
    )
    for member in members:
        GameSessionParticipant.objects.create(
            session=session, lobby_membership=member, user=member.user,
            actor_id=str(member.public_id), role=member.role,
            seat_number=member.seat_number, is_bot=member.is_bot,
        )
    return session, first, second, watcher


def submit(session, user, column, version, key=None, **kwargs):
    return submit_game_action(
        session_uuid=str(session.public_id), user=user,
        action={"type": "drop_disc", "column": column},
        state_version=version, idempotency_key=key or str(uuid4()), **kwargs,
    )


def test_service_persists_one_versioned_action_and_replays_same_key():
    session, first, second, _ = session_fixture()
    initial = deepcopy(session.authoritative_state)
    key = str(uuid4())

    first_result = submit(session, first, 3, 1, key)
    second_result = submit(session, first, 3, 1, key)
    session.refresh_from_db()

    assert first_result.replayed is False
    assert second_result.replayed is True
    assert second_result.response == first_result.response
    assert session.state_version == 2
    assert session.authoritative_state["board"][5][3] == "red"
    assert session.public_state == session.authoritative_state
    assert session.spectator_state == session.authoritative_state
    assert session.initial_state == initial
    assert GameActionReceipt.objects.filter(session=session).count() == 1
    with pytest.raises(GameActionConflict):
        submit(session, first, 4, 1, key)
    with pytest.raises(StaleGameState):
        submit(session, second, 0, 1)


def test_service_rejects_wrong_actor_and_spectator_without_persisting():
    session, first, second, watcher = session_fixture(spectator=True)
    with pytest.raises(UnauthorizedGameAction):
        submit(session, second, 0, 1)
    with pytest.raises(GameActionDenied):
        submit(session, watcher, 0, 1)
    with pytest.raises(GameActionDenied):
        submit(session, None, 0, 1)
    session.refresh_from_db()
    assert session.state_version == 1
    assert GameActionReceipt.objects.filter(session=session).count() == 0


def test_service_completes_win_and_blocks_post_game_actions():
    session, first, second, _ = session_fixture()
    users = (first, second)
    final_key = str(uuid4())
    for index, column in enumerate([3, 6, 1, 1, 2, 4, 0]):
        outcome = submit(
            session, users[index % 2], column, index + 1,
            final_key if index == 6 else None,
        )
    session.refresh_from_db()
    session.lobby.refresh_from_db()

    assert outcome.response["result"] == {
        "outcome": "win",
        "winner_actor_id": session.authoritative_state["players"][0]["actor_id"],
    }
    assert session.status == "completed"
    assert session.lobby.status == LobbyStatus.COMPLETED
    assert session.ended_at is not None
    assert session.state_version == 8
    replay = submit(session, first, 0, 7, final_key)
    assert replay.replayed is True
    assert replay.response == outcome.response
    with pytest.raises(GameActionConflict):
        submit(session, second, 0, 8)
    assert GameActionReceipt.objects.filter(session=session).count() == 7


def test_suspended_user_is_rechecked_from_database():
    session, first, _, _ = session_fixture()
    first.is_active = False
    first.save(update_fields=["is_active"])
    with pytest.raises(GameActionDenied):
        submit(session, first, 3, 1)


def test_lock_conflict_does_not_persist_action():
    session, first, _, _ = session_fixture()

    @contextmanager
    def unavailable(_session_uuid):
        raise GameActionLockUnavailable("busy")
        yield

    with pytest.raises(GameActionConflict):
        submit(session, first, 0, 1, lock_context=unavailable)
    session.refresh_from_db()
    assert session.state_version == 1


def test_bot_uses_same_action_service_and_human_cannot_claim_bot_seat():
    session, first, second, _ = session_fixture(bot_second=True)
    submit(session, first, 3, 1)
    bot_actor_id = session.participants.get(is_bot=True).actor_id

    with pytest.raises(GameActionDenied):
        submit(session, second, 2, 2)
    outcome = submit_game_action(
        session_uuid=str(session.public_id), bot_actor_id=bot_actor_id,
        action={"type": "drop_disc", "column": 2}, state_version=2,
        idempotency_key=str(uuid4()),
    )
    assert outcome.response["state"]["board"][5][2] == "yellow"


def test_invalid_action_never_changes_durable_state():
    session, first, _, _ = session_fixture()
    with pytest.raises(Exception) as error:
        submit_game_action(
            session_uuid=str(session.public_id), user=first,
            action={"type": "drop_disc", "column": 3, "winner": "forged"},
            state_version=1, idempotency_key=str(uuid4()),
        )
    assert getattr(error.value, "code", None) == "invalid_action_payload"
    session.refresh_from_db()
    assert session.state_version == 1
    assert GameActionReceipt.objects.filter(session=session).count() == 0


async def connect(session, user):
    socket = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/")
    socket.scope["user"] = user
    connected, _ = await socket.connect()
    return socket, connected


def test_websocket_action_broadcast_reconnect_and_rejection():
    session, first, second, watcher = session_fixture(spectator=True)
    outsider = get_user_model().objects.create_user(username="outside-game")

    async def scenario():
        first_socket, first_ok = await connect(session, first)
        first_snapshot = await first_socket.receive_json_from()
        second_socket, second_ok = await connect(session, second)
        await second_socket.receive_json_from()
        spectator_socket, spectator_ok = await connect(session, watcher)
        spectator_snapshot = await spectator_socket.receive_json_from()
        outsider_socket, outsider_ok = await connect(session, outsider)
        request_id = str(uuid4())
        await first_socket.send_json_to({
            "type": "GAME_ACTION", "request_id": request_id,
            "payload": {"action": {"type": "drop_disc", "column": 3}, "state_version": 1},
        })
        first_event = await first_socket.receive_json_from()
        second_event = await second_socket.receive_json_from()
        spectator_event = await spectator_socket.receive_json_from()
        await first_socket.send_json_to({
            "type": "GAME_ACTION", "request_id": request_id,
            "payload": {"action": {"type": "drop_disc", "column": 3}, "state_version": 1},
        })
        replay = await first_socket.receive_json_from()
        second_no_duplicate = await second_socket.receive_nothing(timeout=0.1)
        await second_socket.send_json_to({
            "type": "GAME_ACTION", "request_id": str(uuid4()),
            "payload": {"action": {"type": "drop_disc", "column": 7}, "state_version": 2},
        })
        error = await second_socket.receive_json_from()
        await spectator_socket.send_json_to({
            "type": "GAME_ACTION", "request_id": str(uuid4()),
            "payload": {"action": {"type": "drop_disc", "column": 0}, "state_version": 2},
        })
        spectator_error = await spectator_socket.receive_json_from()
        await second_socket.send_json_to({
            "type": "GAME_ACTION", "request_id": str(uuid4()),
            "payload": {"action": {"type": "drop_disc", "column": 0}, "state_version": 1},
        })
        stale_error = await second_socket.receive_json_from()
        await first_socket.disconnect()
        reconnect_socket, reconnect_ok = await connect(session, first)
        reconnect_snapshot = await reconnect_socket.receive_json_from()
        await reconnect_socket.send_json_to({
            "type": "GAME_RESYNC", "request_id": str(uuid4()), "payload": {},
        })
        resync_snapshot = await reconnect_socket.receive_json_from()
        await reconnect_socket.disconnect()
        await second_socket.disconnect()
        await spectator_socket.disconnect()
        if outsider_ok:
            await outsider_socket.disconnect()
        return (
            first_ok, second_ok, spectator_ok, outsider_ok, reconnect_ok,
            first_snapshot, spectator_snapshot, first_event, second_event,
            spectator_event, replay, error, spectator_error, stale_error,
            reconnect_snapshot, resync_snapshot, request_id, second_no_duplicate,
        )

    result = async_to_sync(scenario)()
    (first_ok, second_ok, spectator_ok, outsider_ok, reconnect_ok,
     initial, watcher_initial, first_event, second_event, watcher_event,
     replay, error, spectator_error, stale_error, reconnected, resynced, request_id,
     second_no_duplicate) = result

    assert (first_ok, second_ok, spectator_ok, outsider_ok, reconnect_ok) == (
        True, True, True, False, True,
    )
    assert initial["type"] == "GAME_SNAPSHOT"
    assert initial["payload"]["state_version"] == 1
    assert watcher_initial["payload"]["private_state"] is None
    assert first_event["type"] == second_event["type"] == watcher_event["type"] == "GAME_STATE"
    assert first_event["request_id"] == request_id
    assert first_event["payload"]["state_version"] == 2
    assert first_event["payload"]["state"]["board"][5][3] == "red"
    assert watcher_event["payload"]["state"]["board"][5][3] == "red"
    assert replay["type"] == "GAME_ACTION_ACK"
    assert second_no_duplicate is True
    assert error["type"] == "ERROR"
    assert error["payload"]["code"] == "illegal_game_action"
    assert spectator_error["payload"]["code"] == "permission_denied"
    assert stale_error["payload"]["code"] == "stale_game_state"
    assert reconnected["payload"]["state_version"] == 2
    assert resynced["type"] == "GAME_SNAPSHOT"
    assert resynced["payload"]["state"] == reconnected["payload"]["state"]
