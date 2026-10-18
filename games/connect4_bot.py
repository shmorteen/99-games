"""Deterministic, pure Connect4 move selection for a server-owned bot."""

from collections.abc import Mapping

from .connect4_moves import legal_actions
from .connect4_state import COLUMNS, CONNECT_LENGTH, ROWS, serialize_state
from .engine import GameAlreadyCompleted, InvalidGameConfiguration, UnauthorizedGameAction


def choose_bot_action(
    state: Mapping[str, object], actor_id: str, *, difficulty: str = "casual"
) -> dict[str, object]:
    """Win, block an immediate loss, then prefer safe central columns.

    The seeded Connect4 catalog has a single ``casual`` difficulty. Fixed
    tie-breaks make worker retries choose the same action for a given version.
    """

    if difficulty not in ("", "casual"):
        raise InvalidGameConfiguration("Unsupported Connect4 bot difficulty.")
    current = serialize_state(state)
    if current["status"] == "completed":
        raise GameAlreadyCompleted()
    actions = legal_actions(current, actor_id)
    if not actions:
        raise UnauthorizedGameAction("It is not this actor's turn.")
    marker = next(player["marker"] for player in current["players"]
                  if player["actor_id"] == actor_id)
    opponent = "yellow" if marker == "red" else "red"
    columns = sorted((action["column"] for action in actions),
                     key=lambda column: (abs(column - COLUMNS // 2), column))
    board = current["board"]

    for column in columns:
        if _wins_after_drop(board, column, marker):
            return {"type": "drop_disc", "column": column}
    for column in columns:
        if _wins_after_drop(board, column, opponent):
            return {"type": "drop_disc", "column": column}
    for column in columns:
        projected = _drop(board, column, marker)
        if not any(_wins_after_drop(projected, reply, opponent)
                   for reply in range(COLUMNS) if projected[0][reply] is None):
            return {"type": "drop_disc", "column": column}
    return {"type": "drop_disc", "column": columns[0]}


def _drop(board, column, marker):
    copy = [list(row) for row in board]
    row = next(index for index in range(ROWS - 1, -1, -1)
               if copy[index][column] is None)
    copy[row][column] = marker
    return copy


def _wins_after_drop(board, column, marker):
    if board[0][column] is not None:
        return False
    row = next(index for index in range(ROWS - 1, -1, -1)
               if board[index][column] is None)
    projected = _drop(board, column, marker)
    for row_step, column_step in ((0, 1), (1, 0), (1, 1), (1, -1)):
        length = 1
        for sign in (-1, 1):
            r, c = row + sign * row_step, column + sign * column_step
            while 0 <= r < ROWS and 0 <= c < COLUMNS and projected[r][c] == marker:
                length += 1
                r += sign * row_step
                c += sign * column_step
        if length >= CONNECT_LENGTH:
            return True
    return False


__all__ = ["choose_bot_action"]
