"""KSA-026 spectator and host-issued OBS presentation."""

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from ksa_games.asgi import application
from lobbies.models import GameLobby
from play.models import GameActionReceipt, GameSession
from play.overlays import issue_overlay_token
from tests.test_connect4_game_actions import session_fixture


pytestmark = pytest.mark.django_db(transaction=True)


def spectator_url(session):
    return reverse("games:connect4_spectator", args=[session.public_id])


def overlay_url(session, token=None):
    path = reverse("games:connect4_overlay", args=[session.public_id])
    return path + "?token=" + (token if token is not None else issue_overlay_token(session))


def test_spectator_page_is_read_only_and_public_safe(client):
    session, first, _, watcher = session_fixture(spectator=True)
    secret = "spectator-secret-should-never-render"
    GameSession.objects.filter(pk=session.pk).update(
        authoritative_state={**session.authoritative_state, "secret": secret},
        public_state={**session.public_state, "secret": secret},
        spectator_state={**session.spectator_state, "secret": secret},
    )
    client.force_login(watcher)
    response = client.get(spectator_url(session))
    assert response.status_code == 200
    assert response.content.count(b'class="connect4-cell') == 42
    assert b'connect4-viewer-bootstrap' in response.content
    assert b'data-column=' not in response.content
    assert b'GAME_ACTION' not in response.content
    assert secret.encode() not in response.content
    assert response.context["snapshot"]["state"]["move_count"] == 0
    assert finders.find("play/connect4_spectator.js")
    assert finders.find("play/connect4_spectator.css")
    client.force_login(first)
    assert client.get(spectator_url(session)).status_code == 404


def test_spectator_page_rejects_unauthorized_and_disabled_viewers(client):
    session, _, _, watcher = session_fixture(spectator=True)
    outsider = get_user_model().objects.create_user(username="spectator-outsider")
    assert client.get(spectator_url(session)).status_code == 302
    client.force_login(outsider)
    assert client.get(spectator_url(session)).status_code == 404
    GameLobby.objects.filter(pk=session.lobby_id).update(
        allow_spectators=False, spectator_limit=0
    )
    client.force_login(watcher)
    assert client.get(spectator_url(session)).status_code == 404


def test_overlay_requires_host_link_and_uses_only_spectator_state(client, monkeypatch):
    session, host, opponent, watcher = session_fixture(spectator=True)
    secret = "overlay-private-payload"
    GameSession.objects.filter(pk=session.pk).update(
        authoritative_state={**session.authoritative_state, "secret": secret},
        spectator_state={**session.spectator_state, "secret": secret},
    )
    assert client.get(overlay_url(session, "invalid")).status_code == 404
    assert client.get(overlay_url(session)).status_code == 200
    response = client.get(overlay_url(session))
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert secret.encode() not in response.content
    assert b'data-column=' not in response.content
    client.force_login(watcher)
    assert b'Open OBS overlay' not in client.get(spectator_url(session)).content
    client.force_login(opponent)
    assert b'Open OBS overlay' not in client.get(
        reverse("games:connect4_player", args=[session.public_id])
    ).content
    client.force_login(host)
    player = client.get(reverse("games:connect4_player", args=[session.public_id]))
    link = player.context["overlay_url"]
    assert parse_qs(urlparse(link).query)["token"]
    assert client.get(urlparse(link).path + "?" + urlparse(link).query).status_code == 200
    monkeypatch.setattr("play.overlays.OVERLAY_MAX_AGE", -1)
    assert client.get(overlay_url(session)).status_code == 404


def test_overlay_link_revokes_on_host_transfer(client):
    session, _, second, _ = session_fixture(spectator=True)
    token = issue_overlay_token(session)
    GameLobby.objects.filter(pk=session.lobby_id).update(host=second)
    assert client.get(overlay_url(session, token)).status_code == 404


def test_overlay_link_is_scoped_to_session_and_active_host(client):
    session, host, _, _ = session_fixture(spectator=True)
    other, _, _, _ = session_fixture(spectator=True)
    token = issue_overlay_token(session)
    assert client.get(overlay_url(other, token)).status_code == 404
    host.is_active = False
    host.save(update_fields=["is_active"])
    assert client.get(overlay_url(session, token)).status_code == 404


def test_overlay_websocket_live_resync_and_action_denial():
    session, host, _, watcher = session_fixture(spectator=True)
    token = issue_overlay_token(session)
    secret = "socket-spectator-secret"
    GameSession.objects.filter(pk=session.pk).update(
        spectator_state={**session.spectator_state, "secret": secret}
    )

    async def scenario():
        socket = WebsocketCommunicator(
            application, f"/ws/games/{session.public_id}/?overlay_token={token}"
        )
        ok, _ = await socket.connect()
        initial = await socket.receive_json_from()
        await socket.send_json_to({"type": "GAME_ACTION", "request_id": str(uuid4()),
                                   "payload": {"action": {"type": "drop_disc", "column": 0},
                                               "state_version": 1}})
        error = await socket.receive_json_from()
        await socket.send_json_to({"type": "GAME_RESYNC", "payload": {},
                                   "request_id": str(uuid4())})
        resync = await socket.receive_json_from()
        player = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/")
        player.scope["user"] = host
        player_ok, _ = await player.connect()
        await player.receive_json_from()
        await player.send_json_to({"type": "GAME_ACTION", "request_id": str(uuid4()),
                                   "payload": {"action": {"type": "drop_disc", "column": 3},
                                               "state_version": 1}})
        await player.receive_json_from()
        live = await socket.receive_json_from()
        await player.disconnect()
        await socket.disconnect()
        invalid = WebsocketCommunicator(
            application, f"/ws/games/{session.public_id}/?overlay_token=invalid"
        )
        invalid_ok, invalid_code = await invalid.connect()
        if invalid_ok:
            await invalid.disconnect()
        return ok, initial, error, resync, invalid_ok, invalid_code, player_ok, live

    (ok, initial, error, resync, invalid_ok, invalid_code,
     player_ok, live) = async_to_sync(scenario)()
    assert ok and player_ok and not invalid_ok
    assert invalid_code == 4403
    assert initial["type"] == resync["type"] == "GAME_SNAPSHOT"
    assert initial["payload"]["private_state"] is None
    assert secret not in str(initial)
    assert error["payload"]["code"] == "permission_denied"
    assert live["type"] == "GAME_STATE"
    assert live["payload"]["state"]["board"][5][3] == "red"
    assert "events" not in live["payload"]
    assert GameActionReceipt.objects.filter(session=session).count() == 1
    client_state = client_state_after_move(session, watcher)
    assert client_state["state"]["board"][5][3] == "red"


def client_state_after_move(session, watcher):
    from play.services import get_game_snapshot
    return get_game_snapshot(session_uuid=str(session.public_id), user=watcher)
