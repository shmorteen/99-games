from django.contrib import admin

from .models import GameSession, GameSessionParticipant


class GameSessionParticipantInline(admin.TabularInline):
    model = GameSessionParticipant
    extra = 0
    readonly_fields = (
        "public_id",
        "lobby_membership",
        "user",
        "actor_id",
        "role",
        "seat_number",
        "is_bot",
        "bot_reference",
        "private_state",
        "created_at",
    )
    can_delete = False


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "game",
        "lobby",
        "status",
        "engine_key",
        "engine_version",
        "state_version",
        "started_at",
    )
    list_filter = ("status", "game")
    search_fields = ("public_id", "lobby__name", "lobby__lobby_code", "game__name")
    readonly_fields = (
        "public_id",
        "lobby",
        "game",
        "status",
        "engine_key",
        "engine_version",
        "configuration",
        "initial_state",
        "public_state",
        "spectator_state",
        "state_version",
        "started_at",
        "ended_at",
        "created_at",
        "updated_at",
    )
    inlines = (GameSessionParticipantInline,)


@admin.register(GameSessionParticipant)
class GameSessionParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "actor_id",
        "role",
        "user",
        "seat_number",
        "is_bot",
        "created_at",
    )
    list_filter = ("role", "is_bot")
    search_fields = (
        "actor_id",
        "user__username",
        "user__email",
        "bot_reference",
        "session__public_id",
    )
    readonly_fields = (
        "public_id",
        "session",
        "lobby_membership",
        "user",
        "actor_id",
        "role",
        "seat_number",
        "is_bot",
        "bot_reference",
        "private_state",
        "created_at",
    )
