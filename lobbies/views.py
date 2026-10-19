"""Authenticated browser entry into durable lobby services."""

from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from games.models import GameDefinition

from .forms import PublicLobbyCreateForm
from .models import GameLobby, LobbyMembership, LobbyStatus, LobbyVisibility
from .services import LobbyServiceError, create_public_lobby, join_lobby


@login_required
@require_http_methods(["GET", "POST"])
def create_lobby(request, game_slug: str) -> HttpResponse:
    game = get_object_or_404(
        GameDefinition.objects.public_catalog().playable(), slug=game_slug
    )
    if request.method == "POST":
        form = PublicLobbyCreateForm(request.POST)
        if form.is_valid():
            try:
                lobby = create_public_lobby(
                    game=game,
                    user=request.user,
                    name=form.cleaned_data["name"],
                    request_id=str(form.cleaned_data["request_id"]),
                )
            except (LobbyServiceError, ValidationError) as error:
                form.add_error(None, str(error))
            else:
                return redirect("lobbies:detail", lobby_uuid=lobby.public_id)
    else:
        form = PublicLobbyCreateForm(initial={
            "name": f"{game.name} Lobby", "request_id": uuid4(),
        })
    return render(request, "lobbies/create.html", {
        "page_title": "Create a lobby", "game": game, "form": form,
    }, status=400 if request.method == "POST" else 200)


def _visible_lobby(request, lobby_uuid):
    lobby = get_object_or_404(
        GameLobby.objects.select_related("game", "game__category", "host"),
        public_id=lobby_uuid,
    )
    is_member = LobbyMembership.objects.active().filter(
        lobby=lobby, user=request.user
    ).exists()
    if not is_member and not (
        lobby.game.is_active
        and lobby.game.is_playable
        and lobby.game.category.is_active
    ):
        raise Http404
    if lobby.visibility != LobbyVisibility.PUBLIC and not is_member:
        raise Http404
    return lobby, is_member


def _detail(request, lobby, is_member, *, error=None, status=200):
    members = list(
        LobbyMembership.objects.active().filter(lobby=lobby)
        .select_related("user").order_by("seat_number", "joined_at")
    )
    seated_count = sum(member.seat_number is not None for member in members)
    can_join = (
        lobby.visibility == LobbyVisibility.PUBLIC
        and lobby.status == LobbyStatus.WAITING
        and not is_member
        and seated_count < lobby.maximum_players
    )
    return render(request, "lobbies/detail.html", {
        "page_title": lobby.name, "lobby": lobby, "members": members,
        "is_member": is_member, "can_join": can_join, "error": error,
        "seated_count": seated_count,
    }, status=status)


@login_required
@require_http_methods(["GET"])
def lobby_detail(request, lobby_uuid) -> HttpResponse:
    lobby, is_member = _visible_lobby(request, lobby_uuid)
    return _detail(request, lobby, is_member)


@login_required
@require_POST
def join_public_lobby(request, lobby_uuid) -> HttpResponse:
    lobby, is_member = _visible_lobby(request, lobby_uuid)
    if lobby.visibility != LobbyVisibility.PUBLIC:
        raise Http404
    try:
        join_lobby(lobby=lobby, user=request.user)
    except LobbyServiceError as error:
        return _detail(request, lobby, is_member, error=str(error), status=400)
    return redirect("lobbies:detail", lobby_uuid=lobby.public_id)
