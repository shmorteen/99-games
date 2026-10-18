from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from games.engine import GameEngineError
from games.registry import GameEngineRegistryError, game_engine_registry
from play.models import GameSession, GameSessionParticipant
from .locks import LobbyStartLockUnavailable, acquire_lobby_start_lock
from .models import (
    PLAYER_SEAT_ROLES,
    GameLobby,
    LobbyAuditEvent,
    LobbyAuditEventType,
    LobbyBan,
    LobbyMembership,
    LobbyStatus,
    LobbyVisibility,
    MembershipConnectionStatus,
    MembershipRole,
)


logger = logging.getLogger(__name__)


class LobbyServiceError(Exception):
    """Base exception for lobby service failures."""


class LobbyAuthenticationError(LobbyServiceError):
    """Raised when a lobby mutation needs an authenticated saved user."""


class LobbyAccessDenied(LobbyServiceError):
    """Raised when a user is not allowed to join or mutate a lobby."""


class LobbyCredentialsError(LobbyServiceError):
    """Raised when lobby credentials are missing, invalid, or expired."""


class LobbyNotJoinable(LobbyServiceError):
    """Raised when lobby state does not allow joining."""


class LobbyAlreadyMember(LobbyServiceError):
    """Raised when a user already has an active membership."""


class LobbyFull(LobbyServiceError):
    """Raised when the requested lobby role has no remaining capacity."""


class LobbyMembershipNotFound(LobbyServiceError):
    """Raised when a user has no active membership to leave."""


class LobbyJoinConflict(LobbyServiceError):
    """Raised when concurrent writes prevent a deterministic join."""


class LobbyValidationError(LobbyServiceError):
    """Raised when a lobby event payload is structurally invalid."""


class LobbyStartError(LobbyServiceError):
    """Raised when a game session cannot be started safely."""


class LobbyStartConflict(LobbyServiceError):
    """Raised when a lobby start lock cannot be acquired."""


@dataclass(frozen=True)
class GameStartResult:
    session: GameSession
    public_state: dict
    spectator_state: dict
    private_states_by_user_id: dict[str, dict]
    game_route: str


HOST_SUCCESSOR_ROLES = (
    MembershipRole.CO_HOST,
    MembershipRole.PLAYER,
    MembershipRole.MODERATOR,
)
ACTIVE_GAME_LEAVE_POLICY = "disconnect_forfeit"
MAX_JOIN_RETRIES = 2


def join_lobby(
    *,
    lobby: GameLobby,
    user,
    as_spectator: bool = False,
    password: str | None = None,
    invite_token: str | None = None,
    idempotency_key: str | None = None,
) -> LobbyMembership:
    """Join a waiting lobby as a player or spectator."""

    _require_authenticated_user(user)
    _require_unsuspended_user(user)
    key = _normalize_idempotency_key(idempotency_key)
    last_error: IntegrityError | None = None

    for _attempt in range(MAX_JOIN_RETRIES):
        try:
            with transaction.atomic():
                locked_lobby = _lock_lobby(lobby)
                idempotent_event = _idempotent_event(
                    lobby=locked_lobby,
                    actor=user,
                    event_type=LobbyAuditEventType.JOINED,
                    key=key,
                )
                if idempotent_event and idempotent_event.membership_id:
                    return idempotent_event.membership

                _validate_joinable_lobby(locked_lobby)
                _validate_join_credentials(
                    locked_lobby,
                    password=password,
                    invite_token=invite_token,
                )
                _validate_not_banned(locked_lobby, user)

                active_memberships = _locked_active_memberships(locked_lobby)
                if _active_user_membership(active_memberships, user):
                    raise LobbyAlreadyMember("User already has an active membership.")

                if as_spectator:
                    membership = _create_spectator_membership(
                        locked_lobby,
                        user,
                        active_memberships,
                    )
                else:
                    membership = _create_player_membership(
                        locked_lobby,
                        user,
                        active_memberships,
                    )

                _create_audit_event(
                    lobby=locked_lobby,
                    actor=user,
                    membership=membership,
                    event_type=LobbyAuditEventType.JOINED,
                    idempotency_key=key,
                    metadata={
                        "role": membership.role,
                        "seat_number": membership.seat_number,
                        "as_spectator": as_spectator,
                    },
                )
                return membership
        except IntegrityError as error:
            last_error = error

    raise LobbyJoinConflict(
        "Lobby membership changed while joining; retry."
    ) from last_error


def leave_lobby(
    *,
    lobby: GameLobby,
    user,
    idempotency_key: str | None = None,
) -> LobbyMembership:
    """Leave an active lobby membership and transfer host ownership if needed."""

    _require_authenticated_user(user)
    key = _normalize_idempotency_key(idempotency_key)

    with transaction.atomic():
        locked_lobby = _lock_lobby(lobby)
        idempotent_event = _idempotent_event(
            lobby=locked_lobby,
            actor=user,
            event_type=LobbyAuditEventType.LEFT,
            key=key,
        )
        if idempotent_event and idempotent_event.membership_id:
            return idempotent_event.membership

        membership = (
            LobbyMembership.objects.select_for_update()
            .active()
            .filter(lobby=locked_lobby, user=user)
            .order_by("joined_at", "id")
            .first()
        )
        if membership is None:
            raise LobbyMembershipNotFound("User has no active lobby membership.")

        now = timezone.now()
        was_host = (
            membership.role == MembershipRole.HOST
            or locked_lobby.host_id == user.pk
        )
        metadata = dict(membership.metadata or {})
        connection_status = MembershipConnectionStatus.OFFLINE
        if locked_lobby.status == LobbyStatus.ACTIVE:
            metadata["active_game_leave_policy"] = ACTIVE_GAME_LEAVE_POLICY
            connection_status = MembershipConnectionStatus.DISCONNECTED

        membership.left_at = now
        membership.is_ready = False
        membership.connection_status = connection_status
        membership.metadata = metadata
        membership.save(
            update_fields=[
                "left_at",
                "is_ready",
                "connection_status",
                "metadata",
                "updated_at",
            ]
        )

        _create_audit_event(
            lobby=locked_lobby,
            actor=user,
            membership=membership,
            event_type=LobbyAuditEventType.LEFT,
            idempotency_key=key,
            metadata={
                "role": membership.role,
                "seat_number": membership.seat_number,
                "active_game_leave_policy": metadata.get("active_game_leave_policy"),
            },
        )

        if was_host:
            _transfer_host_after_leave(locked_lobby, membership, actor=user, now=now)

        return membership


def set_membership_ready(
    *,
    lobby: GameLobby,
    user,
    is_ready: bool,
    member_public_id: str | None = None,
) -> LobbyMembership:
    """Update the caller's own ready state."""

    _require_authenticated_user(user)
    with transaction.atomic():
        locked_lobby = _lock_lobby(lobby)
        if locked_lobby.status != LobbyStatus.READY_CHECK:
            raise LobbyNotJoinable("Ready state can be changed only during ready check.")
        membership = _active_membership_for_user(locked_lobby, user)
        if member_public_id and str(membership.public_id) != str(member_public_id):
            raise LobbyAccessDenied("Users cannot change another member's ready state.")
        if not membership.can_be_ready:
            raise LobbyAccessDenied("This membership cannot be marked ready.")

        membership.is_ready = bool(is_ready)
        membership.save(update_fields=["is_ready", "updated_at"])
        return membership


def transfer_lobby_host(
    *,
    lobby: GameLobby,
    user,
    target_member_public_id: str,
) -> LobbyMembership:
    """Transfer lobby host ownership to an active human player."""

    _require_authenticated_user(user)
    if not target_member_public_id:
        raise LobbyValidationError("A target member is required.")

    with transaction.atomic():
        locked_lobby = _lock_lobby(lobby)
        actor_membership = _active_membership_for_user(locked_lobby, user)
        if (
            actor_membership.role != MembershipRole.HOST
            or locked_lobby.host_id != user.pk
        ):
            raise LobbyAccessDenied("Only the current host can transfer host.")

        target = _active_membership_by_public_id(
            locked_lobby,
            target_member_public_id,
        )
        if target.role not in (
            MembershipRole.HOST,
            MembershipRole.CO_HOST,
            MembershipRole.PLAYER,
        ) or not target.user_id:
            raise LobbyAccessDenied("Host can transfer only to an eligible human member.")

        if actor_membership.pk != target.pk:
            actor_membership.role = MembershipRole.PLAYER
            actor_membership.save(update_fields=["role", "updated_at"])

        locked_lobby.host = target.user
        locked_lobby.save(update_fields=["host", "updated_at"])
        target.lobby = locked_lobby
        target.role = MembershipRole.HOST
        target.save(update_fields=["role", "updated_at"])
        return target


def add_lobby_bot(
    *,
    lobby: GameLobby,
    user,
    bot_reference: str,
) -> LobbyMembership:
    """Add a bot membership through host-authorized lobby service rules."""

    _require_authenticated_user(user)
    reference = (bot_reference or "").strip()
    if not reference:
        raise LobbyValidationError("A bot reference is required.")

    with transaction.atomic():
        locked_lobby = _lock_lobby(lobby)
        _require_lobby_manager(locked_lobby, user)
        if not locked_lobby.allow_bot_fill or not locked_lobby.game.supports_bots:
            raise LobbyAccessDenied("Bots are not enabled for this lobby.")

        active_memberships = _locked_active_memberships(locked_lobby)
        seat_number = _next_open_seat(locked_lobby, active_memberships)
        return LobbyMembership.objects.create(
            lobby=locked_lobby,
            role=MembershipRole.BOT,
            bot_reference=reference,
            seat_number=seat_number,
            is_ready=True,
            connection_status=MembershipConnectionStatus.ONLINE,
        )


def remove_lobby_bot(
    *,
    lobby: GameLobby,
    user,
    target_member_public_id: str,
) -> LobbyMembership:
    """Remove an active bot membership without touching human members."""

    _require_authenticated_user(user)
    if not target_member_public_id:
        raise LobbyValidationError("A target bot member is required.")

    with transaction.atomic():
        locked_lobby = _lock_lobby(lobby)
        _require_lobby_manager(locked_lobby, user)
        membership = _active_membership_by_public_id(
            locked_lobby,
            target_member_public_id,
        )
        if membership.role != MembershipRole.BOT:
            raise LobbyAccessDenied("Bot removal cannot target a human member.")

        membership.left_at = timezone.now()
        membership.connection_status = MembershipConnectionStatus.OFFLINE
        membership.is_ready = False
        membership.save(
            update_fields=[
                "left_at",
                "connection_status",
                "is_ready",
                "updated_at",
            ]
        )
        return membership


def begin_ready_check(
    *,
    lobby: GameLobby,
    user,
    timeout_seconds: int | None = None,
    idempotency_key: str | None = None,
) -> GameLobby:
    """Move a waiting lobby into ready-check state and reset ready flags."""

    _require_authenticated_user(user)
    _require_unsuspended_user(user)
    key = _normalize_idempotency_key(idempotency_key)
    timeout = _ready_check_timeout_seconds(timeout_seconds)

    with transaction.atomic():
        locked_lobby = _lock_lobby(lobby)
        _require_lobby_manager(locked_lobby, user)
        idempotent_event = _idempotent_event(
            lobby=locked_lobby,
            actor=user,
            event_type=LobbyAuditEventType.READY_CHECK_STARTED,
            key=key,
        )
        if idempotent_event:
            return locked_lobby
        if locked_lobby.status != LobbyStatus.WAITING:
            raise LobbyNotJoinable("Ready check can start only from waiting lobbies.")

        now = timezone.now()
        locked_lobby.status = LobbyStatus.READY_CHECK
        locked_lobby.ready_check_started_at = now
        locked_lobby.ready_check_expires_at = now + timedelta(seconds=timeout)
        locked_lobby.save(
            update_fields=[
                "status",
                "ready_check_started_at",
                "ready_check_expires_at",
                "updated_at",
            ]
        )

        for membership in _locked_active_memberships(locked_lobby):
            if membership.role == MembershipRole.BOT:
                if not membership.is_ready:
                    membership.is_ready = True
                    membership.save(update_fields=["is_ready", "updated_at"])
            elif membership.role in PLAYER_SEAT_ROLES:
                if membership.is_ready:
                    membership.is_ready = False
                    membership.save(update_fields=["is_ready", "updated_at"])

        _create_audit_event(
            lobby=locked_lobby,
            actor=user,
            membership=_active_membership_for_user(locked_lobby, user),
            event_type=LobbyAuditEventType.READY_CHECK_STARTED,
            idempotency_key=key,
            metadata={"timeout_seconds": timeout},
        )
        return locked_lobby


def expire_ready_check(
    *,
    lobby: GameLobby,
    now=None,
    behavior: str | None = None,
) -> GameLobby:
    """Apply the configured ready-check timeout behavior when expired."""

    now = now or timezone.now()
    behavior = behavior or getattr(
        settings,
        "KSA_READY_CHECK_TIMEOUT_BEHAVIOR",
        "return_to_waiting",
    )

    with transaction.atomic():
        locked_lobby = _lock_lobby(lobby)
        if locked_lobby.status != LobbyStatus.READY_CHECK:
            return locked_lobby
        if (
            locked_lobby.ready_check_expires_at
            and locked_lobby.ready_check_expires_at > now
        ):
            return locked_lobby
        _apply_ready_check_timeout(
            locked_lobby,
            behavior=behavior,
            actor=None,
            now=now,
        )
        return locked_lobby


def start_game(
    *,
    lobby: GameLobby,
    user,
    idempotency_key: str | None = None,
    lock_context=None,
) -> GameStartResult:
    """Start exactly one authoritative game session for a ready lobby."""

    _require_authenticated_user(user)
    _require_unsuspended_user(user)
    lock_factory = lock_context or acquire_lobby_start_lock

    try:
        with lock_factory(str(lobby.public_id)):
            return _start_game_with_lock(
                lobby=lobby,
                user=user,
                idempotency_key=idempotency_key,
            )
    except LobbyStartLockUnavailable as error:
        raise LobbyStartConflict("Could not acquire lobby start lock.") from error
    except LobbyServiceError:
        raise
    except (GameEngineError, GameEngineRegistryError, ValueError, RuntimeError) as error:
        logger.exception("Could not start game for lobby %s", lobby.public_id)
        raise LobbyStartError("Could not start game for this lobby.") from error


def _start_game_with_lock(
    *,
    lobby: GameLobby,
    user,
    idempotency_key: str | None,
) -> GameStartResult:
    key = _normalize_idempotency_key(idempotency_key)
    with transaction.atomic():
        locked_lobby = _lock_lobby(lobby)
        actor_membership = _require_lobby_manager(locked_lobby, user)
        idempotent_result = _idempotent_game_start_result(
            lobby=locked_lobby,
            actor=user,
            key=key,
        )
        if idempotent_result is not None:
            return idempotent_result

        if GameSession.objects.select_for_update().filter(lobby=locked_lobby).exists():
            raise LobbyNotJoinable("This lobby already has an active game session.")

        _validate_ready_check_current(locked_lobby, actor=user)
        active_memberships = _locked_active_memberships(locked_lobby)
        player_memberships = _player_seat_memberships(active_memberships)
        _validate_startable_lobby(locked_lobby, player_memberships)

        engine = game_engine_registry.create(
            locked_lobby.game.engine_key,
            locked_lobby.game.engine_version,
        )
        engine.validate_config(locked_lobby.game_configuration)
        actors = _engine_actor_payloads(player_memberships)

        now = timezone.now()
        locked_lobby.status = LobbyStatus.STARTING
        locked_lobby.save(update_fields=["status", "updated_at"])

        initial_state = dict(
            engine.create_initial_state(locked_lobby.game_configuration, actors)
        )
        public_state = dict(engine.get_public_state(initial_state))
        spectator_state = dict(engine.get_spectator_state(initial_state))
        session = GameSession.objects.create(
            lobby=locked_lobby,
            game=locked_lobby.game,
            engine_key=locked_lobby.game.engine_key,
            engine_version=locked_lobby.game.engine_version,
            configuration=dict(locked_lobby.game_configuration),
            initial_state=initial_state,
            public_state=public_state,
            spectator_state=spectator_state,
            state_version=1,
            started_at=now,
        )
        private_states_by_user_id = _create_session_participants(
            session=session,
            engine=engine,
            state=initial_state,
            active_memberships=active_memberships,
        )

        locked_lobby.status = LobbyStatus.ACTIVE
        locked_lobby.started_at = now
        locked_lobby.save(update_fields=["status", "started_at", "updated_at"])
        _create_audit_event(
            lobby=locked_lobby,
            actor=user,
            membership=actor_membership,
            event_type=LobbyAuditEventType.GAME_STARTED,
            idempotency_key=key,
            metadata={
                "session_id": session.pk,
                "session_uuid": str(session.public_id),
                "engine_key": session.engine_key,
                "engine_version": session.engine_version,
            },
        )
        return GameStartResult(
            session=session,
            public_state=public_state,
            spectator_state=spectator_state,
            private_states_by_user_id=private_states_by_user_id,
            game_route=_game_route(session),
        )


def _idempotent_game_start_result(*, lobby, actor, key: str) -> GameStartResult | None:
    event = _idempotent_event(
        lobby=lobby,
        actor=actor,
        event_type=LobbyAuditEventType.GAME_STARTED,
        key=key,
    )
    if not event:
        return None
    session_id = (event.metadata or {}).get("session_id")
    if not session_id:
        return None
    session = GameSession.objects.select_for_update().get(pk=session_id)
    return _game_start_result_from_session(session)


def _game_start_result_from_session(session: GameSession) -> GameStartResult:
    private_states_by_user_id = {}
    for participant in session.participants.select_related("user").all():
        if participant.user_id and participant.role in PLAYER_SEAT_ROLES:
            private_states_by_user_id[str(participant.user_id)] = {
                "participant_uuid": str(participant.public_id),
                "actor_id": participant.actor_id,
                "private_state": participant.private_state,
            }
    return GameStartResult(
        session=session,
        public_state=dict(session.public_state),
        spectator_state=dict(session.spectator_state),
        private_states_by_user_id=private_states_by_user_id,
        game_route=_game_route(session),
    )


def _validate_ready_check_current(lobby: GameLobby, *, actor) -> None:
    if lobby.status != LobbyStatus.READY_CHECK:
        raise LobbyNotJoinable("Game start requires an active ready check.")
    if lobby.ready_check_expires_at and lobby.ready_check_expires_at <= timezone.now():
        _apply_ready_check_timeout(
            lobby,
            behavior=getattr(
                settings,
                "KSA_READY_CHECK_TIMEOUT_BEHAVIOR",
                "return_to_waiting",
            ),
            actor=actor,
            now=timezone.now(),
        )
        raise LobbyNotJoinable("Ready check has expired.")


def _validate_startable_lobby(
    lobby: GameLobby,
    player_memberships: list[LobbyMembership],
) -> None:
    if not lobby.game.is_playable:
        raise LobbyAccessDenied("Only playable games can be started.")
    if len(player_memberships) < lobby.minimum_players:
        raise LobbyAccessDenied("Minimum player count has not been met.")
    if len(player_memberships) > lobby.maximum_players:
        raise LobbyAccessDenied("Player capacity has been exceeded.")

    unready_humans = [
        membership
        for membership in player_memberships
        if not membership.is_bot and not membership.is_ready
    ]
    if unready_humans:
        raise LobbyAccessDenied("All human players must be ready before start.")


def _player_seat_memberships(
    active_memberships: list[LobbyMembership],
) -> list[LobbyMembership]:
    return [
        membership
        for membership in active_memberships
        if membership.role in PLAYER_SEAT_ROLES
    ]


def _engine_actor_payloads(
    player_memberships: list[LobbyMembership],
) -> list[dict]:
    return [
        {
            "actor_id": str(membership.public_id),
            "membership_uuid": str(membership.public_id),
            "role": membership.role,
            "seat_number": membership.seat_number,
            "is_bot": membership.is_bot,
            "bot_reference": membership.bot_reference if membership.is_bot else "",
            "profile_public_id": _profile_public_id(membership),
        }
        for membership in player_memberships
    ]


def _create_session_participants(
    *,
    session: GameSession,
    engine,
    state: dict,
    active_memberships: list[LobbyMembership],
) -> dict[str, dict]:
    private_states_by_user_id = {}
    player_memberships = _player_seat_memberships(active_memberships)
    player_membership_ids = {membership.pk for membership in player_memberships}
    for membership in active_memberships:
        actor_id = str(membership.public_id)
        private_state = {}
        if membership.pk in player_membership_ids:
            private_state = dict(engine.get_private_state(state, actor_id))

        participant = GameSessionParticipant.objects.create(
            session=session,
            lobby_membership=membership,
            user=membership.user if membership.user_id else None,
            actor_id=actor_id,
            role=membership.role,
            seat_number=membership.seat_number,
            is_bot=membership.is_bot,
            bot_reference=membership.bot_reference if membership.is_bot else "",
            private_state=private_state,
        )
        if membership.user_id and membership.pk in player_membership_ids:
            private_states_by_user_id[str(membership.user_id)] = {
                "participant_uuid": str(participant.public_id),
                "actor_id": actor_id,
                "private_state": private_state,
            }
    return private_states_by_user_id


def _ready_check_timeout_seconds(timeout_seconds: int | None) -> int:
    if timeout_seconds is None:
        timeout_seconds = getattr(settings, "KSA_READY_CHECK_TIMEOUT_SECONDS", 30)
    try:
        parsed = int(timeout_seconds)
    except (TypeError, ValueError) as error:
        raise LobbyValidationError("Ready-check timeout must be a positive integer.") from error
    if parsed <= 0:
        raise LobbyValidationError("Ready-check timeout must be a positive integer.")
    return parsed


def _apply_ready_check_timeout(
    lobby: GameLobby,
    *,
    behavior: str,
    actor,
    now,
) -> None:
    if behavior != "return_to_waiting":
        raise LobbyValidationError("Unsupported ready-check timeout behavior.")
    for membership in _locked_active_memberships(lobby):
        if membership.role in PLAYER_SEAT_ROLES and membership.is_ready:
            membership.is_ready = False
            membership.save(update_fields=["is_ready", "updated_at"])
    lobby.status = LobbyStatus.WAITING
    lobby.ready_check_started_at = None
    lobby.ready_check_expires_at = None
    lobby.save(
        update_fields=[
            "status",
            "ready_check_started_at",
            "ready_check_expires_at",
            "updated_at",
        ]
    )
    _create_audit_event(
        lobby=lobby,
        actor=actor,
        membership=None,
        event_type=LobbyAuditEventType.READY_CHECK_EXPIRED,
        metadata={"behavior": behavior, "expired_at": now.isoformat()},
    )


def _game_route(session: GameSession) -> str:
    return f"/games/{session.game.slug}/sessions/{session.public_id}/"


def _profile_public_id(membership: LobbyMembership) -> str | None:
    if membership.is_bot or not membership.user_id:
        return None
    profile = getattr(membership.user, "arena_profile", None)
    return str(profile.public_id) if profile else None


def _require_authenticated_user(user) -> None:
    if (
        not getattr(user, "is_authenticated", False)
        or getattr(user, "pk", None) is None
    ):
        raise LobbyAuthenticationError("A saved authenticated user is required.")


def _require_unsuspended_user(user) -> None:
    if not getattr(user, "is_active", True):
        raise LobbyAccessDenied("Suspended users cannot join lobbies.")


def _normalize_idempotency_key(value: str | None) -> str:
    return (value or "").strip()


def _lock_lobby(lobby: GameLobby) -> GameLobby:
    return (
        GameLobby.objects.select_for_update()
        .select_related("game", "host")
        .get(pk=lobby.pk)
    )


def _locked_active_memberships(lobby: GameLobby) -> list[LobbyMembership]:
    return list(
        LobbyMembership.objects.select_for_update()
        .active()
        .filter(lobby=lobby)
        .select_related("user")
        .order_by("joined_at", "id")
    )


def _active_membership_for_user(lobby: GameLobby, user) -> LobbyMembership:
    membership = (
        LobbyMembership.objects.select_for_update()
        .active()
        .filter(lobby=lobby, user=user)
        .select_related("user")
        .first()
    )
    if membership is None:
        raise LobbyMembershipNotFound("User has no active lobby membership.")
    return membership


def _active_membership_by_public_id(
    lobby: GameLobby,
    member_public_id: str,
) -> LobbyMembership:
    membership = (
        LobbyMembership.objects.select_for_update()
        .active()
        .filter(lobby=lobby, public_id=member_public_id)
        .select_related("user")
        .first()
    )
    if membership is None:
        raise LobbyMembershipNotFound("Active lobby membership was not found.")
    return membership


def _require_lobby_manager(lobby: GameLobby, user) -> LobbyMembership:
    membership = _active_membership_for_user(lobby, user)
    if membership.role not in (MembershipRole.HOST, MembershipRole.CO_HOST):
        raise LobbyAccessDenied("Only lobby hosts and co-hosts can do this.")
    return membership


def _idempotent_event(
    *,
    lobby: GameLobby,
    actor,
    event_type: str,
    key: str,
) -> LobbyAuditEvent | None:
    if not key:
        return None
    return (
        LobbyAuditEvent.objects.select_related("membership")
        .for_idempotency_key(
            lobby=lobby,
            actor=actor,
            event_type=event_type,
            key=key,
        )
        .first()
    )


def _validate_joinable_lobby(lobby: GameLobby) -> None:
    if lobby.status != LobbyStatus.WAITING:
        raise LobbyNotJoinable("Only waiting lobbies can be joined.")


def _validate_join_credentials(
    lobby: GameLobby,
    *,
    password: str | None,
    invite_token: str | None,
) -> None:
    if lobby.visibility == LobbyVisibility.PUBLIC:
        return

    if lobby.visibility == LobbyVisibility.PRIVATE:
        if not password or not lobby.check_password(password):
            raise LobbyCredentialsError("A valid lobby password is required.")
        return

    if lobby.visibility == LobbyVisibility.INVITE_ONLY:
        _validate_invite_token(lobby, invite_token)
        return

    raise LobbyAccessDenied("This lobby visibility is not joinable yet.")


def _validate_invite_token(lobby: GameLobby, invite_token: str | None) -> None:
    token = (invite_token or "").strip()
    if not token:
        raise LobbyCredentialsError("A valid invite token is required.")

    tokens = lobby.invite_token_metadata.get("tokens", {})
    token_data = tokens.get(token) if isinstance(tokens, dict) else None
    if not isinstance(token_data, dict):
        raise LobbyCredentialsError("A valid invite token is required.")

    expires_at_value = token_data.get("expires_at")
    if not expires_at_value:
        return

    expires_at = parse_datetime(str(expires_at_value))
    if expires_at is None:
        raise LobbyCredentialsError("Invite token expiry is invalid.")
    if timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
    if expires_at <= timezone.now():
        raise LobbyCredentialsError("Invite token has expired.")


def _validate_not_banned(lobby: GameLobby, user) -> None:
    if LobbyBan.objects.active().filter(lobby=lobby, user=user).exists():
        raise LobbyAccessDenied("Banned users cannot join this lobby.")


def _active_user_membership(
    active_memberships: list[LobbyMembership],
    user,
) -> LobbyMembership | None:
    for membership in active_memberships:
        if membership.user_id == user.pk:
            return membership
    return None


def _create_spectator_membership(
    lobby: GameLobby,
    user,
    active_memberships: list[LobbyMembership],
) -> LobbyMembership:
    if not lobby.allow_spectators:
        raise LobbyAccessDenied("Spectators are not enabled for this lobby.")

    active_spectators = [
        membership
        for membership in active_memberships
        if membership.role == MembershipRole.SPECTATOR
    ]
    if len(active_spectators) >= lobby.spectator_limit:
        raise LobbyFull("Spectator capacity has been reached.")

    return LobbyMembership.objects.create(
        lobby=lobby,
        user=user,
        role=MembershipRole.SPECTATOR,
        connection_status=MembershipConnectionStatus.ONLINE,
    )


def _create_player_membership(
    lobby: GameLobby,
    user,
    active_memberships: list[LobbyMembership],
) -> LobbyMembership:
    seat_number = _next_open_seat(lobby, active_memberships)
    role = MembershipRole.PLAYER
    active_host_exists = any(
        membership.role == MembershipRole.HOST for membership in active_memberships
    )
    if user.pk == lobby.host_id and not active_host_exists:
        role = MembershipRole.HOST

    return LobbyMembership.objects.create(
        lobby=lobby,
        user=user,
        role=role,
        seat_number=seat_number,
        connection_status=MembershipConnectionStatus.ONLINE,
    )


def _next_open_seat(
    lobby: GameLobby,
    active_memberships: list[LobbyMembership],
) -> int:
    active_seated_members = [
        membership
        for membership in active_memberships
        if membership.role in PLAYER_SEAT_ROLES
    ]
    if len(active_seated_members) >= lobby.maximum_players:
        raise LobbyFull("Player capacity has been reached.")

    taken_seats = {
        membership.seat_number
        for membership in active_seated_members
        if membership.seat_number is not None
    }
    for seat_number in range(1, lobby.maximum_players + 1):
        if seat_number not in taken_seats:
            return seat_number

    raise LobbyFull("Player capacity has been reached.")


def _create_audit_event(
    *,
    lobby: GameLobby,
    actor,
    membership: LobbyMembership | None,
    event_type: str,
    idempotency_key: str = "",
    metadata: dict | None = None,
) -> LobbyAuditEvent:
    return LobbyAuditEvent.objects.create(
        lobby=lobby,
        actor=actor,
        membership=membership,
        event_type=event_type,
        idempotency_key=idempotency_key,
        metadata=metadata or {},
    )


def _transfer_host_after_leave(
    lobby: GameLobby,
    leaving_membership: LobbyMembership,
    *,
    actor,
    now,
) -> None:
    active_memberships = _locked_active_memberships(lobby)
    successor = _host_successor(active_memberships)
    previous_host_id = lobby.host_id

    if successor is None:
        lobby.status = LobbyStatus.CANCELLED
        lobby.ended_at = lobby.ended_at or now
        lobby.save(update_fields=["status", "ended_at", "updated_at"])
        _create_audit_event(
            lobby=lobby,
            actor=actor,
            membership=leaving_membership,
            event_type=LobbyAuditEventType.LOBBY_CANCELLED,
            metadata={
                "previous_host_id": previous_host_id,
                "reason": "host_left_without_successor",
            },
        )
        return

    if successor.seat_number is None:
        successor.seat_number = _next_successor_seat(
            lobby,
            active_memberships,
            preferred_seat=leaving_membership.seat_number,
        )

    lobby.host = successor.user
    lobby.save(update_fields=["host", "updated_at"])

    successor.lobby = lobby
    successor.role = MembershipRole.HOST
    successor.save(update_fields=["role", "seat_number", "updated_at"])

    _create_audit_event(
        lobby=lobby,
        actor=actor,
        membership=successor,
        event_type=LobbyAuditEventType.HOST_TRANSFERRED,
        metadata={
            "previous_host_id": previous_host_id,
            "new_host_id": successor.user_id,
        },
    )


def _host_successor(
    active_memberships: list[LobbyMembership],
) -> LobbyMembership | None:
    human_memberships = [
        membership
        for membership in active_memberships
        if membership.user_id and membership.role != MembershipRole.BOT
    ]
    for role in HOST_SUCCESSOR_ROLES:
        for membership in human_memberships:
            if membership.role == role:
                return membership
    return None


def _next_successor_seat(
    lobby: GameLobby,
    active_memberships: list[LobbyMembership],
    *,
    preferred_seat: int | None,
) -> int:
    taken_seats = {
        membership.seat_number
        for membership in active_memberships
        if membership.role in PLAYER_SEAT_ROLES and membership.seat_number is not None
    }
    if preferred_seat and preferred_seat not in taken_seats:
        return preferred_seat
    for seat_number in range(1, lobby.maximum_players + 1):
        if seat_number not in taken_seats:
            return seat_number
    raise LobbyFull("No seat is available for host transfer.")


__all__ = [
    "GameStartResult",
    "LobbyAccessDenied",
    "LobbyAlreadyMember",
    "LobbyAuthenticationError",
    "LobbyCredentialsError",
    "LobbyFull",
    "LobbyJoinConflict",
    "LobbyMembershipNotFound",
    "LobbyNotJoinable",
    "LobbyServiceError",
    "LobbyStartConflict",
    "LobbyStartError",
    "LobbyValidationError",
    "add_lobby_bot",
    "begin_ready_check",
    "expire_ready_check",
    "join_lobby",
    "leave_lobby",
    "remove_lobby_bot",
    "set_membership_ready",
    "start_game",
    "transfer_lobby_host",
]
