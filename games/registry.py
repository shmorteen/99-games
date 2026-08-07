from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
from inspect import isabstract
import re
from typing import Any

from django.conf import settings

from .engine import BaseGameEngine


ENGINE_KEY_MAX_LENGTH = 120
ENGINE_VERSION_MAX_LENGTH = 32
ENGINE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*(?:[.][a-z0-9][a-z0-9_-]*)*$")
ENGINE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


@dataclass(frozen=True, order=True)
class EngineRegistration:
    key: str
    version: str
    engine_class: type[BaseGameEngine]


@dataclass(frozen=True)
class EngineRegistryIssue:
    code: str
    message: str
    key: str | None = None
    version: str | None = None
    module: str | None = None


class GameEngineRegistryError(Exception):
    code = "game_engine_registry_error"

    def __init__(
        self,
        message: str,
        *,
        key: str | None = None,
        version: str | None = None,
    ) -> None:
        self.message = message
        self.key = key
        self.version = version
        super().__init__(message)


class DuplicateGameEngine(GameEngineRegistryError):
    code = "duplicate_game_engine"


class UnknownGameEngine(GameEngineRegistryError):
    code = "unknown_game_engine"


class InvalidGameEngine(GameEngineRegistryError):
    code = "invalid_game_engine"


class InvalidGameEngineKey(GameEngineRegistryError):
    code = "invalid_game_engine_key"


class InvalidGameEngineVersion(GameEngineRegistryError):
    code = "invalid_game_engine_version"


def normalize_engine_key(engine_key: str) -> str:
    normalized = str(engine_key or "").strip()
    if (
        not normalized
        or len(normalized) > ENGINE_KEY_MAX_LENGTH
        or not ENGINE_KEY_PATTERN.fullmatch(normalized)
    ):
        raise InvalidGameEngineKey(
            "Engine key must be lowercase letters, numbers, underscores, "
            "hyphens, or dotted segments.",
            key=normalized,
        )
    return normalized


def normalize_engine_version(engine_version: str) -> str:
    normalized = str(engine_version or "").strip()
    if (
        not normalized
        or len(normalized) > ENGINE_VERSION_MAX_LENGTH
        or not ENGINE_VERSION_PATTERN.fullmatch(normalized)
    ):
        raise InvalidGameEngineVersion(
            "Engine version must be non-empty and contain only letters, "
            "numbers, dots, underscores, plus signs, or hyphens.",
            version=normalized,
        )
    return normalized


def is_valid_engine_version(engine_version: str) -> bool:
    try:
        normalize_engine_version(engine_version)
    except InvalidGameEngineVersion:
        return False
    return True


class GameEngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[tuple[str, str], type[BaseGameEngine]] = {}
        self._issues: list[EngineRegistryIssue] = []
        self._loaded_modules: set[str] = set()

    def register(
        self,
        engine_key: str,
        engine_version: str,
        engine_class: type[BaseGameEngine] | None = None,
    ):
        if engine_class is None:
            def decorator(cls: type[BaseGameEngine]) -> type[BaseGameEngine]:
                self.register(engine_key, engine_version, cls)
                return cls

            return decorator

        key, version = self._normalize_key_version(
            engine_key,
            engine_version,
            record_errors=True,
        )
        self._validate_engine_class(engine_class, key=key, version=version)

        registration_key = (key, version)
        if registration_key in self._engines:
            error = DuplicateGameEngine(
                f"Game engine '{key}' version '{version}' is already registered.",
                key=key,
                version=version,
            )
            self._record_error(error)
            raise error

        self._engines[registration_key] = engine_class
        return engine_class

    def get(self, engine_key: str, engine_version: str) -> type[BaseGameEngine]:
        key, version = self._normalize_key_version(engine_key, engine_version)
        try:
            return self._engines[(key, version)]
        except KeyError as error:
            raise UnknownGameEngine(
                f"No game engine is registered for key '{key}' version '{version}'.",
                key=key,
                version=version,
            ) from error

    def create(self, engine_key: str, engine_version: str) -> BaseGameEngine:
        return self.get(engine_key, engine_version)()

    def exists(self, engine_key: str, engine_version: str) -> bool:
        try:
            key, version = self._normalize_key_version(engine_key, engine_version)
        except (InvalidGameEngineKey, InvalidGameEngineVersion):
            return False
        return (key, version) in self._engines

    def registered_engines(self) -> tuple[EngineRegistration, ...]:
        return tuple(
            EngineRegistration(key, version, engine_class)
            for (key, version), engine_class in sorted(self._engines.items())
        )

    def validate_game_definition(self, game_definition: Any) -> None:
        if not getattr(game_definition, "is_playable", False):
            return
        self.get(
            getattr(game_definition, "engine_key", ""),
            getattr(game_definition, "engine_version", ""),
        )

    @property
    def registration_issues(self) -> tuple[EngineRegistryIssue, ...]:
        return tuple(self._issues)

    def record_issue(
        self,
        code: str,
        message: str,
        *,
        key: str | None = None,
        version: str | None = None,
        module: str | None = None,
    ) -> None:
        self._issues.append(
            EngineRegistryIssue(
                code=code,
                message=message,
                key=key,
                version=version,
                module=module,
            )
        )

    def module_loaded(self, module_path: str) -> bool:
        return module_path in self._loaded_modules

    def mark_module_loaded(self, module_path: str) -> None:
        self._loaded_modules.add(module_path)

    def _normalize_key_version(
        self,
        engine_key: str,
        engine_version: str,
        *,
        record_errors: bool = False,
    ) -> tuple[str, str]:
        try:
            key = normalize_engine_key(engine_key)
        except InvalidGameEngineKey as error:
            if record_errors:
                self._record_error(error)
            raise

        try:
            version = normalize_engine_version(engine_version)
        except InvalidGameEngineVersion as error:
            if record_errors:
                self._record_error(
                    InvalidGameEngineVersion(
                        error.message,
                        key=key,
                        version=error.version,
                    )
                )
            raise

        return key, version

    def _validate_engine_class(
        self,
        engine_class: type[BaseGameEngine],
        *,
        key: str,
        version: str,
    ) -> None:
        if (
            not isinstance(engine_class, type)
            or engine_class is BaseGameEngine
            or not issubclass(engine_class, BaseGameEngine)
            or isabstract(engine_class)
        ):
            error = InvalidGameEngine(
                "Registered game engines must be concrete BaseGameEngine subclasses.",
                key=key,
                version=version,
            )
            self._record_error(error)
            raise error

    def _record_error(self, error: GameEngineRegistryError) -> None:
        self.record_issue(
            error.code,
            error.message,
            key=error.key,
            version=error.version,
        )


game_engine_registry = GameEngineRegistry()


def configured_engine_modules(modules: Iterable[str] | None = None) -> tuple[str, ...]:
    if modules is not None:
        return tuple(modules)
    return tuple(getattr(settings, "KSA_GAME_ENGINE_MODULES", ()))


def register_available_game_engines(
    *,
    registry: GameEngineRegistry = game_engine_registry,
    modules: Iterable[str] | None = None,
) -> None:
    for module_path in configured_engine_modules(modules):
        if registry.module_loaded(module_path):
            continue

        try:
            module = import_module(module_path)
            register_hook = getattr(module, "register_engines", None)
            if callable(register_hook):
                register_hook(registry)
        except GameEngineRegistryError as error:
            matching_issue = any(
                issue.code == error.code
                and issue.message == error.message
                and issue.key == error.key
                and issue.version == error.version
                for issue in registry.registration_issues
            )
            if not matching_issue:
                registry.record_issue(
                    error.code,
                    error.message,
                    key=error.key,
                    version=error.version,
                    module=module_path,
                )
        except Exception as error:
            registry.record_issue(
                "engine_module_import_failed",
                f"Could not load game engine module '{module_path}': {error}",
                module=module_path,
            )
        else:
            registry.mark_module_loaded(module_path)


__all__ = [
    "DuplicateGameEngine",
    "EngineRegistration",
    "EngineRegistryIssue",
    "GameEngineRegistry",
    "GameEngineRegistryError",
    "InvalidGameEngine",
    "InvalidGameEngineKey",
    "InvalidGameEngineVersion",
    "UnknownGameEngine",
    "configured_engine_modules",
    "game_engine_registry",
    "is_valid_engine_version",
    "normalize_engine_key",
    "normalize_engine_version",
    "register_available_game_engines",
]
