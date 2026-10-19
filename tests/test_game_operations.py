"""KSA-035 staff diagnostics stay read-only and audience-safe."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
import pytest

from ksa_games.health import ReadinessReport, UNAVAILABLE
from play.models import GameActionReceipt
from tests.test_connect4_replay import completed_session


pytestmark = pytest.mark.django_db(transaction=True)


def operator(*, permitted=True):
    user = get_user_model().objects.create_user(
        username="game-operator" if permitted else "unpermitted-staff",
        email="operator@example.com" if permitted else "staff@example.com",
        password="StrongPass123!", is_staff=True,
    )
    if permitted:
        user.user_permissions.add(Permission.objects.get(codename="view_gamesession"))
        user.user_permissions.add(Permission.objects.get(codename="view_gameactionreceipt"))
    return user


def test_staff_inspection_replays_validated_public_frames(client):
    session, _, _, _ = completed_session()
    client.force_login(operator())

    response = client.get(reverse("admin:play_gamesession_inspect", args=[session.pk]))

    assert response.status_code == 200
    report = response.json()
    assert report["audit"] == {
        "session_uuid": str(session.public_id),
        "state_version": 8,
        "receipt_count": 7,
        "versions_contiguous": True,
    }
    assert len(report["replay"]["frames"]) == 8
    assert report["replay"]["result"]["outcome"] == "win"
    assert "request_hash" not in response.content.decode()
    assert "private_state" not in response.content.decode()


def test_staff_inspection_rejects_tampered_replay_without_partial_frames(client):
    session, _, _, _ = completed_session()
    receipt = GameActionReceipt.objects.filter(session=session).first()
    GameActionReceipt.objects.filter(pk=receipt.pk).update(request_hash="0" * 64)
    client.force_login(operator())

    response = client.get(reverse("admin:play_gamesession_inspect", args=[session.pk]))

    assert response.status_code == 200
    assert response.json()["audit"]["versions_contiguous"] is True
    assert response.json()["replay"] == {"status": "unavailable"}


def test_missing_receipt_is_reported_and_no_partial_replay_is_returned(client):
    session, _, _, _ = completed_session()
    GameActionReceipt.objects.filter(session=session).first().delete()
    client.force_login(operator())

    response = client.get(reverse("admin:play_gamesession_inspect", args=[session.pk]))

    assert response.status_code == 200
    assert response.json()["audit"]["versions_contiguous"] is False
    assert response.json()["replay"] == {"status": "unavailable"}


def test_operational_views_require_staff_and_view_permission(client):
    session, _, _, _ = completed_session()
    inspect_url = reverse("admin:play_gamesession_inspect", args=[session.pk])
    health_url = reverse("game-operations-health")
    for url in (inspect_url, health_url):
        assert client.get(url).status_code == 302
    client.force_login(operator())
    assert client.post(inspect_url).status_code == 405
    assert client.post(health_url).status_code == 405
    client.force_login(operator(permitted=False))
    assert client.get(inspect_url).status_code == 404
    assert client.get(health_url).status_code == 403


def test_realtime_health_uses_readiness_and_safe_counts(client, monkeypatch):
    client.force_login(operator())
    url = reverse("game-operations-health")
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"
    assert response.json()["actions_last_five_minutes"] == 0

    monkeypatch.setattr(
        "play.operations.build_readiness_report",
        lambda: ReadinessReport({"database": UNAVAILABLE, "redis": UNAVAILABLE}),
    )
    response = client.get(url)
    assert response.status_code == 503
    assert response.json()["active_sessions"] is None
    assert response.json()["actions_last_five_minutes"] is None
    assert "redis://" not in response.content.decode()


def test_action_receipt_admin_is_immutable_and_hides_saved_response():
    model_admin = admin.site._registry[GameActionReceipt]
    assert "response" not in model_admin.readonly_fields
    assert "response" not in model_admin.list_display
    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_delete_permission(None) is False


def test_action_receipt_admin_does_not_render_response_payload(client):
    session, _, _, _ = completed_session()
    receipt = GameActionReceipt.objects.filter(session=session).first()
    GameActionReceipt.objects.filter(pk=receipt.pk).update(
        response={**receipt.response, "private_token": "hidden-audit-value"}
    )
    client.force_login(operator())

    for name, args in (
        ("admin:play_gameactionreceipt_changelist", []),
        ("admin:play_gameactionreceipt_change", [receipt.pk]),
    ):
        response = client.get(reverse(name, args=args))
        assert response.status_code == 200
        assert b"hidden-audit-value" not in response.content
