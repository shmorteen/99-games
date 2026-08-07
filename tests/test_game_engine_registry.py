import sys
import types
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.core.checks import Tags, run_checks
from django.test import override_settings

from games.engine import BaseGameEngine, GameTransition
from games.models import GameCategory, GameDefinition
from games.registry import (
    DuplicateGameEngine,
    GameEngineRegistry,
    InvalidGameEngine,
    InvalidGameEngineVersion,
    UnknownGameEngine,
    configured_engine_modules,
    register_available_game_engines,
)


class RegistryTestEngine(BaseGameEngine):
    def validate_config(self, config):
        return None

    def create_initial_state(self, config, actors):
        return {"actors": [actor["actor_id"] for actor in actors], "complete": False}

    def get_public_state(self, state):
        return {"complete": state["complete"]}

    def get_spectator_state(self, state):
        return {"complete": state["complete"]}

    def get_private_state(self, state, actor_id):
        return {"actor_id": actor_id}

    def legal_actions(self, state, actor_id):
        return [{"type": "noop"}]

    def apply_action(
        self,
        state,
        actor_id,
        action,
        *,
        idempotency_key=None,
        state_version=None,
    ):
        return GameTransition(state=dict(state), events=[])

    def handle_timeout(self, state, actor_id=None):
        return GameTransition(state=dict(state), events=[])

    def bot_action(self, state, actor_id, *, difficulty=None):
        return {"type": "noop"}

    def is_complete(self, state):
        return bool(state["complete"])

    def build_results(self, state):
        return {"complete": self.is_complete(state)}


class RegistryTestEngineV2(RegistryTestEngine):
    pass


def category(slug="board-games"):
    return GameCategory.objects.get(slug=slug)


def create_definition(**overrides):
    values = {
        "category": category(),
        "name": "Registry Test Game",
        "slug": "registry-test-game",
        "short_description": "A registry test game.",
        "engine_key": "",
        "engine_version": "",
        "minimum_players": 1,
        "maximum_players": 2,
        "is_playable": False,
        "is_active": True,
    }
    values.update(overrides)
    return GameDefinition(**values)


def game_check_messages():
    return [
        message
        for message in run_checks(tags=[Tags.models], databases=["default"])
        if message.id.startswith("games.")
    ]


def test_registry_registers_and_retrieves_engine_class():
    registry = GameEngineRegistry()

    registered = registry.register("test-engine", "1.0", RegistryTestEngine)

    assert registered is RegistryTestEngine
    assert registry.exists("test-engine", "1.0") is True
    assert registry.get("test-engine", "1.0") is RegistryTestEngine
    assert isinstance(registry.create("test-engine", "1.0"), RegistryTestEngine)
    assert registry.registered_engines()[0].key == "test-engine"


def test_registry_decorator_registers_engine_class():
    registry = GameEngineRegistry()

    @registry.register("decorated-engine", "1.0")
    class DecoratedEngine(RegistryTestEngine):
        pass

    assert registry.get("decorated-engine", "1.0") is DecoratedEngine


def test_registry_rejects_duplicate_engine_key_and_version():
    registry = GameEngineRegistry()
    registry.register("duplicate-engine", "1.0", RegistryTestEngine)

    with pytest.raises(DuplicateGameEngine) as error:
        registry.register("duplicate-engine", "1.0", RegistryTestEngineV2)

    assert "already registered" in str(error.value)
    assert registry.registration_issues[0].code == "duplicate_game_engine"


def test_registry_returns_clear_unknown_engine_error():
    registry = GameEngineRegistry()

    with pytest.raises(UnknownGameEngine) as error:
        registry.get("missing-engine", "1.0")

    assert "No game engine is registered" in str(error.value)
    assert error.value.key == "missing-engine"
    assert error.value.version == "1.0"


def test_registry_keeps_versions_distinct_for_same_engine_key():
    registry = GameEngineRegistry()
    registry.register("versioned-engine", "1.0", RegistryTestEngine)
    registry.register("versioned-engine", "2.0", RegistryTestEngineV2)

    assert registry.get("versioned-engine", "1.0") is RegistryTestEngine
    assert registry.get("versioned-engine", "2.0") is RegistryTestEngineV2


def test_registry_rejects_invalid_engine_classes_and_versions():
    class AbstractEngine(BaseGameEngine):
        pass

    registry = GameEngineRegistry()

    with pytest.raises(InvalidGameEngine):
        registry.register("bad-class", "1.0", object)
    with pytest.raises(InvalidGameEngine):
        registry.register("abstract-class", "1.0", AbstractEngine)
    with pytest.raises(InvalidGameEngineVersion):
        registry.register("bad-version", "one version", RegistryTestEngine)

    assert {issue.code for issue in registry.registration_issues} == {
        "invalid_game_engine",
        "invalid_game_engine_version",
    }


def test_registry_validates_game_definition_objects():
    registry = GameEngineRegistry()
    registry.register("definition-engine", "1.0", RegistryTestEngine)
    valid_definition = SimpleNamespace(
        is_playable=True,
        engine_key="definition-engine",
        engine_version="1.0",
    )
    missing_definition = SimpleNamespace(
        is_playable=True,
        engine_key="definition-engine",
        engine_version="2.0",
    )

    registry.validate_game_definition(valid_definition)
    with pytest.raises(UnknownGameEngine):
        registry.validate_game_definition(missing_definition)


def test_startup_registration_imports_configured_engine_modules(monkeypatch):
    module_name = "tests.fake_ksa_engine_module"
    module = types.ModuleType(module_name)

    def register_engines(registry):
        registry.register("module-engine", "1.0", RegistryTestEngine)

    module.register_engines = register_engines
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = GameEngineRegistry()

    register_available_game_engines(registry=registry, modules=(module_name,))
    register_available_game_engines(registry=registry, modules=(module_name,))

    assert registry.exists("module-engine", "1.0") is True
    assert registry.registration_issues == ()


def test_configured_engine_modules_reads_django_setting():
    with override_settings(KSA_GAME_ENGINE_MODULES=("games.example_engines",)):
        assert configured_engine_modules() == ("games.example_engines",)


@pytest.mark.django_db
def test_game_definition_validation_uses_registry(monkeypatch):
    registry = GameEngineRegistry()
    registry.register("model-engine", "1.0", RegistryTestEngine)
    monkeypatch.setattr("games.models.game_engine_registry", registry)

    game = create_definition(
        name="Model Engine",
        slug="model-engine",
        engine_key="model-engine",
        engine_version="1.0",
        is_playable=True,
    )

    game.full_clean()


@pytest.mark.django_db
def test_game_definition_rejects_invalid_engine_version():
    game = create_definition(
        name="Invalid Version",
        slug="invalid-version",
        engine_key="invalid-version",
        engine_version="bad version",
        is_playable=True,
    )

    with pytest.raises(ValidationError) as error:
        game.full_clean()

    assert "engine_version" in error.value.message_dict


@pytest.mark.django_db
def test_django_system_check_reports_duplicate_engine_registration(monkeypatch):
    registry = GameEngineRegistry()
    registry.register("duplicate-system-check", "1.0", RegistryTestEngine)
    with pytest.raises(DuplicateGameEngine):
        registry.register("duplicate-system-check", "1.0", RegistryTestEngineV2)
    monkeypatch.setattr("games.checks.game_engine_registry", registry)

    messages = game_check_messages()

    assert any(message.id == "games.E001" for message in messages)


@pytest.mark.django_db
def test_django_system_check_reports_missing_engine_for_playable_game(monkeypatch):
    monkeypatch.setattr("games.checks.game_engine_registry", GameEngineRegistry())
    GameDefinition.objects.bulk_create(
        [
            create_definition(
                name="Missing Engine",
                slug="missing-engine-system-check",
                engine_key="missing-engine",
                engine_version="1.0",
                is_playable=True,
            )
        ]
    )

    messages = game_check_messages()

    assert any(
        message.id == "games.E002" and "missing-engine" in message.msg
        for message in messages
    )


@pytest.mark.django_db
def test_django_system_check_reports_invalid_engine_versions(monkeypatch):
    monkeypatch.setattr("games.checks.game_engine_registry", GameEngineRegistry())
    GameDefinition.objects.bulk_create(
        [
            create_definition(
                name="Invalid Engine Version",
                slug="invalid-engine-version-system-check",
                engine_key="bad-version",
                engine_version="bad version",
                is_playable=True,
            )
        ]
    )

    messages = game_check_messages()

    assert any(message.id == "games.E003" for message in messages)


@pytest.mark.django_db
def test_catalog_queries_do_not_mark_unregistered_games_playable():
    game = GameDefinition.objects.create(
        category=category(),
        name="Unregistered Catalog Game",
        slug="unregistered-catalog-game",
        short_description="Catalog only.",
        engine_key="unregistered-catalog-game",
        engine_version="1.0",
        minimum_players=1,
        maximum_players=2,
        is_playable=False,
        is_active=True,
    )

    catalog_game = GameDefinition.objects.public_catalog().get(pk=game.pk)

    assert catalog_game.is_playable is False
    assert game not in GameDefinition.objects.playable()
