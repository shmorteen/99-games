"""KSA-025 player-only Connect4 page and initial server render."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from play.models import GameSession, GameSessionParticipant
from play.services import submit_game_action
from tests.test_connect4_game_actions import session_fixture


pytestmark = pytest.mark.django_db(transaction=True)


def page_url(session):
    return reverse("games:connect4_player", args=[session.public_id])


def test_player_page_renders_board_controls_and_bootstrap(client):
    session, first, _, _ = session_fixture()
    client.force_login(first)

    response = client.get(page_url(session))

    assert response.status_code == 200
    assert response.context["actor_id"] == session.initial_state["players"][0]["actor_id"]
    assert response.context["player_marker"] == "red"
    assert response.context["snapshot"]["state_version"] == 1
    assert response.context["snapshot"]["audience"] == "player"
    assert response.content.count(b'class="connect4-cell') == 42
    assert response.content.count(b'data-column="') == 7
    assert b'"turn_actor_id"' in response.content
    assert b'"actor_id"' in response.content
    assert b"Your turn" in response.content
    assert b"/ws/games/" in response.content
    assert finders.find("play/connect4.js")
    assert finders.find("play/connect4.css")


def test_page_denies_nonplayers_without_leaking_board(client):
    session, first, _, watcher = session_fixture(spectator=True)
    outsider = get_user_model().objects.create_user(username="page-outsider")

    assert client.get(page_url(session)).status_code == 302
    for user in (watcher, outsider):
        client.force_login(user)
        response = client.get(page_url(session))
        assert response.status_code == 404
        assert b'"board"' not in response.content

    first.is_active = False
    first.save(update_fields=["is_active"])
    client.force_login(first)
    assert client.get(page_url(session)).status_code in (302, 404)


def test_page_disables_controls_when_not_turn_or_column_full(client):
    session, first, second, _ = session_fixture()
    client.force_login(second)
    waiting = client.get(page_url(session))
    assert waiting.status_code == 200
    assert all(not control["enabled"] for control in waiting.context["columns"])
    assert waiting.context["status_text"] == "Opponent's turn."

    actors = (first, second)
    for index in range(6):
        submit_game_action(
            session_uuid=str(session.public_id), user=actors[index % 2],
            action={"type": "drop_disc", "column": 0},
            state_version=index + 1, idempotency_key=str(uuid4()),
        )
    client.force_login(first)
    response = client.get(page_url(session))
    assert response.context["columns"][0]["enabled"] is False
    assert all(control["enabled"] for control in response.context["columns"][1:])
    assert response.context["snapshot"]["state_version"] == 7
    assert response.content.count(b'class="connect4-cell') == 42


def test_page_only_serves_matching_connect4_session(client):
    session, first, _, _ = session_fixture()
    client.force_login(first)
    assert client.get(reverse("games:connect4_player", args=[uuid4()])).status_code == 404

    GameSession.objects.filter(pk=session.pk).update(engine_key="hangman")
    assert client.get(page_url(session)).status_code == 404


def test_completed_page_shows_server_result_and_disables_all_columns(client):
    session, first, second, _ = session_fixture()
    users = (first, second)
    for index, column in enumerate((3, 6, 1, 1, 2, 4, 0)):
        submit_game_action(
            session_uuid=str(session.public_id), user=users[index % 2],
            action={"type": "drop_disc", "column": column},
            state_version=index + 1, idempotency_key=str(uuid4()),
        )

    client.force_login(first)
    winner_page = client.get(page_url(session))
    assert winner_page.context["status_text"] == "You won!"
    assert all(not column["enabled"] for column in winner_page.context["columns"])
    assert winner_page.context["snapshot"]["state"]["result"]["winner_actor_id"] == (
        winner_page.context["actor_id"]
    )

    client.force_login(second)
    loser_page = client.get(page_url(session))
    assert loser_page.context["status_text"] == "Opponent won."


def test_player_page_bootstrap_uses_public_state_only(client):
    session, first, _, _ = session_fixture()
    secret = "private-answer-should-not-render"
    GameSession.objects.filter(pk=session.pk).update(
        authoritative_state={**session.authoritative_state, "secret": secret},
        public_state={**session.public_state, "secret": secret},
    )
    GameSessionParticipant.objects.filter(session=session, user=first).update(
        private_state={"secret": secret}
    )
    client.force_login(first)

    response = client.get(page_url(session))

    assert response.status_code == 200
    assert secret.encode() not in response.content
    assert response.context["snapshot"]["private_state"] == {}
