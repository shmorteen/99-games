"""Read-only, public-metadata diagnostics for game operations."""

from datetime import timedelta

from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.utils import timezone
from django.views.decorators.http import require_GET

from ksa_games.health import OK, build_readiness_report

from .models import GameActionReceipt, GameSession, GameSessionStatus


def action_audit(session: GameSession) -> dict:
    """Summarize persisted version continuity without returning action payloads."""

    versions = list(
        GameActionReceipt.objects.filter(session=session)
        .values_list("response__state_version", flat=True)
    )
    valid_versions = all(type(version) is int for version in versions)
    contiguous = (
        valid_versions
        and len(versions) == session.state_version - 1
        and sorted(versions) == list(range(2, session.state_version + 1))
    )
    return {
        "session_uuid": str(session.public_id),
        "state_version": session.state_version,
        "receipt_count": len(versions),
        "versions_contiguous": contiguous,
    }


@require_GET
@staff_member_required
@permission_required("play.view_gamesession", raise_exception=True)
def game_operations_health(request):
    """Permission-gated realtime dependency and action throughput snapshot."""

    report = build_readiness_report()
    recent_cutoff = timezone.now() - timedelta(minutes=5)
    database_ready = report.checks["database"] == OK
    return JsonResponse(
        {
            "status": "ready" if report.is_ready else "not_ready",
            "checks": report.checks,
            "active_sessions": GameSession.objects.filter(
                status=GameSessionStatus.ACTIVE
            ).count() if database_ready else None,
            "actions_last_five_minutes": GameActionReceipt.objects.filter(
                created_at__gte=recent_cutoff
            ).count() if database_ready else None,
        },
        status=200 if report.is_ready else 503,
    )
