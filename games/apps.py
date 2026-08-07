from django.apps import AppConfig


class GamesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "games"

    def ready(self) -> None:
        from . import checks  # noqa: F401
        from .registry import register_available_game_engines

        register_available_game_engines()
