from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.core.validators import MaxLengthValidator, MinLengthValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.db.models.signals import post_save
from django.dispatch import receiver


DISPLAY_NAME_MAX_LENGTH = 24
DISPLAY_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]*[A-Za-z0-9]$")
display_name_validator = RegexValidator(
    regex=DISPLAY_NAME_PATTERN,
    message=(
        "Display names may contain only letters, numbers, spaces, hyphens, "
        "and underscores, and must start and end with a letter or number."
    ),
)


def normalize_display_name(value: str) -> str:
    return " ".join(value.strip().split())


def default_display_name_for_user(user) -> str:
    return f"Player {user.pk}"


class ArenaProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="arena_profile",
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    display_name = models.CharField(
        max_length=DISPLAY_NAME_MAX_LENGTH,
        validators=[
            MinLengthValidator(3),
            MaxLengthValidator(DISPLAY_NAME_MAX_LENGTH),
            display_name_validator,
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("display_name"),
                name="unique_arena_profile_display_name_ci",
            )
        ]
        ordering = ("display_name",)

    def __str__(self) -> str:
        return self.display_name

    def full_clean(self, *args, **kwargs) -> None:
        self.display_name = normalize_display_name(self.display_name)
        super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_arena_profile_for_user(sender, instance, created, **kwargs):
    if not created:
        return

    ArenaProfile.objects.get_or_create(
        user=instance,
        defaults={"display_name": default_display_name_for_user(instance)},
    )
