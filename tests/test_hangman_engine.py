import pytest

from games.engine import (
    GameAlreadyCompleted,
    IllegalGameAction,
    InvalidActionPayload,
    InvalidGameActor,
    InvalidGameConfiguration,
    StaleGameState,
    UnauthorizedGameAction,
)
from games.hangman import HangmanEngine, register_engines
from games.registry import GameEngineRegistry


ACTORS = [
    {"actor_id": "11111111-1111-4111-8111-111111111111", "seat": 1},
    {"actor_id": "22222222-2222-4222-8222-222222222222", "seat": 2},
]


@pytest.fixture
def engine():
    return HangmanEngine()


@pytest.fixture
def state(engine, monkeypatch):
    monkeypatch.setattr("games.hangman.secrets.choice", lambda words: "ORBIT")
    return engine.create_initial_state({"max_wrong_guesses": 6}, ACTORS)


def test_initial_state_hides_answer_and_registers(engine, state):
    registry = GameEngineRegistry()
    register_engines(registry)
    assert registry.create("hangman", "0.1").__class__ is HangmanEngine
    assert state["answer"] == "ORBIT"
    for view in (
        engine.get_public_state(state),
        engine.get_spectator_state(state),
        engine.get_private_state(state, ACTORS[0]["actor_id"]),
    ):
        assert "answer" not in view
        assert view["mask"] == "_____"
    assert len(engine.legal_actions(state, ACTORS[0]["actor_id"])) == 26
    assert engine.legal_actions(state, ACTORS[1]["actor_id"]) == ()


def test_correct_guess_rotates_turn_and_does_not_mutate(engine, state):
    before = state.copy()
    transition = engine.apply_action(state, ACTORS[0]["actor_id"], {"type": "guess_letter", "letter": "o"}, state_version=0)
    assert engine.get_public_state(transition.state)["mask"] == "O____"
    assert transition.next_actor == ACTORS[1]["actor_id"]
    assert transition.state["wrong_guesses"] == 0
    assert state == before
    assert "answer" not in transition.events[0]


def test_wrong_guesses_loss_and_answer_reveal(engine, state):
    for letter in "ACDEFJ":
        state = engine.apply_action(state, state["turn_actor_id"], {"type": "guess_letter", "letter": letter}).state
    assert engine.is_complete(state)
    assert engine.build_results(state)["outcome"] == "loss"
    assert engine.get_public_state(state)["answer"] == "ORBIT"
    assert engine.legal_actions(state, ACTORS[0]["actor_id"]) == ()
    with pytest.raises(GameAlreadyCompleted):
        engine.apply_action(state, ACTORS[0]["actor_id"], {"type": "guess_letter", "letter": "O"})


def test_win_derived_from_letters(engine, state):
    for letter in "ORBIT":
        state = engine.apply_action(state, state["turn_actor_id"], {"type": "guess_letter", "letter": letter}).state
    assert engine.build_results(state) == {"outcome": "win", "answer": "ORBIT", "wrong_guesses": 0}


def test_invalid_actions_and_actors(engine, state):
    actor = ACTORS[0]["actor_id"]
    with pytest.raises(InvalidGameActor):
        engine.get_private_state(state, "33333333-3333-4333-8333-333333333333")
    with pytest.raises(UnauthorizedGameAction):
        engine.apply_action(state, ACTORS[1]["actor_id"], {"type": "guess_letter", "letter": "A"})
    with pytest.raises(StaleGameState):
        engine.apply_action(state, actor, {"type": "guess_letter", "letter": "A"}, state_version=1)
    for action in ({"type": "guess_letter", "letter": "AB"}, {"type": "guess_letter", "letter": "A", "winner": actor}, {"type": "bad", "letter": "A"}):
        with pytest.raises(InvalidActionPayload):
            engine.apply_action(state, actor, action)
    updated = engine.apply_action(state, actor, {"type": "guess_letter", "letter": "A"}).state
    with pytest.raises(IllegalGameAction):
        engine.apply_action(updated, ACTORS[1]["actor_id"], {"type": "guess_letter", "letter": "a"})


def test_timeout_is_deterministic_and_finishes(engine, state):
    first = engine.handle_timeout(state, ACTORS[0]["actor_id"])
    assert first.state == engine.handle_timeout(state, ACTORS[0]["actor_id"]).state
    assert first.state["wrong_guesses"] == 1
    assert first.next_actor == ACTORS[1]["actor_id"]
    with pytest.raises(UnauthorizedGameAction):
        engine.handle_timeout(first.state, ACTORS[0]["actor_id"])
    current = first.state
    for _ in range(5):
        current = engine.handle_timeout(current).state
    assert engine.build_results(current)["outcome"] == "loss"


def test_bot_and_state_isolation(engine, state):
    actor = ACTORS[0]["actor_id"]
    assert engine.bot_action(state, actor) == {"type": "guess_letter", "letter": "A"}
    with pytest.raises(InvalidGameConfiguration):
        engine.bot_action(state, actor, difficulty="expert")
    state["internal_note"] = "do not display"
    assert "internal_note" not in engine.get_public_state(state)
    assert "internal_note" not in engine.get_spectator_state(state)
    state["wrong_guesses"] = 7
    with pytest.raises(Exception) as error:
        engine.get_public_state(state)
    assert error.value.code == "invalid_hangman_state"


def test_rejects_forged_attempt_counts(engine, state):
    state["wrong_guesses"] = 1
    with pytest.raises(Exception) as error:
        engine.get_spectator_state(state)
    assert error.value.code == "invalid_hangman_state"


@pytest.mark.parametrize("config", [{"answer": "SECRET"}, {"max_wrong_guesses": True}, {"max_wrong_guesses": 0}, {"max_wrong_guesses": 20}])
def test_rejects_unsafe_config(engine, config):
    with pytest.raises(InvalidGameConfiguration):
        engine.create_initial_state(config, ACTORS)
