"""Hangman pages and shared action transport for an existing session."""

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from games.hangman import HangmanEngine
from games.models import GameCategory, GameDefinition
from ksa_games.asgi import application
from lobbies.models import GameLobby
from play.models import GameActionReceipt, GameSession, GameSessionParticipant
from play.overlays import issue_overlay_token
from play.services import get_game_snapshot, submit_game_action
from tests.test_connect4_game_actions import session_fixture


pytestmark = pytest.mark.django_db(transaction=True)


def hangman_session(*, spectator=True):
    session, first, second, watcher = session_fixture(spectator=spectator)
    category, _ = GameCategory.objects.get_or_create(
        slug="word-games", defaults={"name": "Word Games"}
    )
    game, _ = GameDefinition.objects.get_or_create(
        slug="hangman", defaults={
            "category": category, "name": "Hangman", "short_description": "Guess the word.",
            "engine_key": "hangman", "engine_version": "0.1",
            "minimum_players": 1, "maximum_players": 8,
            "default_configuration": {"max_wrong_guesses": 6},
            "is_playable": False,
        }
    )
    members = list(GameSessionParticipant.objects.filter(session=session, role__in=["host", "player"]).order_by("seat_number"))
    state = HangmanEngine().create_initial_state(
        {"max_wrong_guesses": 6},
        [{"actor_id": member.actor_id, "seat": member.seat_number} for member in members],
    )
    state["answer"] = "ORBIT"
    engine = HangmanEngine()
    GameLobby.objects.filter(pk=session.lobby_id).update(game=game)
    GameSession.objects.filter(pk=session.pk).update(
        game=game, engine_key="hangman", engine_version="0.1",
        configuration={"max_wrong_guesses": 6}, initial_state=state,
        authoritative_state=state, public_state=engine.get_public_state(state),
        spectator_state=engine.get_spectator_state(state),
    )
    session.refresh_from_db()
    return session, first, second, watcher


def url(name, session):
    return reverse(f"games:hangman_{name}", args=[session.public_id])


def test_player_and_spectator_pages_keep_answer_hidden(client):
    session, first, second, watcher = hangman_session()
    client.force_login(first)
    player = client.get(url("player", session))
    assert player.status_code == 200
    assert player.content.count(b'data-letter=') == 26
    assert b'ORBIT' not in player.content
    assert player.context["snapshot"]["state"]["mask"] == "_____"
    assert finders.find("play/hangman.js")
    assert finders.find("play/hangman.css")
    overlay_link = player.context["overlay_url"]
    assert parse_qs(urlparse(overlay_link).query)["token"]
    client.force_login(second)
    assert client.get(url("player", session)).status_code == 200
    assert client.get(url("player", session)).context["overlay_url"] is None
    client.force_login(watcher)
    spectator = client.get(url("spectator", session))
    assert spectator.status_code == 200
    assert b'data-letter=' not in spectator.content
    assert b'ORBIT' not in spectator.content
    assert client.get(url("player", session)).status_code == 404
    assert client.get(url("overlay", session)).status_code == 404
    overlay = client.get(url("overlay", session) + "?token=" + issue_overlay_token(session))
    assert overlay.status_code == 200
    assert b'ORBIT' not in overlay.content
    assert overlay["Cache-Control"] == "no-store"


def test_authorization_and_rules(client):
    session, first, _, watcher = hangman_session()
    outsider = get_user_model().objects.create_user(username=f"hangman-out-{uuid4().hex[:8]}")
    assert client.get(url("player", session)).status_code == 302
    assert client.get(url("spectator", session)).status_code == 302
    client.force_login(outsider)
    assert client.get(url("player", session)).status_code == 404
    assert client.get(url("spectator", session)).status_code == 404
    client.force_login(first)
    assert client.get(url("spectator", session)).status_code == 404
    assert client.get(reverse("games:hangman_rules")).status_code == 200
    GameLobby.objects.filter(pk=session.lobby_id).update(allow_spectators=False)
    client.force_login(watcher)
    assert client.get(url("spectator", session)).status_code == 404


def test_stored_public_and_private_fields_cannot_leak_answer(client):
    session, first, _, watcher = hangman_session()
    GameSession.objects.filter(pk=session.pk).update(
        public_state={"answer": "ORBIT", "injected": "private marker"},
        spectator_state={"answer": "ORBIT", "injected": "private marker"},
    )
    GameSessionParticipant.objects.filter(session=session, user=first).update(
        private_state={"answer": "ORBIT", "injected": "private marker"}
    )
    for user, kind in ((first, "player"), (watcher, "spectator")):
        client.force_login(user)
        response = client.get(url(kind, session))
        assert response.status_code == 200
        assert b"ORBIT" not in response.content
        assert b"private marker" not in response.content
        snapshot = get_game_snapshot(session_uuid=str(session.public_id), user=user)
        assert "ORBIT" not in str(snapshot)


def test_hangman_overlay_token_revokes_with_host_and_expiry(client, monkeypatch):
    session, host, second, _ = hangman_session()
    token = issue_overlay_token(session)
    address = url("overlay", session) + "?token=" + token
    assert client.get(address).status_code == 200
    monkeypatch.setattr("play.overlays.OVERLAY_MAX_AGE", -1)
    assert client.get(address).status_code == 404
    monkeypatch.setattr("play.overlays.OVERLAY_MAX_AGE", 24 * 60 * 60)
    GameLobby.objects.filter(pk=session.lobby_id).update(host=second)
    assert client.get(address).status_code == 404
    GameLobby.objects.filter(pk=session.lobby_id).update(host=host)
    host.is_active = False
    host.save(update_fields=["is_active"])
    assert client.get(address).status_code == 404


def test_shared_action_service_persists_safe_snapshots_and_completion(client):
    session, first, second, watcher = hangman_session()
    users = (first, second)
    first_action = submit_game_action(
        session_uuid=str(session.public_id), user=first,
        action={"type": "guess_letter", "letter": "O"},
        state_version=1, idempotency_key=str(uuid4()),
    )
    assert first_action.response["state"]["mask"] == "O____"
    assert "answer" not in first_action.response["state"]
    assert "answer" not in first_action.response["spectator_state"]
    assert get_game_snapshot(session_uuid=str(session.public_id), user=watcher)["state"]["mask"] == "O____"
    for index, letter in enumerate("RBIT", start=2):
        outcome = submit_game_action(
            session_uuid=str(session.public_id), user=users[(index - 1) % 2],
            action={"type": "guess_letter", "letter": letter},
            state_version=index, idempotency_key=str(uuid4()),
        )
    session.refresh_from_db()
    assert outcome.response["is_complete"] is True
    assert outcome.response["state"]["answer"] == "ORBIT"
    assert session.status == "completed"
    client.force_login(watcher)
    assert b'ORBIT' in client.get(url("spectator", session)).content
    assert GameActionReceipt.objects.filter(session=session).count() == 5


def test_hangman_websocket_player_and_overlay_are_audience_scoped():
    session, first, _, _ = hangman_session()
    token = issue_overlay_token(session)

    async def scenario():
        player = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/")
        player.scope["user"] = first
        player_ok, _ = await player.connect()
        initial = await player.receive_json_from()
        overlay = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/?overlay_token={token}")
        overlay_ok, _ = await overlay.connect()
        overlay_initial = await overlay.receive_json_from()
        await overlay.send_json_to({"type": "GAME_ACTION", "request_id": str(uuid4()), "payload": {"action": {"type": "guess_letter", "letter": "O"}, "state_version": 1}})
        denied = await overlay.receive_json_from()
        await player.send_json_to({"type": "GAME_ACTION", "request_id": str(uuid4()), "payload": {"action": {"type": "guess_letter", "letter": "O"}, "state_version": 1}})
        player_live = await player.receive_json_from()
        overlay_live = await overlay.receive_json_from()
        await player.disconnect()
        await overlay.disconnect()
        return player_ok, overlay_ok, initial, overlay_initial, denied, player_live, overlay_live

    player_ok, overlay_ok, initial, overlay_initial, denied, player_live, overlay_live = async_to_sync(scenario)()
    assert player_ok and overlay_ok
    assert "ORBIT" not in str(initial)
    assert "ORBIT" not in str(overlay_initial)
    assert denied["payload"]["code"] == "permission_denied"
    assert player_live["payload"]["state"]["mask"] == "O____"
    assert overlay_live["payload"]["state"]["mask"] == "O____"
    assert "ORBIT" not in str(overlay_live)
