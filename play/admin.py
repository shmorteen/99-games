from django.contrib import admin
from django.http import JsonResponse, Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from games.engine import GameEngineError

from .models import GameActionReceipt, GameSession, GameSessionParticipant
from .operations import action_audit
from .replays import ReplayUnavailable, build_connect4_admin_replay


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
        "inspection_link",
    )
    inlines = (GameSessionParticipantInline,)

    @admin.display(description="Operational inspection")
    def inspection_link(self, obj):
        if obj is None or obj.pk is None:
            return "—"
        url = reverse("admin:play_gamesession_inspect", args=[obj.pk])
        return format_html('<a href="{}">Inspect audit and replay</a>', url)

    def get_urls(self):
        return [
            path(
                "<path:object_id>/inspect/",
                self.admin_site.admin_view(self.inspect_session),
                name="play_gamesession_inspect",
            ),
            *super().get_urls(),
        ]

    def inspect_session(self, request, object_id):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        if not self.has_view_permission(request):
            raise Http404
        session = get_object_or_404(GameSession, pk=object_id)
        result = {"audit": action_audit(session), "replay": None}
        if session.engine_key == "connect4" and session.status == "completed":
            try:
                result["replay"] = build_connect4_admin_replay(
                    session_uuid=str(session.public_id), user=request.user
                )
            except (ReplayUnavailable, GameEngineError):
                result["replay"] = {"status": "unavailable"}
        return JsonResponse(result)


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


@admin.register(GameActionReceipt)
class GameActionReceiptAdmin(admin.ModelAdmin):
    """Immutable action trail with no authoritative or private state payloads."""

    list_display = ("public_id", "session", "actor_id", "state_version", "created_at")
    search_fields = ("public_id", "session__public_id", "participant__actor_id")
    list_filter = ("session__game", "created_at")
    readonly_fields = (
        "public_id", "session", "participant", "idempotency_key",
        "request_hash", "state_version", "created_at",
    )
    fields = readonly_fields

    @admin.display(description="Actor")
    def actor_id(self, obj):
        return obj.participant.actor_id

    @admin.display(description="State version")
    def state_version(self, obj):
        response = obj.response
        return response.get("state_version") if isinstance(response, dict) else None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
