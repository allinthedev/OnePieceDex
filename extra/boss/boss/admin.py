from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import BossSchedule


@admin.register(BossSchedule)
class BossScheduleAdmin(admin.ModelAdmin):
    """
    Boss fights set up ahead of time.

    The bot checks every minute: when a plan comes due it opens the fight in the channel below,
    leaves the joining window open, then runs the rounds by itself if it was told to. Only one
    fight runs at a time, so a plan that comes due during another one waits its turn.
    """

    autocomplete_fields = ("ball",)
    save_on_top = True
    readonly_fields = ("state", "started_at", "created_at")
    fieldsets = [
        (None, {"fields": ["name", "ball", "hp", "enabled", "state"]}),
        (
            "When and where",
            {
                "description": "Times are UTC. The joining window runs from the start time; the first round "
                "begins once it closes.",
                "fields": ["starts_at", "join_minutes", "channel_id", "started_at"],
            },
        ),
        (
            "Automatic rounds",
            {
                "description": "Leave this on and the whole fight plays itself. Turn it off to have the bot "
                "only open the fight, and drive the rounds yourself with the /boss admin commands.",
                "fields": ["auto", "min_damage", "max_damage", "swings", "pattern", "seconds_per_round"],
            },
        ),
        (
            "Pictures",
            {
                "description": "All optional. Without them the treasure's own cards are used. Animated GIFs "
                "work for the attack and defend ones.",
                "fields": ["start_image", "attack_image", "defend_image"],
            },
        ),
    ]
    list_display = ("name", "ball_name", "hp", "starts_at", "auto", "enabled", "state")
    list_editable = ("enabled",)
    list_filter = ("enabled", "auto", "starts_at")
    search_fields = ("name", "ball__country")
    list_select_related = ("ball",)
    date_hierarchy = "starts_at"

    @admin.display(description="Treasure", ordering="ball__country")
    def ball_name(self, obj: BossSchedule) -> str:
        return obj.ball.country

    @admin.display(description="State")
    def state(self, obj: BossSchedule | None):
        if obj is None or obj.pk is None:
            return "The bot picks this up within a minute of the start time."
        if obj.started_at:
            return format_html("<b>Opened</b> on {}", f"{obj.started_at:%Y-%m-%d %H:%M}")
        if not obj.enabled:
            return mark_safe("<span style='color: crimson'>Cancelled</span>")
        if obj.starts_at > timezone.now():
            return format_html("Waiting for {}", f"{obj.starts_at:%Y-%m-%d %H:%M}")
        return mark_safe("<span style='color: green'><b>Due</b></span>, opening shortly")
