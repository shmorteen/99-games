from __future__ import annotations

from contextlib import contextmanager, nullcontext

from django.conf import settings
import redis


class LobbyStartLockUnavailable(RuntimeError):
    """Raised when the lobby start lock cannot be acquired."""


@contextmanager
def acquire_lobby_start_lock(lobby_public_id: str):
    backend = getattr(settings, "KSA_LOBBY_START_LOCK_BACKEND", "redis")
    if backend == "noop":
        with nullcontext():
            yield
        return
    if backend != "redis":
        raise LobbyStartLockUnavailable("Unsupported lobby start lock backend.")

    redis_url = getattr(
        settings,
        "KSA_LOBBY_START_LOCK_REDIS_URL",
        getattr(settings, "KSA_REDIS_URL", "redis://localhost:6379/0"),
    )
    prefix = getattr(settings, "KSA_LOBBY_START_LOCK_PREFIX", "ksa-games")
    timeout = getattr(settings, "KSA_LOBBY_START_LOCK_TIMEOUT_SECONDS", 10)
    blocking_timeout = getattr(
        settings,
        "KSA_LOBBY_START_LOCK_BLOCKING_TIMEOUT_SECONDS",
        5,
    )
    client = redis.Redis.from_url(redis_url)
    lock = client.lock(
        f"{prefix}:lobby-start:{lobby_public_id}",
        timeout=timeout,
        blocking_timeout=blocking_timeout,
    )
    if not lock.acquire(blocking=True):
        raise LobbyStartLockUnavailable("Could not acquire lobby start lock.")
    try:
        yield
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


__all__ = ["LobbyStartLockUnavailable", "acquire_lobby_start_lock"]
