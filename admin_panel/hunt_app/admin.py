import random

from django.contrib import admin, messages
from django.http import HttpRequest
from django.utils.html import format_html

from bd_models.models import Ball

from .models import Hunt, HuntCompletion, Poneglyph, PoneglyphClaim, PoneglyphRequirement


class PoneglyphInline(admin.TabularInline):
    model = Poneglyph
    extra = 1
    fields = ("position", "name", "hint", "opens_at", "draw_count", "draw_min_rarity", "draw_max_rarity")
    ordering = ("position", "pk")
    show_change_link = True


@admin.register(Hunt)
class HuntAdmin(admin.ModelAdmin):
    """
    A hunt is a handful of poneglyphs. Add them below, then open each one and give it the
    treasures to gather — by hand, or with the "Draw the treasures" action.
    """

    autocomplete_fields = ("reward_ball", "reward_special")
    save_on_top = True
    inlines = [PoneglyphInline]
    readonly_fields = ("banner_preview", "created_at")
    fieldsets = [
        (None, {"fields": ["name", "description", "mode", "enabled"]}),
        (
            "When",
            {
                "description": "Both can be left empty for a hunt that is simply always on. Times are UTC. A "
                "poneglyph can also have its own opening date, to release one a week.",
                "fields": ["starts_at", "ends_at"],
            },
        ),
        (
            "Pictures",
            {
                "description": "Animated GIFs work here and play in Discord. One stone picture is reused for "
                "every poneglyph, which is the point: a nine-stone hunt needs one illustration, not nine.",
                "fields": [
                    "poneglyph_image",
                    "poneglyph_emoji",
                    "image",
                    "completed_image",
                    "announce_completion",
                    "banner_preview",
                ],
            },
        ),
        (
            "Reward for finishing",
            {
                "description": "Handed over once every poneglyph of the hunt is held — by the player in an "
                "individual hunt, by the crew in a crew one.",
                "fields": ["reward_money", "reward_ball", "reward_special", "completion_message"],
            },
        ),
    ]

    list_display = ("name", "mode", "enabled", "poneglyph_count", "reward_money", "starts_at", "ends_at")
    list_editable = ("enabled",)
    list_filter = ("mode", "enabled", "starts_at", "ends_at")
    search_fields = ("name", "description")

    @admin.display(description="Poneglyphs")
    def poneglyph_count(self, obj: Hunt) -> int:
        return obj.poneglyphs.count()

    @admin.display(description="Preview")
    def banner_preview(self, obj: Hunt | None):
        if obj is None or not obj.image:
            return "Upload a banner and it shows up here once saved."
        return format_html('<img src="/media/{}" style="max-width: 480px" />', obj.image.name)


class PoneglyphRequirementInline(admin.TabularInline):
    model = PoneglyphRequirement
    extra = 1
    autocomplete_fields = ("ball", "special")
    fields = ("ball", "special", "amount", "consume")


@admin.register(Poneglyph)
class PoneglyphAdmin(admin.ModelAdmin):
    """
    One stone and the treasures it asks for.

    Fill the set in by hand, or select the poneglyphs in the list and run "Draw the treasures":
    the bot picks them at random inside the rarity range and you can edit the result before the
    stone opens.
    """

    save_on_top = True
    inlines = [PoneglyphRequirementInline]
    fieldsets = [
        (None, {"fields": ["hunt", "name", "hint", "position"]}),
        (
            "Opening",
            {
                "description": "Leave the opening date empty to open with the hunt. The announcement date is "
                "written by the bot; clear it to have the stone announced again.",
                "fields": ["opens_at", "announced_at"],
            },
        ),
        (
            "Drawing the treasures",
            {
                "description": "Used by the <b>Draw the treasures</b> action in the poneglyph list. It replaces "
                "whatever is in the set below, so draw first and adjust afterwards.",
                "fields": ["draw_count", "draw_min_rarity", "draw_max_rarity"],
            },
        ),
    ]
    list_display = ("name", "hunt", "position", "requirement_count", "opens_at", "announced_at")
    list_filter = ("hunt",)
    search_fields = ("name", "hint")
    list_select_related = ("hunt",)
    ordering = ("hunt", "position")
    actions = ["draw_requirements"]

    @admin.display(description="Treasures asked for")
    def requirement_count(self, obj: Poneglyph) -> int:
        return obj.requirements.count()

    @admin.action(description="Draw the treasures of the selected poneglyphs")
    def draw_requirements(self, request: HttpRequest, queryset):
        """
        Fill each selected stone's set with treasures picked at random.

        Disabled treasures and ones at a rarity of 0 are left out: they never spawn, so asking
        for them would make a poneglyph impossible. Anything already in the set is replaced.
        """
        for poneglyph in queryset:
            pool = Ball.objects.filter(enabled=True, rarity__gt=0)
            if poneglyph.draw_min_rarity is not None:
                pool = pool.filter(rarity__gte=poneglyph.draw_min_rarity)
            if poneglyph.draw_max_rarity is not None:
                pool = pool.filter(rarity__lte=poneglyph.draw_max_rarity)
            ball_ids = list(pool.values_list("pk", flat=True))
            wanted = max(poneglyph.draw_count, 1)
            if len(ball_ids) < wanted:
                self.message_user(
                    request,
                    f"{poneglyph.name}: only {len(ball_ids)} treasure(s) match that rarity range, "
                    f"{wanted} needed. Widen the range.",
                    level=messages.ERROR,
                )
                continue
            drawn = random.sample(ball_ids, wanted)
            poneglyph.requirements.all().delete()
            PoneglyphRequirement.objects.bulk_create(
                [PoneglyphRequirement(poneglyph=poneglyph, ball_id=ball_id) for ball_id in drawn]
            )
            self.message_user(
                request, f"{poneglyph.name}: drew {wanted} treasure(s).", level=messages.SUCCESS
            )


@admin.register(PoneglyphClaim)
class PoneglyphClaimAdmin(admin.ModelAdmin):
    """Read-only: claims are written by the bot when a set is handed in."""

    list_display = ("poneglyph", "hunt_name", "player", "crew", "claimed_at")
    list_filter = ("poneglyph__hunt", "crew", "claimed_at")
    search_fields = ("player__discord_id", "poneglyph__name")
    list_select_related = ("poneglyph", "poneglyph__hunt", "player", "crew")
    date_hierarchy = "claimed_at"

    @admin.display(description="Hunt")
    def hunt_name(self, obj: PoneglyphClaim) -> str:
        return obj.poneglyph.hunt.name

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return False


@admin.register(HuntCompletion)
class HuntCompletionAdmin(admin.ModelAdmin):
    """Read-only: written by the bot when a hunt's reward is handed over."""

    list_display = ("hunt", "player", "crew", "completed_at", "reward_instance")
    list_filter = ("hunt", "crew", "completed_at")
    search_fields = ("player__discord_id",)
    list_select_related = ("hunt", "player", "crew")
    date_hierarchy = "completed_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return False
