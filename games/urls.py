from django.urls import path

from . import views
from play.views import (
    connect4_overlay, connect4_player, connect4_replay, connect4_results,
    connect4_spectator, hangman_overlay, hangman_player, hangman_rules,
    hangman_spectator, werewolves_moderator, werewolves_overlay,
    werewolves_player, werewolves_rules, werewolves_spectator,
)


app_name = "games"

urlpatterns = [
    path("", views.game_catalog, name="catalog"),
    path("werewolves-vs-villagers/rules/", werewolves_rules, name="werewolves_rules"),
    path("werewolves-vs-villagers/sessions/<uuid:session_uuid>/", werewolves_player, name="werewolves_player"),
    path("werewolves-vs-villagers/sessions/<uuid:session_uuid>/spectate/", werewolves_spectator, name="werewolves_spectator"),
    path("werewolves-vs-villagers/sessions/<uuid:session_uuid>/moderate/", werewolves_moderator, name="werewolves_moderator"),
    path("werewolves-vs-villagers/sessions/<uuid:session_uuid>/overlay/", werewolves_overlay, name="werewolves_overlay"),
    path("hangman/rules/", hangman_rules, name="hangman_rules"),
    path("hangman/sessions/<uuid:session_uuid>/", hangman_player, name="hangman_player"),
    path("hangman/sessions/<uuid:session_uuid>/spectate/", hangman_spectator, name="hangman_spectator"),
    path("hangman/sessions/<uuid:session_uuid>/overlay/", hangman_overlay, name="hangman_overlay"),
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
