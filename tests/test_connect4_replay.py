"""KSA-028 durable Connect4 replay and completed results."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from games.connect4_state import serialize_state
from lobbies.models import GameLobby
from play.models import GameActionReceipt, GameSession, GameSessionParticipant
from play.services import submit_game_action
from tests.test_connect4_game_actions import session_fixture
from tests.test_connect4_results import DRAW_COLUMNS


pytestmark = pytest.mark.django_db(transaction=True)


WIN_COLUMNS = [3, 6, 1, 1, 2, 4, 0]


def completed_session(*, spectator=True, columns=WIN_COLUMNS):
    session, first, second, watcher = session_fixture(spectator=spectator)
    for index, column in enumerate(columns):
        submit_game_action(
            session_uuid=str(session.public_id), user=(first, second)[index % 2],
            action={"type": "drop_disc", "column": column},
            state_version=index + 1, idempotency_key=str(uuid4()),
        )
    session.refresh_from_db()
    return session, first, second, watcher


def page_url(session, kind):
    return reverse(f"games:connect4_{kind}", args=[session.public_id])


def test_replay_reconstructs_each_version_and_terminal_result(client):
    from play.replays import build_connect4_replay

    session, first, _, watcher = completed_session()
    replay = build_connect4_replay(session_uuid=str(session.public_id), user=first)
    assert len(replay["frames"]) == 8
    assert [frame["state_version"] for frame in replay["frames"]] == list(range(1, 9))
    assert replay["frames"][0]["state"]["move_count"] == 0
    assert replay["frames"][-1]["state"] == serialize_state(session.spectator_state)
    assert [frame["move"]["column"] for frame in replay["frames"][1:]] == WIN_COLUMNS
    assert replay["result"] == {"outcome": "win", "winner_marker": "red",
                                "move_count": 7}
    assert build_connect4_replay(session_uuid=str(session.public_id), user=watcher) == replay

    client.force_login(first)
    result_page = client.get(page_url(session, "results"))
    replay_page = client.get(page_url(session, "replay"))
    assert result_page.status_code == replay_page.status_code == 200
    assert b"Red wins" in result_page.content
    assert result_page.content.count(b'class="connect4-cell') == 42
    assert b'connect4-replay-bootstrap' in replay_page.content
    assert b'data-column=' not in replay_page.content
    assert finders.find("play/connect4_replay.js")
    assert finders.find("play/connect4_replay.css")
    assert b"View final result and replay" in client.get(
        page_url(session, "player")
    ).content
    client.force_login(watcher)
    assert b"View final result and replay" in client.get(
        page_url(session, "spectator")
    ).content


def test_draw_result_is_derived_from_validated_final_board(client):
    session, first, _, _ = completed_session(columns=DRAW_COLUMNS)
    client.force_login(first)
    response = client.get(page_url(session, "results"))
    assert response.status_code == 200
    assert b"Draw game" in response.content
    assert response.context["replay"]["result"] == {
        "outcome": "draw", "winner_marker": None, "move_count": 42,
    }
    assert response.context["replay"]["frames"][-1]["state_version"] == 43


def test_replay_includes_bot_moves_from_shared_action_service(client):
    session, first, _, _ = session_fixture(bot_second=True)
    bot_actor_id = session.participants.get(is_bot=True).actor_id
    for index, column in enumerate(WIN_COLUMNS):
        actor = {"user": first} if index % 2 == 0 else {"bot_actor_id": bot_actor_id}
        submit_game_action(
            session_uuid=str(session.public_id), action={"type": "drop_disc", "column": column},
            state_version=index + 1, idempotency_key=str(uuid4()), **actor,
        )
    client.force_login(first)
    page = client.get(page_url(session, "replay"))
    assert page.status_code == 200
    assert [frame["move"]["column"] for frame in page.context["replay"]["frames"][1:]] == WIN_COLUMNS


def test_result_and_replay_require_authorized_completed_session(client):
    session, first, _, watcher = session_fixture(spectator=True)
    outsider = get_user_model().objects.create_user(username="replay-outsider")
    for kind in ("results", "replay"):
        client.logout()
        assert client.get(page_url(session, kind)).status_code == 302
        client.force_login(first)
        assert client.get(page_url(session, kind)).status_code == 404
        client.force_login(outsider)
        assert client.get(page_url(session, kind)).status_code == 404

    session, first, _, watcher = completed_session()
    GameLobby.objects.filter(pk=session.lobby_id).update(
        allow_spectators=False, spectator_limit=0
    )
    client.force_login(watcher)
    assert client.get(page_url(session, "replay")).status_code == 404
    client.force_login(first)
    assert client.get(page_url(session, "results")).status_code == 200
    first.is_active = False
    first.save(update_fields=["is_active"])
    assert client.get(page_url(session, "results")).status_code in (302, 404)

    session, first, _, _ = completed_session()
    membership = GameSessionParticipant.objects.get(session=session, user=first).lobby_membership
    type(membership).objects.filter(pk=membership.pk).update(left_at=session.ended_at)
    client.force_login(first)
    assert client.get(page_url(session, "replay")).status_code == 404


def test_replay_rejects_missing_or_tampered_history(client):
    session, first, _, _ = completed_session()
    client.force_login(first)
    receipt = GameActionReceipt.objects.filter(session=session).first()
    receipt.delete()
    assert client.get(page_url(session, "replay")).status_code == 404

    session, first, _, _ = completed_session()
    client.force_login(first)
    receipt = GameActionReceipt.objects.filter(session=session).first()
    response = dict(receipt.response)
    response["events"] = [{"type": "connect4_disc_dropped", "column": 6}]
    GameActionReceipt.objects.filter(pk=receipt.pk).update(response=response)
    assert client.get(page_url(session, "results")).status_code == 404

    session, first, _, _ = completed_session()
    client.force_login(first)
    altered = {**session.authoritative_state, "result": {
        "outcome": "draw", "winner_actor_id": None,
    }}
    GameSession.objects.filter(pk=session.pk).update(authoritative_state=altered)
    assert client.get(page_url(session, "results")).status_code == 404

    session, first, _, _ = completed_session()
    client.force_login(first)
    receipt = GameActionReceipt.objects.filter(session=session).first()
    GameActionReceipt.objects.filter(pk=receipt.pk).update(request_hash="0" * 64)
    assert client.get(page_url(session, "replay")).status_code == 404


def test_replay_rejects_other_game_engine(client):
    session, first, _, _ = completed_session()
    GameSession.objects.filter(pk=session.pk).update(engine_key="hangman")
    client.force_login(first)
    assert client.get(page_url(session, "results")).status_code == 404


def test_replay_strips_unknown_fields_from_every_saved_state(client):
    session, first, _, _ = completed_session()
    secret = "replay-secret-must-not-leak"
    GameSession.objects.filter(pk=session.pk).update(
        authoritative_state={**session.authoritative_state, "secret": secret},
        spectator_state={**session.spectator_state, "secret": secret},
    )
    for receipt in GameActionReceipt.objects.filter(session=session):
        response = dict(receipt.response)
        response["state"] = {**response["state"], "secret": secret}
        response["spectator_state"] = {
            **response["spectator_state"], "secret": secret,
        }
        GameActionReceipt.objects.filter(pk=receipt.pk).update(response=response)
    client.force_login(first)
    for kind in ("results", "replay"):
        page = client.get(page_url(session, kind))
        assert page.status_code == 200
        assert secret.encode() not in page.content
