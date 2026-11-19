from django.contrib import admin

from .models import RoyaleMatch, RoyaleSettings


@admin.register(RoyaleSettings)
class RoyaleSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (None, {"fields": ("enabled",)}),
        (
            "The bridge",
            {
                "fields": ("shared_secret", "allowed_guild_ids"),
                "description": "Royale posts its reports to this bot on the host's own loopback, so "
                "nothing here is reachable from the internet. The secret is what proves a report really "
                "came from Royale; with it empty the webhook server does not start.",
            },
        ),
    )

    def has_add_permission(self, request):
        # one row, like the other settings pages
        return not RoyaleSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RoyaleMatch)
class RoyaleMatchAdmin(admin.ModelAdmin):
    list_display = (
        "match_id",
        "received_at",
        "mode",
        "rounds",
        "players_reported",
        "players_known",
        "kills_reported",
        "points_awarded",
    )
    list_filter = ("mode", "received_at")
    search_fields = ("match_id", "island")
    date_hierarchy = "received_at"
    readonly_fields = (
        "match_id",
        "guild_id",
        "channel_id",
        "mode",
        "island",
        "rounds",
        "players_reported",
        "players_known",
        "kills_reported",
        "points_awarded",
        "report",
        "received_at",
    )

    def has_add_permission(self, request):
        # these only ever arrive from Royale; one added by hand would block the real one, since
        # the match id is unique and an existing row means "already scored"
        return False
