"""Celery application entrypoint for KSA Games."""
from __future__ import annotations

import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.settings")

app = Celery("ksa_games")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.imports = ("ksa_games.tasks", "play.tasks")

celery_app = app
