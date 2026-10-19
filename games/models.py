from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ProtectedError
from django.db.models.functions import Lower
from django.utils.text import slugify

from .registry import game_engine_registry, is_valid_engine_version


CATEGORY_NAME_MAX_LENGTH = 80
CATEGORY_SLUG_MAX_LENGTH = 96
CATEGORY_ICON_MAX_LENGTH = 80
GAME_NAME_MAX_LENGTH = 120
GAME_SLUG_MAX_LENGTH = 96
GAME_SHORT_DESCRIPTION_MAX_LENGTH = 240
GAME_ENGINE_KEY_MAX_LENGTH = 120
GAME_ENGINE_VERSION_MAX_LENGTH = 32
GAME_ASSET_MAX_LENGTH = 255


def normalize_category_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_category_slug(value: str) -> str:
    normalized = slugify(normalize_category_name(value))
    if not normalized:
        raise ValidationError("Category slug must contain at least one letter or number.")
    return normalized


def normalize_game_name(value: str) -> str:
    return " ".join((value or "").strip().split())


def normalize_game_slug(value: str) -> str:
    normalized = slugify(normalize_game_name(value))
    if not normalized:
        raise ValidationError("Game slug must contain at least one letter or number.")
    return normalized


def is_registered_game_engine(engine_key: str, engine_version: str) -> bool:
    return game_engine_registry.exists(engine_key, engine_version)


def validate_json_object(value, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError({field_name: "Must be a JSON object."})


def validate_difficulty_options(value) -> None:
    if not isinstance(value, list):
        raise ValidationError({"difficulty_options": "Must be a JSON list."})

    if any(not isinstance(option, str) or not option.strip() for option in value):
        raise ValidationError(
            {"difficulty_options": "Difficulty options must be non-empty strings."}
        )


class GameCategoryQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def public_catalog(self):
        return self.active()


class GameCategory(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=CATEGORY_NAME_MAX_LENGTH, unique=True)
    slug = models.SlugField(
        max_length=CATEGORY_SLUG_MAX_LENGTH,
        unique=True,
        blank=True,
    )
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=CATEGORY_ICON_MAX_LENGTH, blank=True)
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = GameCategoryQuerySet.as_manager()

    class Meta:
        ordering = ("display_order", "name")
        indexes = [
            models.Index(
                fields=("is_active", "display_order"),
                name="game_category_public_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="unique_game_category_name_ci",
            ),
            models.UniqueConstraint(
                Lower("slug"),
                name="unique_game_category_slug_ci",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        self.name = normalize_category_name(self.name)
        if not self.name:
            raise ValidationError({"name": "Category name is required."})

        slug_source = self.slug or self.name
        self.slug = normalize_category_slug(slug_source)
        super().clean()

    def full_clean(self, *args, **kwargs) -> None:
        self.name = normalize_category_name(self.name)
        if self.slug:
            normalized_slug = slugify(normalize_category_name(self.slug))
            if normalized_slug:
                self.slug = normalized_slug
        super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def contains_games(self) -> bool:
        related_games = getattr(self, "game_definitions", None)
        exists = getattr(related_games, "exists", None)
        return bool(exists()) if callable(exists) else False

    def delete(self, *args, **kwargs):
        if self.contains_games():
            raise ProtectedError(
                "Cannot delete a game category that still contains games.",
                [self],
            )
        return super().delete(*args, **kwargs)


class GameDefinitionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def public_catalog(self):
        return self.active().filter(category__is_active=True)

    def playable(self):
        return self.filter(is_playable=True)


class GameDefinition(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    category = models.ForeignKey(
        GameCategory,
        on_delete=models.PROTECT,
        related_name="game_definitions",
    )
    slug = models.SlugField(max_length=GAME_SLUG_MAX_LENGTH, unique=True, blank=True)
    name = models.CharField(max_length=GAME_NAME_MAX_LENGTH)
    short_description = models.CharField(max_length=GAME_SHORT_DESCRIPTION_MAX_LENGTH)
    full_description = models.TextField(blank=True)
    engine_key = models.CharField(max_length=GAME_ENGINE_KEY_MAX_LENGTH, blank=True)
    engine_version = models.CharField(
        max_length=GAME_ENGINE_VERSION_MAX_LENGTH,
        blank=True,
    )
    minimum_players = models.PositiveSmallIntegerField(default=1)
    maximum_players = models.PositiveSmallIntegerField(default=2)
    estimated_duration_minutes = models.PositiveIntegerField(default=0)
    supports_bots = models.BooleanField(default=False)
    supports_spectators = models.BooleanField(default=False)
    supports_ranked = models.BooleanField(default=False)
    supports_private_lobbies = models.BooleanField(default=False)
    supports_broadcasts = models.BooleanField(default=False)
    difficulty_options = models.JSONField(default=list, blank=True)
    rules = models.JSONField(default=dict, blank=True)
    default_configuration = models.JSONField(default=dict, blank=True)
    thumbnail = models.CharField(max_length=GAME_ASSET_MAX_LENGTH, blank=True)
    banner = models.CharField(max_length=GAME_ASSET_MAX_LENGTH, blank=True)
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    is_playable = models.BooleanField(default=False, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = GameDefinitionQuerySet.as_manager()

    class Meta:
        ordering = ("category__display_order", "display_order", "name", "pk")
        indexes = [
            models.Index(fields=("slug",), name="game_def_slug_idx"),
            models.Index(fields=("category",), name="game_def_category_idx"),
            models.Index(fields=("is_active",), name="game_def_active_idx"),
            models.Index(fields=("is_playable",), name="game_def_playable_idx"),
            models.Index(fields=("is_featured",), name="game_def_featured_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("slug"),
                name="unique_game_definition_slug_ci",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_players__gte=1),
                name="game_def_min_players_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(maximum_players__gte=models.F("minimum_players")),
                name="game_def_max_players_gte_min",
            ),
            models.CheckConstraint(
                condition=models.Q(estimated_duration_minutes__gte=0),
                name="game_def_duration_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(is_playable=False) | ~models.Q(engine_key=""),
                name="game_def_playable_has_engine",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        self.name = normalize_game_name(self.name)
        if not self.name:
            raise ValidationError({"name": "Game name is required."})

        slug_source = self.slug or self.name
        self.slug = normalize_game_slug(slug_source)
        self.engine_key = (self.engine_key or "").strip()
        self.engine_version = (self.engine_version or "").strip()

        errors = {}
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
            self.estimated_duration_minutes is not None
            and self.estimated_duration_minutes < 0
        ):
            errors["estimated_duration_minutes"] = (
                "Estimated duration cannot be negative."
            )

        try:
            validate_difficulty_options(self.difficulty_options)
        except ValidationError as error:
            errors.update(error.message_dict)
        for field_name in ("rules", "default_configuration"):
            try:
                validate_json_object(getattr(self, field_name), field_name)
            except ValidationError as error:
                errors.update(error.message_dict)

        if self.is_playable:
            if not self.engine_key:
                errors["engine_key"] = "Playable games require an engine key."
            if not self.engine_version:
                errors["engine_version"] = "Playable games require an engine version."
            elif not is_valid_engine_version(self.engine_version):
                errors["engine_version"] = (
                    "Engine version must contain only letters, numbers, dots, "
                    "underscores, plus signs, or hyphens."
                )
            if (
                self.engine_key
                and self.engine_version
                and "engine_version" not in errors
                and not is_registered_game_engine(self.engine_key, self.engine_version)
            ):
                errors["is_playable"] = "Playable games require a registered engine."

        if errors:
            raise ValidationError(errors)

        super().clean()

    def full_clean(self, *args, **kwargs) -> None:
        self.name = normalize_game_name(self.name)
        if self.slug:
            normalized_slug = slugify(normalize_game_name(self.slug))
            if normalized_slug:
                self.slug = normalized_slug
        super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
