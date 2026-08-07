from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from ksa_games.database import (
    POSTGRES_ENGINE,
    SQLITE_ENGINE,
    build_database_config,
)


def test_default_database_config_uses_local_sqlite(monkeypatch):
    monkeypatch.delenv("KSA_DATABASE_URL", raising=False)
    monkeypatch.delenv("KSA_DATABASE_ENGINE", raising=False)
    monkeypatch.delenv("KSA_SQLITE_PATH", raising=False)

    config = build_database_config(Path("/app"))

    assert config == {
        "ENGINE": SQLITE_ENGINE,
        "NAME": Path("/app") / "db.sqlite3",
    }


def test_sqlite_path_can_be_overridden(monkeypatch):
    monkeypatch.delenv("KSA_DATABASE_URL", raising=False)
    monkeypatch.setenv("KSA_DATABASE_ENGINE", "sqlite")
    monkeypatch.setenv("KSA_SQLITE_PATH", "C:/tmp/ksa.sqlite3")

    config = build_database_config(Path("/app"))

    assert config == {
        "ENGINE": SQLITE_ENGINE,
        "NAME": "C:/tmp/ksa.sqlite3",
    }


def test_postgres_config_uses_discrete_environment_values(monkeypatch):
    monkeypatch.delenv("KSA_DATABASE_URL", raising=False)
    monkeypatch.setenv("KSA_DATABASE_ENGINE", "postgresql")
    monkeypatch.setenv("KSA_DB_NAME", "ksa_games")
    monkeypatch.setenv("KSA_DB_USER", "ksa_user")
    monkeypatch.setenv("KSA_DB_PASSWORD", "not-a-real-secret")
    monkeypatch.setenv("KSA_DB_HOST", "db")
    monkeypatch.setenv("KSA_DB_PORT", "5433")
    monkeypatch.setenv("KSA_DB_CONN_MAX_AGE", "60")
    monkeypatch.setenv("KSA_DB_SSLMODE", "require")

    config = build_database_config(Path("/app"))

    assert config == {
        "ENGINE": POSTGRES_ENGINE,
        "NAME": "ksa_games",
        "USER": "ksa_user",
        "PASSWORD": "not-a-real-secret",
        "HOST": "db",
        "PORT": "5433",
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": "require"},
    }


def test_postgres_config_requires_database_name(monkeypatch):
    monkeypatch.delenv("KSA_DATABASE_URL", raising=False)
    monkeypatch.setenv("KSA_DATABASE_ENGINE", "postgresql")
    monkeypatch.delenv("KSA_DB_NAME", raising=False)

    with pytest.raises(ImproperlyConfigured, match="KSA_DB_NAME must be set"):
        build_database_config(Path("/app"))


def test_postgres_url_config_is_supported(monkeypatch):
    monkeypatch.setenv(
        "KSA_DATABASE_URL",
        "postgresql://ksa_user:secret%21@db.example.com:5432/ksa_games"
        "?sslmode=require",
    )

    config = build_database_config(Path("/app"))

    assert config == {
        "ENGINE": POSTGRES_ENGINE,
        "NAME": "ksa_games",
        "USER": "ksa_user",
        "PASSWORD": "secret!",
        "HOST": "db.example.com",
        "PORT": "5432",
        "OPTIONS": {"sslmode": "require"},
    }


def test_database_url_rejects_unsupported_scheme(monkeypatch):
    monkeypatch.setenv("KSA_DATABASE_URL", "mysql://example/db")

    with pytest.raises(ImproperlyConfigured, match="KSA_DATABASE_URL must use"):
        build_database_config(Path("/app"))


def test_invalid_database_engine_is_rejected(monkeypatch):
    monkeypatch.delenv("KSA_DATABASE_URL", raising=False)
    monkeypatch.setenv("KSA_DATABASE_ENGINE", "memory")

    with pytest.raises(ImproperlyConfigured, match="KSA_DATABASE_ENGINE"):
        build_database_config(Path("/app"))


def test_conn_max_age_must_be_non_negative(monkeypatch):
    monkeypatch.delenv("KSA_DATABASE_URL", raising=False)
    monkeypatch.setenv("KSA_DATABASE_ENGINE", "postgresql")
    monkeypatch.setenv("KSA_DB_NAME", "ksa_games")
    monkeypatch.setenv("KSA_DB_CONN_MAX_AGE", "-1")

    with pytest.raises(ImproperlyConfigured, match="KSA_DB_CONN_MAX_AGE"):
        build_database_config(Path("/app"))
