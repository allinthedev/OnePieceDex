"""
Exercise the battle engine's Capacity resolution for real. The engine is pure Python, so it runs
without Django or a database.
"""

import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "extra/battle/battle_app/battle_ext"))
import engine  # noqa: E402


@dataclass
class Settings:
    """The defaults from BattleSettings, as plain values."""

    attack_variance_min: float = 0.6
    attack_variance_max: float = 1.0
    crit_chance: float = 0.5
    crit_multiplier: float = 2.0
    crit_fail_multiplier: float = 0.5
    dodge_chance: float = 0.0  # off, so the numbers below are repeatable; the dodge has a section of its own
    heal_percent_min: float = 25.0
    heal_percent_max: float = 45.0
    heal_uses_per_battle: int = 2
    capacity_uses_per_battle: int = 1
    default_capacity_multiplier: float = 1.5
    tier_same_multiplier: float = 0.7
    tier_enemy_1_higher_multiplier: float = 0.5
    tier_enemy_2plus_higher_multiplier: float = 0.3
    tier_enemy_1_lower_multiplier: float = 0.9
    tier_enemy_2plus_lower_multiplier: float = 1.0
    tier_enemy_2plus_lower_bonus_crit_chance: float = 0.0  # off, so the numbers below are repeatable


def card(effect: str = "", value: float = 0.0, *, rarity: float = 50.0, attack: int = 100, health: int = 1000):
    return engine.BattleBall(
        instance_id=1,
        ball_id=1,
        name="Tester",
        owner_id=1,
        health=health,
        max_health=health,
        attack=attack,
        rarity=rarity,
        capacity_name="Fire fist",
        capacity_effect=effect,
        capacity_value=value,
    )


settings = Settings()
failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


print("=== heal_percent: heals 30% of max health ===")
random.seed(1)
attacker = card("heal_percent", 30, health=1000)
attacker.health = 400
result = engine.resolve_action(engine.BattleAction.CAPACITY, attacker, card(rarity=50.0), settings)
check("heals exactly 300", result.healed == 300, f"healed={result.healed}, hp={attacker.health}")
check("names the capacity", "Fire fist" in result.text, result.text)
check("deals no damage", result.damage == 0)

print("=== heal_percent cannot overheal ===")
attacker = card("heal_percent", 90, health=1000)
attacker.health = 950
engine.resolve_action(engine.BattleAction.CAPACITY, attacker, card(), settings)
check("capped at max health", attacker.health == 1000, f"hp={attacker.health}")

print("=== flat_damage: 500, ignoring the attack stat ===")
attacker = card("flat_damage", 500, attack=1, rarity=50.0)
defender = card(rarity=50.0, health=1000)
result = engine.resolve_action(engine.BattleAction.CAPACITY, attacker, defender, settings)
# same tier -> x0.7, matchup x1.0
check("500 x 0.7 same-tier = 350", result.damage == 350, f"damage={result.damage}")
check("ignores the attack stat of 1", result.damage > 1)

print("=== damage_multiplier: x3 on the attack stat ===")
random.seed(7)
attacker = card("damage_multiplier", 3, attack=100, rarity=50.0)
defender = card(rarity=50.0, health=10_000)
result = engine.resolve_action(engine.BattleAction.CAPACITY, attacker, defender, settings)
# 100 * variance(0.6..1.0) * 1.0 matchup * 0.7 tier * 3
check("lands in 126..210", 126 <= result.damage <= 210, f"damage={result.damage}")

print("=== no effect set: falls back to the default multiplier ===")
random.seed(7)
plain = card("", 0, attack=100, rarity=50.0)
result = engine.resolve_action(engine.BattleAction.CAPACITY, plain, card(rarity=50.0, health=10_000), settings)
check("lands in 63..105 (x1.5)", 63 <= result.damage <= 105, f"damage={result.damage}")

print("=== an effect with no value is treated as no effect ===")
random.seed(7)
broken = card("flat_damage", 0, attack=100, rarity=50.0)
result = engine.resolve_action(engine.BattleAction.CAPACITY, broken, card(rarity=50.0, health=10_000), settings)
check("does not deal 0 damage", result.damage >= 1, f"damage={result.damage}")

print("=== one use per battle ===")
attacker = card("flat_damage", 500, rarity=50.0)
defender = card(rarity=50.0, health=10_000)
engine.resolve_action(engine.BattleAction.CAPACITY, attacker, defender, settings)
again = engine.resolve_action(engine.BattleAction.CAPACITY, attacker, defender, settings)
check("second use is refused", "already used its Capacity" in again.text, again.text)
check("and a plain attack is thrown in its place", again.damage > 0 and defender.health < 10_000 - 350, again.text)
check("which is not the Capacity again", again.damage != 350 and attacker.capacity_uses == 1, f"damage={again.damage}")

print("=== a heal that is used up attacks instead ===")
attacker = card(rarity=50.0, health=1000)
attacker.health = 100
defender = card(rarity=50.0, health=10_000)
for _ in range(settings.heal_uses_per_battle):
    engine.resolve_action(engine.BattleAction.HEAL, attacker, defender, settings)
before = attacker.health
third = engine.resolve_action(engine.BattleAction.HEAL, attacker, defender, settings)
check("the third heal heals nothing", attacker.health == before and third.healed == 0, third.text)
check("it says so, and hits", "no more heals left" in third.text and third.damage > 0, third.text)
check("the defender took it", defender.health == 10_000 - third.damage)
boosted = engine.resolve_action(
    engine.BattleAction.HEAL, attacker, card(rarity=50.0, health=10_000), settings, item_effect=("extra_heal", 50.0)
)
check("a healing item does not turn into a stronger attack", 42 <= boosted.damage <= 70, f"damage={boosted.damage}")

print("=== a Capacity that hurts can be dodged, one that heals cannot ===")
sure_dodge = Settings(dodge_chance=1.0)
attacker = card("flat_damage", 500, rarity=50.0)
defender = card(rarity=50.0, health=1000)
result = engine.resolve_action(engine.BattleAction.CAPACITY, attacker, defender, sure_dodge)
check("dodged: no damage", result.dodged and result.damage == 0 and defender.health == 1000, result.text)
check("the Capacity is spent all the same", attacker.capacity_uses == 1)
plain = card("", 0, attack=100, rarity=50.0)
result = engine.resolve_action(engine.BattleAction.CAPACITY, plain, defender, sure_dodge)
check("the plain special attack is dodged too", result.dodged and defender.health == 1000, result.text)
healer = card("heal_percent", 30, health=1000)
healer.health = 400
result = engine.resolve_action(engine.BattleAction.CAPACITY, healer, defender, sure_dodge)
check("a healing Capacity always lands", result.healed == 300 and not result.dodged, result.text)

print("=== from_dict survives a state written by an older version ===")
stored = card("heal_percent", 30).to_dict()
stored["capacity_logic"] = {"10-04-2026": {"card": "frame.jpg"}}  # the field that used to be there
stored.pop("capacity_value")  # and one the old version never wrote
revived = engine.BattleBall.from_dict(stored)
check("unknown key dropped, no crash", revived.capacity_effect == "heal_percent")
check("missing key falls back", revived.capacity_value == 0.0)

print("=== round trip ===")
original = card("damage_multiplier", 2.5)
copy = engine.BattleBall.from_dict(original.to_dict())
check("to_dict/from_dict is lossless", copy == original)

print()
print(f"{'ALL PASS' if not failures else str(len(failures)) + ' FAILURE(S): ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
