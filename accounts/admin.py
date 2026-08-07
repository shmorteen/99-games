from django.contrib import admin

from .models import ArenaProfile


@admin.register(ArenaProfile)
class ArenaProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "public_id", "user_email", "created_at")
    search_fields = ("display_name", "public_id", "user__email", "user__username")
    readonly_fields = ("public_id", "user", "created_at", "updated_at")
    ordering = ("display_name",)
    list_select_related = ("user",)

    @admin.display(description="User email")
    def user_email(self, obj):
        return obj.user.email
