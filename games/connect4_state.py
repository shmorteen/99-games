"""Pure, JSON-safe Connect4 state representation for KSA-021.

Actor records must come from the server's lobby memberships. No game engine is
registered here: results, timeouts, persistence, and bots are later tasks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from uuid import UUID

from .engine import (
    GameEngineError,
    InvalidGameActor,
    InvalidGameConfiguration,
    JSONDict,
    assert_json_serializable,
)


SCHEMA_VERSION = "connect4.state.v1"
GAME_KEY = "connect4"
ROWS = 6
COLUMNS = 7
CONNECT_LENGTH = 4
MARKERS = ("red", "yellow")
CONFIG = MappingProxyType(
    {"rows": ROWS, "columns": COLUMNS, "connect": CONNECT_LENGTH}
)


class InvalidConnect4State(GameEngineError):
    code = "invalid_connect4_state"
    default_message = "The Connect4 state is invalid."


def validate_config(config: Mapping[str, object]) -> dict[str, int]:
    """Accept the seeded standard 6-by-7, connect-four configuration only."""

    if not isinstance(config, Mapping) or any(key not in CONFIG for key in config):
        raise InvalidGameConfiguration("Unsupported Connect4 configuration.")
    normalized = {key: config.get(key, value) for key, value in CONFIG.items()}
    if any(
        type(value) is not int or value != CONFIG[key]
        for key, value in normalized.items()
    ):
        raise InvalidGameConfiguration(
            "Connect4 requires a 6-by-7 board and four in a row."
        )
    return dict(CONFIG)


def create_initial_state(
    config: Mapping[str, object],
    actors: Sequence[Mapping[str, object]],
) -> JSONDict:
    """Build an empty board from two server-supplied seated actor UUIDs."""

    validate_config(config)
    players = _players_from_actors(actors)
    state: JSONDict = {
        "schema_version": SCHEMA_VERSION,
        "game": GAME_KEY,
        "status": "in_progress",
        "rows": ROWS,
        "columns": COLUMNS,
        "connect_length": CONNECT_LENGTH,
        "board": [[None for _ in range(COLUMNS)] for _ in range(ROWS)],
        "players": players,
        "turn_actor_id": players[0]["actor_id"],
        "move_count": 0,
    }
    return serialize_state(state)


def serialize_state(state: Mapping[str, object]) -> JSONDict:
    """Validate structural invariants and return a detached, public JSON shape.

    Unknown fields are omitted so future internal or actor-private data cannot
    be copied into a spectator-safe payload by this serializer.
    """

    if not isinstance(state, Mapping):
        raise InvalidConnect4State()
    if (
        state.get("schema_version") != SCHEMA_VERSION
        or state.get("game") != GAME_KEY
        or state.get("status") != "in_progress"
        or type(state.get("rows")) is not int
        or state["rows"] != ROWS
        or type(state.get("columns")) is not int
        or state["columns"] != COLUMNS
        or type(state.get("connect_length")) is not int
        or state["connect_length"] != CONNECT_LENGTH
    ):
        raise InvalidConnect4State()

    players = _state_players(state.get("players"))
    board, red_count, yellow_count = _state_board(state.get("board"))
    move_count = state.get("move_count")
    if (
        type(move_count) is not int
        or move_count != red_count + yellow_count
        or red_count not in (yellow_count, yellow_count + 1)
    ):
        raise InvalidConnect4State()
    expected_actor = players[move_count % 2]["actor_id"]
    if state.get("turn_actor_id") != expected_actor:
        raise InvalidConnect4State()

    serialized: JSONDict = {
        "schema_version": SCHEMA_VERSION,
        "game": GAME_KEY,
        "status": "in_progress",
        "rows": ROWS,
        "columns": COLUMNS,
        "connect_length": CONNECT_LENGTH,
        "board": board,
        "players": players,
        "turn_actor_id": expected_actor,
        "move_count": move_count,
    }
    assert_json_serializable(serialized, label="Connect4 state")
    return serialized


def _players_from_actors(actors: object) -> list[JSONDict]:
    if (
        isinstance(actors, (str, bytes))
        or not isinstance(actors, Sequence)
        or len(actors) != 2
    ):
        raise InvalidGameActor("Connect4 requires exactly two seated actors.")
    by_seat: dict[int, str] = {}
    for actor in actors:
        if not isinstance(actor, Mapping):
            raise InvalidGameActor("Connect4 actor records must be objects.")
        seat = actor.get("seat_number")
        if type(seat) is not int or seat not in (1, 2) or seat in by_seat:
            raise InvalidGameActor("Connect4 actors need distinct seats one and two.")
        by_seat[seat] = _actor_uuid(actor.get("actor_id"), InvalidGameActor)
    if len(set(by_seat.values())) != 2:
        raise InvalidGameActor("Connect4 actors must be distinct.")
    return [
        {"actor_id": by_seat[seat], "seat_number": seat, "marker": MARKERS[seat - 1]}
        for seat in (1, 2)
    ]


def _state_players(value: object) -> list[JSONDict]:
    if not isinstance(value, list) or len(value) != 2:
        raise InvalidConnect4State()
    players = []
    for seat, marker, player in zip((1, 2), MARKERS, value, strict=True):
        if (
            not isinstance(player, Mapping)
            or type(player.get("seat_number")) is not int
            or player["seat_number"] != seat
            or player.get("marker") != marker
        ):
            raise InvalidConnect4State()
        players.append(
            {
                "actor_id": _actor_uuid(player.get("actor_id"), InvalidConnect4State),
                "seat_number": seat,
                "marker": marker,
            }
        )
    if players[0]["actor_id"] == players[1]["actor_id"]:
        raise InvalidConnect4State()
    return players


def _state_board(value: object) -> tuple[list[list[str | None]], int, int]:
    if not isinstance(value, list) or len(value) != ROWS:
        raise InvalidConnect4State()
    board: list[list[str | None]] = []
    red_count = yellow_count = 0
    for row in value:
        if not isinstance(row, list) or len(row) != COLUMNS:
            raise InvalidConnect4State()
        serialized_row = []
        for cell in row:
            if cell is None:
                serialized_row.append(None)
            elif cell == MARKERS[0]:
                red_count += 1
                serialized_row.append(MARKERS[0])
            elif cell == MARKERS[1]:
                yellow_count += 1
                serialized_row.append(MARKERS[1])
            else:
                raise InvalidConnect4State()
        board.append(serialized_row)
    for column in range(COLUMNS):
        found_empty = False
        for row in range(ROWS - 1, -1, -1):
            cell = board[row][column]
            if cell is None:
                found_empty = True
            elif found_empty:
                raise InvalidConnect4State(
                    "Connect4 discs cannot float above empty cells."
                )
    return board, red_count, yellow_count


def _actor_uuid(value: object, error_type: type[GameEngineError]) -> str:
    try:
        if not isinstance(value, (str, UUID)):
            raise ValueError
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as error:
        raise error_type("Connect4 actor IDs must be UUIDs.") from error


__all__ = [
    "CONFIG",
    "CONNECT_LENGTH",
    "COLUMNS",
    "GAME_KEY",
    "InvalidConnect4State",
    "MARKERS",
    "ROWS",
    "SCHEMA_VERSION",
    "create_initial_state",
    "serialize_state",
    "validate_config",
]
