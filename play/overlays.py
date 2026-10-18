"""Host-issued, short-lived read-only Connect4 broadcast access."""

from django.core import signing

from games.connect4_state import serialize_state
from games.engine import GameEngineError
from lobbies.models import LobbyBan

from .models import GameSession
from .services import GameActionDenied


OVERLAY_SALT = "play.connect4.overlay.v1"
OVERLAY_MAX_AGE = 24 * 60 * 60


def issue_overlay_token(session):
    return signing.dumps(
        {"session": str(session.public_id), "host": session.lobby.host_id},
        salt=OVERLAY_SALT,
    )


def get_overlay_snapshot(*, session_uuid, token):
    try:
        claims = signing.loads(token, salt=OVERLAY_SALT, max_age=OVERLAY_MAX_AGE)
        if not isinstance(claims, dict) or claims.get("session") != str(session_uuid):
            raise GameActionDenied("Overlay link is unavailable.")
        session = GameSession.objects.select_related("lobby", "lobby__host").get(
            public_id=session_uuid, engine_key="connect4", engine_version="0.1",
            game__slug="connect4",
        )
        host = session.lobby.host
        if (
            claims.get("host") != host.pk or not host.is_active
            or LobbyBan.objects.active().filter(lobby=session.lobby, user=host).exists()
        ):
            raise GameActionDenied("Overlay link is unavailable.")
        state = serialize_state(session.spectator_state)
    except (signing.BadSignature, GameSession.DoesNotExist, GameEngineError,
            TypeError, ValueError) as error:
        raise GameActionDenied("Overlay link is unavailable.") from error
    return {
        "session_uuid": str(session.public_id),
        "state_version": session.state_version,
        "status": session.status,
        "audience": "spectator",
        "actor_id": None,
        "state": state,
        "private_state": None,
    }
