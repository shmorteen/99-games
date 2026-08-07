"""KSA Games Django project package."""

from .celery import celery_app


__all__ = ("celery_app",)
