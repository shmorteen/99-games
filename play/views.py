"""Player-facing session pages."""

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from games.connect4_moves import legal_actions
from games.connect4_state import serialize_state
from games.engine import GameEngineError
from .models import GameSession
from .services import GameActionError, get_game_snapshot
from .overlays import get_overlay_snapshot, issue_overlay_token


def _connect4_session(session_uuid):
    return get_object_or_404(
        GameSession.objects.select_related("game", "lobby"),
        public_id=session_uuid, game__slug="connect4",
        engine_key="connect4", engine_version="0.1",
    )


def _viewer_context(session, snapshot, *, overlay):
    state = serialize_state(snapshot["state"])
    result = state.get("result")
    if result and result["outcome"] == "draw":
        status_text = "Draw game."
    elif result:
        winner = next(
            player["marker"] for player in state["players"]
            if player["actor_id"] == result["winner_actor_id"]
        )
        status_text = f"{winner.title()} wins!"
    else:
        current = next(
            player["marker"] for player in state["players"]
            if player["actor_id"] == state["turn_actor_id"]
        )
        status_text = f"{current.title()} to move."
    return {
        "page_title": "Connect4 overlay" if overlay else "Watch Connect4",
        "session": session, "snapshot": {
            "session_uuid": str(session.public_id),
            "state_version": snapshot["state_version"], "state": state,
        },
        "board_rows": state["board"], "status_text": status_text,
        "is_overlay": overlay,
        "base_template": "play/overlay_base.html" if overlay else "games/base.html",
    }


@login_required
def connect4_spectator(request, session_uuid):
    session = _connect4_session(session_uuid)
    try:
        snapshot = get_game_snapshot(
            session_uuid=str(session.public_id), user=request.user
        )
        if snapshot["audience"] != "spectator":
            raise Http404
        context = _viewer_context(session, snapshot, overlay=False)
    except (GameActionError, GameEngineError) as error:
        raise Http404 from error
    response = render(request, "play/connect4_spectator.html", context)
    response["Cache-Control"] = "no-store"
    return response


def connect4_overlay(request, session_uuid):
    session = _connect4_session(session_uuid)
    token = request.GET.get("token", "")
    try:
        snapshot = get_overlay_snapshot(session_uuid=str(session.public_id), token=token)
        context = _viewer_context(session, snapshot, overlay=True)
    except (GameActionError, GameEngineError) as error:
        raise Http404 from error
    context["websocket_query"] = "?" + urlencode({"overlay_token": token})
    response = render(request, "play/connect4_spectator.html", context)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required
def connect4_player(request, session_uuid):
    """Serve one participant's initial Connect4 board and realtime controls."""

    session = _connect4_session(session_uuid)
    try:
        snapshot = get_game_snapshot(
            session_uuid=str(session.public_id), user=request.user
        )
        if snapshot["audience"] != "player":
            raise Http404
        state = serialize_state(snapshot["state"])
        snapshot = {**snapshot, "state": state, "private_state": {}}
        actor_id = snapshot["actor_id"]
        legal_columns = {
            action["column"] for action in legal_actions(state, actor_id)
        }
    except (GameActionError, GameEngineError) as error:
        raise Http404 from error

    player_marker = next(
        player["marker"] for player in state["players"]
        if player["actor_id"] == actor_id
    )
    if state["status"] == "completed":
        result = state["result"]
        if result["outcome"] == "draw":
            status_text = "Draw game."
        elif result["winner_actor_id"] == actor_id:
            status_text = "You won!"
        else:
            status_text = "Opponent won."
    elif state["turn_actor_id"] == actor_id:
        status_text = "Your turn — choose a column."
    else:
        status_text = "Opponent's turn."

    columns = [
        {"index": index, "number": index + 1, "enabled": index in legal_columns}
        for index in range(state["columns"])
    ]
    overlay_url = None
    if session.lobby.host_id == request.user.pk:
        path = reverse("games:connect4_overlay", args=[session.public_id])
        overlay_url = request.build_absolute_uri(
            path + "?" + urlencode({"token": issue_overlay_token(session)})
        )
    response = render(request, "play/connect4_player.html", {
        "page_title": "Connect4 match",
        "session": session,
        "snapshot": snapshot,
        "actor_id": actor_id,
        "player_marker": player_marker,
        "status_text": status_text,
        "columns": columns,
        "board_rows": state["board"],
        "overlay_url": overlay_url,
    })
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
