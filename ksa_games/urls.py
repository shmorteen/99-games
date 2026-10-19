"""URL configuration for the KSA Games project shell."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.decorators.http import require_GET

from .health import liveness, readiness
from play.operations import game_operations_health


@require_GET
def project_shell(request):
    """Return a minimal public response proving URL routing is wired."""
    return JsonResponse({"service": "KSA Games", "status": "project-shell"})


urlpatterns = [
    path("admin/game-health/", game_operations_health, name="game-operations-health"),
    path("admin/", admin.site.urls),
    path("", project_shell, name="project-shell"),
    path("accounts/", include("allauth.urls")),
    path("games/", include("games.urls")),
    path("lobbies/", include("lobbies.urls")),
    path("health/live/", liveness, name="health-live"),
    path("health/ready/", readiness, name="health-ready"),
]
