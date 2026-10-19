"""Private-ballot tally patterns; callers decide eligibility and resolution."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


def plurality_target(targets: Iterable[str]) -> str | None:
    """Return a unique plurality target; empty and tied ballots return None."""

    ballots = tuple(targets)
    if any(type(target) is not str or not target for target in ballots):
        raise ValueError("ballot targets must be nonempty strings")
    counts = Counter(ballots)
    if not counts:
        return None
    maximum = max(counts.values())
    leaders = [target for target, count in counts.items() if count == maximum]
    return leaders[0] if len(leaders) == 1 else None
