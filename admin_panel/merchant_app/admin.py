from typing import TYPE_CHECKING

from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe

from bd_models import treasure_value

from .models import GlobalShop, MerchantItem, MerchantSettings

if TYPE_CHECKING:
    from django.db.models import QuerySet


@admin.register(MerchantSettings)
class MerchantSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: HttpRequest) -> bool:
        return super().has_add_permission(request) and MerchantSettings.objects.first() is None

    def has_delete_permission(self, request: HttpRequest, obj: MerchantSettings | None = None) -> bool:
        return False


@admin.register(MerchantItem)
class MerchantItemAdmin(admin.ModelAdmin):
    autocomplete_fields = ("ball", "special", "boost", "event_pass")
    save_on_top = True
    readonly_fields = ("hotel_value",)
    fieldsets = [
        (None, {"fields": ["name", "kind", "rarity", "stock", "per_player_limit"]}),
        (
            "What it costs",
            {
                "description": "Fill the berry price OR the currency price, never both. To sell the same "
                "thing both ways, make the item a second time: each copy then has its own stock and its own "
                "limit per player.",
                "fields": ["prize", "event_pass", "price_currency"],
            },
        ),
        (
            "Time range",
            {
                "fields": ["start_date", "end_date"],
                "description": "An optional time range to make the item limited in time. As soon "
                "as the item is loaded in the bot's cache, it will automatically load and unload "
                "at the specified time.",
            },
        ),
        (
            "Rewards",
            {
                "description": "A treasure item needs a treasure, a boost item needs a boost. The other one "
                "stays empty.",
                "fields": ["ball", "special", "hotel_value", "boost"],
            },
        ),
    ]

    list_display = (
        "name",
        "kind",
        "prize",
        "currency_price",
        "rarity",
        "stock",
        "per_player_limit",
        "ball_name",
        "sale_value",
        "special_name",
    )
    list_editable = ("rarity", "prize", "stock")
    list_filter = ("kind", "event_pass", "created_at", "start_date", "end_date")
    list_select_related = ("ball", "special", "boost", "event_pass")

    search_fields = ["name", "pk"]

    @admin.display(description="Hotel value")
    def sale_value(self, obj: MerchantItem):
        """What the Hotel pays for the treasure behind this item, to price it against."""
        if obj.ball_id is None:
            return "-"
        return treasure_value.short_label(obj.ball.rarity)

    @admin.display(description="In currency")
    def currency_price(self, obj: MerchantItem):
        if not obj.price_currency:
            return "-"
        event_pass = obj.event_pass
        label = f"{event_pass.currency_emoji} {event_pass.currency_name}".strip() if event_pass else "?"
        return f"{obj.price_currency:,} {label}".strip()

    @admin.display(description="Hotel de Vente")
    def hotel_value(self, obj: MerchantItem | None):
        if obj is None or obj.ball_id is None:
            return "Pick the treasure below and save, and what the Hotel pays for it shows up here."
        lines = treasure_value.detail_lines(obj.ball.rarity)
        return format_html_join(mark_safe("<br>"), "{}", ((line,) for line in lines))

    @admin.display(description="Name of the ball")
    def ball_name(self, obj: MerchantItem):
        if obj.ball_id is None:
            return obj.boost.name if obj.boost_id else "-"
        return obj.ball.country

    @admin.display(description="Name of the special")
    def special_name(self, obj: MerchantItem):
        return obj.special.name if obj.special else "-"


@admin.register(GlobalShop)
class GlobalShopAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "name",
        "item_count",
        "happy_hour_discount_percent",
        "auto_announce_weekday",
        "announced_at",
    )
    search_fields = ("name",)
    filter_horizontal = ("items",)
    save_on_top = True
    fieldsets = [
        (None, {"fields": ["name", "banner", "items"]}),
        (
            "Announcement",
            {
                "description": "The bot posts this in every spawn channel when an admin runs "
                "<code>merchant announce &lt;shop name&gt;</code>, or on the weekly slot below. Saving the shop "
                "here does not announce it: the command or the schedule is what sends the message and starts "
                "the happy hour.",
                "fields": ["announcement_text", "happy_hour_minutes", "happy_hour_discount_percent", "announced_at"],
            },
        ),
        (
            "Weekly schedule",
            {
                "description": "Leave the day empty and the shop is only ever announced by hand. The hour is "
                "UTC, and a shop announced within the last twelve hours is skipped, so the slot cannot fire twice.",
                "fields": ["auto_announce_weekday", "auto_announce_hour"],
            },
        ),
    ]

    @admin.display(description="Number of items")
    def item_count(self, obj: GlobalShop) -> int:
        return obj.items.count()

    def get_queryset(self, request: "HttpRequest") -> "QuerySet[GlobalShop]":
        return super().get_queryset(request).prefetch_related("items")
