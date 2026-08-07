"""ASGI config for the KSA Games project."""
import os

from django.core.asgi import get_asgi_application

from .routing import build_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.settings")

django_asgi_application = get_asgi_application()
application = build_asgi_application(django_asgi_application)
