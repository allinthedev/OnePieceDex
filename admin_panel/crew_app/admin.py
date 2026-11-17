from django.contrib import admin
from django.db.models import Sum
from django.http import HttpRequest
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from .models import Crew, CrewMembership, CrewWar, CrewWarEntry, CrewWarRule


class CrewMembershipInline(admin.TabularInline):
    model = CrewMembership
    extra = 0
    autocomplete_fields = ("player",)
    fields = ("player", "joined_at")
    readonly_fields = ("joined_at",)
    can_delete = True


@admin.register(Crew)
class CrewAdmin(admin.ModelAdmin):
    """
    The crews players can pick from /player settings. Eight or so is a good number: enough for
    rivalry, few enough that every one of them has a real population.
    """

    save_on_top = True
    inlines = [CrewMembershipInline]
    readonly_fields = ("flag_preview", "created_at")
    fieldsets = [
        (None, {"fields": ["name", "emoji", "description", "enabled", "position"]}),
        (
            "Picture",
            {
                "description": "The flag is shown when a player looks at the crew. The victory picture is "
                "posted in the spawn channels when this crew finishes a hunt — that is the one worth "
                "animating, since it only ever plays on a win.",
                "fields": ["image", "victory_image", "flag_preview"],
            },
        ),
    ]
    list_display = ("name", "emoji", "enabled", "member_count", "position")
    list_editable = ("enabled", "position")
    list_filter = ("enabled",)
    search_fields = ("name", "description")

    @admin.display(description="Members")
    def member_count(self, obj: Crew) -> int:
        return obj.members.count()

    @admin.display(description="Preview")
    def flag_preview(self, obj: Crew | None):
        if obj is None or not obj.image:
            return "Upload a flag and it shows up here once saved."
        return format_html('<img src="/media/{}" style="max-width: 320px" />', obj.image.name)


@admin.register(CrewMembership)
class CrewMembershipAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player", "crew")
    list_display = ("player", "crew", "joined_at")
    list_filter = ("crew", "joined_at")
    search_fields = ("player__discord_id",)
    list_select_related = ("player", "crew")


class CrewWarRuleInline(admin.TabularInline):
    model = CrewWarRule
    extra = 1
    fields = ("source", "points", "daily_cap", "minimum_value")
    verbose_name = "scoring rule"
    verbose_name_plural = "What is worth points"


@admin.register(CrewWar)
class CrewWarAdmin(admin.ModelAdmin):
    """
    A season scored between crews.

    Add a rule per deed worth points. A deed with no rule scores nothing, so a war only ever
    counts what you have decided it counts.
    """

    save_on_top = True
    inlines = [CrewWarRuleInline]
    readonly_fields = ("standings_preview", "created_at")

    def save_related(self, request, form, formsets, change):
        # the rules are held for half a minute while the war is scored, so a change made here
        # would otherwise take that long to show up
        super().save_related(request, form, formsets, change)
        self._forget_cached_war()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._forget_cached_war()

    @staticmethod
    def _forget_cached_war():
        # imported here rather than at the top: scoring pulls in the bot's event bus, which the
        # panel has no reason to load on startup
        from .scoring import invalidate

        invalidate()
    fieldsets = [
        (None, {"fields": ["name", "description", "enabled"]}),
        (
            "When",
            {
                "description": "Nothing scores outside this window. Both can be left empty for a war with no "
                "end in sight. Times are UTC.",
                "fields": ["starts_at", "ends_at"],
            },
        ),
        ("Picture", {"fields": ["image"]}),
        ("Standings", {"fields": ["standings_preview"]}),
    ]
    list_display = ("name", "enabled", "starts_at", "ends_at", "rule_count", "entry_count")
    list_editable = ("enabled",)
    list_filter = ("enabled", "starts_at", "ends_at")
    search_fields = ("name", "description")

    @admin.display(description="Rules")
    def rule_count(self, obj: CrewWar) -> int:
        return obj.rules.count()

    @admin.display(description="Deeds scored")
    def entry_count(self, obj: CrewWar) -> int:
        return obj.entries.count()

    @admin.display(description="Standings")
    def standings_preview(self, obj: CrewWar | None):
        if obj is None or obj.pk is None:
            return "The table appears here once the war has been saved and someone has scored."
        rows = (
            CrewWarEntry.objects.filter(war=obj)
            .values("crew__name")
            .annotate(total=Sum("points"))
            .order_by("-total")
        )
        if not rows:
            return "Nobody has scored yet."
        return format_html_join(
            mark_safe("<br>"), "{} — {}", ((row["crew__name"], row["total"]) for row in rows)
        )


@admin.register(CrewWarEntry)
class CrewWarEntryAdmin(admin.ModelAdmin):
    """Read-only: one line per deed, written by the bot. This is what the standings add up."""

    list_display = ("created_at", "war", "crew", "player", "source", "points")
    list_filter = ("war", "crew", "source", "created_at")
    search_fields = ("player__discord_id",)
    list_select_related = ("war", "crew", "player")
    date_hierarchy = "created_at"
    list_per_page = 50

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return False
