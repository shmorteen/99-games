"""Short-lived distributed lock for game actions."""

from contextlib import contextmanager, nullcontext

from django.conf import settings
import redis


class GameActionLockUnavailable(RuntimeError):
    pass


@contextmanager
def acquire_game_action_lock(session_uuid: str):
    backend = getattr(settings, "KSA_GAME_ACTION_LOCK_BACKEND", "redis")
    if backend == "noop":
        with nullcontext():
            yield
        return
    if backend != "redis":
        raise GameActionLockUnavailable("Unsupported game action lock backend.")

    client = redis.Redis.from_url(settings.KSA_GAME_ACTION_LOCK_REDIS_URL)
    lock = client.lock(
        f"ksa-games:game-action:{session_uuid}",
        timeout=10,
        blocking_timeout=5,
    )
    try:
        if not lock.acquire(blocking=True):
            raise GameActionLockUnavailable("Could not acquire game action lock.")
        try:
            yield
        finally:
            try:
                lock.release()
            except redis.exceptions.LockError:
                pass
    except redis.exceptions.RedisError as error:
        raise GameActionLockUnavailable("Game action lock is unavailable.") from error
