"""Connect4 bot scheduling and shared-service turn execution."""

from functools import partial
import logging
from uuid import NAMESPACE_URL, uuid5

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from kombu.exceptions import OperationalError

from games.connect4_bot import choose_bot_action
from games.engine import StaleGameState
from lobbies.models import LobbyStatus, MembershipRole

from .models import GameSession, GameSessionStatus
from .services import GameActionDenied, submit_game_action


logger = logging.getLogger(__name__)


def maybe_schedule_connect4_bot_turn(session, state):
    """Queue only a current bot turn, after the surrounding write commits."""

    if not getattr(settings, "KSA_CONNECT4_BOT_AUTOMATION_ENABLED", True):
        return False
    if (session.engine_key, session.engine_version) != ("connect4", "0.1"):
        return False
    actor_id = state.get("turn_actor_id")
    if not actor_id or state.get("status") != "in_progress":
        return False
    if not session.participants.filter(
        actor_id=actor_id, is_bot=True, role=MembershipRole.BOT,
        lobby_membership__left_at__isnull=True,
        lobby_membership__kicked_at__isnull=True,
    ).exists():
        return False
    transaction.on_commit(partial(
        enqueue_connect4_bot_turn, str(session.public_id), session.state_version
    ))
    return True


def enqueue_connect4_bot_turn(session_uuid, expected_version):
    """Publish a version-bound task without failing an already committed move."""

    from .tasks import connect4_bot_turn

    try:
        connect4_bot_turn.delay(session_uuid, expected_version)
    except OperationalError:
        logger.exception("Could not queue Connect4 bot turn for %s", session_uuid)


def run_connect4_bot_turn(session_uuid, *, expected_version):
    """Read fresh state, choose one move, and submit via the human action path."""

    if type(expected_version) is not int or expected_version < 1:
        return None
    session = GameSession.objects.select_related("lobby").filter(
        public_id=session_uuid, engine_key="connect4", engine_version="0.1",
        status=GameSessionStatus.ACTIVE, lobby__status=LobbyStatus.ACTIVE,
    ).first()
    if session is None or session.state_version != expected_version:
        return None
    state = session.authoritative_state
    actor_id = state.get("turn_actor_id")
    if not actor_id or state.get("status") != "in_progress":
        return None
    if not session.participants.filter(
        actor_id=actor_id, is_bot=True, role=MembershipRole.BOT,
        lobby_membership__left_at__isnull=True,
        lobby_membership__kicked_at__isnull=True,
    ).exists():
        return None

    action = choose_bot_action(
        state, actor_id, difficulty=session.lobby.bot_difficulty or "casual"
    )
    key = str(uuid5(NAMESPACE_URL, f"connect4:{session_uuid}:{expected_version}:{actor_id}"))
    try:
        outcome = submit_game_action(
            session_uuid=session_uuid, bot_actor_id=actor_id, action=action,
            state_version=expected_version, idempotency_key=key,
        )
    except (GameActionDenied, StaleGameState):
        return None
    broadcast_bot_action(outcome.response, request_id=key)
    return outcome


def broadcast_bot_action(response, *, request_id):
    """Use the game consumer's audience filtering for human and bot events."""

    session_uuid = response["session_uuid"]
    async_to_sync(get_channel_layer().group_send)(
        f"game_{session_uuid.replace('-', '')}",
        {"type": "game.event", "response": response, "request_id": request_id},
    )
