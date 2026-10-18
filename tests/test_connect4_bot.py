"""KSA-027 deterministic Connect4 strategy and worker automation."""

from uuid import uuid4
from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
import pytest
from django.db import transaction
from django.test import override_settings
from kombu.exceptions import OperationalError

from games.connect4_bot import choose_bot_action
from games.connect4_moves import apply_move, legal_actions
from games.connect4_state import create_initial_state
from games.engine import GameAlreadyCompleted, InvalidGameConfiguration, UnauthorizedGameAction
from ksa_games.asgi import application
from play.bots import maybe_schedule_connect4_bot_turn
from play.models import GameActionReceipt
from play.services import submit_game_action
from tests.test_connect4_game_actions import session_fixture


pytestmark = pytest.mark.django_db(transaction=True)


def state_after(columns):
    state = create_initial_state({}, [
        {"actor_id": str(uuid4()), "seat_number": 1},
        {"actor_id": str(uuid4()), "seat_number": 2},
    ])
    for column in columns:
        state = apply_move(state, state["turn_actor_id"],
                           {"type": "drop_disc", "column": column}).state
    return state


def test_bot_takes_win_blocks_loss_and_prefers_center():
    opening = state_after([])
    assert choose_bot_action(opening, opening["turn_actor_id"]) == {
        "type": "drop_disc", "column": 3,
    }
    winning = state_after([0, 6, 1, 6, 2, 5])
    assert choose_bot_action(winning, winning["turn_actor_id"])["column"] == 3
    blocking = state_after([6, 0, 5, 1, 5, 2])
    assert choose_bot_action(blocking, blocking["turn_actor_id"])["column"] == 3


@pytest.mark.parametrize("columns", [
    [0, 1, 0, 5, 0, 2, 0],
    [4, 2, 2, 1, 2, 1, 3, 1, 3, 2, 1],
    [0, 3, 2, 4, 3, 1, 4, 3, 5, 2, 4, 4],
])
def test_bot_detects_vertical_and_diagonal_wins(columns):
    state = state_after(columns[:-1])
    assert choose_bot_action(state, state["turn_actor_id"])["column"] == columns[-1]


def test_bot_never_chooses_full_column_and_rejects_invalid_turn():
    state = state_after([3, 3, 3, 3, 3, 3])
    actor = state["turn_actor_id"]
    action = choose_bot_action(state, actor)
    assert action in legal_actions(state, actor)
    assert action["column"] != 3
    opponent = next(player["actor_id"] for player in state["players"]
                    if player["actor_id"] != actor)
    with pytest.raises(UnauthorizedGameAction):
        choose_bot_action(state, opponent)
    with pytest.raises(InvalidGameConfiguration):
        choose_bot_action(state, actor, difficulty="impossible")
    terminal = state_after([3, 6, 1, 6, 2, 4, 0])
    with pytest.raises(GameAlreadyCompleted):
        choose_bot_action(terminal, actor)


def test_worker_uses_shared_service_and_is_safe_to_repeat():
    from play.bots import run_connect4_bot_turn

    session, first, _, _ = session_fixture(bot_second=True)
    submit_game_action(session_uuid=str(session.public_id), user=first,
                       action={"type": "drop_disc", "column": 0},
                       state_version=1, idempotency_key=str(uuid4()))
    with patch("play.bots.broadcast_bot_action") as broadcast:
        result = run_connect4_bot_turn(str(session.public_id), expected_version=2)
        repeated = run_connect4_bot_turn(str(session.public_id), expected_version=2)
    session.refresh_from_db()
    assert result is not None
    assert repeated is None
    assert session.state_version == 3
    assert session.authoritative_state["board"][5][3] == "yellow"
    assert GameActionReceipt.objects.filter(session=session).count() == 2
    broadcast.assert_called_once()


def test_worker_rejects_human_turn_and_wrong_session():
    from play.bots import run_connect4_bot_turn

    human, _, _, _ = session_fixture()
    bot, _, _, _ = session_fixture(bot_second=True)
    assert run_connect4_bot_turn(str(human.public_id), expected_version=1) is None
    assert run_connect4_bot_turn(str(bot.public_id), expected_version=1) is None
    assert run_connect4_bot_turn(str(uuid4()), expected_version=1) is None
    assert GameActionReceipt.objects.count() == 0


@override_settings(KSA_CONNECT4_BOT_AUTOMATION_ENABLED=True)
def test_service_queues_bot_only_after_committed_human_move():
    session, first, _, _ = session_fixture(bot_second=True)
    with patch("play.bots.enqueue_connect4_bot_turn") as enqueue:
        submit_game_action(session_uuid=str(session.public_id), user=first,
                           action={"type": "drop_disc", "column": 0},
                           state_version=1, idempotency_key=str(uuid4()))
    enqueue.assert_called_once_with(str(session.public_id), 2)


@override_settings(KSA_CONNECT4_BOT_AUTOMATION_ENABLED=True)
def test_initial_bot_turn_is_queued_only_after_commit():
    session, _, _, _ = session_fixture(bot_second=True)
    bot = session.participants.get(is_bot=True)
    with patch("play.bots.enqueue_connect4_bot_turn") as enqueue:
        with transaction.atomic():
            assert maybe_schedule_connect4_bot_turn(
                session, {"status": "in_progress", "turn_actor_id": bot.actor_id}
            ) is True
            enqueue.assert_not_called()
        enqueue.assert_called_once_with(str(session.public_id), 1)
    with patch("play.bots.enqueue_connect4_bot_turn") as enqueue:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                maybe_schedule_connect4_bot_turn(
                    session, {"status": "in_progress", "turn_actor_id": bot.actor_id}
                )
                raise RuntimeError("rolled back")
        enqueue.assert_not_called()


def test_broker_publish_failure_does_not_reverse_committed_move(caplog):
    from play.bots import enqueue_connect4_bot_turn

    with patch("play.tasks.connect4_bot_turn.delay", side_effect=OperationalError("down")):
        enqueue_connect4_bot_turn(str(uuid4()), 2)
    assert "Could not queue Connect4 bot turn" in caplog.text


def test_bot_move_reaches_players_and_spectators_through_shared_consumer():
    from play.bots import run_connect4_bot_turn

    session, first, _, watcher = session_fixture(spectator=True, bot_second=True)
    submit_game_action(session_uuid=str(session.public_id), user=first,
                       action={"type": "drop_disc", "column": 0},
                       state_version=1, idempotency_key=str(uuid4()))

    async def scenario():
        player = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/")
        player.scope["user"] = first
        player_ok, _ = await player.connect()
        await player.receive_json_from()
        spectator = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/")
        spectator.scope["user"] = watcher
        spectator_ok, _ = await spectator.connect()
        await spectator.receive_json_from()
        await database_sync_to_async(run_connect4_bot_turn)(
            str(session.public_id), expected_version=2
        )
        player_event = await player.receive_json_from()
        spectator_event = await spectator.receive_json_from()
        await player.disconnect()
        await spectator.disconnect()
        return player_ok, spectator_ok, player_event, spectator_event

    player_ok, spectator_ok, player_event, spectator_event = async_to_sync(scenario)()
    assert player_ok and spectator_ok
    assert player_event["type"] == spectator_event["type"] == "GAME_STATE"
    assert player_event["payload"]["state_version"] == 3
    assert spectator_event["payload"]["state"]["board"][5][3] == "yellow"
    assert "events" not in spectator_event["payload"]


def test_celery_registers_bot_turn_task():
    from ksa_games.celery import celery_app

    celery_app.loader.import_default_modules()
    assert "play.connect4_bot_turn" in celery_app.tasks
    assert celery_app.tasks["play.connect4_bot_turn"].run(str(uuid4()), 1) is None
