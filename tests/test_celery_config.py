import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

from ksa_games.celery_config import (
    DEFAULT_CELERY_BROKER_URL,
    DEFAULT_CELERY_RESULT_BACKEND,
    DEFAULT_CELERY_TASK_DEFAULT_QUEUE,
    build_celery_config,
)


def test_default_celery_config_uses_redis(monkeypatch):
    monkeypatch.delenv("KSA_CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("KSA_CELERY_RESULT_BACKEND", raising=False)
    monkeypatch.delenv("KSA_CELERY_TASK_DEFAULT_QUEUE", raising=False)

    config = build_celery_config()

    assert config["CELERY_BROKER_URL"] == DEFAULT_CELERY_BROKER_URL
    assert config["CELERY_RESULT_BACKEND"] == DEFAULT_CELERY_RESULT_BACKEND
    assert config["CELERY_TASK_DEFAULT_QUEUE"] == DEFAULT_CELERY_TASK_DEFAULT_QUEUE
    assert config["CELERY_TASK_SERIALIZER"] == "json"
    assert config["CELERY_RESULT_SERIALIZER"] == "json"
    assert config["CELERY_ACCEPT_CONTENT"] == ["json"]


def test_celery_config_uses_environment_values(monkeypatch):
    monkeypatch.setenv("KSA_CELERY_BROKER_URL", "redis://cache.example.com:6379/4")
    monkeypatch.setenv("KSA_CELERY_RESULT_BACKEND", "redis://cache.example.com:6379/5")
    monkeypatch.setenv("KSA_CELERY_TASK_DEFAULT_QUEUE", "ksa-worker")
    monkeypatch.setenv("KSA_CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP", "off")

    config = build_celery_config()

    assert config["CELERY_BROKER_URL"] == "redis://cache.example.com:6379/4"
    assert config["CELERY_RESULT_BACKEND"] == "redis://cache.example.com:6379/5"
    assert config["CELERY_TASK_DEFAULT_QUEUE"] == "ksa-worker"
    assert config["CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP"] is False


def test_blank_broker_url_is_rejected(monkeypatch):
    monkeypatch.setenv("KSA_CELERY_BROKER_URL", " ")

    with pytest.raises(ImproperlyConfigured, match="KSA_CELERY_BROKER_URL"):
        build_celery_config()


def test_invalid_retry_flag_is_rejected(monkeypatch):
    monkeypatch.setenv("KSA_CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP", "maybe")

    with pytest.raises(ImproperlyConfigured, match="KSA_CELERY_BROKER"):
        build_celery_config()


def test_celery_app_imports_django_settings():
    celery_module = importlib.import_module("ksa_games.celery")

    assert celery_module.celery_app.main == "ksa_games"
    assert celery_module.celery_app.conf.broker_url == DEFAULT_CELERY_BROKER_URL
    assert celery_module.celery_app.conf.result_backend == DEFAULT_CELERY_RESULT_BACKEND


def test_smoke_task_is_import_safe_and_registered():
    celery_module = importlib.import_module("ksa_games.celery")
    importlib.import_module("ksa_games.tasks")
    celery_module.celery_app.loader.import_default_modules()

    task = celery_module.celery_app.tasks["ksa_games.smoke"]

    assert task.run() == "ok"


def test_no_out_of_scope_celery_tasks_are_registered():
    celery_module = importlib.import_module("ksa_games.celery")
    importlib.import_module("ksa_games.tasks")
    celery_module.celery_app.loader.import_default_modules()

    project_tasks = sorted(
        task_name
        for task_name in celery_module.celery_app.tasks
        if task_name.startswith("ksa_games.")
    )

    assert project_tasks == ["ksa_games.smoke"]
