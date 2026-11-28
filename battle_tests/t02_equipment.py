"""3. equipment: `/battle equip`, `/battle unequip`, the three layers of affinity on the loaded data, stats."""

import random
import sys

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 2
r = h.Report("t02_equipment")
bm = h.bm

GOMU = "Gomu Gomu no Mi (Gum Gum)"
GORO = "Goro Goro no Mi (Thunder Thunder)"
NO_PLAN = "You don't have a battle being set up right now!"
FROZEN = "You cannot change your deck, you're already ready."
MOVE_IT = "Take it off with `/battle unequip` to move it."


def worn(card: dict) -> list[tuple]:
    return [(entry["slot"], entry["name"], entry["percent"]) for entry in card["equipment"]]


def stats(card: dict) -> tuple:
    return card["attack"], card["max_health"]


async def rules(w: h.World):
    await w.player(1)
    await w.player(2)
    luffy = await w.give(1, "Monkey D. Luffy")
    zoro = await w.give(1, "Roronoa Zoro")
    nami = await w.give(1, "Nami")
    gomu = await w.give(1, GOMU)
    wado = await w.give(1, "Wado Ichimonji")
    yoru = await w.give(1, "Yoru")
    goro = await w.give(1, GORO)
    await w.give(2, "Usopp")
    kabuto = await w.give(2, "Kabuto")

    i = await w.cmd_card(1, "equip", item=wado, character=zoro)
    r.check("equip with no battle being set up", i.first, NO_PLAN)
    i = await w.cmd_card(1, "unequip", item=wado)
    r.check("unequip with no battle being set up", i.first, NO_PLAN)

    _, fight = await w.propose(1, 2)
    i = await w.cmd_card(1, "equip", item=wado, character=zoro)
    not_in_deck = "That character is not in your deck: add them with `/battle add` first."
    r.check("equip on a character that is not in the deck", i.first, not_in_deck)
    await w.cmd_card(1, "add", countryball=luffy)
    await w.cmd_card(1, "add", countryball=zoro)

    i = await w.cmd_card(1, "equip", item=nami, character=zoro)
    r.check("a character cannot be equipped", i.first, "Only a weapon or a devil fruit can be equipped.")
    try:
        await w.cmd_card(1, "equip", item=kabuto, character=zoro)
        r.ok("somebody else's item is refused before the command runs", False)
    except h.commands.BadArgument:
        r.ok("somebody else's item is refused before the command runs", True)

    # Luffy 310/301. Gomu Gomu 630/530 at 200% is +1260/+1060.
    i = await w.cmd_card(1, "equip", item=gomu, character=luffy)
    told = f"**Monkey D. Luffy** now holds **{GOMU}**: +1260 ATK, +1060 HP (200% of its stats)."
    r.check("Luffy + Gomu Gomu", i.first, told)
    card = fight.card(await fight.state(), "p1", 0)
    r.check("Luffy's stats with his fruit", (*stats(card), card["health"]), (1570, 1361, 1361))
    r.check("his own stats are untouched underneath", (card["base_attack"], card["base_health"]), (310, 301))

    # Wado 230/230 at 30% is +69/+69, and weapon + fruit is 10% on the total: 1639 -> 1803, 1430 -> 1573
    i = await w.cmd_card(1, "equip", item=wado, character=luffy)
    r.ok("Luffy + Wado Ichimonji is 30%", i.said("+69 ATK, +69 HP (30% of its stats)"), i.first)
    r.ok("the full set is announced", i.said("Weapon and fruit together: +10% on top."), "")
    card = fight.card(await fight.state(), "p1", 0)
    r.check("Luffy's stats with the full set", (*stats(card), card["health"]), (1803, 1573, 1573))
    r.check("what he wears", worn(card), [("fruit", GOMU, 200), ("weapon", "Wado Ichimonji", 30)])
    listed = "┗ Wado Ichimonji (30%) · Gomu Gomu no Mi (Gum Gum) (200%)" in fight.proposal.text()
    r.ok("the proposal lists what he wears, weapon first", listed, "")

    i = await w.cmd_card(1, "equip", item=wado, character=zoro)
    r.check("an item already on another character", i.first, f"That one is already on **Monkey D. Luffy**. {MOVE_IT}")
    i = await w.cmd_card(1, "equip", item=wado, character=luffy)
    r.check("an item already on this character", i.first, f"That one is already on this character. {MOVE_IT}")

    # a second weapon takes the place of the first: Yoru 360/300, Luffy has 30% of any western sword too
    i = await w.cmd_card(1, "equip", item=yoru, character=luffy)
    replaced = i.said("+108 ATK, +90 HP (30% of its stats)") and i.said("Wado Ichimonji was put back.")
    r.ok("a second weapon replaces the first", replaced, i.first)
    card = fight.card(await fight.state(), "p1", 0)
    r.check("one weapon and one fruit, no more", worn(card), [("fruit", GOMU, 200), ("weapon", "Yoru", 30)])
    wanted = (round((310 + 1260 + 108) * 1.1), round((301 + 1060 + 90) * 1.1))
    r.check("stats follow the replacement", stats(card), wanted)

    i = await w.cmd_card(1, "equip", item=goro, character=luffy)
    r.ok("a second fruit replaces the first", i.said(f"{GOMU} was put back."), i.first)
    card = fight.card(await fight.state(), "p1", 0)
    default = [("weapon", "Yoru", 30), ("fruit", GORO, 50)]
    r.check("Luffy with somebody else's fruit gets the default 50%", worn(card), default)

    # the freed Wado goes to Zoro: 296/238 + 200% of 230/230
    i = await w.cmd_card(1, "equip", item=wado, character=zoro)
    r.ok("Zoro + Wado Ichimonji is 200%", i.said("+460 ATK, +460 HP (200% of its stats)"), i.first)
    card = fight.card(await fight.state(), "p1", 1)
    r.check("Zoro's stats with one item: no set bonus", stats(card), (756, 698))

    # taking things back
    i = await w.cmd_card(1, "unequip", item=gomu)
    r.check("unequip something nobody holds", i.first, "Nobody in your deck is holding that.")
    i = await w.cmd_card(1, "unequip", item=yoru)
    took = i.said("Took") and i.said("Yoru") and i.said("back from **Monkey D. Luffy**")
    r.ok("unequip the weapon", took, i.first)
    card = fight.card(await fight.state(), "p1", 0)
    r.check("without the weapon the set bonus goes too", stats(card), (310 + 195, 301 + 160))
    await w.cmd_card(1, "unequip", item=goro)
    card = fight.card(await fight.state(), "p1", 0)
    bare = (*stats(card), card["health"], card["equipment"])
    r.check("with nothing left Luffy is back to his own stats", bare, (310, 301, 301, []))

    # removing a character frees what it held
    await w.cmd_card(1, "remove", countryball=zoro)
    await w.cmd_card(1, "add", countryball=nami)
    i = await w.cmd_card(1, "equip", item=wado, character=nami)
    freed = i.said("+115 ATK, +115 HP (50% of its stats)")
    r.ok("an item is free again once its bearer left the deck (and Nami gets 50%)", freed, i.first)

    # a card's own bonus counts, on the item too
    sharp = await w.give(1, "Wado Ichimonji", attack_bonus=10, health_bonus=-10)
    await w.cmd_card(1, "add", countryball=zoro)
    i = await w.cmd_card(1, "equip", item=sharp, character=zoro)
    counted = i.said("+506 ATK, +414 HP (200% of its stats)")
    r.ok("the item's own +10%/-10% is counted before the share", counted, i.first)

    # the other side cannot touch any of it, and Ready freezes it
    i = await w.cmd_card(2, "unequip", item=kabuto)
    r.check("the opponent holds nothing of ours", i.first, "Nobody in your deck is holding that.")
    await fight.ready(1)
    i = await w.cmd_card(1, "equip", item=yoru, character=luffy)
    r.check("equip after Ready is refused", i.first, FROZEN)
    i = await w.cmd_card(1, "unequip", item=sharp)
    r.check("unequip after Ready is refused", i.first, FROZEN)
    await w.close_everything()

    # a retired item
    battle_settings = await w.cog.get_settings()
    retired = next(
        (b for b in h.bd.balls.values() if not b.enabled and bm.role_of(b.pk, battle_settings) in ("weapon", "fruit")),
        None,
    )
    if retired is None:
        r.note("no retired weapon or fruit in the dump: not tested")
    else:
        _, fight = await w.propose(1, 2)
        await w.cmd_card(1, "add", countryball=luffy)
        old = await w.give(1, retired.pk)
        i = await w.cmd_card(1, "equip", item=old, character=luffy)
        told = f"**{retired.country}** has been retired from the dex and sits battles out."
        r.check(f"a retired item ({retired.country}) is refused", i.first, told)
        await w.close_everything()


async def layers(w: h.World):
    """The percentages asked for by name, then a sample of the whole table against a plain re-reading of it."""
    battle_settings = await w.cog.get_settings()
    wanted = [
        ("Monkey D. Luffy", GOMU, 200),
        ("Monkey D. Luffy", "Wado Ichimonji", 30),
        ("Monkey D. Luffy", "Hassaikai", 50),
        ("Roronoa Zoro", "Wado Ichimonji", 200),
        ("Roronoa Zoro", "Yoru", 130),
        ("Roronoa Zoro", "Shodai Kitetsu", 150),
        ("Roronoa Zoro", GOMU, 50),
        ("Kaido", "Hassaikai", 200),
        ("Vinsmoke Sanji", "Wado Ichimonji", 25),
        ("Vinsmoke Sanji", "Hassaikai", 25),
        ("Vinsmoke Sanji", GOMU, 50),
        ("Nami", "Sorcery Clima Tact", 200),
        ("Nami", "Wado Ichimonji", 50),
        ("Marshall D. Teach (Blackbeard)", GORO, 120),
    ]
    for character, item, percent in wanted:
        got = await h.battle_cog.equip_percent(h.BALL[character], h.BALL[item], battle_settings)
        r.check(f"{character} + {item}", got, percent)

    # an independent reading of the table: exact pair, then the character's narrowest group, then anybody's
    # exact item, then anybody's narrowest group, then the default
    rows = [row async for row in bm.EquipAffinity.objects.all()]
    sizes = bm.group_sizes()

    def oracle(character_id: int, item_id: int) -> int:
        item_groups = set(bm.group_ids_of(item_id))
        for who in (character_id, None):
            exact = [x for x in rows if x.character_id == who and x.item_id == item_id]
            if exact:
                return exact[0].percent
            kinds = [x for x in rows if x.character_id == who and x.item_group_id in item_groups]
            if kinds:
                return min(kinds, key=lambda x: (sizes[x.item_group_id], x.pk)).percent
        return battle_settings.default_equip_percent

    characters = [pk for pk in h.bd.groups[h.GROUP["Characters"]]._ball_ids if h.bd.balls[pk].enabled]
    items = [
        pk
        for name in ("Weapons", "Devil fruits")
        for pk in h.bd.groups[h.GROUP[name]]._ball_ids
        if h.bd.balls[pk].enabled
    ]
    picker = random.Random(20261128)
    canonical = [(x.character_id, x.item_id) for x in rows if x.character_id and x.item_id]
    pairs = canonical + [(picker.choice(characters), picker.choice(items)) for _ in range(1500)]
    wrong = []
    spread: dict[int, int] = {}
    for index, (character_id, item_id) in enumerate(pairs):
        got = await h.battle_cog.equip_percent(character_id, item_id, battle_settings)
        if index < len(canonical):
            spread[got] = spread.get(got, 0) + 1
        if got != oracle(character_id, item_id):
            names = (h.bd.balls[character_id].country, h.bd.balls[item_id].country)
            wrong.append((*names, got, oracle(character_id, item_id)))
    r.check(f"{len(pairs)} pairs (every canonical pair + 1500 at random) agree with the table", wrong[:5], [])
    r.note(f"canonical pairs by percent: {dict(sorted(spread.items()))}")


async def in_battle(w: h.World):
    """What is worn has to survive the start of the battle and every turn written back to the state."""
    h.script_random()
    fight = await w.fight(
        11, 12, [("Monkey D. Luffy", [GOMU, "Wado Ichimonji"])], [("Kaido", ["Hassaikai"]), "Nami", "Usopp"]
    )
    state = await fight.state()
    card = fight.card(state, "p1")
    before = (*stats(card), worn(card))
    gear = [("fruit", GOMU, 200), ("weapon", "Wado Ichimonji", 30)]
    r.check("the equipped stats are the ones the battle starts with", before, (1803, 1573, gear))
    r.ok("the board shows what is worn", "┗ Hassaikai (200%)" in fight.board.text(), "")
    await fight.act(11, "attack")
    await fight.act(12, "attack")
    state = await fight.state()
    card = fight.card(state, "p1")
    r.check("two turns later nothing of it was lost", (*stats(card), worn(card)), before)
    r.check("a defeated card keeps what it wore", worn(fight.card(state, "p2")), [("weapon", "Hassaikai", 200)])
    i = await w.cmd_card(11, "unequip", item=card["equipment"][0]["instance_id"])
    r.check("no unequip once the battle runs", i.first, NO_PLAN)
    await fight.act(11, "forfeit")


async def main(w: h.World):
    await r.scenario("rules of equipping", rules, w)
    await r.scenario("the three layers on the loaded data", layers, w)
    await r.scenario("equipment during the battle", in_battle, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
