import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
README = ROOT / "README.md"

EXPECTED_APP_ENV = {
    "KSA_DEBUG",
    "KSA_SECRET_KEY",
    "KSA_ALLOWED_HOSTS",
    "KSA_DATABASE_ENGINE",
    "KSA_DB_NAME",
    "KSA_DB_USER",
    "KSA_DB_PASSWORD",
    "KSA_DB_HOST",
    "KSA_DB_PORT",
    "KSA_REDIS_URL",
    "KSA_CHANNEL_PREFIX",
    "KSA_CELERY_BROKER_URL",
    "KSA_CELERY_RESULT_BACKEND",
    "KSA_CELERY_TASK_DEFAULT_QUEUE",
    "KSA_CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP",
    "KSA_GOOGLE_OAUTH_CLIENT_ID",
    "KSA_GOOGLE_OAUTH_CLIENT_SECRET",
}


def compose_config(tmp_path):
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("KSA_"):
            env.pop(name)
    env["DOCKER_CONFIG"] = str(tmp_path / "docker-config")

    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def parse_env_example():
    values = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        values[key] = value
    return values


def test_docker_compose_config_succeeds_and_defines_required_services(tmp_path):
    config = compose_config(tmp_path)

    assert set(config["services"]) == {"web", "db", "redis", "worker"}
    assert config["services"]["web"]["command"] == [
        "daphne",
        "-b",
        "0.0.0.0",
        "-p",
        "8000",
        "ksa_games.asgi:application",
    ]
    assert config["services"]["worker"]["command"] == [
        "celery",
        "-A",
        "ksa_games",
        "worker",
        "--loglevel=info",
    ]
    assert config["services"]["db"]["image"] == "postgres:16-alpine"
    assert config["services"]["redis"]["image"] == "redis:7-alpine"


def test_compose_app_services_use_documented_environment_variables(tmp_path):
    config = compose_config(tmp_path)
    env_example = parse_env_example()

    for service_name in ("web", "worker"):
        service_env = config["services"][service_name]["environment"]
        assert EXPECTED_APP_ENV <= set(service_env)
        assert EXPECTED_APP_ENV <= set(env_example)
        assert service_env["KSA_DATABASE_ENGINE"] == "postgresql"
        assert service_env["KSA_DB_HOST"] == "db"
        assert service_env["KSA_REDIS_URL"] == "redis://redis:6379/0"


def test_database_service_uses_documented_ksa_environment_interpolation():
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "POSTGRES_DB: ${KSA_DB_NAME:-ksa_games}" in compose_text
    assert "POSTGRES_USER: ${KSA_DB_USER:-ksa_games}" in compose_text
    assert "POSTGRES_PASSWORD: ${KSA_DB_PASSWORD:-ksa_games_dev_password}" in compose_text


def test_postgres_data_is_preserved_in_named_volume(tmp_path):
    config = compose_config(tmp_path)
    db_volumes = config["services"]["db"]["volumes"]

    assert "postgres_data" in config["volumes"]
    assert {
        "type": "volume",
        "source": "postgres_data",
        "target": "/var/lib/postgresql/data",
        "volume": {},
    } in db_volumes


def test_only_web_publishes_host_ports(tmp_path):
    config = compose_config(tmp_path)

    assert config["services"]["web"]["ports"][0]["published"] == "8000"
    for service_name in ("db", "redis", "worker"):
        assert "ports" not in config["services"][service_name]


def test_env_example_contains_only_local_placeholder_secrets():
    env_example = parse_env_example()

    assert env_example["KSA_SECRET_KEY"].startswith("django-insecure-compose-local-dev")
    assert env_example["KSA_DB_PASSWORD"] == "ksa_games_dev_password"
    assert env_example["KSA_GOOGLE_OAUTH_CLIENT_ID"] == ""
    assert env_example["KSA_GOOGLE_OAUTH_CLIENT_SECRET"] == ""


def test_readme_documents_compose_django_check_workflow():
    readme = README.read_text(encoding="utf-8")

    assert "docker compose config" in readme
    assert "docker compose run --rm web python manage.py check" in readme
    assert "docker compose run --rm web python manage.py makemigrations --check --dry-run" in readme
    assert "docker compose run --rm web pytest" in readme
