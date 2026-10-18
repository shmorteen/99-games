from copy import deepcopy
from uuid import uuid4

import pytest

from games.engine import (
    GameAlreadyCompleted, IllegalGameAction, InvalidActionPayload,
    InvalidGameActor, InvalidGameConfiguration, StaleGameState,
    UnauthorizedGameAction,
)
from games.registry import GameEngineRegistry
from games.werewolves import WerewolvesEngine, register_engines


ACTORS = [{"actor_id": str(uuid4()), "seat": seat} for seat in range(1, 6)]


@pytest.fixture
def engine():
    return WerewolvesEngine()


@pytest.fixture
def state(engine, monkeypatch):
    monkeypatch.setattr("games.werewolves.secrets.SystemRandom", lambda: type("Picker", (), {"sample": lambda self, players, k: players[:k]})())
    return engine.create_initial_state({"day_seconds": 300, "night_seconds": 120}, ACTORS)


def test_initial_roles_registration_and_hidden_views(engine, state):
    registry = GameEngineRegistry()
    register_engines(registry)
    assert registry.create("werewolves-vs-villagers", "0.1").__class__ is WerewolvesEngine
    assert state["phase"] == "night"
    assert [player["role"] for player in state["players"]].count("werewolf") == 1
    wolf = state["players"][0]["actor_id"]
    villager = state["players"][1]["actor_id"]
    for visible in (engine.get_public_state(state), engine.get_spectator_state(state)):
        assert "werewolf" not in str(visible)
        assert "votes" not in visible
    assert engine.get_private_state(state, wolf)["role"] == "werewolf"
    assert engine.get_private_state(state, villager)["role"] == "villager"
    assert "werewolf" not in str(engine.get_private_state(state, villager))
    assert engine.legal_actions(state, villager) == ()
    assert len(engine.legal_actions(state, wolf)) == 4


def test_night_then_day_votes_end_in_villager_win(engine, state):
    wolf = state["players"][0]["actor_id"]
    victim = state["players"][1]["actor_id"]
    original = deepcopy(state)
    night = engine.apply_action(state, wolf, {"type": "vote", "target_actor_id": victim}, state_version=0)
    assert state == original
    assert night.state["phase"] == "day"
    assert night.state["players"][1]["alive"] is False
    assert "target_actor_id" not in night.events[0]
    assert "actor_id" not in night.events[0]
    current = night.state
    for player in current["players"]:
        if not player["alive"]:
            continue
        target = victim if player["actor_id"] != wolf else current["players"][2]["actor_id"]
        if target == victim:
            target = wolf
        current = engine.apply_action(current, player["actor_id"], {"type": "vote", "target_actor_id": target}).state
    assert engine.is_complete(current)
    assert engine.build_results(current)["winner"] == "villagers"
    assert "role" in engine.get_public_state(current)["players"][0]


def test_vote_validation_and_private_ballot(engine, state):
    wolf = state["players"][0]["actor_id"]
    victim = state["players"][1]["actor_id"]
    with pytest.raises(InvalidGameActor):
        engine.get_private_state(state, str(uuid4()))
    with pytest.raises(UnauthorizedGameAction):
        engine.apply_action(state, victim, {"type": "vote", "target_actor_id": wolf})
    with pytest.raises(StaleGameState):
        engine.apply_action(state, wolf, {"type": "vote", "target_actor_id": victim}, state_version=1)
    for action in ({"type": "vote", "target_actor_id": victim, "winner": "werewolves"}, {"type": "vote"}, {"type": "bad", "target_actor_id": victim}):
        with pytest.raises(InvalidActionPayload):
            engine.apply_action(state, wolf, action)
    with pytest.raises(IllegalGameAction):
        engine.apply_action(state, wolf, {"type": "vote", "target_actor_id": wolf})


def test_timeout_resolves_tie_and_eventually_draws(engine, state):
    first = engine.handle_timeout(state)
    assert first.state == engine.handle_timeout(state).state
    assert first.state["phase"] == "day"
    assert first.state["last_eliminated_actor_id"] is None
    current = first.state
    for _ in range(39):
        current = engine.handle_timeout(current).state
    assert engine.build_results(current)["winner"] == "draw"
    with pytest.raises(GameAlreadyCompleted):
        engine.handle_timeout(current)


def test_werewolf_parity_win_and_private_votes(engine, state):
    wolf, first, second, third, fourth = [player["actor_id"] for player in state["players"]]
    current = engine.apply_action(state, wolf, {"type": "vote", "target_actor_id": first}).state
    ballots = ((wolf, second), (second, third), (third, second), (fourth, second))
    for voter, target in ballots:
        current = engine.apply_action(current, voter, {"type": "vote", "target_actor_id": target}).state
    assert current["phase"] == "night"
    current = engine.apply_action(current, wolf, {"type": "vote", "target_actor_id": third}).state
    assert engine.build_results(current) == {"winner": "werewolves"}


def test_tied_day_vote_eliminates_nobody_and_ballots_stay_private(engine, state):
    wolf, first, second, third, fourth = [player["actor_id"] for player in state["players"]]
    current = engine.apply_action(state, wolf, {"type": "vote", "target_actor_id": first}).state
    current = engine.apply_action(current, wolf, {"type": "vote", "target_actor_id": second}).state
    assert engine.get_private_state(current, wolf)["vote_target_actor_id"] == second
    assert "votes" not in engine.get_public_state(current)
    with pytest.raises(IllegalGameAction):
        engine.apply_action(current, wolf, {"type": "vote", "target_actor_id": third})
    for voter, target in ((second, wolf), (third, wolf), (fourth, second)):
        current = engine.apply_action(current, voter, {"type": "vote", "target_actor_id": target}).state
    assert current["last_eliminated_actor_id"] is None
    assert current["phase"] == "night"


@pytest.mark.parametrize("config", [{"day_seconds": 0, "night_seconds": 120}, {"day_seconds": True, "night_seconds": 120}, {"day_seconds": 300, "night_seconds": 120, "roles": []}])
def test_invalid_config(engine, config):
    with pytest.raises(InvalidGameConfiguration):
        engine.create_initial_state(config, ACTORS)


def test_rejects_forged_state_and_bots(engine, state):
    state["players"][0]["role"] = "villager"
    with pytest.raises(Exception) as error:
        engine.get_public_state(state)
    assert error.value.code == "invalid_werewolves_state"
    clean = engine.create_initial_state({"day_seconds": 300, "night_seconds": 120}, ACTORS)
    with pytest.raises(InvalidGameConfiguration):
        engine.bot_action(clean, clean["players"][0]["actor_id"])
    clean["votes"] = {clean["players"][0]["actor_id"]: []}
    with pytest.raises(Exception) as malformed:
        engine.get_public_state(clean)
    assert malformed.value.code == "invalid_werewolves_state"
