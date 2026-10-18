from django.urls import path

from . import views
from play.views import (
    connect4_overlay, connect4_player, connect4_replay, connect4_results,
    connect4_spectator,
)


app_name = "games"

urlpatterns = [
    path("", views.game_catalog, name="catalog"),
    path(
        "connect4/sessions/<uuid:session_uuid>/",
        connect4_player,
        name="connect4_player",
    ),
    path("connect4/sessions/<uuid:session_uuid>/spectate/", connect4_spectator,
         name="connect4_spectator"),
    path("connect4/sessions/<uuid:session_uuid>/overlay/", connect4_overlay,
         name="connect4_overlay"),
    path("connect4/sessions/<uuid:session_uuid>/results/", connect4_results,
         name="connect4_results"),
    path("connect4/sessions/<uuid:session_uuid>/replay/", connect4_replay,
         name="connect4_replay"),
    path("categories/<slug:slug>/", views.game_category_detail, name="category"),
    path("<slug:slug>/", views.game_detail, name="detail"),
]
