from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

from games.models import GameDefinition
from lobbies.models import GameLobby, LobbyMembership, MembershipRole


SESSION_STATUS_MAX_LENGTH = 20
ACTOR_ID_MAX_LENGTH = 80
ENGINE_KEY_MAX_LENGTH = 120
ENGINE_VERSION_MAX_LENGTH = 32


class GameSessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class GameSession(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    lobby = models.OneToOneField(
        GameLobby,
        on_delete=models.PROTECT,
        related_name="game_session",
    )
    game = models.ForeignKey(
        GameDefinition,
        on_delete=models.PROTECT,
        related_name="sessions",
    )
    status = models.CharField(
        max_length=SESSION_STATUS_MAX_LENGTH,
        choices=GameSessionStatus.choices,
        default=GameSessionStatus.ACTIVE,
        db_index=True,
    )
    engine_key = models.CharField(max_length=ENGINE_KEY_MAX_LENGTH)
    engine_version = models.CharField(max_length=ENGINE_VERSION_MAX_LENGTH)
    configuration = models.JSONField(default=dict)
    initial_state = models.JSONField(default=dict)
    authoritative_state = models.JSONField(default=dict)
    public_state = models.JSONField(default=dict)
    spectator_state = models.JSONField(default=dict)
    state_version = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-started_at", "-id")
        indexes = [
            models.Index(fields=("game", "status"), name="game_session_game_status_idx"),
            models.Index(fields=("status", "started_at"), name="game_session_stat_start_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.game} session {self.public_id}"

    def clean(self) -> None:
        errors = {}
        for field_name in (
            "configuration",
            "initial_state",
            "authoritative_state",
            "public_state",
            "spectator_state",
        ):
            if not isinstance(getattr(self, field_name), dict):
                errors[field_name] = "Must be a JSON object."
        if self.ended_at and self.started_at and self.ended_at < self.started_at:
            errors["ended_at"] = "End time cannot be before start time."
        if errors:
            raise ValidationError(errors)
        super().clean()

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class GameSessionParticipant(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    session = models.ForeignKey(
        GameSession,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    lobby_membership = models.ForeignKey(
        LobbyMembership,
        on_delete=models.PROTECT,
        related_name="game_participations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="game_participations",
        null=True,
        blank=True,
    )
    actor_id = models.CharField(max_length=ACTOR_ID_MAX_LENGTH)
    role = models.CharField(
        max_length=20,
        choices=MembershipRole.choices,
    )
    seat_number = models.PositiveSmallIntegerField(null=True, blank=True)
    is_bot = models.BooleanField(default=False)
    bot_reference = models.CharField(max_length=80, blank=True)
    private_state = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("seat_number", "id")
        indexes = [
            models.Index(fields=("session", "role"), name="game_participant_role_idx"),
            models.Index(fields=("user", "session"), name="game_participant_user_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("session", "lobby_membership"),
                name="unique_session_lobby_membership",
            ),
            models.UniqueConstraint(
                fields=("session", "actor_id"),
                name="unique_session_actor_id",
            ),
            models.UniqueConstraint(
                fields=("session", "seat_number"),
                condition=models.Q(seat_number__isnull=False),
                name="unique_session_seat_number",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.session_id}:{self.actor_id}"

    def clean(self) -> None:
        if not isinstance(self.private_state, dict):
            raise ValidationError({"private_state": "Must be a JSON object."})
        super().clean()

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class GameActionReceipt(models.Model):
    """Durable idempotency response for one accepted session action."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    session = models.ForeignKey(
        GameSession, on_delete=models.CASCADE, related_name="action_receipts"
    )
    participant = models.ForeignKey(GameSessionParticipant, on_delete=models.PROTECT)
    idempotency_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("session", "participant", "idempotency_key"),
                name="unique_session_action_receipt",
            ),
        ]


__all__ = [
    "GameActionReceipt",
    "GameSession",
    "GameSessionParticipant",
    "GameSessionStatus",
]
