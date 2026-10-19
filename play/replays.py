"""Validated, spectator-safe Connect4 history from durable action receipts."""

import hashlib
import json

from django.db import transaction

from games.connect4_moves import apply_move
from games.connect4_state import serialize_state
from games.engine import GameEngineError
from lobbies.models import PLAYER_SEAT_ROLES

from .models import GameActionReceipt, GameSession, GameSessionStatus
from .services import GameActionError, get_game_snapshot


class ReplayUnavailable(GameActionError):
    code = "replay_unavailable"


def build_connect4_replay(*, session_uuid, user):
    """Rebuild a completed match and reject missing or altered history.

    Receipt JSON is never exposed directly. Every transition is replayed with
    server rules and serialized through the Connect4 public-state whitelist.
    """

    return _build_connect4_replay(session_uuid=session_uuid, user=user, staff=False)


def build_connect4_admin_replay(*, session_uuid, user):
    """Let an authorized operator inspect validated, public-only replay frames."""

    if not (
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_staff", False)
        and user.has_perm("play.view_gamesession")
    ):
        raise ReplayUnavailable("Completed replay is unavailable.")
    return _build_connect4_replay(session_uuid=session_uuid, user=user, staff=True)


def _build_connect4_replay(*, session_uuid, user, staff):
    with transaction.atomic():
        if not staff:
            get_game_snapshot(session_uuid=session_uuid, user=user)
        session = GameSession.objects.select_related("game").filter(
            public_id=session_uuid, game__slug="connect4",
            engine_key="connect4", engine_version="0.1",
            status=GameSessionStatus.COMPLETED,
        ).first()
        if session is None:
            raise ReplayUnavailable("Completed replay is unavailable.")
        try:
            current = serialize_state(session.initial_state)
            if current["move_count"] != 0 or current["status"] != "in_progress":
                raise ReplayUnavailable("Completed replay is unavailable.")
            receipts = list(
                GameActionReceipt.objects.filter(session=session)
                .select_related("participant")
            )
            if len(receipts) != session.state_version - 1 or len(receipts) > 42:
                raise ReplayUnavailable("Completed replay is unavailable.")
            for receipt in receipts:
                if not isinstance(receipt.response, dict):
                    raise ReplayUnavailable("Completed replay is unavailable.")
                version = receipt.response.get("state_version")
                if type(version) is not int:
                    raise ReplayUnavailable("Completed replay is unavailable.")
            receipts.sort(key=lambda receipt: receipt.response["state_version"])
            frames = [{"state_version": 1, "state": current, "move": None}]
            for version, receipt in enumerate(receipts, start=2):
                response = receipt.response
                events = response.get("events")
                if (
                    response["state_version"] != version
                    or response.get("session_uuid") != str(session.public_id)
                    or receipt.participant.role not in PLAYER_SEAT_ROLES
                    or not isinstance(events, list) or not events
                    or not isinstance(events[0], dict)
                ):
                    raise ReplayUnavailable("Completed replay is unavailable.")
                column = events[0].get("column")
                action = {"type": "drop_disc", "column": column}
                encoded_request = json.dumps(
                    {"action": action, "state_version": version - 1},
                    sort_keys=True, separators=(",", ":"), allow_nan=False,
                )
                if receipt.request_hash != hashlib.sha256(
                    encoded_request.encode("utf-8")
                ).hexdigest():
                    raise ReplayUnavailable("Completed replay is unavailable.")
                transition = apply_move(
                    current, receipt.participant.actor_id,
                    action,
                )
                next_state = serialize_state(transition.state)
                if (
                    events != [dict(event) for event in transition.events]
                    or response.get("is_complete") != transition.is_complete
                    or response.get("result") != transition.result
                    or serialize_state(response.get("state")) != next_state
                    or serialize_state(response.get("spectator_state")) != next_state
                ):
                    raise ReplayUnavailable("Completed replay is unavailable.")
                dropped = transition.events[0]
                frames.append({
                    "state_version": version,
                    "state": next_state,
                    "move": {
                        "number": next_state["move_count"],
                        "column": dropped["column"],
                        "row": dropped["row"],
                        "marker": dropped["marker"],
                    },
                })
                current = next_state
            if (
                current["status"] != "completed"
                or session.state_version != len(frames)
                or any(
                    serialize_state(saved) != current
                    for saved in (
                        session.authoritative_state, session.public_state,
                        session.spectator_state,
                    )
                )
            ):
                raise ReplayUnavailable("Completed replay is unavailable.")
        except (GameEngineError, KeyError, TypeError, ValueError) as error:
            raise ReplayUnavailable("Completed replay is unavailable.") from error

    result = current["result"]
    winner_marker = None
    if result["outcome"] == "win":
        winner_marker = next(
            player["marker"] for player in current["players"]
            if player["actor_id"] == result["winner_actor_id"]
        )
    return {
        "session_uuid": str(session.public_id),
        "frames": frames,
        "result": {
            "outcome": result["outcome"],
            "winner_marker": winner_marker,
            "move_count": current["move_count"],
        },
    }
