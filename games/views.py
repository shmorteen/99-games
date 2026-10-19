from __future__ import annotations

from dataclasses import dataclass

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from lobbies.models import GameLobby, LobbyStatus, LobbyVisibility

from .models import GameCategory, GameDefinition


PAGE_SIZE = 12
TRUTHY_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CatalogFilters:
    query: str = ""
    category_slug: str = ""
    min_players: int | None = None
    max_duration: int | None = None
    bots_only: bool = False
    playable_only: bool = False


def parse_positive_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def parse_catalog_filters(request: HttpRequest) -> CatalogFilters:
    return CatalogFilters(
        query=request.GET.get("q", "").strip(),
        category_slug=request.GET.get("category", "").strip(),
        min_players=parse_positive_int(request.GET.get("min_players")),
        max_duration=parse_positive_int(request.GET.get("max_duration")),
        bots_only=request.GET.get("bots", "").lower() in TRUTHY_VALUES,
        playable_only=request.GET.get("playable", "").lower() in TRUTHY_VALUES,
    )


def base_game_queryset():
    return GameDefinition.objects.public_catalog().select_related("category")


def apply_catalog_filters(queryset, filters: CatalogFilters):
    if filters.query:
        queryset = queryset.filter(
            Q(name__icontains=filters.query)
            | Q(short_description__icontains=filters.query)
            | Q(full_description__icontains=filters.query)
        )

    if filters.category_slug:
        queryset = queryset.filter(category__slug=filters.category_slug)

    if filters.min_players is not None:
        queryset = queryset.filter(
            minimum_players__lte=filters.min_players,
            maximum_players__gte=filters.min_players,
        )

    if filters.max_duration is not None:
        queryset = queryset.filter(
            estimated_duration_minutes__lte=filters.max_duration
        )

    if filters.bots_only:
        queryset = queryset.filter(supports_bots=True)

    if filters.playable_only:
        queryset = queryset.filter(is_playable=True)

    return queryset


def shared_catalog_context(request: HttpRequest) -> dict[str, object]:
    pagination_query = request.GET.copy()
    pagination_query.pop("page", None)
    encoded_pagination_query = pagination_query.urlencode()
    return {
        "active_categories": GameCategory.objects.public_catalog(),
        "query_params": request.GET.copy(),
        "pagination_query": f"{encoded_pagination_query}&"
        if encoded_pagination_query
        else "",
    }


def game_catalog(request: HttpRequest) -> HttpResponse:
    filters = parse_catalog_filters(request)
    games = apply_catalog_filters(base_game_queryset(), filters)
    paginator = Paginator(games, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        **shared_catalog_context(request),
        "page_title": "Game Catalog",
        "filters": filters,
        "page_obj": page_obj,
        "games": page_obj.object_list,
    }
    return render(request, "games/catalog.html", context)


def game_category_detail(request: HttpRequest, slug: str) -> HttpResponse:
    category = get_object_or_404(GameCategory.objects.public_catalog(), slug=slug)
    filters = parse_catalog_filters(request)
    games = base_game_queryset().filter(category=category)
    games = apply_catalog_filters(games, filters)
    paginator = Paginator(games, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        **shared_catalog_context(request),
        "page_title": category.name,
        "category": category,
        "filters": filters,
        "page_obj": page_obj,
        "games": page_obj.object_list,
    }
    return render(request, "games/category.html", context)


def game_detail(request: HttpRequest, slug: str) -> HttpResponse:
    game = get_object_or_404(base_game_queryset(), slug=slug)
    open_public_lobbies = GameLobby.objects.filter(
        game=game, status=LobbyStatus.WAITING, visibility=LobbyVisibility.PUBLIC
    ).count()
    context = {
        **shared_catalog_context(request),
        "page_title": game.name,
        "game": game,
        "active_public_lobby_count": open_public_lobbies,
    }
    return render(request, "games/detail.html", context)
