"""
The staff pages of the Secret Santa.

`SantaGift.kind` is the one thing on these pages that must never reach a player: it says whether a parcel was
filled by its giver, paid for, or filled in by the bot because nobody turned up. Knowing that is what lets you
run the event; telling anyone would turn "no penalty for not giving" into a penalty.
"""

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import SantaEntry, SantaGift, SantaWish, SecretSanta

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


class WishInline(admin.TabularInline):
    model = SantaWish
    extra = 0
    fields = ("position", "ball")
    autocomplete_fields = ("ball",)
    ordering = ("position",)


@admin.register(SecretSanta)
class SecretSantaAdmin(admin.ModelAdmin):
    save_on_top = True
    list_display = ("name", "special", "signup_closes_at", "opens_at", "signed_up", "state", "enabled")
    list_filter = ("enabled", "special")
    search_fields = ("name", "description")
    autocomplete_fields = ("event_pass", "special")
    readonly_fields = ("state", "signed_up", "drawn_at", "filled_at", "created_at")
    fieldsets = [
        (None, {"fields": ["name", "emoji", "description", "enabled", "state", "signed_up"]}),
        (
            "What it hands out",
            {
                "fields": ["special", "event_pass", "price"],
                "description": "Every card in a parcel comes out as the special. The pass is where the currency "
                "comes from, for players who fill their parcel by paying rather than by giving a card of their "
                "own — a price of zero turns that way of filling it off.",
            },
        ),
        (
            "The stages",
            {
                "fields": ["signup_opens_at", "signup_closes_at", "wrap_until", "opens_at", "closes_at"],
                "description": "In order, and all UTC: people sign up, the chain is drawn with /santa admin "
                "draw, parcels are filled until the wrapping time, and then opened from the opening day.",
            },
        ),
        (
            "The lists",
            {
                "fields": ["wishlist_size", "min_rarity"],
                "description": "A LOWER rarity is a RARER treasure, so the floor is the rarest a card may be "
                "asked for: put the rarity of your T10 there and nothing rarer than a T10 can be wished for.",
            },
        ),
        (
            "Parcels nobody filled",
            {
                "fields": ["fill_the_rest", "announce_to", "announced_at"],
                "description": "Leave the filling on. It is what makes it true that there is no penalty for "
                "not giving: a parcel the bot filled and a parcel a player filled are identical to everyone "
                "but you.",
            },
        ),
        ("Filled by the bot", {"fields": ["drawn_at", "filled_at"], "classes": ["collapse"]}),
    ]

    @admin.display(description="Signed up")
    def signed_up(self, obj: SecretSanta | None) -> int:
        if obj is None or obj.pk is None:
            return 0
        return obj.entries.count()

    @admin.display(description="State")
    def state(self, obj: SecretSanta | None):
        if obj is None or obj.pk is None:
            return "Save it, then players can sign up."
        if not obj.enabled:
            return "Off"
        now = timezone.now()
        if obj.signups_open(now):
            return mark_safe("<span style='color: green'><b>Signing up</b></span>")
        if obj.drawn_at is None:
            return mark_safe("<span style='color: crimson'>Waiting to be drawn</span> — /santa admin draw")
        if obj.wrapping_open(now):
            filled = obj.gifts.count()
            owed = obj.entries.filter(gives_to__isnull=False).count()
            return mark_safe(f"<span style='color: green'><b>Wrapping</b></span>, {filled}/{owed} filled")
        if obj.opening_open(now):
            return mark_safe("<span style='color: green'><b>Opening</b></span>")
        return "Over" if now > obj.closes_at else "Between stages"


@admin.register(SantaEntry)
class SantaEntryAdmin(admin.ModelAdmin):
    """Who is in, and who they were drawn to give to. The chain, laid out."""

    inlines = (WishInline,)
    list_display = ("player", "santa", "joined_at", "gives_to", "listed", "filled")
    list_filter = ("santa",)
    search_fields = ("player__discord_id",)
    list_select_related = ("santa", "player", "gives_to", "gives_to__player")
    autocomplete_fields = ("player", "gives_to")
    readonly_fields = ("joined_at",)

    @admin.display(description="Wishes")
    def listed(self, obj: SantaEntry) -> int:
        return obj.wishes.count()

    @admin.display(description="Parcel filled", boolean=True)
    def filled(self, obj: SantaEntry) -> bool:
        return obj.gift_given.exists()


@admin.register(SantaGift)
class SantaGiftAdmin(admin.ModelAdmin):
    """
    Every parcel. `kind` is for you alone — see this module's note.
    """

    list_display = ("wrapped_at", "santa", "ball", "receiver", "kind", "opened_at")
    list_filter = ("santa", "kind", "opened_at")
    search_fields = ("ball__country", "receiver__player__discord_id", "giver__player__discord_id")
    list_select_related = ("santa", "ball", "receiver", "receiver__player", "giver")
    readonly_fields = (
        "santa",
        "giver",
        "receiver",
        "ball",
        "kind",
        "attack_bonus",
        "health_bonus",
        "roll_bonuses",
        "frame",
        "wrapped_at",
        "opened_at",
        "instance",
    )
    date_hierarchy = "wrapped_at"
    actions = ("let_them_open_again",)

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False

    @admin.action(description="Let the selected parcels be opened again")
    def let_them_open_again(self, request: "HttpRequest", queryset: "QuerySet[SantaGift]"):
        """For a parcel whose card was lost to something going wrong. The old card is not taken back."""
        count = queryset.filter(opened_at__isnull=False).update(opened_at=None, instance=None)
        self.message_user(
            request,
            f"{count} can be opened again. Whatever card they already made is left where it is.",
            messages.SUCCESS if count else messages.WARNING,
        )
