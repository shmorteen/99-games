"""Pure Werewolves vs Villagers voting engine with secret role boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import secrets
from uuid import UUID

from .engine import (
    BaseGameEngine, GameAlreadyCompleted, GameEngineError, GameTransition,
    IllegalGameAction, InvalidActionPayload, InvalidGameActor,
    InvalidGameConfiguration, StaleGameState, UnauthorizedGameAction,
)
from .families.hidden_role import public_players
from .families.vote import plurality_target


SCHEMA_VERSION = "werewolves.state.v1"
GAME_KEY = "werewolves-vs-villagers"
MAX_ROUNDS = 20
ROLES = ("werewolf", "villager")


class InvalidWerewolvesState(GameEngineError):
    code = "invalid_werewolves_state"
    default_message = "The Werewolves vs Villagers state is invalid."


def _uuid(value: object) -> str:
    try:
        parsed = UUID(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or str(parsed) != value:
        raise ValueError("Canonical UUID required.")
    return str(parsed)


def _winner(players: list[dict]) -> str | None:
    wolves = sum(player["alive"] and player["role"] == "werewolf" for player in players)
    villagers = sum(player["alive"] and player["role"] == "villager" for player in players)
    if wolves == 0:
        return "villagers"
    if wolves >= villagers:
        return "werewolves"
    return None


class WerewolvesEngine(BaseGameEngine):
    def validate_config(self, config: Mapping[str, object]) -> None:
        if not isinstance(config, Mapping) or set(config) - {"day_seconds", "night_seconds"}:
            raise InvalidGameConfiguration()
        for key, default in (("day_seconds", 300), ("night_seconds", 120)):
            value = config.get(key, default)
            if type(value) is not int or not 30 <= value <= 3600:
                raise InvalidGameConfiguration(f"{key} must be between 30 and 3600.")

    def create_initial_state(self, config: Mapping[str, object], actors: Sequence[Mapping[str, object]]) -> dict:
        self.validate_config(config)
        if not isinstance(actors, Sequence) or isinstance(actors, (str, bytes)) or not 5 <= len(actors) <= 20:
            raise InvalidGameConfiguration("Five to twenty seated players are required.")
        try:
            seated = [(actor["seat"], _uuid(actor["actor_id"])) for actor in actors]
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidGameConfiguration("Invalid actor record.") from error
        if any(type(seat) is not int for seat, _ in seated) or sorted(seat for seat, _ in seated) != list(range(1, len(seated) + 1)) or len({actor for _, actor in seated}) != len(seated):
            raise InvalidGameConfiguration("Actors need unique consecutive seats and UUIDs.")
        seated.sort()
        wolf_count = max(1, len(seated) // 4)
        wolves = set(secrets.SystemRandom().sample([actor for _, actor in seated], wolf_count))
        state = {
            "schema_version": SCHEMA_VERSION, "game": GAME_KEY,
            "status": "in_progress", "phase": "night", "round_number": 1,
            "day_seconds": config.get("day_seconds", 300),
            "night_seconds": config.get("night_seconds", 120),
            "players": [
                {"actor_id": actor, "seat": seat, "alive": True,
                 "role": "werewolf" if actor in wolves else "villager"}
                for seat, actor in seated
            ],
            "votes": {}, "action_count": 0,
            "last_eliminated_actor_id": None,
        }
        return self._validated(state)

    def _validated(self, state: Mapping[str, object]) -> dict:
        if not isinstance(state, Mapping) or state.get("schema_version") != SCHEMA_VERSION or state.get("game") != GAME_KEY:
            raise InvalidWerewolvesState()
        players = state.get("players")
        votes = state.get("votes")
        round_number = state.get("round_number")
        count = state.get("action_count")
        if not isinstance(players, list) or not 5 <= len(players) <= 20 or not isinstance(votes, dict) or type(round_number) is not int or not 1 <= round_number <= MAX_ROUNDS or type(count) is not int or count < 0:
            raise InvalidWerewolvesState()
        for key in ("day_seconds", "night_seconds"):
            value = state.get(key)
            if type(value) is not int or not 30 <= value <= 3600:
                raise InvalidWerewolvesState()
        normalized = []
        try:
            for player in players:
                actor = _uuid(player["actor_id"])
                seat = player["seat"]
                alive = player["alive"]
                role = player["role"]
                if type(seat) is not int or type(alive) is not bool or role not in ROLES:
                    raise InvalidWerewolvesState()
                normalized.append({"actor_id": actor, "seat": seat, "alive": alive, "role": role})
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidWerewolvesState() from error
        if [player["seat"] for player in normalized] != list(range(1, len(players) + 1)) or len({player["actor_id"] for player in normalized}) != len(players) or sum(player["role"] == "werewolf" for player in normalized) != max(1, len(players) // 4):
            raise InvalidWerewolvesState()
        by_id = {player["actor_id"]: player for player in normalized}
        phase = state.get("phase")
        status = state.get("status")
        if status not in ("in_progress", "completed") or (status == "in_progress" and phase not in ("night", "day")) or (status == "completed" and phase is not None):
            raise InvalidWerewolvesState()
        last = state.get("last_eliminated_actor_id")
        if last is not None and (type(last) is not str or last not in by_id or by_id[last]["alive"]):
            raise InvalidWerewolvesState()
        if status == "completed":
            if votes:
                raise InvalidWerewolvesState()
            winner = _winner(normalized) or ("draw" if round_number == MAX_ROUNDS else None)
            if winner is None or state.get("result") != {"winner": winner}:
                raise InvalidWerewolvesState()
        else:
            if "result" in state or _winner(normalized) is not None:
                raise InvalidWerewolvesState()
            eligible = {player["actor_id"] for player in normalized if player["alive"] and (phase == "day" or player["role"] == "werewolf")}
            for voter, target in votes.items():
                if type(voter) is not str or type(target) is not str or voter not in eligible or target not in by_id or not by_id[target]["alive"] or target == voter:
                    raise InvalidWerewolvesState()
            if len(votes) >= len(eligible):
                raise InvalidWerewolvesState()
        result = {
            "schema_version": SCHEMA_VERSION, "game": GAME_KEY, "status": status,
            "phase": phase, "round_number": round_number,
            "day_seconds": state["day_seconds"], "night_seconds": state["night_seconds"],
            "players": normalized, "votes": dict(votes), "action_count": count,
            "last_eliminated_actor_id": last,
        }
        if status == "completed":
            result["result"] = dict(state["result"])
        return result

    def _visible(self, state: Mapping[str, object]) -> dict:
        current = self._validated(state)
        completed = current["status"] == "completed"
        return {
            "schema_version": SCHEMA_VERSION, "game": GAME_KEY,
            "status": current["status"], "phase": current["phase"],
            "round_number": current["round_number"],
            "phase_seconds": current["day_seconds"] if current["phase"] == "day" else current["night_seconds"] if current["phase"] == "night" else None,
            "players": public_players(current["players"], reveal_roles=completed),
            "votes_cast": len(current["votes"]),
            "last_eliminated_actor_id": current["last_eliminated_actor_id"],
            **({"result": current["result"]} if completed else {}),
        }

    def get_public_state(self, state: Mapping[str, object]) -> dict:
        return self._visible(state)

    def get_spectator_state(self, state: Mapping[str, object]) -> dict:
        return self._visible(state)

    def get_private_state(self, state: Mapping[str, object], actor_id: str) -> dict:
        current = self._validated(state)
        player = self._actor(current, actor_id)
        return {
            "actor_id": actor_id, "role": player["role"], "alive": player["alive"],
            "vote_target_actor_id": current["votes"].get(actor_id),
            "legal_actions": list(self.legal_actions(current, actor_id)),
        }

    @staticmethod
    def _actor(state: Mapping[str, object], actor_id: str) -> dict:
        for player in state["players"]:
            if player["actor_id"] == actor_id:
                return player
        raise InvalidGameActor()

    def legal_actions(self, state: Mapping[str, object], actor_id: str) -> tuple[dict, ...]:
        current = self._validated(state)
        player = self._actor(current, actor_id)
        if current["status"] == "completed" or not player["alive"] or actor_id in current["votes"] or (current["phase"] == "night" and player["role"] != "werewolf"):
            return ()
        return tuple(
            {"type": "vote", "target_actor_id": target["actor_id"]}
            for target in current["players"] if target["alive"] and target["actor_id"] != actor_id
        )

    def apply_action(self, state: Mapping[str, object], actor_id: str, action: Mapping[str, object], *, idempotency_key: str | None = None, state_version: int | None = None) -> GameTransition:
        current = self._validated(state)
        player = self._actor(current, actor_id)
        if current["status"] == "completed":
            raise GameAlreadyCompleted()
        if state_version is not None and (type(state_version) is not int or state_version != current["action_count"]):
            raise StaleGameState()
        if not player["alive"] or (current["phase"] == "night" and player["role"] != "werewolf"):
            raise UnauthorizedGameAction()
        if not isinstance(action, Mapping) or set(action) != {"type", "target_actor_id"} or action.get("type") != "vote" or type(action.get("target_actor_id")) is not str:
            raise InvalidActionPayload()
        target = action["target_actor_id"]
        if actor_id in current["votes"] or target not in {candidate["target_actor_id"] for candidate in self.legal_actions(current, actor_id)}:
            raise IllegalGameAction("Vote is not legal in this phase.")
        current["votes"][actor_id] = target
        current["action_count"] += 1
        events = [{"type": "werewolves_vote_cast", "phase": current["phase"], "votes_cast": len(current["votes"])}]
        eligible = [candidate for candidate in current["players"] if candidate["alive"] and (current["phase"] == "day" or candidate["role"] == "werewolf")]
        if len(current["votes"]) == len(eligible):
            return self._resolve(current, events)
        return GameTransition(state=self._validated(current), events=events)

    def _resolve(self, current: dict, events: list[dict]) -> GameTransition:
        phase = current["phase"]
        eliminated = plurality_target(current["votes"].values())
        if eliminated is not None:
            self._actor(current, eliminated)["alive"] = False
        current["votes"] = {}
        current["last_eliminated_actor_id"] = eliminated
        events.append({"type": "werewolves_phase_resolved", "phase": phase, "eliminated_actor_id": eliminated})
        winner = _winner(current["players"])
        if winner is None and phase == "day" and current["round_number"] == MAX_ROUNDS:
            winner = "draw"
        if winner is not None:
            current["status"] = "completed"
            current["phase"] = None
            current["result"] = {"winner": winner}
            events.append({"type": "werewolves_game_completed", "result": current["result"]})
        elif phase == "night":
            current["phase"] = "day"
        else:
            current["phase"] = "night"
            current["round_number"] += 1
        validated = self._validated(current)
        complete = validated["status"] == "completed"
        return GameTransition(state=validated, events=events, is_complete=complete, result=validated.get("result"))

    def handle_timeout(self, state: Mapping[str, object], actor_id: str | None = None) -> GameTransition:
        current = self._validated(state)
        if current["status"] == "completed":
            raise GameAlreadyCompleted()
        if actor_id is not None:
            raise UnauthorizedGameAction("Phase timeout must be server-triggered.")
        current["action_count"] += 1
        return self._resolve(current, [{"type": "werewolves_phase_timed_out", "phase": current["phase"]}])

    def bot_action(self, state: Mapping[str, object], actor_id: str, *, difficulty: str | None = None) -> dict:
        current = self._validated(state)
        self._actor(current, actor_id)
        raise InvalidGameConfiguration("Bots are not supported for Werewolves vs Villagers.")

    def is_complete(self, state: Mapping[str, object]) -> bool:
        return self._validated(state)["status"] == "completed"

    def build_results(self, state: Mapping[str, object]) -> dict:
        current = self._validated(state)
        if current["status"] != "completed":
            raise IllegalGameAction("The game is not complete.")
        return dict(current["result"])


def register_engines(registry) -> None:
    registry.register(GAME_KEY, "0.1", WerewolvesEngine)
