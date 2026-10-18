"""KSA-023 terminal Connect4 results from server-owned moves."""

from copy import deepcopy
import json

import pytest

from games.connect4_moves import apply_move, legal_actions
from games.connect4_state import InvalidConnect4State, create_initial_state, serialize_state
from games.engine import GameAlreadyCompleted


FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"


def play(columns):
    state = create_initial_state({}, [
        {"actor_id": FIRST, "seat_number": 1},
        {"actor_id": SECOND, "seat_number": 2},
    ])
    for index, column in enumerate(columns):
        transition = apply_move(
            state,
            (FIRST, SECOND)[index % 2],
            {"type": "drop_disc", "column": column},
        )
        if index < len(columns) - 1:
            assert not transition.is_complete
        state = transition.state
    return transition


@pytest.mark.parametrize("direction,columns,line", [
    ("horizontal", [3, 6, 1, 1, 2, 4, 0], [(5, 0), (5, 1), (5, 2), (5, 3)]),
    ("vertical", [0, 1, 0, 5, 0, 2, 0], [(2, 0), (3, 0), (4, 0), (5, 0)]),
    ("diagonal_down_right", [4, 2, 2, 1, 2, 1, 3, 1, 3, 2, 1],
     [(2, 1), (3, 2), (4, 3), (5, 4)]),
    ("diagonal_down_left", [0, 3, 2, 4, 3, 1, 4, 3, 5, 2, 4, 4],
     [(2, 4), (3, 3), (4, 2), (5, 1)]),
])
def test_four_directions_produce_terminal_wins(direction, columns, line):
    transition = play(columns)
    winner = (FIRST, SECOND)[(len(columns) - 1) % 2]
    marker = ("red", "yellow")[(len(columns) - 1) % 2]

    assert transition.is_complete, direction
    assert all(transition.state["board"][row][column] == marker for row, column in line)
    assert transition.next_actor is None
    assert transition.state["status"] == "completed"
    assert transition.state["turn_actor_id"] is None
    assert transition.result == {"outcome": "win", "winner_actor_id": winner}
    assert transition.state["result"] == transition.result
    assert transition.events[-1] == {
        "type": "connect4_game_completed",
        "result": transition.result,
        "move_number": len(columns),
    }
    assert serialize_state(transition.state) == transition.state
    assert json.loads(json.dumps(transition.to_dict(), allow_nan=False)) == transition.to_dict()


DRAW_COLUMNS = [
    6, 4, 2, 2, 5, 3, 4, 6, 6, 0, 3, 3, 1, 6, 0, 5, 3, 6, 2, 3, 1,
    6, 2, 2, 3, 1, 4, 2, 0, 5, 4, 1, 1, 1, 0, 0, 0, 4, 4, 5, 5, 5,
]


def test_full_board_without_a_line_is_draw():
    transition = play(DRAW_COLUMNS)

    assert transition.state["move_count"] == 42
    assert all(cell is not None for row in transition.state["board"] for cell in row)
    assert transition.is_complete
    assert transition.next_actor is None
    assert transition.state["turn_actor_id"] is None
    assert transition.result == {"outcome": "draw", "winner_actor_id": None}
    assert transition.state["result"] == transition.result


def test_win_on_final_board_cell_takes_precedence_over_draw():
    columns = [
        5, 0, 4, 1, 5, 5, 2, 1, 2, 1, 1, 3, 3, 4, 1, 3, 1, 2, 0, 5, 4,
        2, 4, 6, 5, 2, 2, 5, 3, 4, 6, 6, 0, 4, 6, 0, 6, 6, 0, 0, 3, 3,
    ]
    transition = play(columns)

    assert transition.state["move_count"] == 42
    assert transition.is_complete
    assert transition.result == {"outcome": "win", "winner_actor_id": SECOND}


@pytest.mark.parametrize("columns", [
    [3, 6, 1, 1, 2, 4, 0],
    DRAW_COLUMNS,
])
def test_terminal_states_reject_further_actions(columns):
    state = play(columns).state
    original = deepcopy(state)

    assert legal_actions(state, FIRST) == ()
    assert legal_actions(state, SECOND) == ()
    with pytest.raises(GameAlreadyCompleted):
        apply_move(state, FIRST, {"type": "drop_disc", "column": 0})
    assert state == original


def test_forged_terminal_result_or_unfinished_win_is_invalid():
    win_state = play([3, 6, 1, 1, 2, 4, 0]).state
    for result in (
        {"outcome": "win", "winner_actor_id": SECOND},
        {"outcome": "draw", "winner_actor_id": None},
        {"outcome": "win", "winner_actor_id": FIRST, "score": 100},
    ):
        forged = deepcopy(win_state)
        forged["result"] = result
        with pytest.raises(InvalidConnect4State):
            serialize_state(forged)

    unfinished = deepcopy(win_state)
    unfinished["status"] = "in_progress"
    unfinished["turn_actor_id"] = SECOND
    unfinished.pop("result")
    with pytest.raises(InvalidConnect4State):
        serialize_state(unfinished)
