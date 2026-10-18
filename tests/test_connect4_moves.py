"""KSA-022 legal Connect4 actions and pure move transitions."""

from copy import deepcopy
import json

import pytest

from games.connect4_moves import apply_move, legal_actions
from games.connect4_state import InvalidConnect4State, create_initial_state
from games.engine import (
    IllegalGameAction,
    InvalidActionPayload,
    InvalidGameActor,
    UnauthorizedGameAction,
)


FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"


def initial_state():
    return create_initial_state(
        {"rows": 6, "columns": 7, "connect": 4},
        [
            {"actor_id": SECOND, "seat_number": 2},
            {"actor_id": FIRST, "seat_number": 1},
        ],
    )


def drop(state, actor_id, column):
    return apply_move(state, actor_id, {"type": "drop_disc", "column": column})


def test_legal_actions_are_open_columns_only_for_current_actor():
    state = initial_state()

    assert legal_actions(state, FIRST) == tuple(
        {"type": "drop_disc", "column": column} for column in range(7)
    )
    assert legal_actions(state, SECOND) == ()
    with pytest.raises(InvalidGameActor):
        legal_actions(state, "not-a-member")


def test_first_and_second_moves_obey_gravity_and_server_owned_turn():
    original = initial_state()
    first = drop(original, FIRST, 3)

    assert original["board"] == [[None] * 7 for _ in range(6)]
    assert original["turn_actor_id"] == FIRST
    assert first.state["board"][5][3] == "red"
    assert first.state["board"][4][3] is None
    assert first.state["move_count"] == 1
    assert first.state["turn_actor_id"] == SECOND
    assert first.next_actor == SECOND
    assert first.events[0] == {
        "type": "connect4_disc_dropped",
        "actor_id": FIRST,
        "marker": "red",
        "column": 3,
        "row": 5,
        "move_number": 1,
    }
    assert first.is_complete is False
    assert json.loads(json.dumps(first.to_dict(), allow_nan=False)) == first.to_dict()

    second = drop(first.state, SECOND, 3)
    assert second.state["board"][4][3] == "yellow"
    assert second.state["board"][5][3] == "red"
    assert second.state["move_count"] == 2
    assert second.state["turn_actor_id"] == FIRST
    assert first.state["board"][4][3] is None


@pytest.mark.parametrize(
    "action",
    [
        None,
        [],
        {},
        {"type": "claim_win", "column": 0},
        {"type": "drop_disc"},
        {"type": "drop_disc", "column": None},
        {"type": "drop_disc", "column": True},
        {"type": "drop_disc", "column": "3"},
        {"type": "drop_disc", "column": 3.0},
        {"type": "drop_disc", "column": 3, "row": 5},
        {"type": "drop_disc", "column": 3, "winner": FIRST},
        {"type": "drop_disc", "column": 3, "turn_actor_id": FIRST},
        {"type": "drop_disc", "column": 3, "score": 100},
    ],
)
def test_malformed_or_client_owned_payload_is_rejected_without_mutation(action):
    state = initial_state()
    original = deepcopy(state)

    with pytest.raises(InvalidActionPayload):
        apply_move(state, FIRST, action)

    assert state == original


@pytest.mark.parametrize("column", [-1, 7, 99])
def test_out_of_range_column_is_illegal_without_mutation(column):
    state = initial_state()
    original = deepcopy(state)

    with pytest.raises(IllegalGameAction):
        drop(state, FIRST, column)

    assert state == original


def test_full_column_is_not_legal_and_rejects_another_drop():
    state = initial_state()
    for actor in (FIRST, SECOND, FIRST, SECOND, FIRST, SECOND):
        state = drop(state, actor, 0).state
    original = deepcopy(state)

    assert [row[0] for row in state["board"]] == [
        "yellow", "red", "yellow", "red", "yellow", "red"
    ]
    assert {action["column"] for action in legal_actions(state, FIRST)} == set(range(1, 7))
    with pytest.raises(IllegalGameAction):
        drop(state, FIRST, 0)
    assert state == original


def test_out_of_turn_and_unknown_actor_are_rejected_without_mutation():
    state = initial_state()
    original = deepcopy(state)

    with pytest.raises(UnauthorizedGameAction):
        drop(state, SECOND, 2)
    with pytest.raises(InvalidGameActor):
        drop(state, "not-a-member", 2)

    assert state == original


def test_floating_disc_state_is_rejected_before_legal_action_or_transition():
    state = initial_state()
    state["board"][0][0] = "red"
    state["move_count"] = 1
    state["turn_actor_id"] = SECOND
    original = deepcopy(state)

    with pytest.raises(InvalidConnect4State):
        legal_actions(state, SECOND)
    with pytest.raises(InvalidConnect4State):
        drop(state, SECOND, 1)

    assert state == original
