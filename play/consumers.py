"""Session-scoped game WebSocket messages."""

from urllib.parse import parse_qs, urlparse
from uuid import UUID

from channels.db import database_sync_to_async
from channels.exceptions import DenyConnection
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.utils import timezone

from games.connect4_state import serialize_state
from games.engine import GameEngineError
from .overlays import get_overlay_snapshot
from .services import (
    GameActionError,
    GameActionDenied,
    GameActionInvalid,
    get_game_snapshot,
    submit_game_action,
)


class GameConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.session_uuid = str(self.scope["url_route"]["kwargs"]["session_uuid"])
        self.group_name = f"game_{self.session_uuid.replace('-', '')}"
        self.user = self.scope.get("user")
        query = parse_qs(
            self.scope.get("query_string", b"").decode("ascii", errors="ignore")
        )
        self.overlay_token = query.get("overlay_token", [None])[0]
        if not self._origin_is_allowed():
            raise DenyConnection("WebSocket origin is not allowed.")
        try:
            snapshot = await self._snapshot()
        except GameActionError as error:
            if self.overlay_token is not None:
                await self.close(code=4403)
                return
            raise DenyConnection(str(error)) from error
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_event("GAME_SNAPSHOT", snapshot)

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_error("invalid_message", "Message must be a JSON object.")
            return
        event_type = content.get("type")
        request_id = content.get("request_id")
        payload = content.get("payload")
        if event_type not in ("GAME_ACTION", "GAME_RESYNC"):
            await self.send_error("unknown_event", "Unsupported game event.")
            return
        try:
            if event_type == "GAME_RESYNC":
                if payload != {}:
                    raise GameActionInvalid("GAME_RESYNC payload must be empty.")
                snapshot = await self._snapshot()
                await self.send_event("GAME_SNAPSHOT", snapshot, request_id=request_id)
                return
            if self.overlay_token is not None:
                raise GameActionDenied("Overlay connections are read-only.")
            if not isinstance(request_id, str):
                raise GameActionInvalid("request_id must be a UUID.")
            UUID(request_id)
            if not isinstance(payload, dict) or set(payload) != {
                "action", "state_version"
            }:
                raise GameActionInvalid("GAME_ACTION needs action and state_version.")
            outcome = await self._submit(
                payload["action"], payload["state_version"], request_id
            )
            if outcome.replayed:
                snapshot = await self._snapshot()
                await self.send_event(
                    "GAME_ACTION_ACK",
                    self._audience_payload(outcome.response, snapshot),
                    request_id=request_id,
                )
            else:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "game.event",
                        "response": outcome.response,
                        "request_id": request_id,
                    },
                )
        except ValueError:
            await self.send_error("invalid_payload", "request_id must be a UUID.")
        except (GameActionError, GameEngineError) as error:
            await self.send_error(error.code, str(error), request_id=request_id)

    async def game_event(self, event):
        try:
            snapshot = await self._snapshot()
        except GameActionError:
            return
        await self.send_event(
            "GAME_STATE",
            self._audience_payload(event["response"], snapshot),
            request_id=event["request_id"],
        )

    def _audience_payload(self, response, snapshot):
        audience = snapshot["audience"]
        if response["state"].get("game") == "werewolves-vs-villagers":
            same_version = response["state_version"] == snapshot["state_version"]
            payload = {
                "state_version": snapshot["state_version"],
                "state": snapshot["state"],
                "events": response["events"] if same_version else [],
                "is_complete": snapshot["state"]["status"] == "completed",
                "result": snapshot["state"].get("result"),
            }
            if audience == "player":
                payload["private_state"] = snapshot["private_state"]
            return payload
        if audience == "spectator" and response["state"].get("game") == "connect4":
            return {
                "state_version": response["state_version"],
                "state": serialize_state(response["spectator_state"]),
            }
        payload = {
            "state_version": response["state_version"],
            "state": (
                response["state"] if audience == "player" else response["spectator_state"]
            ),
            "events": response["events"],
            "is_complete": response["is_complete"],
            "result": response["result"],
        }
        return payload

    async def send_event(self, event_type, payload, *, request_id=None):
        await self.send_json({
            "type": event_type,
            "request_id": request_id,
            "server_timestamp": timezone.now().isoformat(),
            "session_uuid": self.session_uuid,
            "payload": payload,
        })

    async def send_error(self, code, message, *, request_id=None):
        await self.send_event(
            "ERROR", {"code": code, "message": message}, request_id=request_id
        )

    def _origin_is_allowed(self):
        origin = dict(self.scope.get("headers") or []).get(b"origin")
        if not origin:
            return True
        host = urlparse(origin.decode("ascii", errors="ignore")).hostname
        allowed = getattr(settings, "ALLOWED_HOSTS", [])
        return bool(host and ("*" in allowed or host in {h.strip("[]") for h in allowed}))

    @database_sync_to_async
    def _snapshot(self):
        if self.overlay_token is not None:
            return get_overlay_snapshot(
                session_uuid=self.session_uuid, token=self.overlay_token
            )
        return get_game_snapshot(session_uuid=self.session_uuid, user=self.user)

    @database_sync_to_async
    def _submit(self, action, state_version, request_id):
        return submit_game_action(
            session_uuid=self.session_uuid,
            user=self.user,
            action=action,
            state_version=state_version,
            idempotency_key=request_id,
        )
