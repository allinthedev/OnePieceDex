"""
The staff pages of the shop: the boosts that exist, what is on sale, what is running and what has been sold.
"""

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .boosts import describe
from .models import ActiveBoost, Boost, ShopOffer, ShopPurchase

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


@admin.register(Boost)
class BoostAdmin(admin.ModelAdmin):
    """
    The boosts staff have set up. One of these is not on sale by itself: an offer in a shop points at it.
    """

    save_on_top = True
    list_display = ("name", "kind", "magnitude", "duration_minutes", "special", "enabled")
    list_filter = ("kind", "enabled")
    search_fields = ("name", "description")
    autocomplete_fields = ("special",)
    fieldsets = [
        (None, {"fields": ["name", "emoji", "kind", "description", "enabled"]}),
        (
            "How strong, how long",
            {
                "fields": ["magnitude", "duration_minutes"],
                "description": "Buying a boost whose kind is already running adds its minutes to what is left "
                "rather than starting a second one. Boosts of different kinds all run at once.",
            },
        ),
        (
            "Chance of a special",
            {
                "fields": ["special"],
                "description": "Only read by a boost of that kind. Name the special whose chance goes up — the "
                "Christmas one — so the hour raises that and nothing else.",
            },
        ),
        (
            "A burst of spawns",
            {
                "fields": ["spawns", "channel_id"],
                "description": "Only read by a boost of that kind. The burst goes out on the main server, in "
                "the channel named here or in its spawn channel.",
            },
        ),
        ("Announcement", {"fields": ["announce"]}),
    ]

    @admin.display(description="What it does")
    def effect(self, obj: Boost) -> str:
        return describe(obj.kind, obj.magnitude, obj.spawns)


@admin.register(ShopOffer)
class ShopOfferAdmin(admin.ModelAdmin):
    """
    What a pass's currency buys. A treasure offer points at one of the pass's own reward bundles, so a card
    sold here is set up exactly like a card a tier hands out.
    """

    save_on_top = True
    list_display = (
        "name",
        "event_pass",
        "kind",
        "price",
        "price_berries",
        "state",
        "sold",
        "stock",
        "per_player",
        "enabled",
    )
    list_filter = ("event_pass", "kind", "enabled", "from_crew_pot")
    search_fields = ("name", "description")
    autocomplete_fields = ("boost", "reward")
    readonly_fields = ("sold", "created_at")
    fieldsets = [
        (None, {"fields": ["event_pass", "name", "emoji", "description", "kind", "position", "enabled"]}),
        (
            "What it costs",
            {
                "fields": ["price", "price_berries"],
                "description": "Fill one, or both. An offer priced both ways asks the player which "
                "they want to pay with; one priced a single way just takes it. An offer with neither "
                "price cannot be saved.",
            },
        ),
        (
            "What it sells",
            {
                "fields": ["boost", "reward"],
                "description": "Fill the one that matches the kind above: a boost, or a reward bundle of "
                "treasures and berries.",
            },
        ),
        (
            "Limits",
            {
                "fields": ["stock", "sold", "per_player", "from_crew_pot"],
                "description": "An empty stock means as many as players can afford. Zero per player means no "
                "limit of their own.",
            },
        ),
        ("When", {"fields": ["starts_at", "ends_at"], "description": "Times are UTC. Both can be left empty."}),
    ]

    @admin.display(description="State")
    def state(self, obj: ShopOffer | None):
        if obj is None or obj.pk is None:
            return "Save it and it shows up in the shop."
        if obj.sold_out:
            return mark_safe("<span style='color: crimson'>Sold out</span>")
        if obj.is_on_sale():
            return mark_safe("<span style='color: green'><b>On sale</b></span>")
        now = timezone.now()
        if obj.starts_at and now < obj.starts_at:
            return format_html("Opens {}", f"{obj.starts_at:%Y-%m-%d %H:%M}")
        if obj.ends_at and now > obj.ends_at:
            return "Closed"
        return "Off"


@admin.register(ActiveBoost)
class ActiveBoostAdmin(admin.ModelAdmin):
    """
    The boosts running right now. The bot rebuilds its own picture of these every half minute, so stopping one
    here takes up to that long to be felt.
    """

    list_display = ("label", "kind", "magnitude", "started_at", "ends_at", "state", "bought_by")
    list_filter = ("kind", "started_at")
    readonly_fields = ("boost", "kind", "magnitude", "special", "bought_by", "started_at")
    actions = ("stop_now", "announce_again")
    date_hierarchy = "started_at"

    @admin.display(description="State")
    def state(self, obj: ActiveBoost):
        if obj.is_live():
            return mark_safe("<span style='color: green'><b>Running</b></span>")
        return "Over" if obj.ends_at <= timezone.now() else "Waiting"

    @admin.action(description="Stop the selected boosts now")
    def stop_now(self, request: "HttpRequest", queryset: "QuerySet[ActiveBoost]"):
        count = queryset.filter(ends_at__gt=timezone.now()).update(ends_at=timezone.now())
        self.message_user(
            request,
            f"{count} stopped. The bot picks it up within half a minute.",
            messages.SUCCESS if count else messages.WARNING,
        )

    @admin.action(description="Announce the selected boosts again")
    def announce_again(self, request: "HttpRequest", queryset: "QuerySet[ActiveBoost]"):
        count = queryset.update(announced_at=None)
        self.message_user(request, f"{count} will be announced again.", messages.SUCCESS)


@admin.register(ShopPurchase)
class ShopPurchaseAdmin(admin.ModelAdmin):
    """Every sale, so a stock can be audited and a refund explained."""

    list_display = ("created_at", "offer", "player", "crew", "price", "paid_with", "summary")
    list_filter = ("offer__event_pass", "offer", "paid_with", "crew", "created_at")
    search_fields = ("player__discord_id", "summary")
    list_select_related = ("offer", "player", "crew")
    readonly_fields = ("offer", "player", "crew", "price", "paid_with", "summary", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False
