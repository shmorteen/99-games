import json

import pytest

from games.engine import (
    BaseGameEngine,
    GameAlreadyCompleted,
    GameEngineError,
    GameTransition,
    IllegalGameAction,
    InvalidActionPayload,
    InvalidGameActor,
    InvalidGameConfiguration,
    StaleGameState,
    UnauthorizedGameAction,
    assert_json_serializable,
)


class ContractTestEngine(BaseGameEngine):
    def validate_config(self, config):
        target_score = config.get("target_score")
        if not isinstance(target_score, int) or target_score < 1:
            raise InvalidGameConfiguration(
                "target_score must be a positive integer.",
                details={"field": "target_score"},
            )

    def create_initial_state(self, config, actors):
        self.validate_config(config)
        if not actors:
            raise InvalidGameConfiguration("at least one actor is required.")

        actor_ids = [str(actor["actor_id"]) for actor in actors]
        return {
            "version": 1,
            "target_score": config["target_score"],
            "score": 0,
            "turn": actor_ids[0],
            "actors": actor_ids,
            "hands": {actor_id: [f"secret-{actor_id}"] for actor_id in actor_ids},
            "applied_keys": [],
            "last_actor": None,
            "complete": False,
        }

    def get_public_state(self, state):
        return {
            "version": state["version"],
            "target_score": state["target_score"],
            "score": state["score"],
            "turn": state["turn"],
            "actors": state["actors"],
            "complete": state["complete"],
        }

    def get_spectator_state(self, state):
        return {
            "score": state["score"],
            "complete": state["complete"],
        }

    def get_private_state(self, state, actor_id):
        self._validate_actor(state, actor_id)
        return {
            "actor_id": actor_id,
            "hand": state["hands"][actor_id],
        }

    def legal_actions(self, state, actor_id):
        self._validate_actor(state, actor_id)
        if state["complete"] or state["turn"] != actor_id:
            return []
        return [{"type": "score", "points": 1}, {"type": "score", "points": 2}]

    def apply_action(
        self,
        state,
        actor_id,
        action,
        *,
        idempotency_key=None,
        state_version=None,
    ):
        self._validate_actor(state, actor_id)
        if state["complete"]:
            raise GameAlreadyCompleted()
        if state_version is not None and state_version != state["version"]:
            raise StaleGameState(details={"expected": state["version"]})
        if idempotency_key and idempotency_key in state["applied_keys"]:
            return GameTransition(
                state=state,
                events=[],
                is_complete=state["complete"],
                next_actor=state["turn"],
            )
        if actor_id != state["turn"]:
            raise UnauthorizedGameAction()
        if action.get("type") != "score":
            raise InvalidActionPayload(details={"field": "type"})

        points = action.get("points")
        if not isinstance(points, int):
            raise InvalidActionPayload(details={"field": "points"})
        if action not in self.legal_actions(state, actor_id):
            raise IllegalGameAction()

        actors = list(state["actors"])
        next_actor = actors[(actors.index(actor_id) + 1) % len(actors)]
        new_score = state["score"] + points
        complete = new_score >= state["target_score"]
        updated_state = {
            **state,
            "version": state["version"] + 1,
            "score": new_score,
            "turn": next_actor,
            "applied_keys": (
                [*state["applied_keys"], idempotency_key]
                if idempotency_key
                else state["applied_keys"]
            ),
            "last_actor": actor_id,
            "complete": complete,
        }
        return GameTransition(
            state=updated_state,
            events=[{"type": "score_applied", "actor_id": actor_id, "points": points}],
            is_complete=complete,
            next_actor=None if complete else next_actor,
            result=self.build_results(updated_state) if complete else None,
        )

    def handle_timeout(self, state, actor_id=None):
        actor = actor_id or state["turn"]
        self._validate_actor(state, actor)
        actors = list(state["actors"])
        next_actor = actors[(actors.index(actor) + 1) % len(actors)]
        updated_state = {
            **state,
            "version": state["version"] + 1,
            "turn": next_actor,
        }
        return GameTransition(
            state=updated_state,
            events=[{"type": "turn_timed_out", "actor_id": actor}],
            next_actor=next_actor,
        )

    def bot_action(self, state, actor_id, *, difficulty=None):
        self._validate_actor(state, actor_id)
        action = self.legal_actions(state, actor_id)[0]
        return {**action, "difficulty": difficulty or "standard"}

    def is_complete(self, state):
        return bool(state["complete"])

    def build_results(self, state):
        if not self.is_complete(state):
            return {"status": "in_progress"}
        return {
            "status": "complete",
            "score": state["score"],
            "winner": state["last_actor"],
        }

    def _validate_actor(self, state, actor_id):
        if actor_id not in state["actors"]:
            raise InvalidGameActor(details={"actor_id": actor_id})


def build_state():
    return ContractTestEngine().create_initial_state(
        {"target_score": 3},
        [{"actor_id": "player-1"}, {"actor_id": "player-2"}],
    )


def test_incomplete_game_engine_cannot_be_instantiated():
    class IncompleteEngine(BaseGameEngine):
        pass

    with pytest.raises(TypeError):
        IncompleteEngine()


def test_valid_test_engine_satisfies_contract_and_expected_behavior():
    engine = ContractTestEngine()
    state = build_state()

    public_state = engine.get_public_state(state)
    private_state = engine.get_private_state(state, "player-1")
    spectator_state = engine.get_spectator_state(state)
    transition = engine.apply_action(
        state,
        "player-1",
        {"type": "score", "points": 1},
        idempotency_key="action-1",
        state_version=1,
    )

    assert public_state["score"] == 0
    assert private_state == {"actor_id": "player-1", "hand": ["secret-player-1"]}
    assert spectator_state == {"score": 0, "complete": False}
    assert engine.legal_actions(state, "player-1")
    assert engine.bot_action(state, "player-1")["type"] == "score"
    assert transition.state["score"] == 1
    assert transition.next_actor == "player-2"
    assert engine.handle_timeout(transition.state).next_actor == "player-1"


def test_contract_engine_rejects_invalid_inputs_and_authorization_failures():
    engine = ContractTestEngine()
    state = build_state()

    with pytest.raises(InvalidGameConfiguration):
        engine.validate_config({"target_score": 0})
    with pytest.raises(InvalidGameActor):
        engine.get_private_state(state, "missing-player")
    with pytest.raises(UnauthorizedGameAction):
        engine.apply_action(state, "player-2", {"type": "score", "points": 1})
    with pytest.raises(InvalidActionPayload):
        engine.apply_action(state, "player-1", {"type": "dance"})
    with pytest.raises(IllegalGameAction):
        engine.apply_action(state, "player-1", {"type": "score", "points": 99})


def test_contract_engine_handles_stale_state_and_idempotent_retries():
    engine = ContractTestEngine()
    state = build_state()

    with pytest.raises(StaleGameState):
        engine.apply_action(
            state,
            "player-1",
            {"type": "score", "points": 1},
            state_version=99,
        )

    transition = engine.apply_action(
        state,
        "player-1",
        {"type": "score", "points": 1},
        idempotency_key="same-action",
        state_version=1,
    )
    duplicate = engine.apply_action(
        transition.state,
        "player-1",
        {"type": "score", "points": 1},
        idempotency_key="same-action",
        state_version=2,
    )

    assert duplicate.state == transition.state
    assert duplicate.events == ()


def test_contract_engine_rejects_actions_after_completion():
    engine = ContractTestEngine()
    state = build_state()
    first = engine.apply_action(
        state,
        "player-1",
        {"type": "score", "points": 2},
    )
    complete = engine.apply_action(
        first.state,
        "player-2",
        {"type": "score", "points": 1},
    )

    assert complete.is_complete is True
    assert complete.result == {"status": "complete", "score": 3, "winner": "player-2"}

    with pytest.raises(GameAlreadyCompleted):
        engine.apply_action(complete.state, "player-1", {"type": "score", "points": 1})


def test_game_transition_serializes_and_round_trips_as_json():
    transition = GameTransition(
        state={"version": 2, "score": 1},
        events=[{"type": "score_applied"}],
        is_complete=False,
        next_actor="player-2",
    )

    payload = transition.to_dict()
    restored = GameTransition.from_dict(json.loads(json.dumps(payload)))

    assert payload == {
        "state": {"version": 2, "score": 1},
        "events": [{"type": "score_applied"}],
        "is_complete": False,
        "next_actor": "player-2",
        "result": None,
    }
    assert restored == transition


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"state": {"value": object()}}, "state"),
        ({"state": {"ok": True}, "events": [{"value": object()}]}, "events"),
        ({"state": {"ok": True}, "result": {"score": float("nan")}}, "result"),
    ],
)
def test_game_transition_rejects_non_json_serializable_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        GameTransition(**kwargs)


def test_standard_engine_exceptions_have_stable_codes_and_json_details():
    exceptions = [
        InvalidGameConfiguration,
        IllegalGameAction,
        UnauthorizedGameAction,
        StaleGameState,
        GameAlreadyCompleted,
        InvalidGameActor,
        InvalidActionPayload,
    ]

    for exception_class in exceptions:
        error = exception_class(details={"field": "example"})
        payload = error.to_dict()

        assert isinstance(error, GameEngineError)
        assert payload["code"] == exception_class.code
        assert payload["message"] == exception_class.default_message
        assert payload["details"] == {"field": "example"}
        assert_json_serializable(payload, label=exception_class.__name__)


def test_public_and_private_state_separation_is_enforced_by_contract_engine():
    engine = ContractTestEngine()
    state = build_state()

    public_state = engine.get_public_state(state)
    spectator_state = engine.get_spectator_state(state)
    player_one_private = engine.get_private_state(state, "player-1")
    player_two_private = engine.get_private_state(state, "player-2")

    assert "hands" not in public_state
    assert "secret-player-1" not in json.dumps(public_state)
    assert "secret-player-2" not in json.dumps(public_state)
    assert "actors" not in spectator_state
    assert "secret-player-1" not in json.dumps(spectator_state)
    assert "secret-player-2" not in json.dumps(spectator_state)
    assert player_one_private["hand"] == ["secret-player-1"]
    assert "secret-player-2" not in json.dumps(player_one_private)
    assert player_two_private["hand"] == ["secret-player-2"]
