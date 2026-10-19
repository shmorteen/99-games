"""KSA-032 audience-specific pages and shared action transport."""

from uuid import uuid4

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from games.models import GameCategory, GameDefinition
from games.werewolves import WerewolvesEngine
from ksa_games.asgi import application
from lobbies.models import GameLobby, LobbyMembership, MembershipRole
from play.models import GameActionReceipt, GameSession, GameSessionParticipant
from play.consumers import GameConsumer
from play.overlays import issue_overlay_token
from play.services import get_game_snapshot, submit_game_action
from tests.test_connect4_game_actions import session_fixture


pytestmark = pytest.mark.django_db(transaction=True)


def werewolves_session(monkeypatch):
    session, first, second, watcher = session_fixture(spectator=True)
    category, _ = GameCategory.objects.get_or_create(
        slug="deduction-games", defaults={"name": "Deduction Games"}
    )
    game, _ = GameDefinition.objects.get_or_create(
        slug="werewolves-vs-villagers", defaults={
            "category": category, "name": "Werewolves vs Villagers",
            "short_description": "Find the hidden team.",
            "engine_key": "werewolves-vs-villagers", "engine_version": "0.1",
            "minimum_players": 5, "maximum_players": 20,
            "default_configuration": {"day_seconds": 300, "night_seconds": 120},
            "is_playable": False,
        }
    )
    GameLobby.objects.filter(pk=session.lobby_id).update(
        game=game, minimum_players=5, maximum_players=5
    )
    session.lobby.refresh_from_db()
    members = list(
        LobbyMembership.objects.filter(lobby=session.lobby, role__in=[MembershipRole.HOST, MembershipRole.PLAYER]).order_by("seat_number")
    )
    users = [first, second]
    for seat in range(3, 6):
        user = get_user_model().objects.create_user(username=f"wolf-seat-{seat}-{uuid4().hex[:8]}")
        member = LobbyMembership.objects.create(
            lobby=session.lobby, user=user, role=MembershipRole.PLAYER, seat_number=seat
        )
        GameSessionParticipant.objects.create(
            session=session, lobby_membership=member, user=user,
            actor_id=str(member.public_id), role=MembershipRole.PLAYER,
            seat_number=seat,
        )
        members.append(member)
        users.append(user)
    monkeypatch.setattr(
        "games.werewolves.secrets.SystemRandom",
        lambda: type("Picker", (), {"sample": lambda self, candidates, count: candidates[:count]})(),
    )
    engine = WerewolvesEngine()
    state = engine.create_initial_state(
        {"day_seconds": 300, "night_seconds": 120},
        [{"actor_id": str(member.public_id), "seat": member.seat_number} for member in members],
    )
    GameSession.objects.filter(pk=session.pk).update(
        game=game, engine_key="werewolves-vs-villagers", engine_version="0.1",
        configuration={"day_seconds": 300, "night_seconds": 120},
        initial_state=state, authoritative_state=state,
        public_state=engine.get_public_state(state),
        spectator_state=engine.get_spectator_state(state),
    )
    session.refresh_from_db()
    return session, users, watcher


def url(kind, session):
    return reverse(f"games:werewolves_{kind}", args=[session.public_id])


def test_player_page_shows_only_own_role_and_host_links(client, monkeypatch):
    session, users, _ = werewolves_session(monkeypatch)
    client.force_login(users[0])
    host = client.get(url("player", session))
    assert host.status_code == 200
    assert host.context["snapshot"]["private_state"]["role"] == "werewolf"
    assert all("role" not in person for person in host.context["snapshot"]["state"]["players"])
    assert host.context["overlay_url"]
    assert host.content.count(b'data-target=') == 4
    assert finders.find("play/werewolves.js")
    assert finders.find("play/werewolves.css")
    client.force_login(users[1])
    villager = client.get(url("player", session))
    assert villager.status_code == 200
    assert villager.context["snapshot"]["private_state"]["role"] == "villager"
    assert villager.context["overlay_url"] is None
    assert b'"role": "werewolf"' not in villager.content
    assert villager["Cache-Control"] == "no-store"


def test_spectator_host_public_and_overlay_are_role_safe(client, monkeypatch):
    session, users, watcher = werewolves_session(monkeypatch)
    client.force_login(watcher)
    spectator = client.get(url("spectator", session))
    assert spectator.status_code == 200
    assert spectator.context["snapshot"]["private_state"] is None
    assert b'data-target=' not in spectator.content
    assert client.get(url("player", session)).status_code == 404
    client.force_login(users[0])
    moderator = client.get(url("moderator", session))
    assert moderator.status_code == 200
    assert moderator.context["snapshot"]["private_state"] is None
    assert "overlay_token=" in moderator.context["websocket_query"]
    assert b'data-target=' not in moderator.content
    client.force_login(users[1])
    assert client.get(url("moderator", session)).status_code == 404
    assert client.get(url("overlay", session)).status_code == 404
    overlay = client.get(url("overlay", session) + "?token=" + issue_overlay_token(session))
    assert overlay.status_code == 200
    assert overlay.context["snapshot"]["private_state"] is None
    assert overlay["Referrer-Policy"] == "no-referrer"


def test_authorization_and_rules(client, monkeypatch):
    session, users, watcher = werewolves_session(monkeypatch)
    outsider = get_user_model().objects.create_user(username=f"wolf-out-{uuid4().hex[:8]}")
    assert client.get(url("player", session)).status_code == 302
    assert client.get(url("spectator", session)).status_code == 302
    client.force_login(outsider)
    assert client.get(url("player", session)).status_code == 404
    assert client.get(url("spectator", session)).status_code == 404
    assert client.get(url("moderator", session)).status_code == 404
    client.force_login(users[0])
    assert client.get(url("spectator", session)).status_code == 404
    assert client.get(reverse("games:werewolves_rules")).status_code == 200
    GameLobby.objects.filter(pk=session.lobby_id).update(allow_spectators=False)
    client.force_login(watcher)
    assert client.get(url("spectator", session)).status_code == 404


def test_saved_public_private_fields_are_ignored(client, monkeypatch):
    session, users, watcher = werewolves_session(monkeypatch)
    GameSession.objects.filter(pk=session.pk).update(
        public_state={"secret": "wolves-are-seat-one"},
        spectator_state={"secret": "wolves-are-seat-one"},
    )
    GameSessionParticipant.objects.filter(session=session).update(
        private_state={"secret": "wolves-are-seat-one"}
    )
    for user, kind in ((users[1], "player"), (watcher, "spectator")):
        client.force_login(user)
        response = client.get(url(kind, session))
        assert response.status_code == 200
        assert b"wolves-are-seat-one" not in response.content
        snapshot = get_game_snapshot(session_uuid=str(session.public_id), user=user)
        assert "wolves-are-seat-one" not in str(snapshot)


def test_overlay_token_expires_and_revokes_after_host_transfer(client, monkeypatch):
    session, users, _ = werewolves_session(monkeypatch)
    address = url("overlay", session) + "?token=" + issue_overlay_token(session)
    assert client.get(address).status_code == 200
    monkeypatch.setattr("play.overlays.OVERLAY_MAX_AGE", -1)
    assert client.get(address).status_code == 404
    monkeypatch.setattr("play.overlays.OVERLAY_MAX_AGE", 24 * 60 * 60)
    GameLobby.objects.filter(pk=session.lobby_id).update(host=users[1])
    assert client.get(address).status_code == 404


def test_action_service_and_websocket_scope_private_roles(monkeypatch):
    session, users, watcher = werewolves_session(monkeypatch)
    target = session.authoritative_state["players"][1]["actor_id"]
    token = issue_overlay_token(session)

    async def scenario():
        wolf = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/")
        wolf.scope["user"] = users[0]
        wolf_ok, _ = await wolf.connect()
        wolf_initial = await wolf.receive_json_from()
        villager = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/")
        villager.scope["user"] = users[1]
        villager_ok, _ = await villager.connect()
        villager_initial = await villager.receive_json_from()
        overlay = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/?overlay_token={token}")
        overlay_ok, _ = await overlay.connect()
        overlay_initial = await overlay.receive_json_from()
        spectator = WebsocketCommunicator(application, f"/ws/games/{session.public_id}/")
        spectator.scope["user"] = watcher
        spectator_ok, _ = await spectator.connect()
        spectator_initial = await spectator.receive_json_from()
        await overlay.send_json_to({"type": "GAME_ACTION", "request_id": str(uuid4()), "payload": {"action": {"type": "vote", "target_actor_id": target}, "state_version": 1}})
        denied = await overlay.receive_json_from()
        await wolf.send_json_to({"type": "GAME_ACTION", "request_id": str(uuid4()), "payload": {"action": {"type": "vote", "target_actor_id": target}, "state_version": 1}})
        wolf_live = await wolf.receive_json_from()
        villager_live = await villager.receive_json_from()
        overlay_live = await overlay.receive_json_from()
        spectator_live = await spectator.receive_json_from()
        await wolf.disconnect()
        await villager.disconnect()
        await overlay.disconnect()
        await spectator.disconnect()
        return wolf_ok, villager_ok, overlay_ok, spectator_ok, wolf_initial, villager_initial, overlay_initial, spectator_initial, denied, wolf_live, villager_live, overlay_live, spectator_live

    (wolf_ok, villager_ok, overlay_ok, spectator_ok, wolf_initial, villager_initial,
     overlay_initial, spectator_initial, denied, wolf_live, villager_live,
     overlay_live, spectator_live) = async_to_sync(scenario)()
    assert wolf_ok and villager_ok and overlay_ok and spectator_ok
    assert wolf_initial["payload"]["private_state"]["role"] == "werewolf"
    assert villager_initial["payload"]["private_state"]["role"] == "villager"
    assert overlay_initial["payload"]["private_state"] is None
    assert spectator_initial["payload"]["private_state"] is None
    assert denied["payload"]["code"] == "permission_denied"
    assert wolf_live["payload"]["private_state"]["role"] == "werewolf"
    assert villager_live["payload"]["private_state"]["role"] == "villager"
    assert "private_state" not in overlay_live["payload"]
    assert "private_state" not in spectator_live["payload"]
    assert all("role" not in person for person in overlay_live["payload"]["state"]["players"])
    assert "actor_id" not in overlay_live["payload"]["events"][0]
    assert "target_actor_id" not in overlay_live["payload"]["events"][0]
    assert GameActionReceipt.objects.filter(session=session).count() == 1
    session.refresh_from_db()
    assert session.authoritative_state["phase"] == "day"
    assert get_game_snapshot(session_uuid=str(session.public_id), user=watcher)["state"]["phase"] == "day"


def test_fanout_uses_one_version_for_public_and_private_state():
    old = {"game": "werewolves-vs-villagers", "status": "in_progress", "phase": "night"}
    fresh = {"game": "werewolves-vs-villagers", "status": "in_progress", "phase": "day"}
    response = {"state_version": 2, "state": old, "events": [{"type": "werewolves_vote_cast"}], "result": None}
    snapshot = {"state_version": 3, "state": fresh, "private_state": {"role": "villager"}, "audience": "player"}
    payload = GameConsumer()._audience_payload(response, snapshot)
    assert payload["state_version"] == 3
    assert payload["state"] == fresh
    assert payload["private_state"] == {"role": "villager"}
    assert payload["events"] == []
