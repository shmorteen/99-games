"""WSGI config for the KSA Games project."""
import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.settings")

application = get_wsgi_application()
