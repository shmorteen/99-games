"""Browser lobby entry is a real, authorized path through durable services."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import GameDefinition
from lobbies.models import GameLobby, LobbyAuditEvent, LobbyMembership, MembershipRole
from lobbies.services import LobbyAccessDenied, create_public_lobby


pytestmark = pytest.mark.django_db


def user(name):
    return get_user_model().objects.create_user(
        username=name, email=f"{name}@example.com", password="StrongPass123!"
    )


def enable_test_game():
    game = GameDefinition.objects.get(slug="hangman")
    GameDefinition.objects.filter(pk=game.pk).update(is_playable=True)
    game.refresh_from_db()
    return game


def create_url(game):
    return reverse("lobbies:create", args=[game.slug])


def test_playable_catalog_links_to_real_lobby_form(client):
    game = enable_test_game()

    response = client.get(reverse("games:detail", args=[game.slug]))

    assert response.status_code == 200
    assert create_url(game).encode() in response.content
    assert b'href="#create-lobby"' not in response.content
    assert b'href="#find-lobby"' not in response.content
    assert b'href="#quick-match"' not in response.content


def test_create_lobby_persists_host_membership_and_audit(client):
    game = enable_test_game()
    host = user("browser-host")
    client.force_login(host)
    request_id = str(uuid4())

    form = client.get(create_url(game))
    assert form.status_code == 200
    assert b"csrfmiddlewaretoken" in form.content
    response = client.post(create_url(game), {
        "name": "Friday Hangman", "request_id": request_id,
    })

    lobby = GameLobby.objects.get(creation_request_id=request_id)
    assert response.status_code == 302
    assert response.url == reverse("lobbies:detail", args=[lobby.public_id])
    assert lobby.host == host
    assert lobby.game == game
    assert lobby.name == "Friday Hangman"
    assert lobby.game_configuration == game.default_configuration
    membership = LobbyMembership.objects.get(lobby=lobby)
    assert membership.user == host
    assert membership.role == MembershipRole.HOST
    assert membership.seat_number == 1
    assert LobbyAuditEvent.objects.filter(lobby=lobby, event_type="joined").count() == 1
    detail = client.get(response.url)
    assert detail.status_code == 200
    assert b"Friday Hangman" in detail.content
    assert str(lobby.public_id).encode() in detail.content
    catalog_detail = client.get(reverse("games:detail", args=[game.slug]))
    assert b"Open public lobbies" in catalog_detail.content
    assert b"<dd>1</dd>" in catalog_detail.content


def test_creation_retry_returns_same_lobby_and_rejects_changed_payload(client):
    game = enable_test_game()
    host = user("retry-host")
    client.force_login(host)
    request_id = str(uuid4())
    payload = {"name": "Retry Table", "request_id": request_id}

    first = client.post(create_url(game), payload)
    second = client.post(create_url(game), payload)
    changed = client.post(create_url(game), {**payload, "name": "Changed Table"})

    assert first.status_code == second.status_code == 302
    assert first.url == second.url
    assert changed.status_code == 400
    assert GameLobby.objects.filter(host=host).count() == 1
    assert LobbyMembership.objects.filter(user=host).count() == 1


def test_creation_uuid_cannot_be_reused_by_another_host(client):
    game = enable_test_game()
    request_id = str(uuid4())
    first, second = user("uuid-first"), user("uuid-second")
    client.force_login(first)
    assert client.post(create_url(game), {
        "name": "First lobby", "request_id": request_id,
    }).status_code == 302
    client.force_login(second)

    response = client.post(create_url(game), {
        "name": "Second lobby", "request_id": request_id,
    })

    assert response.status_code == 400
    assert GameLobby.objects.count() == 1
    assert LobbyMembership.objects.filter(user=second).count() == 0


def test_creation_rejects_missing_csrf_and_invalid_request_id():
    game = enable_test_game()
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user("csrf-host"))
    url = create_url(game)
    assert browser.post(url, {"name": "No token", "request_id": str(uuid4())}).status_code == 403
    form = browser.get(url)
    token = form.cookies["csrftoken"].value
    invalid = browser.post(url, {
        "name": "Invalid ID", "request_id": "not-a-uuid",
        "csrfmiddlewaretoken": token,
    })
    assert invalid.status_code == 400
    assert GameLobby.objects.count() == 0


def test_second_player_joins_and_capacity_is_enforced(client):
    game = enable_test_game()
    GameDefinition.objects.filter(pk=game.pk).update(maximum_players=2)
    host, second, third = user("join-host"), user("join-second"), user("join-third")
    client.force_login(host)
    client.post(create_url(game), {"name": "Two Seats", "request_id": str(uuid4())})
    lobby = GameLobby.objects.get(host=host)
    join_url = reverse("lobbies:join", args=[lobby.public_id])

    client.force_login(second)
    assert client.get(reverse("lobbies:detail", args=[lobby.public_id])).status_code == 200
    joined = client.post(join_url)
    assert joined.status_code == 302
    assert LobbyMembership.objects.filter(lobby=lobby, role=MembershipRole.PLAYER).count() == 1
    assert client.post(join_url).status_code == 400
    client.force_login(third)
    assert client.post(join_url).status_code == 400
    assert LobbyMembership.objects.filter(lobby=lobby).count() == 2


def test_anonymous_and_unplayable_games_cannot_create_or_join(client):
    game = enable_test_game()
    url = create_url(game)
    assert client.get(url).status_code == 302
    assert client.post(url, {"name": "Nope", "request_id": str(uuid4())}).status_code == 302
    client.force_login(user("blocked-host"))
    connect4 = GameDefinition.objects.get(slug="connect4")
    assert client.get(create_url(connect4)).status_code == 404
    assert client.post(create_url(connect4), {
        "name": "Nope", "request_id": str(uuid4()),
    }).status_code == 404
    assert GameLobby.objects.count() == 0


def test_lobby_detail_does_not_expose_private_lobby_to_outsider(client):
    game = enable_test_game()
    host = user("private-host")
    client.force_login(host)
    client.post(create_url(game), {"name": "Private", "request_id": str(uuid4())})
    lobby = GameLobby.objects.get(host=host)
    GameLobby.objects.filter(pk=lobby.pk).update(visibility="private")
    client.force_login(user("private-outsider"))

    assert client.get(reverse("lobbies:detail", args=[lobby.public_id])).status_code == 404
    assert client.post(reverse("lobbies:join", args=[lobby.public_id])).status_code == 404


def test_disabled_game_stops_new_browser_joins(client):
    game = enable_test_game()
    host = user("disabled-host")
    client.force_login(host)
    client.post(create_url(game), {"name": "Disabled", "request_id": str(uuid4())})
    lobby = GameLobby.objects.get(host=host)
    GameDefinition.objects.filter(pk=game.pk).update(is_active=False)
    client.force_login(user("disabled-outsider"))

    assert client.get(reverse("lobbies:detail", args=[lobby.public_id])).status_code == 404
    assert client.post(reverse("lobbies:join", args=[lobby.public_id])).status_code == 404
    assert LobbyMembership.objects.filter(lobby=lobby).count() == 1


def test_suspended_host_cannot_create_lobby():
    game = enable_test_game()
    host = user("suspended-host")
    host.is_active = False
    host.save(update_fields=["is_active"])

    with pytest.raises(LobbyAccessDenied):
        create_public_lobby(
            game=game, user=host, name="Forbidden", request_id=str(uuid4())
        )
    assert GameLobby.objects.count() == 0
