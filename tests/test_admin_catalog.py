import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ksa_games.test_settings")

import django
django.setup()

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone
from games.models import GameCategory, GameDefinition


pytestmark = pytest.mark.django_db


def game(name, order=0):
    return GameDefinition.objects.create(
        category=GameCategory.objects.get(slug="board-games"),
        name=name,
        slug=name.lower().replace(" ", "-"),
        short_description="Catalog admin test.",
        display_order=order,
    )


def superuser():
    return get_user_model().objects.create_superuser(
        username="catalog-admin", email="catalog-admin@example.com", password="StrongPass123!"
    )


def test_admin_catalog_order_controls_public_order(client):
    later = game("Order Later", order=20)
    earlier = game("Order Earlier", order=10)
    model_admin = admin.site._registry[GameDefinition]

    assert "display_order" in model_admin.list_editable
    assert "is_active" in model_admin.list_editable
    assert "is_featured" in model_admin.list_editable
    assert "is_playable" not in model_admin.list_editable
    assert list(
        GameDefinition.objects.public_catalog()
        .filter(pk__in=[later.pk, earlier.pk])
        .values_list("pk", flat=True)
    ) == [earlier.pk, later.pk]


def test_admin_bulk_availability_and_feature_actions_update_timestamps(client):
    target = game("Admin Action Target")
    client.force_login(superuser())
    url = reverse("admin:games_gamedefinition_changelist")
    old_time = timezone.now() - timezone.timedelta(days=1)
    GameDefinition.objects.filter(pk=target.pk).update(updated_at=old_time)

    for action, field, value in (
        ("deactivate_games", "is_active", False),
        ("feature_games", "is_featured", True),
        ("activate_games", "is_active", True),
        ("unfeature_games", "is_featured", False),
    ):
        response = client.post(url, {"action": action, "_selected_action": [target.pk]})
        assert response.status_code == 302
        target.refresh_from_db()
        assert getattr(target, field) is value
        assert target.updated_at > old_time


def test_admin_bulk_actions_require_change_permission(client):
    target = game("View Only Target")
    user = get_user_model().objects.create_user(
        username="catalog-viewer", email="catalog-viewer@example.com", password="StrongPass123!",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="view_gamedefinition"))
    client.force_login(user)

    response = client.post(
        reverse("admin:games_gamedefinition_changelist"),
        {"action": "deactivate_games", "_selected_action": [target.pk]},
    )

    assert response.status_code in (200, 403)
    target.refresh_from_db()
    assert target.is_active is True
