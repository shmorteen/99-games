from django.contrib import admin
from django.utils import timezone

from .models import GameCategory, GameDefinition


@admin.action(description="Activate selected categories")
def activate_categories(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Deactivate selected categories")
def deactivate_categories(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.register(GameCategory)
class GameCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "display_order", "is_active", "created_at")
    list_editable = ("display_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("public_id", "created_at", "updated_at")
    ordering = ("display_order", "name")
    actions = (activate_categories, deactivate_categories)

    def delete_model(self, request, obj):
        obj.delete()

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            obj.delete()


@admin.action(description="Mark selected games active", permissions=["change"])
def activate_games(modeladmin, request, queryset):
    queryset.update(is_active=True, updated_at=timezone.now())


@admin.action(description="Mark selected games inactive", permissions=["change"])
def deactivate_games(modeladmin, request, queryset):
    queryset.update(is_active=False, updated_at=timezone.now())


@admin.action(description="Mark selected games featured", permissions=["change"])
def feature_games(modeladmin, request, queryset):
    queryset.update(is_featured=True, updated_at=timezone.now())


@admin.action(description="Remove selected games from featured", permissions=["change"])
def unfeature_games(modeladmin, request, queryset):
    queryset.update(is_featured=False, updated_at=timezone.now())


@admin.register(GameDefinition)
class GameDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "category",
        "display_order",
        "is_playable",
        "is_active",
        "is_featured",
        "minimum_players",
        "maximum_players",
        "estimated_duration_minutes",
    )
    list_editable = ("display_order", "is_active", "is_featured")
    list_filter = (
        "category",
        "is_active",
        "is_playable",
        "is_featured",
        "supports_bots",
        "supports_spectators",
        "supports_ranked",
        "supports_private_lobbies",
        "supports_broadcasts",
    )
    search_fields = ("name", "slug", "short_description", "engine_key")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("public_id", "created_at", "updated_at")
    ordering = ("category__display_order", "display_order", "name", "pk")
    actions = (activate_games, deactivate_games, feature_games, unfeature_games)
    list_select_related = ("category",)
    fieldsets = (
        (
            "Catalog",
            {
                "fields": (
                    "public_id",
                    "category",
                    "name",
                    "slug",
                    "display_order",
                    "short_description",
                    "full_description",
                    "thumbnail",
                    "banner",
                )
            },
        ),
        (
            "Engine",
            {
                "fields": (
                    "engine_key",
                    "engine_version",
                    "is_playable",
                    "default_configuration",
                    "rules",
                    "difficulty_options",
                )
            },
        ),
        (
            "Availability",
            {
                "fields": (
                    "minimum_players",
                    "maximum_players",
                    "estimated_duration_minutes",
                    "supports_bots",
                    "supports_spectators",
                    "supports_ranked",
                    "supports_private_lobbies",
                    "supports_broadcasts",
                    "is_featured",
                    "is_active",
                )
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
