"""Database configuration helpers for KSA Games settings."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


POSTGRES_ENGINE = "django.db.backends.postgresql"
SQLITE_ENGINE = "django.db.backends.sqlite3"


def build_database_config(base_dir: Path) -> dict[str, object]:
    """Build Django's default database config from environment variables."""
    database_url = os.environ.get("KSA_DATABASE_URL")
    if database_url:
        return database_config_from_url(database_url, base_dir)

    database_engine = os.environ.get("KSA_DATABASE_ENGINE", "sqlite").strip().lower()
    if database_engine in {"postgres", "postgresql"}:
        return postgres_config_from_env()
    if database_engine == "sqlite":
        return sqlite_config_from_env(base_dir)

    raise ImproperlyConfigured(
        "KSA_DATABASE_ENGINE must be either 'postgresql' or 'sqlite'."
    )


def database_config_from_url(database_url: str, base_dir: Path) -> dict[str, object]:
    """Build a database config from KSA_DATABASE_URL."""
    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()

    if scheme in {"postgres", "postgresql"}:
        database_name = parsed.path.lstrip("/")
        if not database_name:
            raise ImproperlyConfigured("KSA_DATABASE_URL must include a database name.")

        try:
            port = parsed.port
        except ValueError as exc:
            raise ImproperlyConfigured(
                "KSA_DATABASE_URL must include a valid port when a port is set."
            ) from exc

        config: dict[str, object] = {
            "ENGINE": POSTGRES_ENGINE,
            "NAME": unquote(database_name),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(port or ""),
        }
        options = postgres_options_from_query(parsed.query)
        if options:
            config["OPTIONS"] = options
        return config

    if scheme == "sqlite":
        return sqlite_config_from_url(parsed.path, base_dir)

    raise ImproperlyConfigured(
        "KSA_DATABASE_URL must use postgresql://, postgres://, or sqlite://."
    )


def postgres_config_from_env() -> dict[str, object]:
    """Build PostgreSQL config from discrete KSA_DB_* environment variables."""
    database_name = os.environ.get("KSA_DB_NAME", "").strip()
    if not database_name:
        raise ImproperlyConfigured(
            "KSA_DB_NAME must be set when KSA_DATABASE_ENGINE=postgresql."
        )

    config: dict[str, object] = {
        "ENGINE": POSTGRES_ENGINE,
        "NAME": database_name,
        "USER": os.environ.get("KSA_DB_USER", "postgres"),
        "PASSWORD": os.environ.get("KSA_DB_PASSWORD", ""),
        "HOST": os.environ.get("KSA_DB_HOST", "localhost"),
        "PORT": os.environ.get("KSA_DB_PORT", "5432"),
    }

    conn_max_age = os.environ.get("KSA_DB_CONN_MAX_AGE")
    if conn_max_age is not None:
        config["CONN_MAX_AGE"] = parse_non_negative_int(
            "KSA_DB_CONN_MAX_AGE", conn_max_age
        )

    sslmode = os.environ.get("KSA_DB_SSLMODE")
    if sslmode:
        config["OPTIONS"] = {"sslmode": sslmode}

    return config


def sqlite_config_from_env(base_dir: Path) -> dict[str, object]:
    """Build local/test SQLite config."""
    sqlite_path = os.environ.get("KSA_SQLITE_PATH")
    return {
        "ENGINE": SQLITE_ENGINE,
        "NAME": sqlite_path or base_dir / "db.sqlite3",
    }


def sqlite_config_from_url(path: str, base_dir: Path) -> dict[str, object]:
    """Build SQLite config from a sqlite:// URL."""
    if not path:
        raise ImproperlyConfigured("sqlite:// URLs must include a database path.")

    if path == "/:memory:":
        database_name: str | Path = ":memory:"
    else:
        database_name = unquote(path)
        if not Path(database_name).is_absolute():
            database_name = base_dir / database_name

    return {
        "ENGINE": SQLITE_ENGINE,
        "NAME": database_name,
    }


def postgres_options_from_query(query: str) -> dict[str, str]:
    """Extract supported PostgreSQL options from a database URL query string."""
    query_params = parse_qs(query)
    options: dict[str, str] = {}
    sslmode = query_params.get("sslmode", [None])[0]
    if sslmode:
        options["sslmode"] = sslmode
    return options


def parse_non_negative_int(name: str, value: str) -> int:
    """Parse a non-negative integer environment value."""
    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a non-negative integer.") from exc

    if parsed_value < 0:
        raise ImproperlyConfigured(f"{name} must be a non-negative integer.")

    return parsed_value
