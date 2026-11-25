"""
The staff pages of the sleigh: the sleigh itself, every gift in it, and the waves that empty it.
"""

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import Sleigh, SleighCard, SleighWave

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


@admin.register(Sleigh)
class SleighAdmin(admin.ModelAdmin):
    save_on_top = True
    list_display = ("name", "special", "opens_at", "closes_at", "per_day", "inside", "state", "enabled")
    list_filter = ("enabled", "special")
    search_fields = ("name", "description")
    autocomplete_fields = ("special",)
    readonly_fields = ("state", "inside", "created_at")
    fieldsets = [
        (None, {"fields": ["name", "emoji", "description", "enabled", "special", "state", "inside"]}),
        (
            "When",
            {
                "fields": ["opens_at", "closes_at", "per_day", "goal"],
                "description": "Times are UTC, and a player's daily allowance turns over at midnight UTC. The "
                "goal is only the bar players see — the sleigh keeps taking gifts past it.",
            },
        ),
        (
            "What a gift is worth",
            {
                "fields": ["points_base", "points_pivot", "points_cap"],
                "description": "Points go to the giver's crew, in the running crew war. A LOWER rarity is a "
                "RARER treasure, so the points are the base multiplied by pivot ÷ rarity: a card ten times "
                "rarer than the pivot is worth ten times the base, up to the ceiling. No war running means no "
                "points, and the gift still goes in.",
            },
        ),
        (
            "Emptying it again",
            {
                "fields": ["empty_at", "wave_count", "wave_hours", "spawn_channel_id", "announce_to"],
                "description": "Once the emptying time passes, whatever is left is split into waves and spawned "
                "back out, one card at a time, for anyone to catch. Four waves six hours apart give every "
                "timezone a fair shot. Leave the emptying time empty to hand the gifts out by hand instead.",
            },
        ),
    ]

    @admin.display(description="Still inside")
    def inside(self, obj: Sleigh | None) -> int:
        if obj is None or obj.pk is None:
            return 0
        return obj.cards.filter(released_at__isnull=True, claimed_by__isnull=True).count()

    @admin.display(description="State")
    def state(self, obj: Sleigh | None):
        if obj is None or obj.pk is None:
            return "Save it, then players can start filling it."
        if not obj.enabled:
            return "Off"
        now = timezone.now()
        if obj.is_open(now):
            return mark_safe("<span style='color: green'><b>Taking gifts</b></span>")
        if now < obj.opens_at:
            return f"Opens {obj.opens_at:%Y-%m-%d %H:%M}"
        if obj.empty_at and now >= obj.empty_at:
            return "Emptying itself"
        return "Closed"


@admin.register(SleighCard)
class SleighCardAdmin(admin.ModelAdmin):
    """
    Every gift. The giver's own card is gone — consumed when they gave it — so this is the only record of it.
    """

    list_display = ("given_at", "ball", "given_by", "crew", "rarity", "points", "where_it_is")
    list_filter = ("sleigh", "crew", "released_at", "given_at")
    search_fields = ("ball__country", "given_by__discord_id", "claimed_by__discord_id")
    list_select_related = ("ball", "given_by", "crew", "claimed_by")
    readonly_fields = (
        "sleigh",
        "ball",
        "given_by",
        "crew",
        "attack_bonus",
        "health_bonus",
        "frame",
        "rarity",
        "points",
        "given_at",
        "released_at",
        "claimed_by",
        "claimed_at",
        "claimed_instance",
    )
    date_hierarchy = "given_at"

    @admin.display(description="Where it is")
    def where_it_is(self, obj: SleighCard) -> str:
        return obj.state

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False


@admin.register(SleighWave)
class SleighWaveAdmin(admin.ModelAdmin):
    """
    The waves, written by the bot once the emptying time has passed. One card of a due wave goes out a minute.
    """

    list_display = ("sleigh", "position", "due_at", "cards", "sent", "state", "announced_at")
    list_filter = ("sleigh", "due_at")
    readonly_fields = ("sleigh", "position", "cards", "created_at")
    actions = ("announce_again", "hold_back")

    @admin.display(description="State")
    def state(self, obj: SleighWave):
        if obj.done:
            return "Done"
        if obj.due_at > timezone.now():
            return f"Waiting, {obj.cards} to send"
        return mark_safe(f"<span style='color: green'><b>Going out</b></span>, {obj.left} left")

    @admin.action(description="Announce the selected waves again")
    def announce_again(self, request: "HttpRequest", queryset: "QuerySet[SleighWave]"):
        count = queryset.update(announced_at=None)
        self.message_user(request, f"{count} will be announced again.", messages.SUCCESS)

    @admin.action(description="Stop the selected waves (mark them finished)")
    def hold_back(self, request: "HttpRequest", queryset: "QuerySet[SleighWave]"):
        count = 0
        for wave in queryset:
            count += SleighWave.objects.filter(pk=wave.pk).update(sent=wave.cards)
        self.message_user(
            request,
            f"{count} stopped. Their cards stay in the sleigh for you to hand out.",
            messages.SUCCESS if count else messages.WARNING,
        )

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False
