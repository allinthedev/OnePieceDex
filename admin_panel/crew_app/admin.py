from django.contrib import admin, messages
from django.db.models import Sum
from django.http import HttpRequest
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from bd_models.models import Player

from .models import (
    Crew,
    CrewMembership,
    CrewWar,
    CrewWarEntry,
    CrewWarPayout,
    CrewWarReward,
    CrewWarRewardCard,
    CrewWarRule,
)


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
    autocomplete_fields = ("ball", "special", "collector", "tier_level")
    fields = ("source", "points", "daily_cap", "minimum_value", "ball", "special", "collector", "tier_level")
    verbose_name = "scoring rule"
    verbose_name_plural = "What is worth points"


class CrewWarRewardInline(admin.TabularInline):
    """
    The ladder, on the war's own page. The cards of a rung are set on the rung itself, which is
    what the change link at the end of each line is for.
    """

    model = CrewWarReward
    extra = 1
    fields = ("scope", "threshold", "name", "money", "cumulative", "message", "card_count")
    readonly_fields = ("card_count",)
    ordering = ("scope", "threshold")
    show_change_link = True
    verbose_name = "reward"
    verbose_name_plural = "What the war pays out"

    @admin.display(description="Cards")
    def card_count(self, obj: CrewWarReward) -> str:
        if obj.pk is None:
            return "Save the rung, then open it to add cards."
        return ", ".join(card.label for card in obj.cards.all()) or "No cards, berries only."


class CrewWarRewardCardInline(admin.TabularInline):
    model = CrewWarRewardCard
    extra = 1
    autocomplete_fields = ("ball", "special")
    fields = ("ball", "special", "frame_key", "amount", "tradeable")
    verbose_name = "card"
    verbose_name_plural = "Cards handed over by this rung"


@admin.register(CrewWarReward)
class CrewWarRewardAdmin(admin.ModelAdmin):
    """
    One rung of a war's reward ladder: the berries and the cards it pays, and what earns it.

    A player rung is earned with points, a crew rung with a finishing place. Add the cards below
    — as many as the rung should hand over, with or without a special or a frame.
    """

    save_on_top = True
    inlines = [CrewWarRewardCardInline]
    autocomplete_fields = ("war",)
    fieldsets = [
        (None, {"fields": ["war", "name", "scope", "threshold"]}),
        (
            "What it pays",
            {
                "description": "The berries here, the cards below. A rung can pay only berries, only cards, "
                "or both.",
                "fields": ["money", "message"],
            },
        ),
        (
            "Stacking",
            {
                "description": "On a player rung, leave <b>cumulative</b> on for a ladder that piles up: a "
                "player on 500 points then gets the 500 rung and every rung under it. Turn it off on the rung "
                "where the ladder should stop paying the ones below. Crew rungs ignore it.",
                "fields": ["cumulative"],
            },
        ),
    ]
    list_display = ("name", "war", "scope", "threshold", "money", "cumulative", "card_count", "paid_count")
    list_filter = ("war", "scope")
    search_fields = ("name",)
    list_select_related = ("war",)

    @admin.display(description="Cards")
    def card_count(self, obj: CrewWarReward) -> int:
        return obj.cards.count()

    @admin.display(description="Handed out")
    def paid_count(self, obj: CrewWarReward) -> int:
        return obj.payouts.count()


@admin.register(CrewWarPayout)
class CrewWarPayoutAdmin(admin.ModelAdmin):
    """Read-only: one line per rung handed to a player, written by the payout action."""

    list_display = ("paid_at", "reward", "player", "crew", "points", "summary", "announced_at")
    list_filter = ("reward__war", "reward", "crew", "paid_at", "announced_at")
    search_fields = ("player__discord_id",)
    list_select_related = ("reward", "player", "crew")
    date_hierarchy = "paid_at"
    actions = ["tell_again"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return False

    @admin.action(description="Send the direct message again")
    def tell_again(self, request: HttpRequest, queryset):
        """
        Forget that these players were told, so the bot messages them again within a couple of
        minutes. The reward itself is untouched — this only sends the message a second time.
        """
        count = queryset.update(announced_at=None)
        self.message_user(request, f"{count} player(s) will be messaged again shortly.", level=messages.SUCCESS)


@admin.register(CrewWar)
class CrewWarAdmin(admin.ModelAdmin):
    """
    A season scored between crews.

    Add a rule per deed worth points. A deed with no rule scores nothing, so a war only ever
    counts what you have decided it counts.
    """

    save_on_top = True
    inlines = [CrewWarRuleInline, CrewWarRewardInline]
    readonly_fields = ("standings_preview", "rewards_preview", "created_at")
    actions = ["hand_out_rewards"]

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
        (
            "Announcements",
            {
                "description": "Where the result of this war is announced once you hand the rewards out: who "
                "won, the final table, and the winning crew's victory picture. Players are always told what "
                "they personally received by direct message, whatever this says. The date is written by the "
                "bot; clear it to have the result announced again.",
                "fields": ["announce_to", "announced_at"],
            },
        ),
        ("Standings", {"fields": ["standings_preview"]}),
        (
            "Paying out",
            {
                "description": "Set the ladder up below, then select this war in the list and run "
                "<b>Hand out the rewards</b>. Nothing is paid until you do, and running it twice pays "
                "nothing twice, so it is safe to run again once the standings have settled.",
                "fields": ["rewards_preview"],
            },
        ),
    ]
    list_display = ("name", "enabled", "starts_at", "ends_at", "rule_count", "entry_count", "announced_at")
    list_editable = ("enabled",)
    list_filter = ("enabled", "starts_at", "ends_at", "announce_to")
    search_fields = ("name", "description")

    @admin.display(description="Rules")
    def rule_count(self, obj: CrewWar) -> int:
        return obj.rules.count()

    @admin.display(description="Deeds scored")
    def entry_count(self, obj: CrewWar) -> int:
        return obj.entries.count()

    @admin.display(description="Who gets what")
    def rewards_preview(self, obj: CrewWar | None):
        """
        The payout as it would happen right now, so it can be read before anything is handed over.
        """
        if obj is None or obj.pk is None:
            return "Save the war and set its ladder up, and the payout appears here."
        from .payouts import plan

        owed = plan(obj)
        if not owed:
            return "Nothing to pay out: either the ladder is empty, or nobody has reached a rung."
        shown = owed[:40]
        # the discord id rather than the primary key: it is the only one of the two that can be
        # pasted into Discord to find out who this is
        discord_ids = dict(
            Player.objects.filter(pk__in=[entry.player_id for entry in shown]).values_list("pk", "discord_id")
        )
        rows = (
            (f"{entry.points:,} points", str(discord_ids.get(entry.player_id, entry.player_id)), entry.summary)
            for entry in shown
        )
        table = format_html_join(mark_safe("<br>"), "{} — {} — {}", rows)
        footer = f"<br>… and {len(owed) - len(shown)} more player(s)." if len(owed) > len(shown) else ""
        head = "1 player is" if len(owed) == 1 else f"{len(owed)} players are"
        return format_html("{} owed something.<br><br>{}{}", head, table, mark_safe(footer))

    @admin.action(description="Hand out the rewards of the selected wars")
    def hand_out_rewards(self, request: HttpRequest, queryset):
        """
        Pay the ladder of every selected war.

        Idempotent by construction: each rung handed to each player writes a row under a unique
        constraint, so a second run finds it there and hands nothing over again.
        """
        from .payouts import hand_out

        for war in queryset:
            paid, already, players = hand_out(war)
            if not paid and not already:
                self.message_user(
                    request,
                    f"{war.name}: nothing to pay out. Either the ladder is empty or nobody reached a rung.",
                    level=messages.WARNING,
                )
                continue
            self.message_user(
                request,
                f"{war.name}: {paid} reward(s) handed to {players} player(s)"
                + (f", {already} were already paid." if already else "."),
                level=messages.SUCCESS,
            )

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
