from django.urls import path

from . import views
from play.views import connect4_player


app_name = "games"

urlpatterns = [
    path("", views.game_catalog, name="catalog"),
    path(
        "connect4/sessions/<uuid:session_uuid>/",
        connect4_player,
        name="connect4_player",
    ),
    path("categories/<slug:slug>/", views.game_category_detail, name="category"),
    path("<slug:slug>/", views.game_detail, name="detail"),
]
