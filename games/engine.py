from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from typing import Any, TypeAlias


JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | dict[str, "JSONValue"] | list["JSONValue"]
JSONDict: TypeAlias = dict[str, JSONValue]


def assert_json_serializable(value: object, *, label: str = "value") -> None:
    """Raise ValueError when a value cannot be stored as strict JSON."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be JSON-serializable.") from error


class GameEngineError(Exception):
    """Base class for expected game engine failures.

    Engine errors represent domain validation failures that application services
    can translate into HTTP, WebSocket, or audit responses. They should not carry
    secret state in their message or details.
    """

    code = "game_engine_error"
    default_message = "The game engine rejected the operation."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, JSONValue] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = dict(details or {})
        assert_json_serializable(self.details, label="error details")
        super().__init__(self.message)

    def to_dict(self) -> JSONDict:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class InvalidGameConfiguration(GameEngineError):
    code = "invalid_game_configuration"
    default_message = "The game configuration is invalid."


class IllegalGameAction(GameEngineError):
    code = "illegal_game_action"
    default_message = "The requested action is not legal in the current state."


class UnauthorizedGameAction(GameEngineError):
    code = "unauthorized_game_action"
    default_message = "The actor is not allowed to perform this action."


class StaleGameState(GameEngineError):
    code = "stale_game_state"
    default_message = "The action targets a stale game state."


class GameAlreadyCompleted(GameEngineError):
    code = "game_already_completed"
    default_message = "The game has already completed."


class InvalidGameActor(GameEngineError):
    code = "invalid_game_actor"
    default_message = "The actor is not part of this game state."


class InvalidActionPayload(GameEngineError):
    code = "invalid_action_payload"
    default_message = "The action payload is invalid."


@dataclass(frozen=True)
class GameTransition:
    """A validated state transition returned by a game engine.

    The transition contains only domain data. Application services persist the
    state, increment versions, publish events, and write audit records.
    """

    state: Mapping[str, JSONValue]
    events: Sequence[Mapping[str, JSONValue]] = field(default_factory=tuple)
    is_complete: bool = False
    next_actor: str | None = None
    result: Mapping[str, JSONValue] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, Mapping):
            raise ValueError("state must be a JSON object.")
        if isinstance(self.events, (str, bytes)) or not isinstance(
            self.events,
            Sequence,
        ):
            raise ValueError("events must be a sequence of JSON objects.")

        events = tuple(self.events)
        for event in events:
            if not isinstance(event, Mapping):
                raise ValueError("events must contain only JSON objects.")
        if self.result is not None and not isinstance(self.result, Mapping):
            raise ValueError("result must be a JSON object when provided.")
        if self.next_actor is not None and not isinstance(self.next_actor, str):
            raise ValueError("next_actor must be a string when provided.")

        assert_json_serializable(dict(self.state), label="state")
        assert_json_serializable([dict(event) for event in events], label="events")
        if self.result is not None:
            assert_json_serializable(dict(self.result), label="result")

        object.__setattr__(self, "events", events)

    def to_dict(self) -> JSONDict:
        payload: JSONDict = {
            "state": dict(self.state),
            "events": [dict(event) for event in self.events],
            "is_complete": self.is_complete,
            "next_actor": self.next_actor,
            "result": dict(self.result) if self.result is not None else None,
        }
        assert_json_serializable(payload, label="transition")
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GameTransition":
        return cls(
            state=payload["state"],
            events=payload.get("events", ()),
            is_complete=bool(payload.get("is_complete", False)),
            next_actor=payload.get("next_actor"),
            result=payload.get("result"),
        )


class BaseGameEngine(ABC):
    """Abstract contract implemented by every playable game.

    Engines receive server-owned JSON configuration, actors, actions, and state.
    They return JSON-serializable state or `GameTransition` objects and raise the
    standard engine exceptions for expected domain failures.

    Engine code must stay pure domain logic: it must not write HTTP responses,
    render templates, send WebSocket messages, trust client-supplied scores or
    winners, or mutate database records directly. Services around the engine are
    responsible for authentication, authorization outside game rules,
    transactions, idempotency-key storage, state-version checks, persistence,
    broadcasting, and audit logging.

    Public state must be safe for every recipient in the game context. Spectator
    state must be safe for spectators and broadcast overlays. Private state must
    be scoped to the requested actor and must never leak hidden state belonging
    to another actor. Timeout handling must be deterministic for the supplied
    state so workers can safely retry scheduled timeout jobs.
    """

    @abstractmethod
    def validate_config(self, config: Mapping[str, JSONValue]) -> None:
        """Validate game configuration before lobby start.

        Raise `InvalidGameConfiguration` for unsupported or unsafe values. This
        method returns `None` when the configuration can be used to create the
        initial state.
        """

    @abstractmethod
    def create_initial_state(
        self,
        config: Mapping[str, JSONValue],
        actors: Sequence[Mapping[str, JSONValue]],
    ) -> JSONDict:
        """Build the first authoritative JSON state from config and actors.

        Actor records are server-supplied and should contain stable public
        identifiers, seating, bot flags, or other non-secret metadata needed by
        the game. The returned object must be JSON-serializable.
        """

    @abstractmethod
    def get_public_state(self, state: Mapping[str, JSONValue]) -> JSONDict:
        """Return state that can be shown without actor-specific secrets."""

    @abstractmethod
    def get_spectator_state(self, state: Mapping[str, JSONValue]) -> JSONDict:
        """Return state safe for spectators and broadcast overlays.

        Spectator state must not include hidden information or actor-private
        controls. It may be stricter than public player state when participants
        can see details that spectators should not receive.
        """

    @abstractmethod
    def get_private_state(
        self,
        state: Mapping[str, JSONValue],
        actor_id: str,
    ) -> JSONDict:
        """Return private state for one actor.

        Raise `InvalidGameActor` when the actor is not part of the state. The
        payload must not include hidden information for any other actor.
        """

    @abstractmethod
    def legal_actions(
        self,
        state: Mapping[str, JSONValue],
        actor_id: str,
    ) -> Sequence[Mapping[str, JSONValue]]:
        """Return currently legal action payloads for the actor."""

    @abstractmethod
    def apply_action(
        self,
        state: Mapping[str, JSONValue],
        actor_id: str,
        action: Mapping[str, JSONValue],
        *,
        idempotency_key: str | None = None,
        state_version: int | None = None,
    ) -> GameTransition:
        """Validate and apply one actor action.

        Engines must derive score, turn, winner, and completion information from
        authoritative state, never from client claims. Raise
        `UnauthorizedGameAction`, `IllegalGameAction`, `InvalidActionPayload`,
        `StaleGameState`, `InvalidGameActor`, or `GameAlreadyCompleted` as
        appropriate. Services persist idempotency outcomes, but engines should
        make duplicate-key handling deterministic when the key is represented in
        supplied state.
        """

    @abstractmethod
    def handle_timeout(
        self,
        state: Mapping[str, JSONValue],
        actor_id: str | None = None,
    ) -> GameTransition:
        """Apply a server-triggered timeout transition for the state."""

    @abstractmethod
    def bot_action(
        self,
        state: Mapping[str, JSONValue],
        actor_id: str,
        *,
        difficulty: str | None = None,
    ) -> JSONDict:
        """Return the action payload a bot actor wants to submit."""

    @abstractmethod
    def is_complete(self, state: Mapping[str, JSONValue]) -> bool:
        """Return whether the game state has reached a terminal result."""

    @abstractmethod
    def build_results(self, state: Mapping[str, JSONValue]) -> JSONDict:
        """Return final server-derived results for completed games."""


__all__ = [
    "BaseGameEngine",
    "GameAlreadyCompleted",
    "GameEngineError",
    "GameTransition",
    "IllegalGameAction",
    "InvalidActionPayload",
    "InvalidGameActor",
    "InvalidGameConfiguration",
    "JSONDict",
    "JSONPrimitive",
    "JSONValue",
    "StaleGameState",
    "UnauthorizedGameAction",
    "assert_json_serializable",
]
