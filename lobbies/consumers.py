from __future__ import annotations

from urllib.parse import urlparse

from channels.db import database_sync_to_async
from channels.exceptions import DenyConnection
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from .models import (
    GameLobby,
    LobbyBan,
    LobbyMembership,
    LobbyStatus,
    LobbyVisibility,
    MembershipConnectionStatus,
    MembershipRole,
)
from .services import (
    LobbyAccessDenied,
    LobbyAlreadyMember,
    LobbyAuthenticationError,
    LobbyCredentialsError,
    LobbyFull,
    LobbyMembershipNotFound,
    LobbyNotJoinable,
    LobbyServiceError,
    LobbyStartConflict,
    LobbyStartError,
    LobbyValidationError,
    add_lobby_bot,
    begin_ready_check,
    join_lobby,
    leave_lobby,
    remove_lobby_bot,
    set_membership_ready,
    start_game,
    transfer_lobby_host,
)


CLIENT_EVENT_TYPES = {
    "LOBBY_JOIN",
    "LOBBY_LEAVE",
    "LOBBY_READY",
    "LOBBY_UNREADY",
    "LOBBY_CHAT",
    "HOST_TRANSFER",
    "BOT_ADD",
    "BOT_REMOVE",
    "READY_CHECK_START",
    "GAME_START",
    "GAME_RESYNC",
}
CHAT_MESSAGE_MAX_LENGTH = 500


class LobbyConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.lobby_uuid = str(self.scope["url_route"]["kwargs"]["lobby_uuid"])
        self.lobby_group_name = f"lobby_{self.lobby_uuid.replace('-', '')}"
        self.user = self.scope.get("user") or AnonymousUser()

        if not self._origin_is_allowed():
            raise DenyConnection("WebSocket origin is not allowed.")

        snapshot = await self._connect_snapshot()
        if snapshot is None:
            raise DenyConnection("Lobby connection is not allowed.")

        await self.channel_layer.group_add(self.lobby_group_name, self.channel_name)
        self.user_lobby_group_name = None
        if getattr(self.user, "is_authenticated", False) and self.user.pk:
            self.user_lobby_group_name = self.user_group_name(self.user.pk)
            await self.channel_layer.group_add(
                self.user_lobby_group_name,
                self.channel_name,
            )
        await self.accept()
        await self.send_lobby_event("LOBBY_SNAPSHOT", snapshot)

    async def disconnect(self, close_code):
        if hasattr(self, "lobby_group_name"):
            await self._mark_disconnected()
            await self.channel_layer.group_discard(
                self.lobby_group_name,
                self.channel_name,
            )
        if getattr(self, "user_lobby_group_name", None):
            await self.channel_layer.group_discard(
                self.user_lobby_group_name,
                self.channel_name,
            )

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_error(
                code="invalid_message",
                message="WebSocket messages must be JSON objects.",
            )
            return

        event_type = content.get("type")
        request_id = content.get("request_id")
        payload = content.get("payload", {})
        if not isinstance(payload, dict):
            await self.send_error(
                code="invalid_payload",
                message="Message payload must be a JSON object.",
                request_id=request_id,
            )
            return
        if event_type not in CLIENT_EVENT_TYPES:
            await self.send_error(
                code="unknown_event",
                message="Unsupported lobby event type.",
                request_id=request_id,
            )
            return

        try:
            handler = getattr(self, f"handle_{event_type.lower()}")
            await handler(payload, request_id)
        except LobbyServiceError as error:
            await self.send_error_for_exception(error, request_id=request_id)
        except (KeyError, TypeError, ValueError) as error:
            await self.send_error(
                code="invalid_payload",
                message=str(error) or "Invalid event payload.",
                request_id=request_id,
            )

    async def handle_lobby_join(self, payload, request_id):
        result = await self._join_lobby(payload, request_id)
        await self.group_lobby_event(
            "LOBBY_MEMBER_JOINED",
            {"member": result["member"]},
            request_id=request_id,
        )
        if result["member"]["role"] == MembershipRole.SPECTATOR:
            await self.group_lobby_event(
                "SPECTATOR_COUNT",
                {"spectator_count": result["spectator_count"]},
                request_id=request_id,
            )

    async def handle_lobby_leave(self, payload, request_id):
        result = await self._leave_lobby(request_id)
        await self.group_lobby_event(
            "LOBBY_MEMBER_LEFT",
            {
                "member_uuid": result["member_uuid"],
                "role": result["role"],
                "seat_number": result["seat_number"],
            },
            request_id=request_id,
        )
        if result["host_changed"]:
            await self.group_lobby_event(
                "HOST_CHANGED",
                result["host_changed"],
                request_id=request_id,
            )
        if result["status_changed"]:
            await self.group_lobby_event(
                "LOBBY_STATUS_CHANGED",
                result["status_changed"],
                request_id=request_id,
            )

    async def handle_lobby_ready(self, payload, request_id):
        await self._set_ready(payload, request_id, is_ready=True)

    async def handle_lobby_unready(self, payload, request_id):
        await self._set_ready(payload, request_id, is_ready=False)

    async def handle_lobby_chat(self, payload, request_id):
        result = await self._validate_chat(payload)
        await self.group_lobby_event("LOBBY_CHAT", result, request_id=request_id)

    async def handle_host_transfer(self, payload, request_id):
        target_member_uuid = payload.get("target_member_uuid")
        result = await self._transfer_host(target_member_uuid)
        await self.group_lobby_event("HOST_CHANGED", result, request_id=request_id)

    async def handle_bot_add(self, payload, request_id):
        result = await self._add_bot(payload)
        await self.group_lobby_event(
            "LOBBY_MEMBER_JOINED",
            {"member": result},
            request_id=request_id,
        )

    async def handle_bot_remove(self, payload, request_id):
        result = await self._remove_bot(payload)
        await self.group_lobby_event("LOBBY_MEMBER_LEFT", result, request_id=request_id)

    async def handle_ready_check_start(self, payload, request_id):
        result = await self._begin_ready_check(payload, request_id)
        await self.group_lobby_event(
            "READY_CHECK_STARTED",
            result,
            request_id=request_id,
        )

    async def handle_game_start(self, payload, request_id):
        result = await self._start_game(request_id)
        private_states = result.pop("private_states_by_user_id")
        public_state = result.pop("public_state")
        await self.group_lobby_event("GAME_STARTED", result, request_id=request_id)
        for user_id, private_payload in private_states.items():
            await self.channel_layer.group_send(
                self.user_group_name(user_id),
                {
                    "type": "lobby.event",
                    "message": self.event_message(
                        "GAME_STARTED_PRIVATE",
                        {**private_payload, "public_state": public_state},
                        request_id=request_id,
                    ),
                },
            )

    async def handle_game_resync(self, payload, request_id):
        snapshot = await self._snapshot()
        await self.send_lobby_event("LOBBY_SNAPSHOT", snapshot, request_id=request_id)

    async def _set_ready(self, payload, request_id, *, is_ready: bool):
        membership = await self._set_ready_state(payload, is_ready=is_ready)
        await self.group_lobby_event(
            "READY_STATE_CHANGED",
            {
                "member_uuid": str(membership.public_id),
                "role": membership.role,
                "is_ready": membership.is_ready,
            },
            request_id=request_id,
        )

    async def group_lobby_event(self, event_type, payload, *, request_id=None):
        await self.channel_layer.group_send(
            self.lobby_group_name,
            {
                "type": "lobby.event",
                "message": self.event_message(
                    event_type,
                    payload,
                    request_id=request_id,
                ),
            },
        )

    async def lobby_event(self, event):
        if event["message"]["type"] == "GAME_STARTED":
            if not await self._can_receive_game_started():
                return
        await self.send_json(event["message"])

    async def send_lobby_event(self, event_type, payload, *, request_id=None):
        await self.send_json(
            self.event_message(event_type, payload, request_id=request_id)
        )

    async def send_error_for_exception(self, error: Exception, *, request_id=None):
        error_map = {
            LobbyAuthenticationError: "authentication_required",
            LobbyAccessDenied: "permission_denied",
            LobbyCredentialsError: "invalid_credentials",
            LobbyNotJoinable: "not_joinable",
            LobbyAlreadyMember: "already_member",
            LobbyFull: "lobby_full",
            LobbyMembershipNotFound: "membership_not_found",
            LobbyStartConflict: "start_conflict",
            LobbyStartError: "start_failed",
            LobbyValidationError: "invalid_payload",
        }
        code = "lobby_error"
        for error_class, mapped_code in error_map.items():
            if isinstance(error, error_class):
                code = mapped_code
                break
        await self.send_error(code=code, message=str(error), request_id=request_id)

    async def send_error(self, *, code, message, request_id=None):
        await self.send_lobby_event(
            "ERROR",
            {"code": code, "message": message},
            request_id=request_id,
        )

    def event_message(self, event_type, payload, *, request_id=None):
        return {
            "type": event_type,
            "request_id": request_id,
            "server_timestamp": timezone.now().isoformat(),
            "lobby_uuid": self.lobby_uuid,
            "payload": payload,
        }

    def user_group_name(self, user_id):
        return f"{self.lobby_group_name}_user_{user_id}"

    def _origin_is_allowed(self) -> bool:
        headers = dict(self.scope.get("headers") or [])
        origin = headers.get(b"origin")
        if not origin:
            return True

        parsed = urlparse(origin.decode("ascii", errors="ignore"))
        origin_host = parsed.hostname
        if not origin_host:
            return False

        allowed_hosts = getattr(settings, "ALLOWED_HOSTS", [])
        if "*" in allowed_hosts:
            return True
        normalized_hosts = {host.strip("[]") for host in allowed_hosts}
        return origin_host in normalized_hosts

    @database_sync_to_async
    def _connect_snapshot(self):
        try:
            lobby = self._lobby()
        except GameLobby.DoesNotExist:
            return None

        if not self._connect_user_allowed(lobby):
            return None

        membership = self._active_membership(lobby)
        if membership:
            if membership.role == MembershipRole.SPECTATOR and not lobby.allow_spectators:
                return None
            membership.connection_status = MembershipConnectionStatus.ONLINE
            membership.save(update_fields=["connection_status", "updated_at"])
        elif lobby.status != LobbyStatus.WAITING:
            return None
        elif lobby.visibility == LobbyVisibility.FRIENDS_ONLY:
            return None

        return self._snapshot_payload(lobby, viewer_membership=membership)

    @database_sync_to_async
    def _snapshot(self):
        lobby = self._lobby()
        return self._snapshot_payload(lobby, viewer_membership=self._active_membership(lobby))

    @database_sync_to_async
    def _mark_disconnected(self):
        if not getattr(self.user, "is_authenticated", False):
            return
        try:
            lobby = self._lobby()
        except GameLobby.DoesNotExist:
            return
        membership = self._active_membership(lobby)
        if membership is None:
            return
        membership.connection_status = MembershipConnectionStatus.DISCONNECTED
        membership.save(update_fields=["connection_status", "updated_at"])

    @database_sync_to_async
    def _can_receive_game_started(self):
        try:
            lobby = self._lobby()
        except GameLobby.DoesNotExist:
            return False
        if not self._connect_user_allowed(lobby):
            return False
        membership = self._active_membership(lobby)
        if membership is not None:
            return membership.role != MembershipRole.SPECTATOR or lobby.allow_spectators
        return bool(
            not getattr(self.user, "is_authenticated", False)
            and getattr(settings, "KSA_ALLOW_GUEST_SPECTATOR_WEBSOCKETS", False)
            and settings.DEBUG
            and lobby.allow_spectators
        )

    @database_sync_to_async
    def _join_lobby(self, payload, request_id):
        lobby = self._lobby()
        membership = join_lobby(
            lobby=lobby,
            user=self.user,
            as_spectator=bool(payload.get("as_spectator", False)),
            password=payload.get("password"),
            invite_token=payload.get("invite_token"),
            idempotency_key=request_id,
        )
        return {
            "member": self._member_payload(membership),
            "spectator_count": self._active_spectator_count(lobby),
        }

    @database_sync_to_async
    def _leave_lobby(self, request_id):
        lobby = self._lobby()
        old_host_id = lobby.host_id
        old_status = lobby.status
        membership = leave_lobby(
            lobby=lobby,
            user=self.user,
            idempotency_key=request_id,
        )
        lobby.refresh_from_db()
        host_changed = None
        if lobby.host_id != old_host_id:
            new_host = self._active_host_membership(lobby)
            host_changed = {
                "new_host_member_uuid": str(new_host.public_id) if new_host else None,
                "new_host_display_name": self._display_name(new_host)
                if new_host
                else None,
            }
        status_changed = None
        if lobby.status != old_status:
            status_changed = {"status": lobby.status}
        return {
            "member_uuid": str(membership.public_id),
            "role": membership.role,
            "seat_number": membership.seat_number,
            "host_changed": host_changed,
            "status_changed": status_changed,
        }

    @database_sync_to_async
    def _set_ready_state(self, payload, *, is_ready):
        lobby = self._lobby()
        return set_membership_ready(
            lobby=lobby,
            user=self.user,
            is_ready=is_ready,
            member_public_id=payload.get("member_uuid"),
        )

    @database_sync_to_async
    def _transfer_host(self, target_member_uuid):
        lobby = self._lobby()
        membership = transfer_lobby_host(
            lobby=lobby,
            user=self.user,
            target_member_public_id=target_member_uuid,
        )
        return {
            "new_host_member_uuid": str(membership.public_id),
            "new_host_display_name": self._display_name(membership),
        }

    @database_sync_to_async
    def _add_bot(self, payload):
        lobby = self._lobby()
        membership = add_lobby_bot(
            lobby=lobby,
            user=self.user,
            bot_reference=payload.get("bot_reference", ""),
        )
        return self._member_payload(membership)

    @database_sync_to_async
    def _remove_bot(self, payload):
        lobby = self._lobby()
        membership = remove_lobby_bot(
            lobby=lobby,
            user=self.user,
            target_member_public_id=payload.get("target_member_uuid"),
        )
        return {
            "member_uuid": str(membership.public_id),
            "role": membership.role,
            "seat_number": membership.seat_number,
        }

    @database_sync_to_async
    def _begin_ready_check(self, payload, request_id):
        lobby = self._lobby()
        ready_lobby = begin_ready_check(
            lobby=lobby,
            user=self.user,
            timeout_seconds=payload.get("timeout_seconds"),
            idempotency_key=request_id,
        )
        return {
            "status": ready_lobby.status,
            "ready_check_started_at": ready_lobby.ready_check_started_at.isoformat()
            if ready_lobby.ready_check_started_at
            else None,
            "ready_check_expires_at": ready_lobby.ready_check_expires_at.isoformat()
            if ready_lobby.ready_check_expires_at
            else None,
        }

    @database_sync_to_async
    def _start_game(self, request_id):
        lobby = self._lobby()
        result = start_game(
            lobby=lobby,
            user=self.user,
            idempotency_key=request_id,
        )
        return {
            "session_uuid": str(result.session.public_id),
            "game_slug": result.session.game.slug,
            "game_route": result.game_route,
            "public_state": result.public_state,
            "spectator_state": result.spectator_state,
            "private_states_by_user_id": result.private_states_by_user_id,
        }

    @database_sync_to_async
    def _validate_chat(self, payload):
        lobby = self._lobby()
        membership = self._active_membership(lobby)
        if membership is None:
            raise LobbyMembershipNotFound("User has no active lobby membership.")
        message = payload.get("message", "")
        if not isinstance(message, str) or not message.strip():
            raise LobbyValidationError("Chat message is required.")
        message = message.strip()
        if len(message) > CHAT_MESSAGE_MAX_LENGTH:
            raise LobbyValidationError("Chat message is too long.")
        return {
            "member_uuid": str(membership.public_id),
            "display_name": self._display_name(membership),
            "message": message,
        }

    def _lobby(self) -> GameLobby:
        return GameLobby.objects.select_related("game", "host").get(
            public_id=self.lobby_uuid
        )

    def _connect_user_allowed(self, lobby: GameLobby) -> bool:
        if not getattr(self.user, "is_authenticated", False):
            return bool(
                getattr(settings, "KSA_ALLOW_GUEST_SPECTATOR_WEBSOCKETS", False)
                and settings.DEBUG
                and lobby.allow_spectators
            )
        if not getattr(self.user, "is_active", True):
            return False
        return not LobbyBan.objects.active().filter(lobby=lobby, user=self.user).exists()

    def _active_memberships(self, lobby: GameLobby):
        return (
            LobbyMembership.objects.active()
            .filter(lobby=lobby)
            .select_related("user", "user__arena_profile")
            .order_by("seat_number", "joined_at", "id")
        )

    def _active_membership(self, lobby: GameLobby):
        if not getattr(self.user, "is_authenticated", False):
            return None
        return self._active_memberships(lobby).filter(user=self.user).first()

    def _active_host_membership(self, lobby: GameLobby):
        return self._active_memberships(lobby).filter(role=MembershipRole.HOST).first()

    def _active_spectator_count(self, lobby: GameLobby) -> int:
        return self._active_memberships(lobby).filter(
            role=MembershipRole.SPECTATOR
        ).count()

    def _snapshot_payload(self, lobby, *, viewer_membership):
        members = [self._member_payload(membership) for membership in self._active_memberships(lobby)]
        return {
            "lobby": {
                "uuid": str(lobby.public_id),
                "code": lobby.lobby_code,
                "name": lobby.name,
                "status": lobby.status,
                "visibility": lobby.visibility,
                "game_slug": lobby.game.slug,
                "minimum_players": lobby.minimum_players,
                "maximum_players": lobby.maximum_players,
                "allow_spectators": lobby.allow_spectators,
                "spectator_limit": lobby.spectator_limit,
                "ready_check_started_at": lobby.ready_check_started_at.isoformat()
                if lobby.ready_check_started_at
                else None,
                "ready_check_expires_at": lobby.ready_check_expires_at.isoformat()
                if lobby.ready_check_expires_at
                else None,
            },
            "viewer": {
                "membership_uuid": str(viewer_membership.public_id)
                if viewer_membership
                else None,
                "role": viewer_membership.role if viewer_membership else None,
                "is_host": bool(
                    viewer_membership and viewer_membership.role == MembershipRole.HOST
                ),
            },
            "members": members,
            "player_count": len(
                [
                    member
                    for member in members
                    if member["role"]
                    in (MembershipRole.HOST, MembershipRole.CO_HOST, MembershipRole.PLAYER)
                ]
            ),
            "spectator_count": len(
                [member for member in members if member["role"] == MembershipRole.SPECTATOR]
            ),
        }

    def _member_payload(self, membership: LobbyMembership):
        return {
            "member_uuid": str(membership.public_id),
            "role": membership.role,
            "seat_number": membership.seat_number,
            "is_ready": membership.is_ready,
            "connection_status": membership.connection_status,
            "is_bot": membership.is_bot,
            "bot_reference": membership.bot_reference if membership.is_bot else "",
            "display_name": self._display_name(membership),
            "profile_public_id": self._profile_public_id(membership),
        }

    def _display_name(self, membership: LobbyMembership | None):
        if membership is None:
            return None
        if membership.is_bot:
            return membership.bot_reference
        profile = getattr(membership.user, "arena_profile", None)
        return profile.display_name if profile else membership.user.get_username()

    def _profile_public_id(self, membership: LobbyMembership | None):
        if membership is None or membership.is_bot:
            return None
        profile = getattr(membership.user, "arena_profile", None)
        return str(profile.public_id) if profile else None


__all__ = ["LobbyConsumer"]
