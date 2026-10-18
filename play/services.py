"""Shared, transactional game-action application for human and bot actors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from games.engine import StaleGameState
from lobbies.models import LobbyBan, LobbyStatus, MembershipRole, PLAYER_SEAT_ROLES
from .action_rules import ACTION_RULES
from .locks import GameActionLockUnavailable, acquire_game_action_lock
from .models import (
    GameActionReceipt,
    GameSession,
    GameSessionParticipant,
    GameSessionStatus,
)


class GameActionError(Exception):
    code = "game_action_error"


class GameActionDenied(GameActionError):
    code = "permission_denied"


class GameActionInvalid(GameActionError):
    code = "invalid_payload"


class GameActionConflict(GameActionError):
    code = "action_conflict"


class GameActionUnavailable(GameActionError):
    code = "unsupported_game"


@dataclass(frozen=True)
class ActionOutcome:
    response: dict
    replayed: bool


def submit_game_action(
    *,
    session_uuid: str,
    action: Mapping[str, object],
    state_version: int,
    idempotency_key: str,
    user=None,
    bot_actor_id: str | None = None,
    lock_context=None,
) -> ActionOutcome:
    """Apply one versioned action and persist an idempotent response.

    WebSocket callers pass an authenticated user; internal bot callers pass a
    server-owned bot actor ID. Both follow the same rule and persistence path.
    """

    session_id = _uuid(session_uuid)
    key = _uuid(idempotency_key)
    if type(state_version) is not int or state_version < 1:
        raise GameActionInvalid("state_version must be a positive integer.")
    if not isinstance(action, Mapping):
        raise GameActionInvalid("action must be a JSON object.")
    if (user is None) == (bot_actor_id is None):
        raise GameActionDenied("Exactly one actor identity is required.")
    try:
        encoded = json.dumps(
            {"action": dict(action), "state_version": state_version},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise GameActionInvalid("action must contain strict JSON values.") from error
    request_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    lock_factory = lock_context or acquire_game_action_lock
    try:
        with lock_factory(session_id):
            with transaction.atomic():
                try:
                    session = (
                        GameSession.objects.select_for_update()
                        .select_related("lobby")
                        .get(public_id=session_id)
                    )
                except GameSession.DoesNotExist as error:
                    raise GameActionDenied("Game session is unavailable.") from error
                participant = _participant(session, user=user, bot_actor_id=bot_actor_id)
                receipt = GameActionReceipt.objects.filter(
                    session=session, participant=participant, idempotency_key=key
                ).first()
                if receipt is not None:
                    if receipt.request_hash != request_hash:
                        raise GameActionConflict(
                            "Request ID was used for another action."
                        )
                    return ActionOutcome(response=receipt.response, replayed=True)

                if (
                    session.status != GameSessionStatus.ACTIVE
                    or session.lobby.status != LobbyStatus.ACTIVE
                ):
                    raise GameActionConflict("Game session is not active.")
                if session.state_version != state_version:
                    raise StaleGameState()
                rules = ACTION_RULES.get((session.engine_key, session.engine_version))
                if rules is None:
                    raise GameActionUnavailable("Game action rules are unavailable.")
                transition = rules.apply(
                    session.authoritative_state, participant.actor_id, action
                )
                authoritative_state = dict(transition.state)
                session.authoritative_state = authoritative_state
                session.public_state = dict(rules.public_state(authoritative_state))
                session.spectator_state = dict(
                    rules.spectator_state(authoritative_state)
                )
                session.state_version += 1
                update_fields = [
                    "authoritative_state",
                    "public_state",
                    "spectator_state",
                    "state_version",
                    "updated_at",
                ]
                if transition.is_complete:
                    session.status = GameSessionStatus.COMPLETED
                    session.ended_at = timezone.now()
                    update_fields += ["status", "ended_at"]
                    lobby = session.lobby
                    lobby.status = LobbyStatus.COMPLETED
                    lobby.ended_at = session.ended_at
                    type(lobby).objects.filter(pk=lobby.pk).update(
                        status=lobby.status,
                        ended_at=lobby.ended_at,
                        updated_at=timezone.now(),
                    )
                session.save(update_fields=update_fields)
                response = {
                    "session_uuid": str(session.public_id),
                    "state_version": session.state_version,
                    "state": session.public_state,
                    "spectator_state": session.spectator_state,
                    "events": [dict(event) for event in transition.events],
                    "is_complete": transition.is_complete,
                    "result": dict(transition.result) if transition.result else None,
                }
                GameActionReceipt.objects.create(
                    session=session,
                    participant=participant,
                    idempotency_key=key,
                    request_hash=request_hash,
                    response=response,
                )
                return ActionOutcome(response=response, replayed=False)
    except GameActionLockUnavailable as error:
        raise GameActionConflict("Game action lock is unavailable.") from error


def get_game_snapshot(*, session_uuid: str, user) -> dict:
    """Return only the authenticated viewer's current state."""

    if (
        not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
        or getattr(user, "pk", None) is None
    ):
        raise GameActionDenied("Game connection is not allowed.")
    try:
        session = GameSession.objects.select_related("lobby").get(
            public_id=_uuid(session_uuid)
        )
    except GameSession.DoesNotExist as error:
        raise GameActionDenied("Game session is unavailable.") from error
    if LobbyBan.objects.active().filter(lobby=session.lobby, user=user).exists():
        raise GameActionDenied("Game connection is not allowed.")
    participant = GameSessionParticipant.objects.filter(
        session=session, user=user, is_bot=False,
        lobby_membership__left_at__isnull=True,
        lobby_membership__kicked_at__isnull=True,
    ).select_related("user").first()
    if participant is None or not participant.user.is_active:
        raise GameActionDenied("Game connection is not allowed.")
    is_player = participant.role in PLAYER_SEAT_ROLES
    if not is_player and (
        participant.role != MembershipRole.SPECTATOR
        or not session.lobby.allow_spectators
    ):
        raise GameActionDenied("Game connection is not allowed.")
    return {
        "session_uuid": str(session.public_id),
        "state_version": session.state_version,
        "status": session.status,
        "audience": "player" if is_player else "spectator",
        "state": session.public_state if is_player else session.spectator_state,
        "private_state": participant.private_state if is_player else None,
    }


def _participant(session, *, user, bot_actor_id):
    query = GameSessionParticipant.objects.filter(
        session=session, role__in=PLAYER_SEAT_ROLES,
        lobby_membership__left_at__isnull=True,
        lobby_membership__kicked_at__isnull=True,
    )
    if user is not None:
        if (
            not getattr(user, "is_authenticated", False)
            or not getattr(user, "is_active", False)
            or getattr(user, "pk", None) is None
            or LobbyBan.objects.active().filter(lobby=session.lobby, user=user).exists()
        ):
            raise GameActionDenied("Actor is not allowed to submit an action.")
        participant = (
            query.filter(user=user, is_bot=False).select_related("user").first()
        )
    else:
        participant = query.filter(actor_id=bot_actor_id, is_bot=True).first()
    if participant is None or (user is not None and not participant.user.is_active):
        raise GameActionDenied("Actor is not an active game player.")
    return participant


def _uuid(value):
    try:
        if not isinstance(value, (str, UUID)):
            raise ValueError
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise GameActionInvalid("A valid UUID is required.") from error
