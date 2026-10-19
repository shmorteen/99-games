"""Rectangular grid patterns shared by drop and line games."""

from __future__ import annotations

from collections.abc import Sequence


def _dimensions(board: Sequence[Sequence[str | None]]) -> tuple[int, int]:
    if isinstance(board, (str, bytes)) or not isinstance(board, Sequence) or not board:
        raise ValueError("board must have at least one row")
    columns = len(board[0]) if isinstance(board[0], Sequence) else 0
    if not columns or any(
        isinstance(row, (str, bytes)) or not isinstance(row, Sequence)
        or len(row) != columns or any(cell is not None and not isinstance(cell, str) for cell in row)
        for row in board
    ):
        raise ValueError("board must be rectangular with string markers or empty cells")
    return len(board), columns


def drop_row(board: Sequence[Sequence[str | None]], column: int) -> int | None:
    """Return the lowest empty row for a column, or None when it is full."""

    rows, columns = _dimensions(board)
    if type(column) is not int or not 0 <= column < columns:
        raise ValueError("column is outside the grid")
    for row in range(rows - 1, -1, -1):
        if board[row][column] is None:
            return row
    return None


def winning_markers(
    board: Sequence[Sequence[str | None]], connect_length: int
) -> set[str]:
    """Find markers with a horizontal, vertical, or diagonal run."""

    rows, columns = _dimensions(board)
    if type(connect_length) is not int or connect_length < 1:
        raise ValueError("connect_length must be a positive integer")
    winners: set[str] = set()
    for row in range(rows):
        for column in range(columns):
            marker = board[row][column]
            if marker is None:
                continue
            for row_step, column_step in ((0, 1), (1, 0), (1, 1), (1, -1)):
                if all(
                    0 <= row + offset * row_step < rows
                    and 0 <= column + offset * column_step < columns
                    and board[row + offset * row_step][column + offset * column_step] == marker
                    for offset in range(connect_length)
                ):
                    winners.add(marker)
    return winners
