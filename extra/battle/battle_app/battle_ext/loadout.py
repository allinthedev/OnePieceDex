"""
The rules of equipping, kept free of Discord and Django like `engine.py` so they can be read, tested and
tuned in one place.

Only characters fight. A weapon and a devil fruit are attached to one, and what the character gets out of
each is a share of the item's own stats: all of it and more when the item is canonically theirs, half when
they have no business holding it. That share is looked up in three layers, the most precise one winning:

1. this character with this exact item           (Zoro with Wado Ichimonji)
2. this character with a kind of item            (Zoro with any katana)
3. anybody with this exact item                  (rarely useful, but it costs nothing to allow)
4. anybody with a kind of item                   (the default of a category)
5. the default set in the battle settings        (when nothing above says anything)

Equipment also changes what a fighter is hurt by. A resistance is a multiplier on the damage taken, tied to
what the defender wears and to what the attacker wears: Luffy shrugs off blunt weapons only while he holds
his Gomu Gomu. Who beats whom regardless of equipment stays in the `Matchup` table.
"""

from dataclasses import dataclass

ROLE_CHARACTER = "character"
SLOT_WEAPON = "weapon"
SLOT_FRUIT = "fruit"
SLOTS = (SLOT_WEAPON, SLOT_FRUIT)


@dataclass(frozen=True)
class AffinityRule:
    """One line of the affinity table. A side left at None means "any"."""

    percent: int
    character_id: int | None = None
    item_id: int | None = None
    group_id: int | None = None
    pk: int = 0


@dataclass(frozen=True)
class ResistanceRule:
    """One line of the resistance table. A side left at None means "any" (or "whatever they wear")."""

    multiplier: float
    character_id: int | None = None
    equipped_item_id: int | None = None
    against_item_id: int | None = None
    against_group_id: int | None = None
    pk: int = 0


def _narrowest(group_id: int | None, group_sizes: dict[int, int]) -> int:
    """Sort key putting the smallest group first: "katanas" says more about a blade than "weapons" does."""
    return group_sizes.get(group_id, 1_000_000) if group_id is not None else 0


def affinity_percent(
    rules: list[AffinityRule],
    character_id: int,
    item_id: int,
    item_group_ids: list[int],
    group_sizes: dict[int, int],
    default: int,
) -> int:
    """
    The share of an item's stats this character receives, in percent.

    The most precise rule wins outright, it is never blended with the others: a character's own sword at
    200% is not averaged with the 50% everybody else gets. Between two rules of the same precision naming
    different groups, the narrower group wins, and a remaining tie goes to the rule entered first.
    """
    groups = set(item_group_ids)
    best: tuple[int, int, int] | None = None
    chosen = default
    for rule in rules:
        if rule.character_id is not None and rule.character_id != character_id:
            continue
        if rule.item_id is not None:
            if rule.item_id != item_id:
                continue
        elif rule.group_id is None or rule.group_id not in groups:
            continue
        # lower is better on every axis: the character's own rule, then an exact item, then a narrow group
        rank = (0 if rule.character_id is not None else 1) * 2 + (0 if rule.item_id is not None else 1)
        key = (rank, _narrowest(rule.group_id, group_sizes), rule.pk)
        if best is None or key < best:
            best, chosen = key, rule.percent
    return chosen


def resistance_multiplier(
    rules: list[ResistanceRule],
    defender_id: int,
    defender_equipped_ids: list[int],
    attacker_items: list[tuple[int, list[int]]],
    group_sizes: dict[int, int],
    floor: float = 0.0,
    ceiling: float = float("inf"),
) -> float:
    """
    What the defender's equipment does to the damage coming in, as one multiplier.

    Each item the attacker wears is looked at on its own: the most precise rule about it applies, and the
    results multiply. So a defender resisting the attacker's weapon and weak to their fruit takes both into
    account, while two rules about the same weapon never stack. An attacker wearing nothing triggers
    nothing, which is the point: these are rules about equipment, not about who the fighters are.

    The product is kept between `floor` and `ceiling`. Each rule is reasonable on its own, but an attacker
    wears two items and the two results multiply: a quarter of the damage against the fruit and half against
    the weapon would leave an eighth, which is an immunity nobody wrote down.

    Parameters
    ----------
    attacker_items: list[tuple[int, list[int]]]
        For each item the attacker wears, its treasure id and the ids of the groups it belongs to.
    """
    worn = set(defender_equipped_ids)
    total = 1.0
    for item_id, item_group_ids in attacker_items:
        groups = set(item_group_ids)
        best: tuple[int, int, int] | None = None
        chosen = 1.0
        for rule in rules:
            if rule.character_id is not None and rule.character_id != defender_id:
                continue
            if rule.equipped_item_id is not None and rule.equipped_item_id not in worn:
                continue
            if rule.against_item_id is not None:
                if rule.against_item_id != item_id:
                    continue
            elif rule.against_group_id is None or rule.against_group_id not in groups:
                continue
            rank = (
                (0 if rule.character_id is not None else 4)
                + (0 if rule.against_item_id is not None else 2)
                + (0 if rule.equipped_item_id is not None else 1)
            )
            key = (rank, _narrowest(rule.against_group_id, group_sizes), rule.pk)
            if best is None or key < best:
                best, chosen = key, rule.multiplier
        total *= chosen
    return max(floor, min(ceiling, total))


def relation_multiplier(
    pair: float | None,
    group_rules: list[tuple[int, float]],
    attacker_group_ids: list[int],
    defender_group_ids: list[int],
    group_sizes: dict[int, int],
) -> float:
    """
    What who the two fighters are does to a hit, whatever they wear.

    A line about this exact pair wins outright ("Akainu against Ace"). Failing that, a bond between the
    members of a group applies when BOTH fighters belong to it ("the Whitebeard Pirates hold back against
    each other"), the narrowest such group winning. No line at all leaves the hit as it is.

    Parameters
    ----------
    pair: float | None
        The multiplier of the line naming this attacker against this defender, None when there is none.
    group_rules: list[tuple[int, float]]
        The bonds, as (group id, multiplier).
    """
    if pair is not None:
        return pair
    shared = set(attacker_group_ids) & set(defender_group_ids)
    best: tuple[int, int] | None = None
    chosen = 1.0
    for group_id, multiplier in group_rules:
        if group_id not in shared:
            continue
        key = (_narrowest(group_id, group_sizes), group_id)
        if best is None or key < best:
            best, chosen = key, multiplier
    return chosen


def contribution(stat: int, percent: int) -> int:
    """What an item adds to one stat of its bearer, never below zero."""
    return max(0, round(stat * percent / 100))


def has_full_set(equipment: list[dict]) -> bool:
    """A character holding both a weapon and a devil fruit."""
    return {entry.get("slot") for entry in equipment} >= set(SLOTS)


def apply_equipment(ball, full_set_percent: int) -> None:
    """
    Recompute a fighter's attack and health from its own stats and what it wears, in place.

    Only meant for the deck-building phase, where a fighter is always at full health: the health bar is
    reset to the new maximum. `ball` is a `BattleBall`; it is not imported here so that this module depends
    on nothing.
    """
    if not ball.base_attack and not ball.base_health:
        # a fighter written before equipment existed: what it has now is what it brought
        ball.base_attack, ball.base_health = ball.attack, ball.max_health
    attack = ball.base_attack + sum(contribution(entry["attack"], entry["percent"]) for entry in ball.equipment)
    health = ball.base_health + sum(contribution(entry["health"], entry["percent"]) for entry in ball.equipment)
    if full_set_percent and has_full_set(ball.equipment):
        attack = round(attack * (1 + full_set_percent / 100))
        health = round(health * (1 + full_set_percent / 100))
    ball.attack = attack
    ball.max_health = health
    ball.health = health


def equipment_line(equipment: list[dict]) -> str:
    """What a fighter wears, on one short line for the deck display. Empty when it wears nothing."""
    parts = []
    for slot in SLOTS:
        for entry in equipment:
            if entry.get("slot") == slot:
                emoji = f"{entry['emoji']} " if entry.get("emoji") else ""
                parts.append(f"{emoji}{entry['name']} ({entry['percent']}%)")
    return " · ".join(parts)
