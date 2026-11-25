"""
The staff pages of the advent calendar: the calendar, its doors, and what has been opened.

The doors, the streak rewards and the surprises are all edited on the calendar's own page, because setting up
twenty-five doors across twenty-five separate pages is how a door ends up forgotten.
"""

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import (
    AdventCalendar,
    AdventDoor,
    AdventOpening,
    AdventStreak,
    AdventStreakGrant,
    AdventSurprise,
    door_date,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


class DoorInline(admin.TabularInline):
    model = AdventDoor
    extra = 0
    fields = ("day", "reward", "message")
    autocomplete_fields = ("reward",)
    ordering = ("day",)


class StreakInline(admin.TabularInline):
    model = AdventStreak
    extra = 0
    fields = ("doors", "reward", "message")
    autocomplete_fields = ("reward",)
    ordering = ("doors",)
    verbose_name = "streak reward"
    verbose_name_plural = "streak rewards"


class SurpriseInline(admin.TabularInline):
    model = AdventSurprise
    extra = 0
    fields = ("name", "emoji", "weight", "reward", "boost", "once_per_player", "enabled", "description")
    autocomplete_fields = ("reward", "boost")
    ordering = ("-weight", "name")


@admin.register(AdventCalendar)
class AdventCalendarAdmin(admin.ModelAdmin):
    save_on_top = True
    inlines = (DoorInline, StreakInline, SurpriseInline)
    list_display = ("name", "event_pass", "starts_on", "door_count", "state", "catch_up_price", "enabled")
    list_filter = ("enabled", "event_pass")
    search_fields = ("name", "description")
    autocomplete_fields = ("event_pass",)
    readonly_fields = ("state", "created_at")
    fieldsets = [
        (None, {"fields": ["event_pass", "name", "emoji", "description", "enabled", "state"]}),
        (
            "When",
            {
                "fields": ["starts_on", "door_count"],
                "description": "Door 1 opens on the starting day, door 2 the day after. A day runs to midnight "
                "UTC, so everyone's day turns over at the same moment.",
            },
        ),
        (
            "Catching up",
            {
                "fields": ["catch_up_price", "catch_up_until"],
                "description": "A door whose day has gone by can be bought open in berries — the one way to "
                "catch up, and where the event takes berries back out of the economy. A price of zero means a "
                "day missed is missed for good.",
            },
        ),
        (
            "Surprises",
            {
                "fields": ["surprise_chance", "announce_to"],
                "description": "The chance, between 0 and 1, that a surprise fires on top of the door. It never "
                "replaces what the door gives. Which surprise is drawn by weight, below.",
            },
        ),
        ("Looks", {"fields": ["background"]}),
    ]

    @admin.display(description="State")
    def state(self, obj: AdventCalendar | None):
        if obj is None or obj.pk is None:
            return "Save it, then fill its doors in below."
        if not obj.enabled:
            return "Off"
        day = obj.day_today()
        if day is not None:
            return mark_safe(f"<span style='color: green'><b>Running</b></span>, today is door {day}")
        if timezone.now().date() < obj.starts_on:
            return f"Opens {obj.starts_on:%Y-%m-%d}"
        catch_up = obj.catch_up_price and timezone.now() <= obj.closes_at
        return "Over, catching up still allowed" if catch_up else "Over"


@admin.register(AdventOpening)
class AdventOpeningAdmin(admin.ModelAdmin):
    """Every door opened, so a complaint can be answered and a calendar audited."""

    list_display = ("opened_at", "calendar", "player", "day", "when_it_was", "paid", "surprise", "summary")
    list_filter = ("calendar", "day", "surprise", "opened_at")
    search_fields = ("player__discord_id", "summary")
    list_select_related = ("calendar", "player", "surprise")
    readonly_fields = ("calendar", "player", "day", "paid", "surprise", "summary", "opened_at")
    date_hierarchy = "opened_at"

    @admin.display(description="Its day")
    def when_it_was(self, obj: AdventOpening) -> str:
        return f"{door_date(obj.calendar.starts_on, obj.day):%Y-%m-%d}"

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False


@admin.register(AdventStreakGrant)
class AdventStreakGrantAdmin(admin.ModelAdmin):
    """The streak rewards already handed out. Deleting one lets it be earned again."""

    list_display = ("given_at", "streak", "player", "summary")
    list_filter = ("streak__calendar", "streak", "given_at")
    search_fields = ("player__discord_id",)
    list_select_related = ("streak", "player")
    readonly_fields = ("streak", "player", "summary", "given_at")
    actions = ("allow_again",)

    @admin.action(description="Let the selected players earn these again")
    def allow_again(self, request: "HttpRequest", queryset: "QuerySet[AdventStreakGrant]"):
        count = queryset.count()
        queryset.delete()
        self.message_user(
            request,
            f"{count} cleared. They will be given again on the next door opened.",
            messages.SUCCESS if count else messages.WARNING,
        )

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False
