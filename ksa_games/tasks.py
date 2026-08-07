"""Import-safe Celery smoke tasks."""
from celery import shared_task


@shared_task(name="ksa_games.smoke")
def celery_smoke() -> str:
    """Return a static value so worker task discovery can be validated."""
    return "ok"
