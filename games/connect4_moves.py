"""Pure Connect4 move validation and terminal transitions.

The caller remains responsible for authenticating the user, loading and
locking the authoritative session, checking its version, and persisting the
returned transition. This module never writes to the database.
"""

from __future__ import annotations

from collections.abc import Mapping

from .connect4_state import COLUMNS, ROWS, calculate_result, serialize_state
from .engine import (
    GameAlreadyCompleted,
    GameTransition,
    IllegalGameAction,
    InvalidActionPayload,
    InvalidGameActor,
    UnauthorizedGameAction,
)


DROP_DISC = "drop_disc"


def legal_actions(state: Mapping[str, object], actor_id: str) -> tuple[dict, ...]:
    """List open zero-based columns for the actor whose turn it is."""

    current = serialize_state(state)
    _player_for_actor(current, actor_id)
    if current["status"] == "completed":
        return ()
    if current["turn_actor_id"] != actor_id:
        return ()
    return tuple(
        {"type": DROP_DISC, "column": column}
        for column in range(COLUMNS)
        if current["board"][0][column] is None
    )


def apply_move(
    state: Mapping[str, object],
    actor_id: str,
    action: Mapping[str, object],
) -> GameTransition:
    """Validate a drop, then return a detached state and server-derived event."""

    current = serialize_state(state)
    player = _player_for_actor(current, actor_id)
    if current["status"] == "completed":
        raise GameAlreadyCompleted()
    if current["turn_actor_id"] != actor_id:
        raise UnauthorizedGameAction("It is not this actor's turn.")
    column = _action_column(action)
    if column < 0 or column >= COLUMNS:
        raise IllegalGameAction("Connect4 column is outside the board.")
    if current["board"][0][column] is not None:
        raise IllegalGameAction("Connect4 column is full.")

    row = next(
        row_index
        for row_index in range(ROWS - 1, -1, -1)
        if current["board"][row_index][column] is None
    )
    marker = player["marker"]
    current["board"][row][column] = marker
    current["move_count"] += 1
    result = calculate_result(
        current["board"], current["players"], current["move_count"]
    )
    next_actor = (
        current["players"][current["move_count"] % 2]["actor_id"]
        if result is None
        else None
    )
    current["turn_actor_id"] = next_actor
    if result is not None:
        current["status"] = "completed"
        current["result"] = result
    updated = serialize_state(current)
    move_number = updated["move_count"]
    events = [
        {
            "type": "connect4_disc_dropped",
            "actor_id": actor_id,
            "marker": marker,
            "column": column,
            "row": row,
            "move_number": move_number,
        }
    ]
    if result is not None:
        events.append(
            {
                "type": "connect4_game_completed",
                "result": result,
                "move_number": move_number,
            }
        )
    return GameTransition(
        state=updated,
        events=tuple(events),
        is_complete=result is not None,
        next_actor=next_actor,
        result=result,
    )


def _player_for_actor(state: dict, actor_id: str) -> dict:
    for player in state["players"]:
        if player["actor_id"] == actor_id:
            return player
    raise InvalidGameActor("Actor is not a Connect4 player.")


def _action_column(action: object) -> int:
    if (
        not isinstance(action, Mapping)
        or set(action) != {"type", "column"}
        or action.get("type") != DROP_DISC
        or type(action.get("column")) is not int
    ):
        raise InvalidActionPayload("Connect4 action must specify a drop_disc column.")
    return action["column"]


__all__ = ["DROP_DISC", "apply_move", "legal_actions"]
