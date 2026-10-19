"""Allowlisted role projection for public and completed views."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def public_players(
    players: Sequence[Mapping[str, object]], *, reveal_roles: bool = False
) -> list[dict[str, object]]:
    """Copy only public actor fields, optionally revealing completed roles."""

    if type(reveal_roles) is not bool:
        raise ValueError("reveal_roles must be a Boolean")
    if isinstance(players, (str, bytes)) or not isinstance(players, Sequence):
        raise ValueError("players must be a sequence")
    visible = []
    for player in players:
        if not isinstance(player, Mapping) or any(
            field not in player for field in ("actor_id", "seat", "alive")
        ) or (reveal_roles and "role" not in player):
            raise ValueError("player is missing required public fields")
        item = {field: player[field] for field in ("actor_id", "seat", "alive")}
        if reveal_roles:
            item["role"] = player["role"]
        visible.append(item)
    return visible
