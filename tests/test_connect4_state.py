"""KSA-021: the durable Connect4 state shape, before move rules exist."""

from copy import deepcopy
import json
from uuid import UUID

import pytest

from games.connect4_state import (
    InvalidConnect4State,
    create_initial_state,
    serialize_state,
    validate_config,
)
from games.engine import InvalidGameActor, InvalidGameConfiguration


FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"
CONFIG = {"rows": 6, "columns": 7, "connect": 4}


def actors():
    return [
        {"actor_id": SECOND, "seat_number": 2, "role": "player", "score": 99},
        {"actor_id": FIRST, "seat_number": 1, "role": "host", "score": 99},
    ]


def test_initial_state_is_empty_json_board_with_server_seats_and_turn():
    supplied_actors = actors()
    original_actors = deepcopy(supplied_actors)

    state = create_initial_state(CONFIG, supplied_actors)

    assert state == {
        "schema_version": "connect4.state.v1",
        "game": "connect4",
        "status": "in_progress",
        "rows": 6,
        "columns": 7,
        "connect_length": 4,
        "board": [[None] * 7 for _ in range(6)],
        "players": [
            {"actor_id": FIRST, "seat_number": 1, "marker": "red"},
            {"actor_id": SECOND, "seat_number": 2, "marker": "yellow"},
        ],
        "turn_actor_id": FIRST,
        "move_count": 0,
    }
    assert supplied_actors == original_actors
    assert json.loads(json.dumps(state, allow_nan=False)) == state
    assert all(UUID(player["actor_id"]) for player in state["players"])


def test_board_rows_are_independent_and_serialization_is_detached():
    state = create_initial_state({}, actors())
    serialized = serialize_state(state)

    serialized["board"][5][0] = "red"
    serialized["players"][0]["marker"] = "yellow"
    assert state["board"][5][0] is None
    assert state["board"][4][0] is None
    assert state["players"][0]["marker"] == "red"


def test_serialization_omits_unrecognized_private_fields():
    state = create_initial_state(CONFIG, actors())
    state["private_answer"] = "must-not-leak"

    serialized = serialize_state(state)

    assert serialized == create_initial_state(CONFIG, actors())
    assert "private_answer" not in json.dumps(serialized)


def test_serializer_keeps_a_structurally_valid_next_turn_state():
    state = create_initial_state(CONFIG, actors())
    state["board"][5][3] = "red"
    state["move_count"] = 1
    state["turn_actor_id"] = SECOND

    assert serialize_state(state) == state


@pytest.mark.parametrize(
    "config",
    [
        None,
        [],
        {"rows": 5, "columns": 7, "connect": 4},
        {"rows": 6, "columns": 8, "connect": 4},
        {"rows": 6, "columns": 7, "connect": 5},
        {"rows": True, "columns": 7, "connect": 4},
        {"rows": 6, "columns": 7, "connect": 4, "winner": FIRST},
    ],
)
def test_configuration_rejects_unsupported_or_client_owned_values(config):
    with pytest.raises(InvalidGameConfiguration):
        validate_config(config)


@pytest.mark.parametrize(
    "supplied_actors",
    [
        [],
        [{"actor_id": FIRST, "seat_number": 1}],
        [
            {"actor_id": FIRST, "seat_number": 1},
            {"actor_id": FIRST, "seat_number": 2},
        ],
        [
            {"actor_id": FIRST, "seat_number": 1},
            {"actor_id": SECOND, "seat_number": 1},
        ],
        [
            {"actor_id": FIRST, "seat_number": 1},
            {"actor_id": SECOND, "seat_number": 3},
        ],
        [
            {"actor_id": "not-a-uuid", "seat_number": 1},
            {"actor_id": SECOND, "seat_number": 2},
        ],
        [
            {"actor_id": FIRST, "seat_number": True},
            {"actor_id": SECOND, "seat_number": 2},
        ],
    ],
)
def test_initial_state_rejects_invalid_actor_roster(supplied_actors):
    with pytest.raises(InvalidGameActor):
        create_initial_state(CONFIG, supplied_actors)


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda state: state["board"].pop(),
        lambda state: state["board"][0].pop(),
        lambda state: state["board"][0].__setitem__(0, "green"),
        lambda state: state.__setitem__("turn_actor_id", SECOND),
        lambda state: state.__setitem__("move_count", 1),
        lambda state: state["players"][1].__setitem__("actor_id", FIRST),
        lambda state: state.__setitem__("schema_version", "unknown"),
    ],
)
def test_serializer_rejects_corrupt_initial_state(corrupt):
    state = create_initial_state(CONFIG, actors())
    corrupt(state)

    with pytest.raises(InvalidConnect4State):
        serialize_state(state)
