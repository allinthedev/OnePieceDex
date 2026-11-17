from typing import TYPE_CHECKING

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..models import Bounty

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


@admin.register(Bounty)
class BountyAdmin(admin.ModelAdmin):
    """
    Wanted posters. One bounty is claimed once: the first player to catch the treasure inside the
    window takes the reward, and their card comes out carrying the special.
    """

    autocomplete_fields = ("ball", "special", "claimed_by")
    save_on_top = True
    readonly_fields = ("state", "claimed_at", "claimed_instance", "created_at")
    fieldsets = [
        (None, {"fields": ["ball", "reward", "special", "state"]}),
        (
            "When",
            {
                "description": "The bounty can only be claimed between these two. Times are UTC.",
                "fields": ["starts_at", "ends_at"],
            },
        ),
        (
            "Announcement",
            {
                "description": "The bot posts the poster in every spawn channel once the bounty opens. Clear "
                "the date below to have it announced again.",
                "fields": ["announcement_text", "announced_at"],
            },
        ),
        (
            "Claim",
            {
                "description": "Filled in by the bot. Clearing the player puts the bounty back up for grabs, "
                "which is the way to undo a claim that should not have counted.",
                "fields": ["claimed_by", "claimed_at", "claimed_instance"],
            },
        ),
    ]

    list_display = ("ball_name", "reward", "special_name", "starts_at", "ends_at", "state")
    list_filter = ("starts_at", "ends_at", "special")
    search_fields = ("ball__country", "claimed_by__discord_id")
    list_select_related = ("ball", "special", "claimed_by")
    date_hierarchy = "starts_at"

    @admin.display(description="Treasure", ordering="ball__country")
    def ball_name(self, obj: Bounty) -> str:
        return obj.ball.country

    @admin.display(description="Special")
    def special_name(self, obj: Bounty) -> str:
        return obj.special.name if obj.special else "—"

    @admin.display(description="State")
    def state(self, obj: Bounty | None):
        """Where this bounty stands, in one cell, so a list can be read down the column."""
        if obj is None or obj.pk is None:
            return "Save it and the bot picks it up on the next catch."
        if obj.claimed_by_id:
            when = f" on {obj.claimed_at:%Y-%m-%d %H:%M}" if obj.claimed_at else ""
            return format_html("<b>Claimed</b> by {}{}", str(obj.claimed_by), when)
        now = timezone.now()
        if now < obj.starts_at:
            return format_html("Opens {}", f"{obj.starts_at:%Y-%m-%d %H:%M}")
        if now > obj.ends_at:
            return mark_safe("<span style='color: crimson'>Expired unclaimed</span>")
        return mark_safe("<span style='color: green'><b>Live</b></span>, nobody has caught it yet")

    def get_queryset(self, request: "HttpRequest") -> "QuerySet[Bounty]":
        return super().get_queryset(request).select_related("ball", "special", "claimed_by")
