"""
9. balance, in numbers: a few thousand automatic battles between typical decks.

The battles are played by a small simulator that calls the real `engine.resolve_action` with the multipliers
the real cog functions give (`get_matchup_multiplier`, `get_equipment_multiplier`) on cards built by the real
`serialize_ball`, `equip_percent`, `serialize_item` and `apply_equipment`. The simulator is first checked
against the real cog: the same decks, the same seed and the same policy must give the same winner in the same
number of turns, battle after battle.

Unlike the rules tests, this file plays with the settings exactly as the database holds them, health
multiplier included: these are the figures players will meet. A last section turns that multiplier.

Typical decks are picked by rule, not by hand: for a rarity tier, the four active characters with a canonical
devil fruit whose attack + health is closest to the median of their tier.
"""

import copy
import itertools
import random
import statistics
import sys

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 8
r = h.Report("t08_balance")
bm = h.bm
engine = h.engine
battle_cog = h.battle_cog
BattleAction = engine.BattleAction
N = 1000
TIER_NAMES = ["T1-15", "T16-35", "T36-85", "T86-140", "T141-180", "T181+"]
_ids = itertools.count(1)


# -- policies: what a player does on their turn. None of them draws a random number. ----------------------


def p_attack(att, dfn, s, m):
    """What the turn clock plays for somebody who is away."""
    return BattleAction.ATTACK


def p_crit(att, dfn, s, m):
    return BattleAction.CRIT


def p_smart(att, dfn, s, m):
    """Finish with a sure Attack when one is enough, else Capacity while it lasts, else gamble."""
    tier, _ = engine.tier_scaling(att.rarity, dfn.rarity, s)
    if att.attack * s.attack_variance_min * m * tier >= dfn.health:
        return BattleAction.ATTACK
    if att.capacity_uses < s.capacity_uses_per_battle:
        return BattleAction.CAPACITY
    return BattleAction.CRIT


def p_smart_heal(att, dfn, s, m):
    """The same, healing when under 35% of health while heals are left."""
    choice = p_smart(att, dfn, s, m)
    if choice is BattleAction.ATTACK:
        return choice
    if att.heal_uses < s.heal_uses_per_battle and att.health <= 0.35 * att.max_health:
        return BattleAction.HEAL
    return choice


BUTTON = {
    BattleAction.ATTACK: "attack",
    BattleAction.CRIT: "crit",
    BattleAction.HEAL: "heal",
    BattleAction.CAPACITY: "capacity",
}


# -- the simulator -----------------------------------------------------------------------------------------


def simulate(deck1, deck2, policy1, policy2, s, mult, first=0):
    """One battle. Mirrors `Battle._play`: first living card of each side, one action a turn."""
    sides = [copy.deepcopy(deck1), copy.deepcopy(deck2)]
    policies = (policy1, policy2)
    active = first
    for turn in range(1, 2001):
        att = next(b for b in sides[active] if not b.dead)
        dfn = next(b for b in sides[1 - active] if not b.dead)
        m = mult[(att.instance_id, dfn.instance_id)]
        engine.resolve_action(policies[active](att, dfn, s, m), att, dfn, s, m, None)
        if all(b.dead for b in sides[1 - active]):
            return active, turn
        active = 1 - active
    return None, 2000


async def multipliers(deck1, deck2, s) -> dict:
    """Relation x equipment for every card against every card of the other deck, from the cog's own functions."""
    table = {}
    for att, dfn in itertools.chain(itertools.product(deck1, deck2), itertools.product(deck2, deck1)):
        relation = await battle_cog.get_matchup_multiplier(att.ball_id, dfn.ball_id)
        worn = await battle_cog.get_equipment_multiplier(att, dfn, s)
        table[(att.instance_id, dfn.instance_id)] = relation * worn
    return table


async def card(w, name: str, items: list[str], s):
    """A fighter as `/battle add` then `/battle equip` build it, without a row in the database."""
    instance = h.BallInstance(ball_id=h.BALL[name], attack_bonus=0, health_bonus=0)
    instance.pk = next(_ids)
    ball = await battle_cog.serialize_ball(instance, 0, w.bot, s)
    for item_name in items:
        item = h.BallInstance(ball_id=h.BALL[item_name], attack_bonus=0, health_bonus=0)
        item.pk = next(_ids)
        slot = bm.role_of(item.ball_id, s)
        percent = await battle_cog.equip_percent(ball.ball_id, item.ball_id, s)
        entry = battle_cog.serialize_item(item, slot, percent, w.bot, s.health_multiplier)
        ball.equipment = [old for old in ball.equipment if old["slot"] != slot] + [entry]
    h.loadout.apply_equipment(ball, s.full_set_bonus_percent)
    return ball


async def deck(w, spec: list[tuple[str, list[str]]], s):
    return [await card(w, name, items, s) for name, items in spec]


def power(cards) -> int:
    return sum(c.attack + c.max_health for c in cards)


async def series(d1, d2, s, policy1=p_smart, policy2=p_smart, n=N, seed=1, alternate=True):
    """
    n battles. With `alternate`, each deck opens half of them, so the figure is about the decks and not about
    who clicked /battle start. Returns (share won by deck 1, mean turns, share won by whoever opened).
    """
    mult = await multipliers(d1, d2, s)
    random.seed(seed)
    wins = opener_wins = 0
    turns = []
    for index in range(n):
        first = index % 2 if alternate else 0
        winner, length = simulate(d1, d2, policy1, policy2, s, mult, first=first)
        wins += winner == 0
        opener_wins += winner == first
        turns.append(length)
    return wins / n, statistics.mean(turns), opener_wins / n


def pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


# -- typical decks -----------------------------------------------------------------------------------------


class Catalogue:
    """The active characters and items, and which item is whose."""

    def __init__(self, s):
        self.s = s
        self.chars = [b for b in h.bd.groups[h.GROUP["Characters"]].balls if b.enabled]
        self.fruits = [b for b in h.bd.groups[h.GROUP["Devil fruits"]].balls if b.enabled]
        self.weapons = [b for b in h.bd.groups[h.GROUP["Weapons"]].balls if b.enabled]
        self.own: dict[int, dict[str, list]] = {}
        for rule in bm.EquipAffinity.objects.filter(character__isnull=False, item__isnull=False):
            item = h.bd.balls[rule.item_id]
            if item.enabled:
                kinds = self.own.setdefault(rule.character_id, {})
                kinds.setdefault(bm.role_of(item.pk, s), []).append((rule.percent, item))
        self.everyones = {item.pk for kinds in self.own.values() for options in kinds.values() for _, item in options}

    def tier(self, ball) -> int:
        return engine.tier_of(ball.rarity, self.s.tier_bounds)

    def typical(self, t: int, n: int = 4) -> list:
        inside = [b for b in self.chars if self.tier(b) == t]
        median = statistics.median(b.attack + b.health for b in inside)
        with_fruit = [b for b in inside if self.own.get(b.pk, {}).get("fruit")]
        return sorted(with_fruit, key=lambda b: (abs(b.attack + b.health - median), b.pk))[:n]

    def canon(self, ball, role: str):
        """A character's own item of a kind: the one giving them the most."""
        options = self.own.get(ball.pk, {}).get(role) or []
        if not options:
            return None
        return max(options, key=lambda x: (x[0] * (x[1].attack + x[1].health), -x[1].pk))[1]

    def median_item(self, pool, t: int, exclude=(), at_least=()):
        """The item of a tier closest to its median. `exclude` is dropped when it leaves nothing."""
        inside = [b for b in pool if self.tier(b) == t and b.pk not in exclude and b.pk not in at_least]
        if not inside:
            inside = [b for b in pool if self.tier(b) == t and b.pk not in at_least]
        median = statistics.median(b.attack + b.health for b in inside)
        return min(inside, key=lambda b: (abs(b.attack + b.health - median), b.pk))

    def specs(self) -> tuple[dict, dict]:
        """Who is in each typical deck and what they are handed, per tier and per way of equipping them."""
        specs: dict[tuple[int, str], list] = {}
        offbrand: dict[int, str] = {}
        for t in range(6):
            members = self.typical(t)
            fruits = [self.canon(b, "fruit") for b in members]
            gear_fruit = self.median_item(
                self.fruits, min(t, 4), exclude=self.everyones, at_least={f.pk for f in fruits}
            )
            gear_weapon = self.median_item(self.weapons, min(t, 2))
            top = [self.median_item(self.fruits, 0).country, self.median_item(self.weapons, 0).country]
            offbrand[t] = f"{gear_fruit.country} + {gear_weapon.country}"
            specs[(t, "bare")] = [(b.country, []) for b in members]
            # their own fruit, and their own weapon for the few who have one
            specs[(t, "canon")] = [
                (b.country, [x.country for x in (self.canon(b, "fruit"), self.canon(b, "weapon")) if x])
                for b in members
            ]
            # the same four fruits, each in the hands of the next character: "any item" at equal cost
            specs[(t, "swapped")] = [
                (b.country, [fruits[(i + 1) % len(members)].country]) for i, b in enumerate(members)
            ]
            # a fruit of their own tier that is nobody's, plus one of the commonest weapons their tier can find
            specs[(t, "offbrand")] = [(b.country, [gear_fruit.country, gear_weapon.country]) for b in members]
            # their own fruit plus a weapon: the full set at its cheapest
            specs[(t, "canon+w")] = [
                (b.country, [self.canon(b, "fruit").country, (self.canon(b, "weapon") or gear_weapon).country])
                for b in members
            ]
            # somebody else's top gear
            specs[(t, "toprare")] = [(b.country, top) for b in members]
        return specs, offbrand


async def build(w: h.World, specs: dict, s, only=None) -> dict:
    return {key: await deck(w, spec, s) for key, spec in specs.items() if only is None or key in only}


async def against_the_cog(w: h.World, s):
    """The same decks, seed and policy through the real cog and through the simulator."""
    straw = [("Roronoa Zoro", ["Wado Ichimonji"]), ("Nami", ["Sorcery Clima Tact"]), "Usopp"]
    others = [("Vinsmoke Sanji", ["Hassaikai"]), ("Portgas D. Ace", ["Mera Mera no Mi (Fire Fire)"]), "Marco"]
    rare = ["Monkey D. Luffy", "Kaido", "Sakazuki (Akainu)"]
    checks = [
        ("bare, same tier", rare, ["Marshall D. Teach (Blackbeard)", "Kaido", "Monkey D. Luffy"]),
        ("equipped, relations and resistances in play", straw, others),
    ]
    user = 1
    policy = p_smart_heal
    for label, spec1, spec2 in checks:
        same = 0
        total = 6
        for seed in range(total):
            fight = await w.fight(user, user + 1, spec1, spec2)
            state = await fight.state()
            d1 = [engine.BattleBall.from_dict(c) for c in state["p1_balls"]]
            d2 = [engine.BattleBall.from_dict(c) for c in state["p2_balls"]]
            mult = await multipliers(d1, d2, s)
            h.real_randomness(seed)
            expected = simulate(d1, d2, policy, policy, s, mult, first=0)
            h.real_randomness(seed)
            while (session := await fight.session()).status == "active":
                st = session.state
                side = st["active"]
                att = engine.BattleBall.from_dict(battle_cog.current_ball(st, side))
                dfn = engine.BattleBall.from_dict(battle_cog.current_ball(st, battle_cog.other_side(side)))
                action = policy(att, dfn, s, mult[(att.instance_id, dfn.instance_id)])
                await fight.act(user if side == "p1" else user + 1, BUTTON[action])
            mine = bm.BattleRecord.objects.filter(player1__discord_id=w.user(user).id)
            record = await mine.select_related("winner").alatest("pk")
            got = (0 if record.winner.discord_id == w.user(user).id else 1, record.turns)
            same += got == expected
            user += 2
        r.check(f"{label}: same winner in the same number of turns as the real cog, seed after seed", same, total)


def describe(decks: dict, offbrand: dict):
    variants = ("bare", "canon", "swapped", "offbrand", "canon+w", "toprare")
    for t in range(6):
        lines = []
        for bare, full in zip(decks[(t, "bare")], decks[(t, "canon")]):
            gear = h.loadout.equipment_line(full.equipment) or "-"
            lines.append(f"{full.name} {bare.attack}/{bare.max_health}->{full.attack}/{full.max_health} [{gear}]")
        r.note(f"{TIER_NAMES[t]:9s} " + ", ".join(lines))
        powers = ", ".join(f"{variant} {power(decks[(t, variant)])}" for variant in variants)
        r.note(f"{'':9s} power (attack + health of the deck): {powers}")
        r.note(f"{'':9s} offbrand = {offbrand[t]}")


async def how_a_battle_plays(s, decks: dict):
    mirror = decks[(0, "bare")]
    rate, turns, opener = await series(mirror, copy.deepcopy(mirror), s, alternate=False)
    r.note(f"same deck, same policy on both sides: the one who opens wins {pct(opener)} of {N} ({turns:.1f} turns)")
    rate, _, _ = await series(mirror, copy.deepcopy(mirror), s)
    r.ok("in a mirror match with the opener alternating, each side wins about half", abs(rate - 0.5) < 0.06, pct(rate))
    for label, pol1, pol2 in (
        ("Crit Gamble every turn against Attack every turn", p_crit, p_attack),
        ("Capacity then Crit Gamble against Attack every turn (a player against the turn clock)", p_smart, p_attack),
        ("the same plus healing under 35% against the same without healing", p_smart_heal, p_smart),
    ):
        rate, turns, _ = await series(mirror, copy.deepcopy(mirror), s, pol1, pol2)
        r.note(f"{label}: {pct(rate)} ({turns:.1f} turns)")
    full_mirror = decks[(0, "canon")]
    rate, turns, _ = await series(full_mirror, copy.deepcopy(full_mirror), s, p_smart_heal, p_smart)
    r.note(f"healing under 35%, rare deck in its own gear against itself: {pct(rate)} ({turns:.1f} turns)")
    for t in (0, 1, 2, 4):
        for variant in ("bare", "canon"):
            one = decks[(t, variant)]
            _, turns, opener = await series(one, copy.deepcopy(one), s, alternate=False)
            r.note(
                f"{TIER_NAMES[t]} deck, {variant}, against itself: the opener wins {pct(opener)} ({turns:.1f} turns)"
            )
    _, turns, opener = await series(mirror, copy.deepcopy(mirror), s, p_attack, p_attack, alternate=False)
    r.note(f"two absent players (the clock attacks for both): the opener wins {pct(opener)} ({turns:.1f} turns)")


async def rarity_alone(s, decks: dict):
    r.note(" " * 12 + "".join(f"{name:>10s}" for name in TIER_NAMES))
    never_ends = 0
    for a in range(6):
        cells = []
        for b in range(6):
            other = decks[(b, "bare")] if a != b else copy.deepcopy(decks[(b, "bare")])
            rate, turns, _ = await series(decks[(a, "bare")], other, s)
            never_ends += turns >= 2000
            cells.append(f"{pct(rate):>10s}")
        r.note(f"{TIER_NAMES[a]:12s}" + "".join(cells))
    r.check("every simulated battle came to an end", never_ends, 0)


CATCH_UP = [
    ("T36-85  in its own fruits   vs T1-15   bare", (2, "canon"), (0, "bare")),
    ("T36-85  in off-brand gear   vs T1-15   bare", (2, "offbrand"), (0, "bare")),
    ("T36-85  own fruit + weapon  vs T1-15   bare", (2, "canon+w"), (0, "bare")),
    ("T36-85  in its own fruits   vs T16-35  bare", (2, "canon"), (1, "bare")),
    ("T36-85  in off-brand gear   vs T16-35  bare", (2, "offbrand"), (1, "bare")),
    ("T141-180 in its own fruits  vs T36-85  bare", (4, "canon"), (2, "bare")),
    ("T141-180 in its own fruits  vs T16-35  bare", (4, "canon"), (1, "bare")),
    ("T141-180 in its own fruits  vs T1-15   bare", (4, "canon"), (0, "bare")),
    ("T141-180 in off-brand gear  vs T36-85  bare", (4, "offbrand"), (2, "bare")),
    ("T181+   in its own fruits   vs T86-140 bare", (5, "canon"), (3, "bare")),
    ("--- and once the rare deck is equipped too", None, None),
    ("T36-85  in its own fruits   vs T1-15   in off-brand gear", (2, "canon"), (0, "offbrand")),
    ("T36-85  in its own fruits   vs T1-15   in its own fruits", (2, "canon"), (0, "canon")),
    ("T16-35  in its own fruits   vs T1-15   in its own fruits", (1, "canon"), (0, "canon")),
    ("T141-180 in its own fruits  vs T36-85  in its own fruits", (4, "canon"), (2, "canon")),
    ("T141-180 in its own fruits  vs T36-85  in off-brand gear", (4, "canon"), (2, "offbrand")),
    ("--- rare items in modest hands", None, None),
    ("T141-180 in top-tier gear at 50% vs T1-15 bare", (4, "toprare"), (0, "bare")),
    ("T141-180 in top-tier gear at 50% vs T1-15 in its own fruits", (4, "toprare"), (0, "canon")),
    ("T36-85  in top-tier gear at 50% vs T1-15 in its own fruits", (2, "toprare"), (0, "canon")),
]
CANON_OR_NOT = [
    ("own fruit (200%) vs the same fruits swapped (50%)", "canon", "swapped"),
    ("own fruit (200%) vs nothing", "canon", "bare"),
    ("the same fruits swapped (50%) vs nothing", "swapped", "bare"),
    ("off-brand fruit + weapon (50% + 50% + set) vs nothing", "offbrand", "bare"),
    ("own fruit + a weapon (set bonus) vs own fruit alone", "canon+w", "canon"),
]
HEADER = f"{'match-up':62s} {'wins':>7s} {'turns':>6s}   power"


async def catch_up(s, decks: dict):
    r.note(HEADER)
    for label, left, right in CATCH_UP:
        if left is None:
            r.note(label)
            continue
        rate, turns, _ = await series(decks[left], decks[right], s)
        r.note(f"{label:62s} {pct(rate):>7s} {turns:6.1f}   {power(decks[left])} vs {power(decks[right])}")


async def canon_or_not(s, decks: dict):
    r.note(HEADER)
    for t in (0, 1, 2, 4):
        for label, left, right in CANON_OR_NOT:
            one, other = decks[(t, left)], decks[(t, right)]
            rate, turns, _ = await series(one, other, s)
            r.note(f"{TIER_NAMES[t]:9s}{label:53s} {pct(rate):>7s} {turns:6.1f}   {power(one)} vs {power(other)}")


async def power_curve(s, decks: dict):
    points = []
    picker = random.Random(7)
    for left, right in itertools.permutations(list(decks), 2):
        ratio = power(decks[left]) / power(decks[right])
        if 0.5 <= ratio <= 2.0 and picker.random() < 0.6:
            rate, _, _ = await series(decks[left], decks[right], s, n=200, seed=3)
            points.append((ratio, rate))
    bands = ((0.5, 0.7), (0.7, 0.85), (0.85, 0.95), (0.95, 1.05), (1.05, 1.18), (1.18, 1.43), (1.43, 2.0))
    for low, high in bands:
        inside = [rate for ratio, rate in points if low <= ratio < high]
        if inside:
            mean = pct(statistics.mean(inside))
            r.note(f"power ratio {low:.2f} to {high:.2f}: wins {mean} on average over {len(inside)} match-ups")


async def turning_the_knob(w: h.World, s, specs: dict):
    """The same match-ups with the health multiplier at 1, 2 and 3: what the setting buys."""
    wanted = {(0, "bare"), (0, "canon"), (2, "bare"), (2, "canon")}
    columns = (
        "opener wins / turns: T1-15 bare, T1-15 geared, T36-85 bare | healing under 35% | T36-85 geared vs T1-15 bare"
    )
    r.note(columns)
    for multiplier in (1.0, 2.0, 3.0):
        tuned = copy.copy(s)
        tuned.health_multiplier = multiplier
        decks = await build(w, specs, tuned, only=wanted)
        cells = []
        for key in ((0, "bare"), (0, "canon"), (2, "bare")):
            _, turns, opener = await series(decks[key], copy.deepcopy(decks[key]), tuned, alternate=False)
            cells.append(f"{pct(opener)} / {turns:4.1f}")
        mirror = decks[(0, "bare")]
        heal, _, _ = await series(mirror, copy.deepcopy(mirror), tuned, p_smart_heal, p_smart)
        upset, _, _ = await series(decks[(2, "canon")], decks[(0, "bare")], tuned)
        r.note(f"x{multiplier:g}:  " + ",  ".join(cells) + f"  |  {pct(heal)}  |  {pct(upset)}")


async def body(w: h.World):
    # the settings as the database holds them, health multiplier included
    w.defaults.clear()
    s = await w.cog.get_settings()
    r.note(f"health multiplier in play: x{s.health_multiplier:g}")
    r.section("the simulator against the real cog")
    await against_the_cog(w, s)
    r.section("typical decks")
    cat = await h.sync_to_async(Catalogue)(s)
    specs, offbrand = cat.specs()
    decks = await build(w, specs, s)
    describe(decks, offbrand)
    r.section("how a battle plays, whatever the decks")
    await how_a_battle_plays(s, decks)
    r.section("rarity alone: nobody wears anything (row beats column, opener alternating)")
    await rarity_alone(s, decks)
    r.section("equipment: does it let a modest deck catch up with a rarer one")
    await catch_up(s, decks)
    r.section("the canonical item against any item, same characters on both sides")
    await canon_or_not(s, decks)
    r.section("how much extra power wins how often (random pairs of the decks above, by power ratio)")
    await power_curve(s, decks)
    r.section("turning the health multiplier")
    await turning_the_knob(w, s, specs)


async def main(w: h.World):
    await r.scenario("balance", body, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
