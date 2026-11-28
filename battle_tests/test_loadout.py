"""Exercise the equip rules for real: both modules are pure Python."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "extra/battle/battle_app/battle_ext"))
import engine  # noqa: E402
import loadout  # noqa: E402
from loadout import AffinityRule as A  # noqa: E402
from loadout import ResistanceRule as R  # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (wanted {want!r})"))
    if not ok:
        failures.append(label)


# treasure ids
LUFFY, ZORO, KAIDO, BENN, NAMI = 1, 2, 3, 4, 5
GOMU, MERA, MAGU, GORO = 10, 11, 12, 13
WADO, YORU, HASSAIKAI, RIFLE = 20, 21, 22, 23
# group ids, with their sizes: the narrower one must win
WEAPONS, SWORDS, KATANAS, BLUNT, FIREARMS = 100, 101, 102, 103, 104
FRUITS, PARAMECIA, LOGIA = 110, 111, 112
SIZES = {WEAPONS: 31, SWORDS: 20, KATANAS: 9, BLUNT: 2, FIREARMS: 1, FRUITS: 165, PARAMECIA: 97, LOGIA: 13}

rules = [
    A(50, group_id=WEAPONS, pk=1),  # layer 1: anybody, any weapon
    A(50, group_id=FRUITS, pk=2),
    A(200, character_id=LUFFY, item_id=GOMU, pk=3),  # layer 2: the canonical item
    A(200, character_id=ZORO, item_id=WADO, pk=4),
    A(200, character_id=KAIDO, item_id=HASSAIKAI, pk=5),
    A(150, character_id=ZORO, group_id=SWORDS, pk=6),  # layer 3: mastery of a kind
    A(170, character_id=ZORO, group_id=KATANAS, pk=7),
    A(25, character_id=LUFFY, group_id=SWORDS, pk=8),  # he cannot use one
    A(110, character_id=BENN, group_id=FIREARMS, pk=9),
]

print("=== affinity: the most precise layer wins ===")
check("Luffy + his Gomu Gomu", loadout.affinity_percent(rules, LUFFY, GOMU, [FRUITS, PARAMECIA], SIZES, 50), 200)
check(
    "Zoro + Wado (own beats mastery)",
    loadout.affinity_percent(rules, ZORO, WADO, [WEAPONS, SWORDS, KATANAS], SIZES, 50),
    200,
)
check(
    "Zoro + another katana (narrowest group)",
    loadout.affinity_percent(rules, ZORO, YORU, [WEAPONS, SWORDS, KATANAS], SIZES, 50),
    170,
)
check("Zoro + a plain sword", loadout.affinity_percent(rules, ZORO, 29, [WEAPONS, SWORDS], SIZES, 50), 150)
check(
    "Luffy + a sword (cannot use it)",
    loadout.affinity_percent(rules, LUFFY, WADO, [WEAPONS, SWORDS, KATANAS], SIZES, 50),
    25,
)
check("Kaido + Hassaikai", loadout.affinity_percent(rules, KAIDO, HASSAIKAI, [WEAPONS, BLUNT], SIZES, 50), 200)
check("Benn + a firearm (mastery)", loadout.affinity_percent(rules, BENN, RIFLE, [WEAPONS, FIREARMS], SIZES, 50), 110)
check(
    "Benn + a sword (category default)",
    loadout.affinity_percent(rules, BENN, WADO, [WEAPONS, SWORDS, KATANAS], SIZES, 50),
    50,
)
check("Nami + somebody's fruit", loadout.affinity_percent(rules, NAMI, MERA, [FRUITS, LOGIA], SIZES, 50), 50)
check("nothing matches at all: the setting", loadout.affinity_percent([], NAMI, MERA, [FRUITS], SIZES, 40), 40)
check(
    "order of the rules does not matter",
    loadout.affinity_percent(list(reversed(rules)), ZORO, YORU, [WEAPONS, SWORDS, KATANAS], SIZES, 50),
    170,
)

print("=== equipment adds up into the fighter ===")


def fighter(attack=100, health=100):
    return engine.BattleBall(
        instance_id=1,
        ball_id=LUFFY,
        name="Luffy",
        owner_id=1,
        health=health,
        max_health=health,
        attack=attack,
        base_attack=attack,
        base_health=health,
    )


def item(slot, ball_id, attack, health, percent):
    return {
        "slot": slot,
        "instance_id": ball_id,
        "ball_id": ball_id,
        "name": f"item{ball_id}",
        "emoji": "",
        "attack": attack,
        "health": health,
        "percent": percent,
        "group_ids": [],
    }


luffy = fighter()
loadout.apply_equipment(luffy, 10)
check("bare fighter is unchanged", (luffy.attack, luffy.max_health), (100, 100))

luffy.equipment = [item("fruit", GOMU, 600, 500, 200)]
loadout.apply_equipment(luffy, 10)
check("own fruit at 200%", (luffy.attack, luffy.max_health, luffy.health), (1300, 1100, 1100))

luffy.equipment = [item("weapon", WADO, 230, 230, 25)]
loadout.apply_equipment(luffy, 10)
check("a sword he cannot use, 25%", (luffy.attack, luffy.max_health), (158, 158))

luffy.equipment = [item("fruit", GOMU, 600, 500, 200), item("weapon", WADO, 230, 230, 25)]
loadout.apply_equipment(luffy, 10)
# (100 + 1200 + 58) * 1.10 = 1493.8 ; (100 + 1000 + 58) * 1.10 = 1273.8
check("full set adds 10% on the total", (luffy.attack, luffy.max_health), (1494, 1274))
loadout.apply_equipment(luffy, 0)
check("full set bonus can be turned off", (luffy.attack, luffy.max_health), (1358, 1158))

luffy.equipment = []
loadout.apply_equipment(luffy, 10)
check("unequipping everything restores the base", (luffy.attack, luffy.max_health), (100, 100))

legacy = engine.BattleBall(instance_id=1, ball_id=1, name="Old", owner_id=1, health=80, max_health=80, attack=70)
loadout.apply_equipment(legacy, 10)
check(
    "a card with no base recorded keeps its stats", (legacy.attack, legacy.max_health, legacy.base_attack), (70, 80, 70)
)

print("=== the card survives its JSON round trip with equipment ===")
luffy.equipment = [item("fruit", GOMU, 600, 500, 200)]
loadout.apply_equipment(luffy, 10)
check("round trip", engine.BattleBall.from_dict(luffy.to_dict()) == luffy, True)
check("display line", loadout.equipment_line(luffy.equipment), f"item{GOMU} (200%)")
check(
    "full set detection",
    (
        loadout.has_full_set(luffy.equipment),
        loadout.has_full_set([item("fruit", 1, 1, 1, 1), item("weapon", 2, 1, 1, 1)]),
    ),
    (False, True),
)

print("=== resistances: conditional on what both sides wear ===")
res = [
    R(0.5, character_id=LUFFY, equipped_item_id=GOMU, against_group_id=BLUNT, pk=1),  # rubber vs blunt
    R(0.25, character_id=LUFFY, equipped_item_id=GOMU, against_item_id=GORO, pk=2),  # rubber vs lightning
    R(1.5, equipped_item_id=MERA, against_item_id=MAGU, pk=3),  # anybody: fire loses to magma
    R(1.2, against_group_id=WEAPONS, pk=4),  # a generic rule, to check precision
    R(0.8, character_id=LUFFY, against_group_id=WEAPONS, pk=5),
]
blunt = (HASSAIKAI, [WEAPONS, BLUNT])
check("Luffy with Gomu vs a blunt weapon", loadout.resistance_multiplier(res, LUFFY, [GOMU], [blunt], SIZES), 0.5)
check(
    "Luffy WITHOUT Gomu: the conditional rule is off",
    loadout.resistance_multiplier(res, LUFFY, [], [blunt], SIZES),
    0.8,
)
check(
    "Luffy with Gomu vs Goro Goro",
    loadout.resistance_multiplier(res, LUFFY, [GOMU], [(GORO, [FRUITS, LOGIA])], SIZES),
    0.25,
)
check(
    "anybody wearing Mera vs Magu",
    loadout.resistance_multiplier(res, NAMI, [MERA], [(MAGU, [FRUITS, LOGIA])], SIZES),
    1.5,
)
check("Mera not worn: no weakness", loadout.resistance_multiplier(res, NAMI, [], [(MAGU, [FRUITS, LOGIA])], SIZES), 1.0)
check("attacker wears nothing: nothing triggers", loadout.resistance_multiplier(res, LUFFY, [GOMU], [], SIZES), 1.0)
both = loadout.resistance_multiplier(res, LUFFY, [GOMU], [blunt, (GORO, [FRUITS, LOGIA])], SIZES)
check("weapon and fruit each count once, multiplied", round(both, 4), 0.125)
check("somebody else vs a weapon: the generic rule", loadout.resistance_multiplier(res, NAMI, [], [blunt], SIZES), 1.2)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILURE(S): {', '.join(failures)}")
sys.exit(1 if failures else 0)
