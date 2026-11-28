"""
Pure combat-resolution helpers for the Battle feature.

Kept independent of Discord/Django so the turn math can be read and adjusted in one place — the
cog owns the actual turn loop, persistence (serializing/deserializing BattleBall to/from
BattleSession.state) and Discord plumbing. Each function here takes plain values (already resolved
by the cog from the Matchup table, BattleSettings, etc.) and returns a small, renderable result.
"""

import random
from bisect import bisect_left
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from battle_app.models import BattleSettings


class BattleAction(str, Enum):
    ATTACK = "attack"
    CRIT = "crit"
    HEAL = "heal"
    CAPACITY = "capacity"


@dataclass
class BattleBall:
    """One card's live state within a battle. JSON-serializable via `to_dict`/`from_dict`."""

    instance_id: int
    ball_id: int
    name: str
    owner_id: int
    health: int
    max_health: int
    attack: int
    rarity: float = 1.0
    emoji: str = ""
    capacity_name: str = ""
    # what the Capacity action does, from the treasure's Buff row. Empty means the plain special attack
    capacity_effect: str = ""
    capacity_value: float = 0.0
    # the fighter's own attack and health, before anything it wears: what `attack` and `max_health` are
    # rebuilt from whenever its equipment changes while the deck is being put together
    base_attack: int = 0
    base_health: int = 0
    # what it wears, at most one entry per slot ("weapon", "fruit"). Each entry is a plain dict so the whole
    # card stays JSON: slot, instance_id, ball_id, name, emoji, attack, health, percent, group_ids. See
    # `loadout.py` for what they mean and how they add up.
    equipment: list = field(default_factory=list)
    dead: bool = False
    heal_uses: int = 0
    capacity_uses: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BattleBall":
        """
        Read a card back out of a battle's stored state, ignoring anything it does not recognise.

        A battle lives in `BattleSession.state` as JSON across restarts, so a card written by an older
        version of this file has to be readable by a newer one. Dropping unknown keys and letting the
        missing ones fall back to their defaults is what keeps a deploy from stranding a battle that is
        halfway through, with a wager already escrowed.
        """
        known = {f.name for f in fields(cls)}
        return cls(**{name: value for name, value in data.items() if name in known})


class ActionResult(NamedTuple):
    text: str
    damage: int = 0
    healed: int = 0
    crit: bool = False
    dodged: bool = False


# the upper bound of every rarity tier but the last, used when the settings hold none. Cut on how the
# treasures are actually spread, so that each tier holds a fair share of them
DEFAULT_TIER_BOUNDS = (15, 35, 85, 140, 180)


def tier_of(rarity: float, bounds) -> int:
    """
    The tier a rarity falls in, 0 being the rarest. With bounds of 15 and 35, T1 to T15 is tier 0, T16 to T35
    tier 1, and everything past the last bound shares the final tier.
    """
    return bisect_left(sorted(bounds), rarity)


def tier_scaling(attacker_rarity: float, defender_rarity: float, settings: "BattleSettings") -> tuple[float, float]:
    """
    Damage multiplier and bonus crit chance from the tier gap between attacker and defender.

    A tier is a band of rarities, not a rarity: rarity runs from 1 to over 200, so comparing the raw numbers
    made a T20 and a T22 "two tiers apart", and nearly every fight in the game fell on one of the two extreme
    multipliers. A LOWER rarity number is a rarer card, so a positive `tier_diff` means the defender is more
    common (an easier matchup) than the attacker.
    """
    bounds = getattr(settings, "tier_bounds", None) or DEFAULT_TIER_BOUNDS
    tier_diff = tier_of(defender_rarity, bounds) - tier_of(attacker_rarity, bounds)
    if tier_diff >= 2:
        return settings.tier_enemy_2plus_lower_multiplier, settings.tier_enemy_2plus_lower_bonus_crit_chance
    if tier_diff == 1:
        return settings.tier_enemy_1_lower_multiplier, 0.0
    if tier_diff == 0:
        return settings.tier_same_multiplier, 0.0
    if tier_diff == -1:
        return settings.tier_enemy_1_higher_multiplier, 0.0
    return settings.tier_enemy_2plus_higher_multiplier, 0.0


def _damaging_action(
    action: BattleAction,
    attacker: BattleBall,
    defender: BattleBall,
    settings: "BattleSettings",
    matchup_multiplier: float,
    item_effect: tuple[str, float] | None,
    lore: bool | None = None,
) -> ActionResult:
    if random.random() < settings.dodge_chance:
        return ActionResult(text=f"**{defender.name}** dodges {attacker.name}'s attack!", dodged=True)

    tier_multiplier, tier_bonus_crit = tier_scaling(attacker.rarity, defender.rarity, settings)
    guaranteed_crit = item_effect is not None and item_effect[0] == "guaranteed_crit"

    if action is BattleAction.CRIT:
        crit = guaranteed_crit or (random.random() < settings.crit_chance + tier_bonus_crit)
        action_multiplier = settings.crit_multiplier if crit else settings.crit_fail_multiplier
    else:
        # A plain Attack has no baseline crit chance — only a favorable tier gap can trigger one.
        crit = guaranteed_crit or (tier_bonus_crit > 0 and random.random() < tier_bonus_crit)
        action_multiplier = settings.crit_multiplier if crit else 1.0

    if item_effect is not None and item_effect[0] == "attack_boost":
        action_multiplier *= item_effect[1]

    base = attacker.attack * random.uniform(settings.attack_variance_min, settings.attack_variance_max)
    damage = max(1, round(base * matchup_multiplier * tier_multiplier * action_multiplier))
    defender.health = max(0, defender.health - damage)
    if defender.health <= 0:
        defender.dead = True

    verb = "lands a **CRITICAL HIT** on" if crit else "hits"
    # `lore` is whether who the two fighters are is in the attacker's favour. The multiplier also
    # carries what they wear, and a sword that bites is not a rivalry: the cog says which is which
    edge = " (lore advantage!)" if (matchup_multiplier > 1.0 if lore is None else lore) else ""
    text = f"**{attacker.name}** {verb} **{defender.name}** for **{damage}**{edge}"
    if defender.dead:
        text += f" — {defender.name} is defeated!"
    return ActionResult(text=text, damage=damage, crit=crit)


def _attack_instead(
    reason: str,
    attacker: BattleBall,
    defender: BattleBall,
    settings: "BattleSettings",
    matchup_multiplier: float,
    lore: bool | None = None,
) -> ActionResult:
    """
    The plain attack a fighter falls back on when what it was asked for is used up. It used to be announced
    and not thrown, which cost the turn. No item goes into it: one meant for the action that could not
    happen does not carry over to another one.
    """
    result = _damaging_action(BattleAction.ATTACK, attacker, defender, settings, matchup_multiplier, None, lore)
    return result._replace(text=f"{reason}\n{result.text}")


def _resolve_heal(
    attacker: BattleBall,
    defender: BattleBall,
    settings: "BattleSettings",
    matchup_multiplier: float,
    item_effect: tuple[str, float] | None,
    lore: bool | None = None,
) -> ActionResult:
    if attacker.heal_uses >= settings.heal_uses_per_battle:
        return _attack_instead(
            f"**{attacker.name}** has no more heals left this battle and attacks instead!",
            attacker,
            defender,
            settings,
            matchup_multiplier,
            lore,
        )

    percent = random.uniform(settings.heal_percent_min, settings.heal_percent_max)
    if item_effect is not None and item_effect[0] == "extra_heal":
        percent += item_effect[1]

    missing = attacker.max_health - attacker.health
    healed = min(missing, round(attacker.max_health * percent / 100))
    attacker.health += healed
    attacker.heal_uses += 1
    return ActionResult(text=f"**{attacker.name}** heals for **{healed}** HP!", healed=healed)


def _resolve_capacity(
    attacker: BattleBall,
    defender: BattleBall,
    settings: "BattleSettings",
    matchup_multiplier: float,
    item_effect: tuple[str, float] | None,
    lore: bool | None = None,
) -> ActionResult:
    if attacker.capacity_uses >= settings.capacity_uses_per_battle:
        return _attack_instead(
            f"**{attacker.name}** has already used its Capacity this battle and attacks instead!",
            attacker,
            defender,
            settings,
            matchup_multiplier,
            lore,
        )

    attacker.capacity_uses += 1
    label = attacker.capacity_name or "Capacity"
    effect_type = attacker.capacity_effect
    value = attacker.capacity_value if attacker.capacity_value > 0 else None

    if effect_type == "heal_percent" and isinstance(value, (int, float)):
        missing = attacker.max_health - attacker.health
        healed = min(missing, round(attacker.max_health * value / 100))
        attacker.health += healed
        return ActionResult(text=f"**{attacker.name}** uses **{label}** and heals for **{healed}** HP!", healed=healed)

    # a Capacity that hurts is a damaging action like the others, and the dodge chance is documented as
    # holding for any of them. A dodged Capacity is spent all the same: it was thrown
    if random.random() < settings.dodge_chance:
        return ActionResult(text=f"**{defender.name}** dodges {attacker.name}'s **{label}**!", dodged=True)

    tier_multiplier, tier_bonus_crit = tier_scaling(attacker.rarity, defender.rarity, settings)

    if effect_type == "flat_damage" and isinstance(value, (int, float)):
        damage = max(1, round(value * matchup_multiplier * tier_multiplier))
        defender.health = max(0, defender.health - damage)
        if defender.health <= 0:
            defender.dead = True
        text = f"**{attacker.name}** unleashes **{label}** on **{defender.name}** for **{damage}**"
        text += f" — {defender.name} is defeated!" if defender.dead else "!"
        return ActionResult(text=text, damage=damage)

    multiplier = value if effect_type == "damage_multiplier" and isinstance(value, (int, float)) else None
    multiplier = multiplier or settings.default_capacity_multiplier
    if item_effect is not None and item_effect[0] == "attack_boost":
        multiplier *= item_effect[1]
    crit = tier_bonus_crit > 0 and random.random() < tier_bonus_crit
    if crit:
        multiplier *= settings.crit_multiplier

    base = attacker.attack * random.uniform(settings.attack_variance_min, settings.attack_variance_max)
    damage = max(1, round(base * matchup_multiplier * tier_multiplier * multiplier))
    defender.health = max(0, defender.health - damage)
    if defender.health <= 0:
        defender.dead = True
    text = f"**{attacker.name}** unleashes **{label}** on **{defender.name}** for **{damage}**"
    text += f" — {defender.name} is defeated!" if defender.dead else "!"
    if crit:
        text += "\n💥 **CRITICAL HIT!**"
    return ActionResult(text=text, damage=damage, crit=crit)


def resolve_action(
    action: BattleAction,
    attacker: BattleBall,
    defender: BattleBall,
    settings: "BattleSettings",
    matchup_multiplier: float = 1.0,
    item_effect: tuple[str, float] | None = None,
    lore: bool | None = None,
) -> ActionResult:
    """
    Resolve one turn's action, mutating `attacker`/`defender` health in place.

    `matchup_multiplier` is everything the pairing does to the damage. `lore` says whether the part of
    it that comes from who the fighters are favours the attacker, which is all the "lore advantage"
    mention is about; left out, it is read off the multiplier as it always was.
    """
    if action is BattleAction.HEAL:
        return _resolve_heal(attacker, defender, settings, matchup_multiplier, item_effect, lore)
    if action is BattleAction.CAPACITY:
        return _resolve_capacity(attacker, defender, settings, matchup_multiplier, item_effect, lore)
    return _damaging_action(action, attacker, defender, settings, matchup_multiplier, item_effect, lore)


def hp_bar(current: int, maximum: int, length: int = 10) -> str:
    """A small unicode HP bar, e.g. '██████░░░░'."""
    if maximum <= 0:
        return "░" * length
    filled = round(length * max(0, current) / maximum)
    filled = min(length, max(0, filled))
    return "█" * filled + "░" * (length - filled)
