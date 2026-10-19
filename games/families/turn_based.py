"""Seat-order rotation for turn-based games."""

from __future__ import annotations

from collections.abc import Sequence


def actor_for_turn(actor_ids: Sequence[str], action_count: int) -> str:
    """Return the next seated actor after action_count accepted turns."""

    if isinstance(actor_ids, (str, bytes)) or not isinstance(actor_ids, Sequence) or not actor_ids:
        raise ValueError("actor_ids must be a nonempty sequence")
    if any(type(actor) is not str or not actor for actor in actor_ids):
        raise ValueError("actor_ids must contain nonempty strings")
    if type(action_count) is not int or action_count < 0:
        raise ValueError("action_count must be a nonnegative integer")
    return actor_ids[action_count % len(actor_ids)]
