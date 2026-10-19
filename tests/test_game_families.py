"""Reusable, pure family patterns used by multiple game engines."""

from copy import deepcopy

import pytest

from games.families.grid import drop_row, winning_markers
from games.families.hidden_role import public_players
from games.families.turn_based import actor_for_turn
from games.families.vote import plurality_target
from games.families.word import mask_answer


def test_grid_drop_and_line_scan_are_detached_and_generic():
    board = [[None, None, "x"], ["x", None, "x"], ["o", "o", "x"]]
    before = deepcopy(board)
    assert drop_row(board, 1) == 1
    assert drop_row(board, 2) is None
    assert winning_markers(board, 3) == {"x"}
    assert winning_markers(board, 4) == set()
    assert board == before
    with pytest.raises(ValueError):
        drop_row(board, True)
    with pytest.raises(ValueError):
        drop_row(board, 3)
    with pytest.raises(ValueError):
        winning_markers(board, 0)


def test_word_masking_preserves_nonletters_without_mutation():
    guesses = ["A", "E"]
    assert mask_answer("SEA-LANE", guesses) == "_EA-_A_E"
    assert guesses == ["A", "E"]
    with pytest.raises(ValueError):
        mask_answer("", guesses)
    with pytest.raises(ValueError):
        mask_answer("WORD", ["AB"])


def test_plurality_tie_empty_and_single_winner():
    assert plurality_target([]) is None
    assert plurality_target(["a", "b"]) is None
    assert plurality_target(["b", "a", "b"]) == "b"
    with pytest.raises(ValueError):
        plurality_target([""])


def test_hidden_role_projection_omits_unknown_fields():
    players = [
        {"actor_id": "a", "seat": 1, "alive": True, "role": "wolf", "secret": "do-not-copy"},
        {"actor_id": "b", "seat": 2, "alive": False, "role": "villager", "secret": "do-not-copy"},
    ]
    before = deepcopy(players)
    active = public_players(players)
    assert active == [
        {"actor_id": "a", "seat": 1, "alive": True},
        {"actor_id": "b", "seat": 2, "alive": False},
    ]
    assert public_players(players, reveal_roles=True)[0]["role"] == "wolf"
    assert "secret" not in str(public_players(players, reveal_roles=True))
    active[0]["alive"] = False
    assert players == before
    with pytest.raises(ValueError):
        public_players([{"actor_id": "a", "seat": 1, "alive": True}], reveal_roles=True)
    with pytest.raises(ValueError):
        public_players(players, reveal_roles="false")


def test_turn_rotation_requires_nonempty_roster_and_nonnegative_count():
    roster = ["a", "b", "c"]
    assert actor_for_turn(roster, 0) == "a"
    assert actor_for_turn(roster, 4) == "b"
    assert roster == ["a", "b", "c"]
    with pytest.raises(ValueError):
        actor_for_turn([], 0)
    with pytest.raises(ValueError):
        actor_for_turn(roster, -1)
    with pytest.raises(ValueError):
        actor_for_turn(roster, True)
