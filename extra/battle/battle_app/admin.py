from typing import TYPE_CHECKING

from django.contrib import admin

from .models import (
    BattleItem,
    BattleRecord,
    BattleSession,
    BattleSettings,
    Buff,
    EquipAffinity,
    EquipResistance,
    GroupMatchup,
    Matchup,
    PlayerBattleItem,
)

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(Buff)
class BuffAdmin(admin.ModelAdmin):
    autocomplete_fields = ("ball", "special")
    list_display = ("display", "health", "attack", "capacity_summary")
    list_filter = ("capacity_effect",)
    search_fields = ("ball__country", "special__name")
    fieldsets = [
        (
            None,
            {
                "description": "Set either a treasure or a special, never both. A row on a special applies to "
                "every treasure of it that has no row of its own.",
                "fields": ["ball", "special", "health", "attack"],
            },
        ),
        (
            "Capacity",
            {
                "description": "What this treasure's Capacity does in a battle. Its <b>name</b> comes from the "
                "treasure itself (Treasures, “capacity name”) and every treasure already has one; only "
                "the effect is set here. Left on the plain special attack, Capacity hits for the default "
                "multiplier in the battle settings.",
                "fields": ["capacity_effect", "capacity_value"],
            },
        ),
    ]

    @admin.display(description="Capacity")
    def capacity_summary(self, obj: Buff) -> str:
        return obj.capacity_summary


@admin.register(BattleSettings)
class BattleSettingsAdmin(admin.ModelAdmin):
    autocomplete_fields = ("character_group", "weapon_group", "fruit_group")
    fieldsets = [
        (
            "Combat",
            {
                "description": (
                    "How fast a battle goes is mostly the <b>health multiplier</b>: every treasure has "
                    "about as much attack as health, so without it a hit takes most of an equal "
                    "opponent's health."
                ),
                "fields": [
                    "health_multiplier",
                    "attack_variance_min",
                    "attack_variance_max",
                    "crit_chance",
                    "crit_multiplier",
                    "crit_fail_multiplier",
                    "dodge_chance",
                    "heal_percent_min",
                    "heal_percent_max",
                    "heal_uses_per_battle",
                    "capacity_uses_per_battle",
                    "default_capacity_multiplier",
                    "turn_timeout_seconds",
                    "max_deck_size",
                ]
            },
        ),
        (
            "Tier-based damage scaling",
            {
                "description": (
                    "A tier is a band of rarities, cut by the bounds below. A lower rarity number is a rarer "
                    "card, so \"enemy is a tier higher\" means the enemy is rarer than your attacker. The "
                    "multipliers run from 0.9 to 1.0 by default: a gap in rarity never costs more than 10% of "
                    "the damage."
                ),
                "fields": [
                    "tier_bounds",
                    "tier_same_multiplier",
                    "tier_enemy_1_higher_multiplier",
                    "tier_enemy_2plus_higher_multiplier",
                    "tier_enemy_1_lower_multiplier",
                    "tier_enemy_2plus_lower_multiplier",
                    "tier_enemy_2plus_lower_bonus_crit_chance",
                ],
            },
        ),
        (
            "Special card bonuses",
            {
                "description": "Flat ATK/HP bonuses for special cards in battle, matching /boss fights.",
                "fields": ["haki_special_bonus", "shiny_special_bonus", "mythical_special_bonus"],
            },
        ),
        (
            "Equipment",
            {
                "description": (
                    "Only characters fight; a weapon and a devil fruit are attached to them. Which treasure "
                    "plays which part is read from its groups. The share of an item's stats each character "
                    "gets is set line by line in <b>Equip affinities</b>; the default below only applies "
                    "when no line there says anything about the pair."
                ),
                "fields": [
                    "character_group",
                    "weapon_group",
                    "fruit_group",
                    "default_equip_percent",
                    "full_set_bonus_percent",
                    "resistance_floor",
                    "resistance_ceiling",
                ],
            },
        ),
        (
            "Anti-abuse earnings",
            {
                "fields": [
                    "guaranteed_daily_wins",
                    "guaranteed_win_reward",
                    "performance_base_reward",
                    "performance_scale_min",
                    "performance_scale_max",
                    "max_rewarded_wins_per_opponent_per_day",
                ]
            },
        ),
    ]

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return super().has_add_permission(request) and BattleSettings.objects.first() is None

    def has_delete_permission(self, request: "HttpRequest", obj: BattleSettings | None = None) -> bool:
        return False


@admin.register(EquipAffinity)
class EquipAffinityAdmin(admin.ModelAdmin):
    """
    The share of an item's stats a character gets. The most precise line wins: a character with an exact
    item, then a character with a kind of item, then a kind of item for anybody.
    """

    autocomplete_fields = ("character", "item", "item_group")
    list_display = ("who", "what", "percent", "layer", "note")
    list_editable = ("percent",)
    list_filter = ("item_group",)
    list_select_related = ("character", "item", "item_group")
    search_fields = ("character__country", "item__country", "item_group__name", "note")
    list_per_page = 100

    @admin.display(description="Character", ordering="character__country")
    def who(self, obj: EquipAffinity) -> str:
        return obj.character.country if obj.character_id else "Anybody"

    @admin.display(description="Item")
    def what(self, obj: EquipAffinity) -> str:
        return obj.item.country if obj.item_id else f"any of “{obj.item_group}”"

    @admin.display(description="Layer")
    def layer(self, obj: EquipAffinity) -> str:
        if obj.character_id and obj.item_id:
            return "2 · their own item"
        if obj.character_id:
            return "3 · a kind they master"
        return "1 · default of a kind"


@admin.register(EquipResistance)
class EquipResistanceAdmin(admin.ModelAdmin):
    """What a defender's equipment does to the damage coming in, depending on what the attacker wears."""

    autocomplete_fields = ("character", "equipped_item", "against_item", "against_group")
    list_display = ("__str__", "multiplier", "note")
    list_editable = ("multiplier",)
    list_filter = ("against_group",)
    list_select_related = ("character", "equipped_item", "against_item", "against_group")
    search_fields = (
        "character__country",
        "equipped_item__country",
        "against_item__country",
        "against_group__name",
        "note",
    )
    list_per_page = 100


@admin.register(Matchup)
class MatchupAdmin(admin.ModelAdmin):
    """
    Who beats whom, whatever they wear: this attacker against this defender. A line here always wins over
    the bond of a group the two share.
    """

    autocomplete_fields = ("attacker", "defender")
    list_display = ("attacker", "defender", "damage_multiplier", "note")
    list_editable = ("damage_multiplier",)
    list_select_related = ("attacker", "defender")
    search_fields = ("attacker__country", "defender__country", "note")


@admin.register(GroupMatchup)
class GroupMatchupAdmin(admin.ModelAdmin):
    """A bond between the members of one group, applied when both fighters belong to it."""

    autocomplete_fields = ("group",)
    list_display = ("group", "damage_multiplier", "note")
    list_editable = ("damage_multiplier",)
    list_select_related = ("group",)
    search_fields = ("group__name", "note")


@admin.register(BattleRecord)
class BattleRecordAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player1", "player2", "winner")
    list_display = ("player1", "player2", "winner", "wager_amount", "winner_earnings", "turns", "created_at")
    list_filter = ("created_at",)
    search_fields = ("player1__discord_id", "player2__discord_id", "winner__discord_id")
    ordering = ["-created_at"]


@admin.register(BattleItem)
class BattleItemAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "effect_type", "effect_value", "enabled")
    list_editable = ("price", "enabled")
    list_filter = ("effect_type", "enabled")
    search_fields = ("name",)


@admin.register(PlayerBattleItem)
class PlayerBattleItemAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player", "item")
    list_display = ("player", "item", "quantity")
    search_fields = ("player__discord_id", "item__name")


@admin.register(BattleSession)
class BattleSessionAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player1", "player2")
    list_display = ("id", "channel_id", "player1", "player2", "wager_amount", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("player1__discord_id", "player2__discord_id", "channel_id")
    ordering = ["-updated_at"]
