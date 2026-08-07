from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from games.engine import BaseGameEngine, GameTransition, InvalidGameConfiguration
from games.models import GameCategory, GameDefinition
from games.registry import GameEngineRegistry
from lobbies.models import (
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
from lobbies.services import (
    LobbyAccessDenied,
    LobbyAlreadyMember,
    LobbyAuthenticationError,
    LobbyCredentialsError,
    LobbyFull,
    LobbyMembershipNotFound,
    LobbyNotJoinable,
    join_lobby,
    leave_lobby,
)


pytestmark = pytest.mark.django_db


class ServiceTestEngine(BaseGameEngine):
    def validate_config(self, config):
        rounds = config.get("rounds", 1)
        if not isinstance(rounds, int) or rounds < 1:
            raise InvalidGameConfiguration("rounds must be a positive integer.")

    def create_initial_state(self, config, actors):
        return {"rounds": config.get("rounds", 1), "complete": False}

    def get_public_state(self, state):
        return {"complete": state["complete"]}

    def get_spectator_state(self, state):
        return {"complete": state["complete"]}

    def get_private_state(self, state, actor_id):
        return {"actor_id": actor_id}

    def legal_actions(self, state, actor_id):
        return [{"type": "noop"}]

    def apply_action(
        self,
        state,
        actor_id,
        action,
        *,
        idempotency_key=None,
        state_version=None,
    ):
        return GameTransition(state=dict(state), events=[])

    def handle_timeout(self, state, actor_id=None):
        return GameTransition(state=dict(state), events=[])

    def bot_action(self, state, actor_id, *, difficulty=None):
        return {"type": "noop"}

    def is_complete(self, state):
        return bool(state["complete"])

    def build_results(self, state):
        return {"complete": self.is_complete(state)}


def install_test_registry(monkeypatch):
    registry = GameEngineRegistry()
    registry.register("service-test-engine", "1.0", ServiceTestEngine)
    monkeypatch.setattr("games.models.game_engine_registry", registry)
    monkeypatch.setattr("lobbies.models.game_engine_registry", registry)
    return registry


def category(slug="board-games"):
    return GameCategory.objects.get(slug=slug)


def create_user(username):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongPass123!",
    )


def create_playable_game(monkeypatch, **overrides):
    install_test_registry(monkeypatch)
    values = {
        "category": category(),
        "name": "Service Test Game",
        "slug": "service-test-game",
        "short_description": "A playable service test game.",
        "engine_key": "service-test-engine",
        "engine_version": "1.0",
        "minimum_players": 1,
        "maximum_players": 4,
        "estimated_duration_minutes": 15,
        "supports_bots": True,
        "supports_spectators": True,
        "supports_ranked": True,
        "supports_private_lobbies": True,
        "difficulty_options": ["easy", "standard"],
        "default_configuration": {"rounds": 2},
        "is_playable": True,
        "is_active": True,
    }
    values.update(overrides)
    return GameDefinition.objects.create(**values)


def create_lobby(monkeypatch, *, host=None, **overrides):
    game = create_playable_game(monkeypatch)
    host = host or create_user("host")
    values = {"game_configuration": {"rounds": 2}}
    values.update(overrides)
    return GameLobby.objects.create_for_host(host=host, game=game, **values)


def invite_metadata(token, expires_at):
    return {"tokens": {token: {"expires_at": expires_at.isoformat()}}}


def test_public_waiting_lobby_join_creates_player_membership_and_audit(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")

    membership = join_lobby(
        lobby=lobby,
        user=player,
        idempotency_key="join-public-player",
    )

    assert membership.user == player
    assert membership.role == MembershipRole.PLAYER
    assert membership.seat_number == 1
    assert membership.connection_status == MembershipConnectionStatus.ONLINE
    assert membership.is_active is True
    audit = LobbyAuditEvent.objects.get(event_type=LobbyAuditEventType.JOINED)
    assert audit.membership == membership
    assert audit.actor == player
    assert audit.idempotency_key == "join-public-player"


def test_host_joins_as_active_host(monkeypatch):
    host = create_user("host")
    lobby = create_lobby(monkeypatch, host=host)

    membership = join_lobby(lobby=lobby, user=host)

    assert membership.role == MembershipRole.HOST
    assert membership.seat_number == 1


def test_join_rejects_unauthenticated_or_suspended_users(monkeypatch):
    lobby = create_lobby(monkeypatch)

    with pytest.raises(LobbyAuthenticationError):
        join_lobby(lobby=lobby, user=AnonymousUser())

    suspended = create_user("suspended")
    suspended.is_active = False
    suspended.save(update_fields=["is_active"])

    with pytest.raises(LobbyAccessDenied):
        join_lobby(lobby=lobby, user=suspended)


def test_join_rejects_non_waiting_lobbies(monkeypatch):
    lobby = create_lobby(monkeypatch, status=LobbyStatus.STARTING)

    with pytest.raises(LobbyNotJoinable):
        join_lobby(lobby=lobby, user=create_user("player"))


def test_spectator_join_requires_spectator_support_and_capacity(monkeypatch):
    lobby = create_lobby(
        monkeypatch,
        allow_spectators=True,
        spectator_limit=1,
    )
    spectator = join_lobby(
        lobby=lobby,
        user=create_user("spectator"),
        as_spectator=True,
    )

    assert spectator.role == MembershipRole.SPECTATOR
    assert spectator.seat_number is None
    assert spectator.consumes_player_seat is False

    with pytest.raises(LobbyFull):
        join_lobby(
            lobby=lobby,
            user=create_user("extra-spectator"),
            as_spectator=True,
        )


def test_spectator_join_rejects_lobby_without_spectators(monkeypatch):
    lobby = create_lobby(monkeypatch, allow_spectators=False)

    with pytest.raises(LobbyAccessDenied):
        join_lobby(
            lobby=lobby,
            user=create_user("spectator"),
            as_spectator=True,
        )


def test_private_lobby_requires_correct_password(monkeypatch):
    lobby = create_lobby(monkeypatch, visibility=LobbyVisibility.PRIVATE)
    lobby.set_password("correct horse battery staple")
    lobby.save()

    with pytest.raises(LobbyCredentialsError):
        join_lobby(lobby=lobby, user=create_user("wrong-password"), password="wrong")

    membership = join_lobby(
        lobby=lobby,
        user=create_user("right-password"),
        password="correct horse battery staple",
    )

    assert membership.role == MembershipRole.PLAYER


def test_invite_only_lobby_requires_valid_unexpired_token(monkeypatch):
    valid_token = "invite-123"
    lobby = create_lobby(
        monkeypatch,
        visibility=LobbyVisibility.INVITE_ONLY,
        invite_token_metadata=invite_metadata(
            valid_token,
            timezone.now() + timedelta(hours=1),
        ),
    )

    with pytest.raises(LobbyCredentialsError):
        join_lobby(lobby=lobby, user=create_user("missing-token"))

    membership = join_lobby(
        lobby=lobby,
        user=create_user("invited-player"),
        invite_token=valid_token,
    )

    assert membership.role == MembershipRole.PLAYER


def test_expired_invite_token_is_rejected(monkeypatch):
    expired_token = "expired-123"
    lobby = create_lobby(
        monkeypatch,
        visibility=LobbyVisibility.INVITE_ONLY,
        invite_token_metadata=invite_metadata(
            expired_token,
            timezone.now() - timedelta(minutes=1),
        ),
    )

    with pytest.raises(LobbyCredentialsError):
        join_lobby(
            lobby=lobby,
            user=create_user("late-player"),
            invite_token=expired_token,
        )


def test_banned_user_cannot_join(monkeypatch):
    lobby = create_lobby(monkeypatch)
    banned = create_user("banned")
    LobbyBan.objects.create(lobby=lobby, user=banned, reason="abuse")

    with pytest.raises(LobbyAccessDenied):
        join_lobby(lobby=lobby, user=banned)


def test_duplicate_join_without_same_idempotency_key_is_rejected(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    join_lobby(lobby=lobby, user=player)

    with pytest.raises(LobbyAlreadyMember):
        join_lobby(lobby=lobby, user=player)


def test_join_is_idempotent_for_same_key(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")

    first = join_lobby(lobby=lobby, user=player, idempotency_key="same-join")
    second = join_lobby(lobby=lobby, user=player, idempotency_key="same-join")

    assert second.pk == first.pk
    assert LobbyMembership.objects.active().filter(lobby=lobby, user=player).count() == 1
    assert LobbyAuditEvent.objects.filter(
        event_type=LobbyAuditEventType.JOINED,
        idempotency_key="same-join",
    ).count() == 1


def test_player_capacity_and_concurrent_overflow_are_blocked(monkeypatch):
    lobby = create_lobby(monkeypatch, minimum_players=1, maximum_players=1)
    join_lobby(lobby=lobby, user=create_user("first-player"))

    with pytest.raises(LobbyFull):
        join_lobby(lobby=lobby, user=create_user("second-player"))

    assert LobbyMembership.objects.active().player_seats().filter(lobby=lobby).count() == 1


def test_leave_marks_membership_inactive_releases_seat_and_audits(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    membership = join_lobby(lobby=lobby, user=player)
    membership.is_ready = True
    membership.save(update_fields=["is_ready", "updated_at"])

    left = leave_lobby(lobby=lobby, user=player, idempotency_key="same-leave")
    left.refresh_from_db()

    assert left.left_at is not None
    assert left.is_ready is False
    assert left.connection_status == MembershipConnectionStatus.OFFLINE
    assert left.is_active is False
    audit = LobbyAuditEvent.objects.get(event_type=LobbyAuditEventType.LEFT)
    assert audit.membership == left
    assert audit.idempotency_key == "same-leave"

    replacement = join_lobby(lobby=lobby, user=create_user("replacement"))
    assert replacement.seat_number == membership.seat_number


def test_leave_is_idempotent_for_same_key(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    membership = join_lobby(lobby=lobby, user=player)

    first = leave_lobby(lobby=lobby, user=player, idempotency_key="repeat-leave")
    second = leave_lobby(lobby=lobby, user=player, idempotency_key="repeat-leave")

    assert first.pk == membership.pk
    assert second.pk == membership.pk
    assert LobbyAuditEvent.objects.filter(
        event_type=LobbyAuditEventType.LEFT,
        idempotency_key="repeat-leave",
    ).count() == 1


def test_leave_requires_active_membership(monkeypatch):
    lobby = create_lobby(monkeypatch)

    with pytest.raises(LobbyMembershipNotFound):
        leave_lobby(lobby=lobby, user=create_user("missing"))


def test_host_leave_transfers_to_active_cohost_before_player(monkeypatch):
    host = create_user("host")
    lobby = create_lobby(monkeypatch, host=host)
    host_membership = join_lobby(lobby=lobby, user=host)
    cohost = LobbyMembership.objects.create(
        lobby=lobby,
        user=create_user("cohost"),
        role=MembershipRole.CO_HOST,
        seat_number=2,
        connection_status=MembershipConnectionStatus.ONLINE,
    )
    player = join_lobby(lobby=lobby, user=create_user("player"))

    leave_lobby(lobby=lobby, user=host)
    lobby.refresh_from_db()
    host_membership.refresh_from_db()
    cohost.refresh_from_db()
    player.refresh_from_db()

    assert lobby.host == cohost.user
    assert host_membership.is_active is False
    assert cohost.role == MembershipRole.HOST
    assert player.role == MembershipRole.PLAYER
    assert LobbyAuditEvent.objects.filter(
        event_type=LobbyAuditEventType.HOST_TRANSFERRED,
        membership=cohost,
    ).exists()


def test_host_leave_transfers_to_earliest_active_player_without_cohost(monkeypatch):
    host = create_user("host")
    lobby = create_lobby(monkeypatch, host=host)
    join_lobby(lobby=lobby, user=host)
    first_player = join_lobby(lobby=lobby, user=create_user("first-player"))
    second_player = join_lobby(lobby=lobby, user=create_user("second-player"))

    leave_lobby(lobby=lobby, user=host)
    lobby.refresh_from_db()
    first_player.refresh_from_db()
    second_player.refresh_from_db()

    assert lobby.host == first_player.user
    assert first_player.role == MembershipRole.HOST
    assert second_player.role == MembershipRole.PLAYER


def test_host_leave_cancels_lobby_when_no_eligible_successor_exists(monkeypatch):
    host = create_user("host")
    lobby = create_lobby(monkeypatch, host=host)
    join_lobby(lobby=lobby, user=host)

    leave_lobby(lobby=lobby, user=host)
    lobby.refresh_from_db()

    assert lobby.status == LobbyStatus.CANCELLED
    assert lobby.ended_at is not None
    assert LobbyAuditEvent.objects.filter(
        event_type=LobbyAuditEventType.LOBBY_CANCELLED,
    ).exists()


def test_active_lobby_leave_records_disconnect_forfeit_policy(monkeypatch):
    lobby = create_lobby(monkeypatch)
    player = create_user("player")
    membership = join_lobby(lobby=lobby, user=player)
    lobby.status = LobbyStatus.ACTIVE
    lobby.started_at = timezone.now()
    lobby.save(update_fields=["status", "started_at", "updated_at"])

    leave_lobby(lobby=lobby, user=player)
    membership.refresh_from_db()

    assert membership.left_at is not None
    assert membership.connection_status == MembershipConnectionStatus.DISCONNECTED
    assert membership.metadata["active_game_leave_policy"] == "disconnect_forfeit"
