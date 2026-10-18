"""Background gameplay work."""

from celery import shared_task

from .bots import run_connect4_bot_turn
from .services import GameActionConflict


@shared_task(
    name="play.connect4_bot_turn", bind=True,
    autoretry_for=(GameActionConflict,), retry_backoff=True, max_retries=3,
)
def connect4_bot_turn(self, session_uuid, expected_version):
    """A stale or completed turn is a no-op; lock contention retries."""

    outcome = run_connect4_bot_turn(session_uuid, expected_version=expected_version)
    return outcome.response["state_version"] if outcome else None
