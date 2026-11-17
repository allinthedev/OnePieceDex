from django.contrib import admin, messages
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from . import pack_value
from .models import BerryTransaction, CurrencySettings, DailyBonusRole, DailyBonusServer, Item, ItemBall


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    autocomplete_fields = ("special",)
    save_on_top = True
    readonly_fields = ("suggested_price",)
    fieldsets = [
        (None, {"fields": ["name", "description", "prize", "suggested_price"]}),
        (
            "Shop display",
            {
                "description": "Reorder the packs directly from the list by editing their position.",
                "fields": ["section", "position"],
            },
        ),
        ("Configure Reward", {"fields": ["minimum_rarity", "maximum_rarity", "special"]}),
        (
            "Pack contents and odds",
            {
                "description": "Left alone, a pack hands over a single treasure drawn exactly like a spawn, "
                "which is how every pack behaved before these settings existed. Raise the treasure count to "
                "turn it into a real pack, and use the three settings below it to decide how generous it is.",
                "fields": [
                    "cards",
                    "packs_per_command",
                    "rarity_flatten",
                    "rare_rarity",
                    "luck_ramp",
                    "pity_every",
                    "special_chance_factor",
                ],
            },
        ),
    ]
    list_display = (
        "name",
        "section",
        "position",
        "prize",
        "suggested",
        "cards",
        "minimum_rarity",
        "maximum_rarity",
    )
    list_editable = ("section", "position", "prize", "cards", "minimum_rarity", "maximum_rarity")
    list_filter = ("section", "created_at", "special")
    ordering = ["section", "position", "prize"]
    list_per_page = 100

    search_fields = ("name",)

    def get_queryset(self, request: HttpRequest):
        # the suggested price reads each pack's treasure list, so fetch them with the page
        # rather than one query per row
        return super().get_queryset(request).prefetch_related("balls__ball")

    @admin.display(description="Suggested")
    def suggested(self, obj: Item):
        """
        The suggested price next to the one being charged, so a list can be read down the
        column and a mispriced pack spotted without opening it.
        """
        value = pack_value.value_of(obj)
        if value is None:
            return "—"
        if not obj.prize:
            return format_html("{} <span style='color: gray'>(free)</span>", f"{value.recommended:,}")
        gap = round((obj.prize - value.recommended) / value.recommended * 100)
        if abs(gap) <= 10:
            return format_html("{} <span style='color: green'>✓</span>", f"{value.recommended:,}")
        colour = "crimson" if gap < 0 else "darkorange"
        return format_html(
            "{} <span style='color: {}'>({}{}%)</span>", f"{value.recommended:,}", colour, "+" if gap > 0 else "", gap
        )

    @admin.display(description="Suggested price")
    def suggested_price(self, obj: Item | None):
        """
        What the Hotel de Vente says this pack's contents are worth, and the price that follows.

        Only ever a suggestion: the price charged is the editable one just above. The margin it
        adds lives on the currency settings page.
        """
        if obj is None or obj.pk is None:
            return (
                "Save the pack and its suggested price appears here, worked out from the treasures it "
                "can hand out. Nothing is charged until you set a price yourself."
            )
        value = pack_value.value_of(obj)
        if value is None:
            return "No suggestion: either the Hotel de Vente is not installed, or this pack has nothing to give."

        if not obj.prize:
            verdict = "This pack is free."
        else:
            gap = round((obj.prize - value.recommended) / value.recommended * 100)
            if abs(gap) <= 10:
                verdict = f"Its price of {obj.prize:,} is in line with that."
            else:
                verdict = f"Its price of {obj.prize:,} is {abs(gap)}% {'above' if gap > 0 else 'below'} it."
        return format_html(
            "<strong>{}</strong> berries<br>"
            "{} of treasures on average, plus the {}% house margin.<br>"
            "{} of that could be sold straight back to the Hotel.<br>{}",
            f"{value.recommended:,}",
            f"{value.contents:,}",
            value.margin_percent,
            f"{value.liquid:,}",
            verdict,
        )


@admin.register(ItemBall)
class ItemBallAdmin(admin.ModelAdmin):
    list_display = ("item_name", "ball_name")

    @admin.display(description="Name of Item")
    def item_name(self, obj: ItemBall):
        return obj.item.name

    @admin.display(description="Name of Ball")
    def ball_name(self, obj: ItemBall):
        return obj.ball.country


@admin.register(CurrencySettings)
class CurrencySettingsAdmin(admin.ModelAdmin):
    fieldsets = [
        ("Spawn", {"fields": ["spawn_chance", "spawn_amount"]}),
        (
            "Daily streak rewards",
            {
                "fields": [
                    "base_daily_amount",
                    "day1_reward",
                    "day2_reward",
                    "day3_reward",
                    "day4_reward",
                    "day5_reward",
                    "day6_reward",
                    "day7_reward",
                    "streak_grace_hours",
                ]
            },
        ),
        (
            "Packs",
            {
                "description": "Only affects the price a pack's own page suggests. What a pack charges is set "
                "on the pack itself.",
                "fields": ["pack_price_margin_percent"],
            },
        ),
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return super().has_add_permission(request) and CurrencySettings.objects.first() is None

    def has_delete_permission(self, request: HttpRequest, obj: CurrencySettings | None = None) -> bool:
        return False


class DailyBonusRoleInline(admin.TabularInline):
    model = DailyBonusRole
    extra = 1


@admin.register(DailyBonusServer)
class DailyBonusServerAdmin(admin.ModelAdmin):
    list_display = ("server_id",)
    search_fields = ("server_id",)
    inlines = [DailyBonusRoleInline]


@admin.register(BerryTransaction)
class BerryTransactionAdmin(admin.ModelAdmin):
    """
    Read-only history of every berry movement. Rows are written by the bot, never here —
    editing them by hand would defeat the point of having an audit trail.
    """

    list_display = ("created_at", "player_link", "signed_amount", "balance_after", "reason", "description", "server_id")
    list_filter = ("reason", "created_at")
    search_fields = ("player__discord_id", "description")
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    list_select_related = ("player",)
    list_per_page = 50
    actions = ["audit_balances"]

    @admin.display(description="Player", ordering="player__discord_id")
    def player_link(self, obj: BerryTransaction):
        """Links to this player's own history — the per-player view."""
        url = reverse("admin:currency_app_berrytransaction_changelist")
        return format_html('<a href="{}?q={}">{}</a>', url, obj.player.discord_id, obj.player)

    @admin.display(description="Amount", ordering="amount")
    def signed_amount(self, obj: BerryTransaction):
        color = "green" if obj.amount >= 0 else "crimson"
        # format_html turns its arguments into strings before formatting them, so the number
        # has to be rendered here rather than through a numeric format spec in the template
        return format_html('<span style="color: {}">{}</span>', color, f"{obj.amount:+,}")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: BerryTransaction | None = None) -> bool:
        return False

    @admin.action(description="Audit berry history of the selected players")
    def audit_balances(self, request: HttpRequest, queryset):
        """
        Replays every ledger row of each selected player, in order, and reports any break.

        This deliberately ignores the current filters and re-reads the player's full history:
        a check against a filtered subset would report gaps that aren't real. Two things are
        verified — that each row's `balance_after` equals the previous one plus the movement,
        and that the last row matches the balance the player actually has now.
        """
        player_ids = set(queryset.values_list("player_id", flat=True))
        for player_id in player_ids:
            rows = list(
                BerryTransaction.objects.filter(player_id=player_id)
                .select_related("player")
                .order_by("created_at", "pk")
            )
            if not rows:
                continue
            player = rows[0].player
            gaps = []
            previous = None
            for row in rows:
                if previous is not None and row.balance_after != previous + row.amount:
                    gaps.append(
                        f"#{row.pk} on {row.created_at:%Y-%m-%d %H:%M}: expected "
                        f"{previous + row.amount:,}, recorded {row.balance_after:,}"
                    )
                previous = row.balance_after

            if gaps:
                self.message_user(
                    request,
                    f"{player}: {len(gaps)} unexplained change(s) — berries moved outside the ledger. "
                    + "; ".join(gaps[:5])
                    + ("; ..." if len(gaps) > 5 else ""),
                    level=messages.ERROR,
                )
            if rows[-1].balance_after != player.money:
                self.message_user(
                    request,
                    f"{player}: current balance is {player.money:,} but the ledger ends at "
                    f"{rows[-1].balance_after:,}.",
                    level=messages.ERROR,
                )
            elif not gaps:
                self.message_user(
                    request, f"{player}: {len(rows)} movement(s), history is consistent.", level=messages.SUCCESS
                )
