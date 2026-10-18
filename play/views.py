"""Player-facing session pages."""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from games.connect4_moves import legal_actions
from games.connect4_state import serialize_state
from games.engine import GameEngineError
from .models import GameSession
from .services import GameActionError, get_game_snapshot


@login_required
def connect4_player(request, session_uuid):
    """Serve one participant's initial Connect4 board and realtime controls."""

    session = get_object_or_404(
        GameSession.objects.select_related("game"),
        public_id=session_uuid,
        game__slug="connect4",
        engine_key="connect4",
        engine_version="0.1",
    )
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
    return render(request, "play/connect4_player.html", {
        "page_title": "Connect4 match",
        "session": session,
        "snapshot": snapshot,
        "actor_id": actor_id,
        "player_marker": player_marker,
        "status_text": status_text,
        "columns": columns,
        "board_rows": state["board"],
    })
