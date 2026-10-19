from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.utils import timezone

from games.engine import InvalidGameConfiguration
from games.models import GameDefinition
from games.registry import GameEngineRegistryError, game_engine_registry


LOBBY_CODE_MAX_LENGTH = 12
LOBBY_CODE_DEFAULT_LENGTH = 8
LOBBY_NAME_MAX_LENGTH = 120
PASSWORD_HASH_MAX_LENGTH = 128
BOT_DIFFICULTY_MAX_LENGTH = 32
BOT_REFERENCE_MAX_LENGTH = 80
MEMBERSHIP_ROLE_MAX_LENGTH = 20
CONNECTION_STATUS_MAX_LENGTH = 20
LOBBY_CODE_PATTERN = re.compile(r"^[A-Z0-9]{6,12}$")


def generate_lobby_code() -> str:
    return uuid.uuid4().hex[:LOBBY_CODE_DEFAULT_LENGTH].upper()


def normalize_lobby_name(value: str) -> str:
    return " ".join((value or "").strip().split())


def normalize_lobby_code(value: str) -> str:
    return (value or "").strip().upper()


class LobbyVisibility(models.TextChoices):
    PUBLIC = "public", "Public"
    PRIVATE = "private", "Private"
    FRIENDS_ONLY = "friends_only", "Friends Only"
    INVITE_ONLY = "invite_only", "Invite Only"


class LobbyStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    READY_CHECK = "ready_check", "Ready Check"
    STARTING = "starting", "Starting"
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    ABANDONED = "abandoned", "Abandoned"


class MembershipRole(models.TextChoices):
    HOST = "host", "Host"
    CO_HOST = "co_host", "Co-Host"
    PLAYER = "player", "Player"
    SPECTATOR = "spectator", "Spectator"
    MODERATOR = "moderator", "Moderator"
    BOT = "bot", "Bot"


class MembershipConnectionStatus(models.TextChoices):
    OFFLINE = "offline", "Offline"
    ONLINE = "online", "Online"
    DISCONNECTED = "disconnected", "Disconnected"


class LobbyAuditEventType(models.TextChoices):
    JOINED = "joined", "Joined"
    LEFT = "left", "Left"
    HOST_TRANSFERRED = "host_transferred", "Host Transferred"
    LOBBY_CANCELLED = "lobby_cancelled", "Lobby Cancelled"
    READY_CHECK_STARTED = "ready_check_started", "Ready Check Started"
    READY_CHECK_EXPIRED = "ready_check_expired", "Ready Check Expired"
    GAME_STARTED = "game_started", "Game Started"


PLAYER_SEAT_ROLES = (
    MembershipRole.HOST,
    MembershipRole.CO_HOST,
    MembershipRole.PLAYER,
    MembershipRole.BOT,
)
READY_ELIGIBLE_ROLES = PLAYER_SEAT_ROLES


class GameLobbyQuerySet(models.QuerySet):
    def active(self):
        return self.exclude(
            status__in=(
                LobbyStatus.COMPLETED,
                LobbyStatus.CANCELLED,
                LobbyStatus.ABANDONED,
            )
        )

    def waiting(self):
        return self.filter(status=LobbyStatus.WAITING)

    def public(self):
        return self.filter(visibility=LobbyVisibility.PUBLIC)


class GameLobbyManager(models.Manager.from_queryset(GameLobbyQuerySet)):
    def create_for_host(self, *, host, game: GameDefinition, **kwargs):
        if not getattr(host, "is_authenticated", False):
            raise PermissionDenied("Only authenticated users can create lobbies.")
        if getattr(host, "pk", None) is None:
            raise ValidationError({"host": "Lobby host must be a saved user."})

        kwargs.setdefault("name", f"{game.name} Lobby")
        kwargs.setdefault("minimum_players", game.minimum_players)
        kwargs.setdefault("maximum_players", game.maximum_players)
        kwargs.setdefault("game_configuration", dict(game.default_configuration or {}))
        return self.create(host=host, game=game, **kwargs)


class GameLobby(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    creation_request_id = models.UUIDField(
        null=True, blank=True, unique=True, editable=False
    )
    lobby_code = models.CharField(
        max_length=LOBBY_CODE_MAX_LENGTH,
        unique=True,
        default=generate_lobby_code,
    )
    name = models.CharField(max_length=LOBBY_NAME_MAX_LENGTH)
    game = models.ForeignKey(
        GameDefinition,
        on_delete=models.PROTECT,
        related_name="lobbies",
    )
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="hosted_lobbies",
    )
    visibility = models.CharField(
        max_length=20,
        choices=LobbyVisibility.choices,
        default=LobbyVisibility.PUBLIC,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=LobbyStatus.choices,
        default=LobbyStatus.WAITING,
        db_index=True,
    )
    minimum_players = models.PositiveSmallIntegerField()
    maximum_players = models.PositiveSmallIntegerField()
    is_ranked = models.BooleanField(default=False)
    allow_bot_fill = models.BooleanField(default=False)
    bot_difficulty = models.CharField(
        max_length=BOT_DIFFICULTY_MAX_LENGTH,
        blank=True,
    )
    allow_spectators = models.BooleanField(default=False)
    spectator_limit = models.PositiveIntegerField(default=0)
    game_configuration = models.JSONField(default=dict, blank=True)
    password_hash = models.CharField(max_length=PASSWORD_HASH_MAX_LENGTH, blank=True)
    invite_token_metadata = models.JSONField(default=dict, blank=True)
    ready_check_started_at = models.DateTimeField(null=True, blank=True)
    ready_check_expires_at = models.DateTimeField(null=True, blank=True)
    scheduled_start_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = GameLobbyManager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("game", "status"), name="game_lobby_game_status_idx"),
            models.Index(fields=("host", "status"), name="game_lobby_host_status_idx"),
            models.Index(fields=("visibility", "status"), name="game_lobby_visibility_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minimum_players__gte=1),
                name="game_lobby_min_players_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(maximum_players__gte=models.F("minimum_players")),
                name="game_lobby_max_players_gte_min",
            ),
            models.CheckConstraint(
                condition=models.Q(spectator_limit__gte=0),
                name="game_lobby_spectator_limit_gte_0",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.lobby_code})"

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    def set_password(self, raw_password: str | None) -> None:
        self.password_hash = make_password(raw_password) if raw_password else ""

    def check_password(self, raw_password: str) -> bool:
        return bool(self.password_hash) and check_password(raw_password, self.password_hash)

    def clean(self) -> None:
        self.name = normalize_lobby_name(self.name)
        self.lobby_code = normalize_lobby_code(self.lobby_code)
        self.bot_difficulty = (self.bot_difficulty or "").strip()

        errors = {}
        if not self.name:
            errors["name"] = "Lobby name is required."
        if not LOBBY_CODE_PATTERN.fullmatch(self.lobby_code):
            errors["lobby_code"] = (
                "Lobby code must be 6-12 uppercase letters or numbers."
            )
        if not self.host_id:
            errors["host"] = "Lobby host is required."

        game = self._selected_game()
        if game is None:
            errors["game"] = "Selected game is required."
        else:
            self._validate_game(errors, game)

        self._validate_json_object(errors, "game_configuration")
        self._validate_json_object(errors, "invite_token_metadata")
        self._validate_password_hash(errors)
        self._validate_time_order(errors)

        if game is not None and "game_configuration" not in errors:
            self._validate_game_configuration(errors, game)

        if errors:
            raise ValidationError(errors)

        super().clean()

    def full_clean(self, *args, **kwargs) -> None:
        self.name = normalize_lobby_name(self.name)
        self.lobby_code = normalize_lobby_code(self.lobby_code)
        super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def _selected_game(self) -> GameDefinition | None:
        if not self.game_id:
            return None
        return self.game

    def _validate_game(self, errors: dict[str, str], game: GameDefinition) -> None:
        if not game.is_active:
            errors["game"] = "Lobby game must be active."
        elif not game.is_playable:
            errors["game"] = "Lobby game must be playable."

        if self.minimum_players is not None and self.minimum_players < 1:
            errors["minimum_players"] = "Minimum players must be at least one."
        if (
            self.minimum_players is not None
            and self.maximum_players is not None
            and self.maximum_players < self.minimum_players
        ):
            errors["maximum_players"] = (
                "Maximum players must be greater than or equal to minimum players."
            )
        if (
            self.minimum_players is not None
            and self.minimum_players < game.minimum_players
        ):
            errors["minimum_players"] = (
                "Lobby minimum players cannot be below the selected game's minimum."
            )
        if (
            self.maximum_players is not None
            and self.maximum_players > game.maximum_players
        ):
            errors["maximum_players"] = (
                "Lobby maximum players cannot exceed the selected game's maximum."
            )

        if self.is_ranked and not game.supports_ranked:
            errors["is_ranked"] = "Selected game does not support ranked lobbies."
        if self.allow_spectators and not game.supports_spectators:
            errors["allow_spectators"] = (
                "Selected game does not support spectators."
            )
        if self.spectator_limit and not self.allow_spectators:
            errors["spectator_limit"] = (
                "Spectator limit requires spectators to be enabled."
            )
        if self.allow_bot_fill and not game.supports_bots:
            errors["allow_bot_fill"] = "Selected game does not support bots."
        if self.bot_difficulty and not self.allow_bot_fill:
            errors["bot_difficulty"] = "Bot difficulty requires bot fill."
        if (
            self.bot_difficulty
            and game.difficulty_options
            and self.bot_difficulty not in game.difficulty_options
        ):
            errors["bot_difficulty"] = "Bot difficulty is not supported by this game."

    def _validate_json_object(self, errors: dict[str, str], field_name: str) -> None:
        if not isinstance(getattr(self, field_name), dict):
            errors[field_name] = "Must be a JSON object."

    def _validate_password_hash(self, errors: dict[str, str]) -> None:
        if not self.password_hash:
            return
        try:
            identify_hasher(self.password_hash)
        except ValueError:
            errors["password_hash"] = "Lobby passwords must be stored as hashes."

    def _validate_time_order(self, errors: dict[str, str]) -> None:
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            errors["ended_at"] = "Lobby end time cannot be before start time."
        if (
            self.ready_check_started_at
            and self.ready_check_expires_at
            and self.ready_check_expires_at < self.ready_check_started_at
        ):
            errors["ready_check_expires_at"] = (
                "Ready-check expiry cannot be before ready-check start."
            )

    def _validate_game_configuration(
        self,
        errors: dict[str, str],
        game: GameDefinition,
    ) -> None:
        if not game.is_playable:
            return
        try:
            engine = game_engine_registry.create(game.engine_key, game.engine_version)
            engine.validate_config(self.game_configuration)
        except InvalidGameConfiguration as error:
            errors["game_configuration"] = error.message
        except GameEngineRegistryError:
            errors["game"] = "Lobby game must have a registered engine."


class LobbyMembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(left_at__isnull=True, kicked_at__isnull=True)

    def inactive(self):
        return self.exclude(left_at__isnull=True, kicked_at__isnull=True)

    def player_seats(self):
        return self.filter(role__in=PLAYER_SEAT_ROLES)

    def spectators(self):
        return self.filter(role=MembershipRole.SPECTATOR)

    def bots(self):
        return self.filter(role=MembershipRole.BOT)


class LobbyMembership(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    lobby = models.ForeignKey(
        GameLobby,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="lobby_memberships",
        null=True,
        blank=True,
    )
    bot_reference = models.CharField(
        max_length=BOT_REFERENCE_MAX_LENGTH,
        blank=True,
    )
    role = models.CharField(
        max_length=MEMBERSHIP_ROLE_MAX_LENGTH,
        choices=MembershipRole.choices,
    )
    seat_number = models.PositiveSmallIntegerField(null=True, blank=True)
    is_ready = models.BooleanField(default=False)
    connection_status = models.CharField(
        max_length=CONNECTION_STATUS_MAX_LENGTH,
        choices=MembershipConnectionStatus.choices,
        default=MembershipConnectionStatus.OFFLINE,
    )
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)
    kicked_at = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LobbyMembershipQuerySet.as_manager()

    class Meta:
        ordering = ("joined_at", "seat_number", "id")
        indexes = [
            models.Index(
                fields=("lobby", "role"),
                name="lobby_member_role_idx",
            ),
            models.Index(
                fields=("lobby", "seat_number"),
                name="lobby_member_seat_idx",
            ),
            models.Index(
                fields=("user", "lobby"),
                name="lobby_member_user_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("lobby", "user"),
                condition=models.Q(
                    left_at__isnull=True,
                    kicked_at__isnull=True,
                    user__isnull=False,
                ),
                name="unique_active_lobby_user",
            ),
            models.UniqueConstraint(
                fields=("lobby", "seat_number"),
                condition=models.Q(
                    left_at__isnull=True,
                    kicked_at__isnull=True,
                    seat_number__isnull=False,
                ),
                name="unique_active_lobby_seat",
            ),
            models.UniqueConstraint(
                fields=("lobby",),
                condition=models.Q(
                    role=MembershipRole.HOST,
                    left_at__isnull=True,
                    kicked_at__isnull=True,
                ),
                name="unique_active_lobby_host",
            ),
            models.UniqueConstraint(
                fields=("lobby", "bot_reference"),
                condition=(
                    models.Q(
                        role=MembershipRole.BOT,
                        left_at__isnull=True,
                        kicked_at__isnull=True,
                    )
                    & ~models.Q(bot_reference="")
                ),
                name="unique_active_lobby_bot",
            ),
        ]

    def __str__(self) -> str:
        actor = self.bot_reference if self.is_bot else self.user
        return f"{self.lobby} - {actor} ({self.role})"

    @property
    def is_active(self) -> bool:
        return self.left_at is None and self.kicked_at is None

    @property
    def is_bot(self) -> bool:
        return self.role == MembershipRole.BOT

    @property
    def is_human(self) -> bool:
        return not self.is_bot

    @property
    def consumes_player_seat(self) -> bool:
        return self.role in PLAYER_SEAT_ROLES

    @property
    def can_be_ready(self) -> bool:
        return self.role in READY_ELIGIBLE_ROLES

    def clean(self) -> None:
        self.bot_reference = (self.bot_reference or "").strip()

        errors = {}
        self._validate_actor(errors)
        self._validate_seat(errors)
        self._validate_ready_status(errors)
        self._validate_json_object(errors, "result")
        self._validate_json_object(errors, "metadata")
        self._validate_time_order(errors)

        if errors:
            raise ValidationError(errors)

        super().clean()

    def full_clean(self, *args, **kwargs) -> None:
        self.bot_reference = (self.bot_reference or "").strip()
        super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def _validate_actor(self, errors: dict[str, str]) -> None:
        if self.role == MembershipRole.BOT:
            if self.user_id:
                errors["user"] = "Bot memberships cannot reference a human user."
            if not self.bot_reference:
                errors["bot_reference"] = "Bot memberships require a bot reference."
            return

        if not self.user_id:
            errors["user"] = "Human memberships require a user."
        if self.bot_reference:
            errors["bot_reference"] = (
                "Human memberships cannot include a bot reference."
            )
        if (
            self.role == MembershipRole.HOST
            and self.lobby_id
            and self.user_id
            and self.user_id != self.lobby.host_id
        ):
            errors["user"] = "Host membership must belong to the lobby host."

    def _validate_seat(self, errors: dict[str, str]) -> None:
        if self.role in PLAYER_SEAT_ROLES:
            if self.seat_number is None:
                errors["seat_number"] = "Player roles require a seat number."
            elif self.lobby_id and self.seat_number > self.lobby.maximum_players:
                errors["seat_number"] = "Seat number exceeds lobby capacity."
            return

        if self.seat_number is not None:
            errors["seat_number"] = "Spectators and moderators cannot occupy seats."

    def _validate_ready_status(self, errors: dict[str, str]) -> None:
        if self.is_ready and self.role not in READY_ELIGIBLE_ROLES:
            errors["is_ready"] = "Ready status applies only to player roles."

    def _validate_json_object(self, errors: dict[str, str], field_name: str) -> None:
        if not isinstance(getattr(self, field_name), dict):
            errors[field_name] = "Must be a JSON object."

    def _validate_time_order(self, errors: dict[str, str]) -> None:
        if self.left_at and self.left_at < self.joined_at:
            errors["left_at"] = "Leave time cannot be before join time."
        if self.kicked_at and self.kicked_at < self.joined_at:
            errors["kicked_at"] = "Kick time cannot be before join time."


class LobbyBanQuerySet(models.QuerySet):
    def active(self):
        return self.filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )


class LobbyBan(models.Model):
    lobby = models.ForeignKey(
        GameLobby,
        on_delete=models.CASCADE,
        related_name="bans",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="lobby_bans",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_lobby_bans",
        null=True,
        blank=True,
    )
    reason = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LobbyBanQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("lobby", "user"), name="lobby_ban_user_idx"),
            models.Index(fields=("expires_at",), name="lobby_ban_expires_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("lobby", "user"),
                name="unique_lobby_ban_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} banned from {self.lobby}"


class LobbyAuditEventQuerySet(models.QuerySet):
    def for_idempotency_key(self, *, lobby, actor, event_type: str, key: str):
        return self.filter(
            lobby=lobby,
            actor=actor,
            event_type=event_type,
            idempotency_key=key,
        )


class LobbyAuditEvent(models.Model):
    lobby = models.ForeignKey(
        GameLobby,
        on_delete=models.CASCADE,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="lobby_audit_events",
        null=True,
        blank=True,
    )
    membership = models.ForeignKey(
        LobbyMembership,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    event_type = models.CharField(
        max_length=32,
        choices=LobbyAuditEventType.choices,
        db_index=True,
    )
    idempotency_key = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LobbyAuditEventQuerySet.as_manager()

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("lobby", "event_type"), name="lobby_audit_type_idx"),
            models.Index(
                fields=("lobby", "actor", "idempotency_key"),
                name="lobby_audit_key_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("lobby", "actor", "event_type", "idempotency_key"),
                condition=~models.Q(idempotency_key=""),
                name="unique_lobby_audit_idempotency",
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_type} for {self.lobby}"

    def clean(self) -> None:
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Must be a JSON object."})
        super().clean()

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


__all__ = [
    "GameLobby",
    "GameLobbyManager",
    "GameLobbyQuerySet",
    "LobbyAuditEvent",
    "LobbyAuditEventQuerySet",
    "LobbyAuditEventType",
    "LobbyBan",
    "LobbyBanQuerySet",
    "LobbyStatus",
    "LobbyVisibility",
    "LobbyMembership",
    "LobbyMembershipQuerySet",
    "MembershipConnectionStatus",
    "MembershipRole",
    "generate_lobby_code",
]
