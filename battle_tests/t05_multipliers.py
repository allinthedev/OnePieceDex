"""
6. the multipliers, on real characters: rarity tiers, an exact pair, a bond between the members of a group,
the mirror match, and what equipment does to the damage coming in, with its bounds.
"""

import itertools
import sys

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 5
r = h.Report("t05_multipliers")
bm = h.bm
engine = h.engine
battle_cog = h.battle_cog

GOMU = "Gomu Gomu no Mi (Gum Gum)"
GORO = "Goro Goro no Mi (Thunder Thunder)"
YAMI = "Yami Yami no Mi (Dark Dark)"
MERO = "Mero Mero no Mi (Love Love)"
MAGU = "Magu Magu no Mi (Magma Magma)"
MERA = "Mera Mera no Mi (Fire Fire)"
PHOENIX = "Tori Tori:Phoenix"
AKAINU = "Sakazuki (Akainu)"
ACE = "Portgas D. Ace"
# the five multipliers of the rarity tiers, from two tiers rarer to two tiers more common
RARER_2, RARER, SAME, COMMONER, COMMONER_2 = 0.9, 0.925, 0.95, 0.975, 1.0
RESISTED = "\n-# 🛡️ Resisted: what they wear changed this hit (x{:g})."
WEAK = "\n-# 💢 Weak point: what they wear changed this hit (x{:g})."


def rarity(name: str) -> float:
    return h.bd.balls[h.BALL[name]].rarity


async def relation(attacker: str, defender: str) -> float:
    return await battle_cog.get_matchup_multiplier(h.BALL[attacker], h.BALL[defender])


async def tiers(w: h.World):
    s = await w.cog.get_settings()
    r.check("the bounds in the database", s.tier_bounds, [15, 35, 85, 140, 180])
    five = (
        s.tier_enemy_2plus_higher_multiplier,
        s.tier_enemy_1_higher_multiplier,
        s.tier_same_multiplier,
        s.tier_enemy_1_lower_multiplier,
        s.tier_enemy_2plus_lower_multiplier,
    )
    r.check("the five multipliers in the database", five, (RARER_2, RARER, SAME, COMMONER, COMMONER_2))
    cases = [
        ("Monkey D. Luffy", "Kaido", SAME, "T5 on T9, same tier"),
        ("Monkey D. Luffy", ACE, COMMONER, "T5 on T22, one tier more common"),
        (ACE, "Monkey D. Luffy", RARER, "T22 on T5, one tier rarer"),
        ("Roronoa Zoro", "Nami", SAME, "T18 on T33, same tier although 15 apart"),
        ("Monkey D. Luffy", "Hassaikai", COMMONER_2, "T5 on T36, two tiers more common"),
        ("Hassaikai", "Monkey D. Luffy", RARER_2, "T36 on T5, two tiers rarer"),
        ("Monkey D. Luffy", "Vinsmoke Sora", COMMONER_2, "T5 on T305, five tiers apart: no more than two"),
        ("Vinsmoke Sora", "Monkey D. Luffy", RARER_2, "T305 on T5, five tiers apart: no less than two"),
    ]
    for attacker, defender, wanted, why in cases:
        got = engine.tier_scaling(rarity(attacker), rarity(defender), s)
        r.check(f"{attacker} on {defender} ({why})", got, (wanted, 0.0))
    edges = [
        (15, 0),
        (15.01, 1),
        (16, 1),
        (35, 1),
        (36, 2),
        (85, 2),
        (86, 3),
        (140, 3),
        (141, 4),
        (180, 4),
        (181, 5),
        (0, 0),
        (352, 5),
    ]
    r.check("where each tier starts and ends", [(x, engine.tier_of(x, s.tier_bounds)) for x, _ in edges], edges)

    characters = [b for b in h.bd.groups[h.GROUP["Characters"]].balls if b.enabled]
    rarities = sorted({b.rarity for b in characters})
    seen: dict = {}
    for a, d in itertools.product(rarities, repeat=2):
        multiplier, crit = engine.tier_scaling(a, d, s)
        seen[multiplier] = seen.get(multiplier, 0) + 1
        if crit:
            seen["crit"] = seen.get("crit", 0) + 1
    span = (min(k for k in seen if k != "crit"), max(k for k in seen if k != "crit"))
    label = f"over the {len(rarities)} rarities of the active characters, never under 0.9 nor over 1.0"
    r.check(label, span, (RARER_2, COMMONER_2))
    r.check("so never under the 0.7 the brief set as the floor", span[0] >= 0.7, True)
    r.check("and no bonus critical chance from the gap", seen.get("crit", 0), 0)
    per_tier: dict[int, int] = {}
    for b in characters:
        tier = engine.tier_of(b.rarity, s.tier_bounds)
        per_tier[tier] = per_tier.get(tier, 0) + 1
    r.note(f"active characters per tier (0 is the rarest): {dict(sorted(per_tier.items()))}")


async def relations(w: h.World):
    r.check("Akainu on Ace: the exact pair", await relation(AKAINU, ACE), 1.3)
    r.check("Ace on Akainu: the pair is one-way", await relation(ACE, AKAINU), 1.0)
    r.check("Luffy on Nami: two Straw Hats hold back", await relation("Monkey D. Luffy", "Nami"), 0.75)
    r.check("Nami on Luffy: a bond goes both ways", await relation("Nami", "Monkey D. Luffy"), 0.75)
    r.check(
        "Zoro on Sanji: the pair beats the bond of their crew", await relation("Roronoa Zoro", "Vinsmoke Sanji"), 1.2
    )
    r.check("Sanji on Zoro: and so does its reverse line", await relation("Vinsmoke Sanji", "Roronoa Zoro"), 1.2)
    mirror = await relation("Monkey D. Luffy", "Monkey D. Luffy")
    r.check("Luffy on Luffy: a mirror match has no relation", mirror, 1.0)
    r.check("Ace on Marco: Whitebeard Pirates", await relation(ACE, "Marco"), 0.5)
    r.check("Luffy on Ace: brothers, but no bond is written for ASL", await relation("Monkey D. Luffy", ACE), 1.0)
    boa = await relation("Boa Hancock", "Monkey D. Luffy")
    r.check("Boa Hancock on Luffy: 0.1, under the floor of the resistances on purpose", boa, 0.1)
    r.check("Luffy on Boa Hancock: one-way", await relation("Monkey D. Luffy", "Boa Hancock"), 1.0)
    r.check("Luffy on Kaido: nothing written, nothing shared", await relation("Monkey D. Luffy", "Kaido"), 1.0)

    wrong = []
    async for row in bm.Matchup.objects.all():
        got = await battle_cog.get_matchup_multiplier(row.attacker_id, row.defender_id)
        if got != row.damage_multiplier:
            wrong.append((row.attacker_id, row.defender_id, got))
    r.check("every line of the pair table is the multiplier its pair gets", wrong, [])

    # every bond, on every pair of members no pair line speaks of
    pairs = {(m.attacker_id, m.defender_id) async for m in bm.Matchup.objects.all()}
    sizes = bm.group_sizes()
    bonds = {bond.group_id: bond.damage_multiplier async for bond in bm.GroupMatchup.objects.all()}
    wrong, checked = [], 0
    for group_id in bonds:
        members = sorted(h.bd.groups[group_id]._ball_ids)
        for a, d in itertools.permutations(members, 2):
            if (a, d) in pairs:
                continue
            shared = [g for g in bonds if a in h.bd.groups[g]._ball_ids and d in h.bd.groups[g]._ball_ids]
            wanted = bonds[min(shared, key=lambda g: (sizes[g], g))]
            checked += 1
            if await battle_cog.get_matchup_multiplier(a, d) != wanted:
                wrong.append((a, d))
    r.check(f"every bond on every pair of its members ({checked} pairs)", wrong[:5], [])


async def loadout_of(w: h.World, a: int, b: int, deck_a, deck_b):
    """Both decks built through the real commands, started, and the two leading cards as the cog sees them."""
    fight = await w.fight(a, b, deck_a, deck_b)
    state = await fight.state()
    first = engine.BattleBall.from_dict(state["p1_balls"][0])
    return fight, first, engine.BattleBall.from_dict(state["p2_balls"][0])


async def worn(attacker, defender, w: h.World) -> float:
    return await battle_cog.get_equipment_multiplier(attacker, defender, await w.cog.get_settings())


async def last_line(fight) -> str:
    return (await fight.state())["log"][-1]


async def resistances(w: h.World):
    h.script_random()
    # Kaido with the Goro Goro and Hassaikai (a blunt weapon), Luffy holding his Gomu Gomu
    fight, kaido, luffy = await loadout_of(
        w, 1, 2, [("Kaido", [GORO, "Hassaikai"]), "Nami"], [("Monkey D. Luffy", [GOMU]), "Usopp"]
    )
    floored = await worn(kaido, luffy, w)
    r.check("Gomu Gomu holder hit with Goro Goro + a blunt weapon: 0.25 x 0.5 floored at 0.25", floored, 0.25)
    r.check("the other way: a Goro Goro holder is weak to the Gomu Gomu", await worn(luffy, kaido, w), 1.5)
    # Kaido 330 + 50% of 390 + 200% of 85 = 695, +10% for the set: 764.5, which a float rounds up to 765
    geared = round((330 + 195 + 170) * (1 + 10 / 100))
    r.check("Kaido's attack in that gear", kaido.attack, geared)
    await fight.act(1, "attack")
    wanted = f"Turn 1: **Kaido** hits **Monkey D. Luffy** for **{round(geared * SAME * 0.25)}**" + RESISTED.format(0.25)
    r.check(f"the hit itself: {geared} x 0.95 (tier) x 0.25", await last_line(fight), wanted)
    await fight.act(2, "attack")
    # 1570 x 0.95 x 1.5: what they WEAR makes it hurt, who they ARE has nothing to say, so no lore mention
    wanted = f"Turn 2: **Monkey D. Luffy** hits **Kaido** for **{round(1570 * SAME * 1.5)}** — Kaido is defeated!"
    r.check(
        "the answer is announced as a weak point, and not as a lore advantage",
        await last_line(fight),
        wanted + WEAK.format(1.5),
    )
    await fight.act(1, "forfeit")

    w.override_settings(resistance_floor=0.05)
    lowered = await worn(kaido, luffy, w)
    r.check("with the floor lowered the same hit would be 0.125: the floor is what holds it", lowered, 0.125)
    w.restore_settings()

    fight, kaido, luffy = await loadout_of(w, 1, 2, [("Kaido", ["Hassaikai"])], [("Monkey D. Luffy", [GOMU])])
    r.check("blunt weapon alone on the Gomu Gomu holder", await worn(kaido, luffy, w), 0.5)
    await fight.act(1, "forfeit")
    fight, kaido, luffy = await loadout_of(w, 1, 2, [("Kaido", [GORO])], [("Monkey D. Luffy", [GOMU])])
    r.check("Goro Goro alone on the Gomu Gomu holder", await worn(kaido, luffy, w), 0.25)
    await fight.act(1, "forfeit")
    fight, kaido, luffy = await loadout_of(w, 1, 2, [("Kaido", [GORO, "Hassaikai"])], ["Monkey D. Luffy"])
    r.check("Luffy without his fruit resists nothing", await worn(kaido, luffy, w), 1.0)
    await fight.act(1, "forfeit")
    fight, kaido, luffy = await loadout_of(w, 1, 2, ["Kaido"], [("Monkey D. Luffy", [GOMU])])
    r.check("an attacker wearing nothing triggers nothing", await worn(kaido, luffy, w), 1.0)
    await fight.act(1, "forfeit")
    fight, zoro, nami = await loadout_of(w, 1, 2, [("Roronoa Zoro", [GORO, "Hassaikai"])], [("Nami", [GOMU])])
    r.check("the rubber rule follows the fruit, whoever wears it", await worn(zoro, nami, w), 0.25)
    await fight.act(1, "forfeit")

    # the phoenix
    fight, zoro, marco = await loadout_of(w, 3, 4, [("Roronoa Zoro", ["Wado Ichimonji"])], [("Marco", [PHOENIX])])
    r.check("Tori Tori:Phoenix holder hit with a weapon", await worn(zoro, marco, w), 0.5)
    # Zoro 296 + 460 = 756; the tier is read from the rules themselves
    tier, _ = engine.tier_scaling(zoro.rarity, marco.rarity, await w.cog.get_settings())
    await fight.act(3, "attack")
    line = await last_line(fight)
    r.ok("the hit itself is halved", f"for **{round(756 * tier * 0.5)}**" in line and "(x0.5)" in line, line)
    await fight.act(4, "forfeit")
    fight, zoro, marco = await loadout_of(w, 3, 4, [("Roronoa Zoro", ["Wado Ichimonji", GORO])], [("Marco", [PHOENIX])])
    r.check("a fruit on top of the weapon adds nothing to it", await worn(zoro, marco, w), 0.5)
    await fight.act(3, "forfeit")
    fight, zoro, marco = await loadout_of(w, 3, 4, [("Roronoa Zoro", [GORO])], [("Marco", [PHOENIX])])
    r.check("a fruit alone is not a weapon", await worn(zoro, marco, w), 1.0)
    await fight.act(3, "forfeit")

    # weaknesses that add up, and the ceiling
    fight, zoro, nami = await loadout_of(w, 5, 6, [("Roronoa Zoro", ["Wado Ichimonji", GORO])], [("Nami", [YAMI])])
    r.check("Yami Yami holder hit with a fruit and a weapon: 1.25 x 1.25", await worn(zoro, nami, w), 1.5625)
    w.override_settings(resistance_ceiling=1.5)
    r.check("a ceiling of 1.5 holds it", await worn(zoro, nami, w), 1.5)
    w.restore_settings()
    await fight.act(5, "forfeit")

    # a rule tied to who the defender is, and how it multiplies with the relation
    fight, boa, luffy = await loadout_of(w, 7, 8, [("Boa Hancock", [MERO]), "Nami"], ["Monkey D. Luffy"])
    r.check("Luffy shrugs off the Mero Mero whatever he wears", await worn(boa, luffy, w), 0.5)
    await fight.act(7, "attack")
    line = await last_line(fight)
    # Boa in her own fruit; T35 on T5 is one tier rarer; 0.1 for who they are, 0.5 for the fruit
    wanted = max(1, round(boa.attack * RARER * 0.1 * 0.5))
    label = f"Boa Hancock with the Mero Mero on Luffy: relation 0.1 x resistance 0.5 ({boa.attack} ATK -> {wanted})"
    r.ok(label, f"for **{wanted}**" in line and "lore advantage" not in line, line)
    await fight.act(8, "forfeit")

    fight, akainu, ace = await loadout_of(w, 9, 10, [(AKAINU, [MAGU])], [(ACE, [MERA]), "Nami"])
    r.check("Akainu with the Magu Magu on Ace with the Mera Mera: resistance side", await worn(akainu, ace, w), 1.5)
    await fight.act(9, "attack")
    line = await last_line(fight)
    wanted = round(akainu.attack * COMMONER * 1.3 * 1.5)
    label = f"the hit multiplies relation 1.3 and weakness 1.5 ({akainu.attack} ATK -> {wanted})"
    r.ok(label, f"for **{wanted}** (lore advantage!)" in line and "Weak point" in line, line)
    await fight.act(10, "forfeit")


async def end_to_end(w: h.World):
    h.script_random()
    fight = await w.fight(21, 22, [AKAINU, "Nami"], [ACE, "Usopp"])
    await fight.act(21, "attack")
    wanted = (
        f"Turn 1: **Sakazuki (Akainu)** hits **Portgas D. Ace** for **{round(350 * COMMONER * 1.3)}**"
        " (lore advantage!) — Portgas D. Ace is defeated!"
    )
    r.check("Akainu on Ace in a real turn: 350 x 0.975 (tier) x 1.3", await last_line(fight), wanted)
    await fight.act(22, "forfeit")

    fight = await w.fight(21, 22, [ACE, "Nami"], [AKAINU, "Usopp"])
    await fight.act(21, "attack")
    wanted = f"Turn 1: **Portgas D. Ace** hits **Sakazuki (Akainu)** for **{round(179 * RARER)}**"
    r.check("Ace on Akainu: 179 x 0.925 and nothing else", await last_line(fight), wanted)
    await fight.act(22, "attack")
    line = await last_line(fight)
    r.ok("and Akainu's answer carries the 1.3", "(lore advantage!)" in line, line)
    await fight.act(21, "forfeit")

    fight = await w.fight(21, 22, ["Monkey D. Luffy", "Nami"], ["Monkey D. Luffy", "Usopp"])
    await fight.act(21, "attack")
    wanted = f"Turn 1: **Monkey D. Luffy** hits **Monkey D. Luffy** for **{round(310 * SAME)}**"
    r.check("mirror match in a real turn: 310 x 0.95, no Straw Hat bond", await last_line(fight), wanted)
    await fight.act(22, "forfeit")

    fight = await w.fight(21, 22, ["Monkey D. Luffy", "Usopp"], ["Nami", "Kaido"])
    await fight.act(21, "attack")
    wanted = f"Turn 1: **Monkey D. Luffy** hits **Nami** for **{round(310 * 0.75 * COMMONER)}** — Nami is defeated!"
    r.check("two Straw Hats in a real turn: 310 x 0.975 x 0.75", await last_line(fight), wanted)
    await fight.act(22, "forfeit")

    fight = await w.fight(21, 22, ["Boa Hancock", "Usopp"], ["Monkey D. Luffy", "Kaido"])
    await fight.act(21, "attack")
    wanted = f"Turn 1: **Boa Hancock** hits **Monkey D. Luffy** for **{round(165 * 0.1 * RARER)}**"
    r.check("Boa Hancock on Luffy in a real turn: 165 x 0.925 x 0.1", await last_line(fight), wanted)
    await fight.act(22, "forfeit")


async def main(w: h.World):
    await r.scenario("rarity tiers", tiers, w)
    await r.scenario("who fights whom", relations, w)
    await r.scenario("resistances of equipment", resistances, w)
    await r.scenario("in real turns", end_to_end, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
