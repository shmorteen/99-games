from django.contrib import admin

from .models import GameLobby, LobbyAuditEvent, LobbyBan, LobbyMembership, LobbyStatus


@admin.register(GameLobby)
class GameLobbyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "lobby_code",
        "game",
        "host",
        "visibility",
        "status",
        "minimum_players",
        "maximum_players",
        "created_at",
    )
    list_filter = ("visibility", "status", "is_ranked", "allow_bot_fill")
    search_fields = ("name", "lobby_code", "game__name", "host__username")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("game", "host")
    fieldsets = (
        (
            "Lobby",
            {
                "fields": (
                    "public_id",
                    "lobby_code",
                    "name",
                    "game",
                    "host",
                    "visibility",
                    "status",
                )
            },
        ),
        (
            "Capacity",
            {
                "fields": (
                    "minimum_players",
                    "maximum_players",
                    "is_ranked",
                    "allow_bot_fill",
                    "bot_difficulty",
                    "allow_spectators",
                    "spectator_limit",
                )
            },
        ),
        (
            "Configuration",
            {
                "fields": (
                    "game_configuration",
                    "invite_token_metadata",
                )
            },
        ),
        (
            "Ready Check",
            {
                "fields": (
                    "ready_check_started_at",
                    "ready_check_expires_at",
                )
            },
        ),
        (
            "Timing",
            {
                "fields": (
                    "scheduled_start_at",
                    "started_at",
                    "ended_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    actions = ("mark_waiting", "mark_cancelled")

    @admin.action(description="Mark selected lobbies as waiting")
    def mark_waiting(self, request, queryset):
        queryset.update(status=LobbyStatus.WAITING)

    @admin.action(description="Mark selected lobbies as cancelled")
    def mark_cancelled(self, request, queryset):
        queryset.update(status=LobbyStatus.CANCELLED)


@admin.register(LobbyMembership)
class LobbyMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "lobby",
        "role",
        "user",
        "bot_reference",
        "seat_number",
        "is_ready",
        "connection_status",
        "joined_at",
        "left_at",
        "kicked_at",
    )
    list_filter = ("role", "connection_status", "is_ready")
    search_fields = (
        "lobby__name",
        "lobby__lobby_code",
        "user__username",
        "user__email",
        "bot_reference",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("lobby", "user")


@admin.register(LobbyBan)
class LobbyBanAdmin(admin.ModelAdmin):
    list_display = ("lobby", "user", "created_by", "expires_at", "created_at")
    list_filter = ("expires_at", "created_at")
    search_fields = (
        "lobby__name",
        "lobby__lobby_code",
        "user__username",
        "user__email",
        "reason",
    )
    readonly_fields = ("created_at",)
    autocomplete_fields = ("lobby", "user", "created_by")


@admin.register(LobbyAuditEvent)
class LobbyAuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "lobby",
        "event_type",
        "actor",
        "membership",
        "idempotency_key",
        "created_at",
    )
    list_filter = ("event_type", "created_at")
    search_fields = (
        "lobby__name",
        "lobby__lobby_code",
        "actor__username",
        "actor__email",
        "idempotency_key",
    )
    readonly_fields = (
        "lobby",
        "event_type",
        "actor",
        "membership",
        "idempotency_key",
        "metadata",
        "created_at",
    )
    autocomplete_fields = ("lobby", "actor", "membership")
