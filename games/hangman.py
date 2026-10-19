"""Server-owned Hangman rules. The answer never leaves active public state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import secrets
import string
from uuid import UUID

from .engine import (
    BaseGameEngine, GameAlreadyCompleted, GameEngineError, GameTransition,
    IllegalGameAction, InvalidActionPayload, InvalidGameActor,
    InvalidGameConfiguration, StaleGameState, UnauthorizedGameAction,
)
from .families.turn_based import actor_for_turn
from .families.word import mask_answer


WORDS = ("ORBIT", "PLANET", "GALAXY", "PUZZLE", "CASTLE", "FOREST", "ROCKET", "BRIDGE")
SCHEMA_VERSION = "hangman.state.v1"


class InvalidHangmanState(GameEngineError):
    code = "invalid_hangman_state"
    default_message = "The Hangman state is invalid."


def _uuid(value: object) -> str:
    try:
        parsed = UUID(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or str(parsed) != value:
        raise ValueError("A canonical actor UUID is required.")
    return str(parsed)


class HangmanEngine(BaseGameEngine):
    def validate_config(self, config: Mapping[str, object]) -> None:
        if not isinstance(config, Mapping) or set(config) - {"max_wrong_guesses"}:
            raise InvalidGameConfiguration()
        maximum = config.get("max_wrong_guesses", 6)
        if type(maximum) is not int or not 1 <= maximum <= 12:
            raise InvalidGameConfiguration("max_wrong_guesses must be between 1 and 12.")

    def create_initial_state(self, config: Mapping[str, object], actors: Sequence[Mapping[str, object]]) -> dict:
        self.validate_config(config)
        if not isinstance(actors, Sequence) or isinstance(actors, (str, bytes)) or not 1 <= len(actors) <= 8:
            raise InvalidGameConfiguration("Hangman requires one to eight players.")
        try:
            seats = [(actor["seat"], _uuid(actor["actor_id"])) for actor in actors]
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidGameConfiguration("Invalid seated actor.") from error
        if any(type(seat) is not int for seat, _ in seats) or sorted(seat for seat, _ in seats) != list(range(1, len(seats) + 1)) or len({actor for _, actor in seats}) != len(seats):
            raise InvalidGameConfiguration("Actors need unique consecutive seats and UUIDs.")
        player_ids = [actor for _, actor in sorted(seats)]
        return {
            "schema_version": SCHEMA_VERSION,
            "game": "hangman",
            "answer": secrets.choice(WORDS),
            "players": player_ids,
            "turn_actor_id": player_ids[0],
            "guessed_letters": [],
            "wrong_guesses": 0,
            "max_wrong_guesses": config.get("max_wrong_guesses", 6),
            "action_count": 0,
            "status": "in_progress",
        }

    def _validated(self, state: Mapping[str, object]) -> dict:
        if not isinstance(state, Mapping) or state.get("schema_version") != SCHEMA_VERSION or state.get("game") != "hangman":
            raise InvalidHangmanState()
        answer = state.get("answer")
        players = state.get("players")
        guesses = state.get("guessed_letters")
        maximum = state.get("max_wrong_guesses")
        wrong = state.get("wrong_guesses")
        count = state.get("action_count")
        if answer not in WORDS or not isinstance(players, list) or not 1 <= len(players) <= 8 or not isinstance(guesses, list) or type(maximum) is not int or not 1 <= maximum <= 12 or type(wrong) is not int or type(count) is not int:
            raise InvalidHangmanState()
        try:
            if len(set(players)) != len(players) or any(_uuid(actor) != actor for actor in players):
                raise InvalidHangmanState()
        except (TypeError, ValueError) as error:
            raise InvalidHangmanState() from error
        if any(type(letter) is not str or len(letter) != 1 or letter not in string.ascii_uppercase for letter in guesses) or len(set(guesses)) != len(guesses) or wrong < 0 or wrong > maximum or count < len(guesses):
            raise InvalidHangmanState()
        timeout_count = count - len(guesses)
        if wrong != timeout_count + sum(letter not in answer for letter in guesses):
            raise InvalidHangmanState()
        won = set(answer) <= set(guesses)
        if won and wrong == maximum:
            raise InvalidHangmanState()
        complete = won or wrong == maximum
        if state.get("status") != ("completed" if complete else "in_progress") or state.get("turn_actor_id") != (None if complete else actor_for_turn(players, count)):
            raise InvalidHangmanState()
        return {
            "schema_version": SCHEMA_VERSION, "game": "hangman", "answer": answer,
            "players": list(players), "turn_actor_id": state["turn_actor_id"],
            "guessed_letters": list(guesses), "wrong_guesses": wrong,
            "max_wrong_guesses": maximum, "action_count": count, "status": state["status"],
        }

    def _visible(self, state: Mapping[str, object]) -> dict:
        current = self._validated(state)
        answer = current.pop("answer")
        guessed = set(current["guessed_letters"])
        current["mask"] = mask_answer(answer, guessed)
        if current["status"] == "completed":
            current["answer"] = answer
            current["result"] = self.build_results(state)
        return current

    def get_public_state(self, state: Mapping[str, object]) -> dict:
        return self._visible(state)

    def get_spectator_state(self, state: Mapping[str, object]) -> dict:
        return self._visible(state)

    def get_private_state(self, state: Mapping[str, object], actor_id: str) -> dict:
        current = self._validated(state)
        self._actor(current, actor_id)
        visible = self._visible(current)
        visible["legal_actions"] = list(self.legal_actions(current, actor_id))
        return visible

    @staticmethod
    def _actor(state: Mapping[str, object], actor_id: str) -> None:
        if actor_id not in state["players"]:
            raise InvalidGameActor()

    def legal_actions(self, state: Mapping[str, object], actor_id: str) -> tuple[dict, ...]:
        current = self._validated(state)
        self._actor(current, actor_id)
        if current["status"] == "completed" or current["turn_actor_id"] != actor_id:
            return ()
        return tuple({"type": "guess_letter", "letter": letter} for letter in string.ascii_uppercase if letter not in current["guessed_letters"])

    def apply_action(self, state: Mapping[str, object], actor_id: str, action: Mapping[str, object], *, idempotency_key: str | None = None, state_version: int | None = None) -> GameTransition:
        current = self._validated(state)
        self._actor(current, actor_id)
        if current["status"] == "completed":
            raise GameAlreadyCompleted()
        if state_version is not None and (type(state_version) is not int or state_version != current["action_count"]):
            raise StaleGameState()
        if current["turn_actor_id"] != actor_id:
            raise UnauthorizedGameAction()
        if not isinstance(action, Mapping) or set(action) != {"type", "letter"} or action.get("type") != "guess_letter" or type(action.get("letter")) is not str or len(action["letter"]) != 1 or action["letter"].upper() not in string.ascii_uppercase:
            raise InvalidActionPayload()
        letter = action["letter"].upper()
        if letter in current["guessed_letters"]:
            raise IllegalGameAction("That letter was already guessed.")
        current["guessed_letters"].append(letter)
        if letter not in current["answer"]:
            current["wrong_guesses"] += 1
        current["action_count"] += 1
        return self._transition(current, {"type": "hangman_letter_guessed", "actor_id": actor_id, "letter": letter, "correct": letter in current["answer"]})

    def _transition(self, current: dict, event: dict) -> GameTransition:
        won = set(current["answer"]) <= set(current["guessed_letters"])
        complete = won or current["wrong_guesses"] == current["max_wrong_guesses"]
        current["status"] = "completed" if complete else "in_progress"
        current["turn_actor_id"] = None if complete else actor_for_turn(current["players"], current["action_count"])
        events = [event]
        result = self.build_results(current) if complete else None
        if result is not None:
            events.append({"type": "hangman_game_completed", "result": result})
        return GameTransition(state=current, events=events, is_complete=complete, next_actor=current["turn_actor_id"], result=result)

    def handle_timeout(self, state: Mapping[str, object], actor_id: str | None = None) -> GameTransition:
        current = self._validated(state)
        if current["status"] == "completed":
            raise GameAlreadyCompleted()
        if actor_id is not None and actor_id != current["turn_actor_id"]:
            raise UnauthorizedGameAction()
        timed_out = current["turn_actor_id"]
        current["wrong_guesses"] += 1
        current["action_count"] += 1
        return self._transition(current, {"type": "hangman_turn_timed_out", "actor_id": timed_out})

    def bot_action(self, state: Mapping[str, object], actor_id: str, *, difficulty: str | None = None) -> dict:
        current = self._validated(state)
        self._actor(current, actor_id)
        if current["status"] == "completed":
            raise GameAlreadyCompleted()
        if current["turn_actor_id"] != actor_id:
            raise UnauthorizedGameAction()
        if difficulty not in (None, "casual"):
            raise InvalidGameConfiguration("Unsupported Hangman bot difficulty.")
        return next(action for action in self.legal_actions(current, actor_id) if action["letter"] not in current["guessed_letters"])

    def is_complete(self, state: Mapping[str, object]) -> bool:
        return self._validated(state)["status"] == "completed"

    def build_results(self, state: Mapping[str, object]) -> dict:
        current = self._validated(state)
        if current["status"] != "completed":
            raise IllegalGameAction("Hangman is not complete.")
        return {"outcome": "win" if set(current["answer"]) <= set(current["guessed_letters"]) else "loss", "answer": current["answer"], "wrong_guesses": current["wrong_guesses"]}


def register_engines(registry) -> None:
    registry.register("hangman", "0.1", HangmanEngine)
