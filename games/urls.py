from django.urls import path

from . import views


app_name = "games"

urlpatterns = [
    path("", views.game_catalog, name="catalog"),
    path("categories/<slug:slug>/", views.game_category_detail, name="category"),
    path("<slug:slug>/", views.game_detail, name="detail"),
]
