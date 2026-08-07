from __future__ import annotations

from django.core.checks import Error, Tags, register
from django.db import DatabaseError, connections

from .registry import (
    GameEngineRegistry,
    game_engine_registry,
    is_valid_engine_version,
)


REGISTRY_ISSUE_CHECK_IDS = {
    "duplicate_game_engine": "games.E001",
    "invalid_game_engine_version": "games.E003",
    "invalid_game_engine_key": "games.E004",
    "invalid_game_engine": "games.E005",
    "engine_module_import_failed": "games.E006",
}
MISSING_ENGINE_CHECK_ID = "games.E002"
INVALID_VERSION_CHECK_ID = "games.E003"


@register(Tags.models)
def check_game_engine_registry(app_configs, **kwargs):
    return build_game_engine_check_messages(
        game_engine_registry,
        databases=kwargs.get("databases"),
    )


def build_game_engine_check_messages(
    registry: GameEngineRegistry,
    *,
    databases: list[str] | tuple[str, ...] | None = None,
):
    messages = []

    for issue in registry.registration_issues:
        messages.append(
            Error(
                issue.message,
                id=REGISTRY_ISSUE_CHECK_IDS.get(issue.code, "games.E099"),
            )
        )

    if not _database_checks_enabled(databases) or not _game_definition_table_exists():
        return messages

    from .models import GameDefinition

    playable_games = GameDefinition.objects.filter(is_playable=True).only(
        "slug",
        "name",
        "engine_key",
        "engine_version",
    )
    for game in playable_games:
        if not is_valid_engine_version(game.engine_version):
            messages.append(
                Error(
                    (
                        f"Playable game '{game.slug}' has invalid engine version "
                        f"'{game.engine_version}'."
                    ),
                    id=INVALID_VERSION_CHECK_ID,
                    obj=game,
                )
            )
            continue

        if not registry.exists(game.engine_key, game.engine_version):
            messages.append(
                Error(
                    (
                        f"Playable game '{game.slug}' references missing engine "
                        f"'{game.engine_key}' version '{game.engine_version}'."
                    ),
                    id=MISSING_ENGINE_CHECK_ID,
                    obj=game,
                )
            )

    return messages


def _database_checks_enabled(databases: list[str] | tuple[str, ...] | None) -> bool:
    return bool(databases and "default" in databases)


def _game_definition_table_exists() -> bool:
    try:
        return "games_gamedefinition" in connections["default"].introspection.table_names()
    except DatabaseError:
        return False


__all__ = [
    "build_game_engine_check_messages",
    "check_game_engine_registry",
]
