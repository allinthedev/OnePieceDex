"""
The lists Discord shows under the treasure arguments of the battle commands while a player types.

Each argument is asked for its list the way Discord asks: through the `autocomplete` of the very parameter
of the very command, so the wiring is tested with the lists. What a player picks, or types by hand past the
list, is still read and checked by the commands; the other files cover that, through the same parameters.
"""

import sys

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

from ballsdex.core.utils.transformers import BallInstanceTransformer  # noqa: E402

BLOCK = 10
r = h.Report("t10_arguments")
bm = h.bm
GOMU = "Gomu Gomu no Mi (Gum Gum)"
ARGUMENTS = {
    ("add", "countryball"): "CharacterTransformer",
    ("remove", "countryball"): "DeckCharacterTransformer",
    ("equip", "item"): "ItemTransformer",
    ("equip", "character"): "DeckCharacterTransformer",
    ("unequip", "item"): "DeckItemTransformer",
}


def hexa(*instance_ids: int) -> list[str]:
    return [f"{pk:X}" for pk in instance_ids]


def values(options: list[tuple[str, str]]) -> list[str]:
    return [value for _, value in options]


async def wiring(w: h.World):
    got = {key: type(w.parameter(*key)._annotation).__name__ for key in ARGUMENTS}
    r.check("each argument has the list made for it", got, ARGUMENTS)
    reading = {}
    for key in ARGUMENTS:
        cls = type(w.parameter(*key)._annotation)
        own = [c for c in cls.__mro__ if c is not BallInstanceTransformer and issubclass(c, BallInstanceTransformer)]
        changed = sorted({name for c in own for name in ("transform", "validate", "get_from_pk") if name in vars(c)})
        reading[key] = (issubclass(cls, BallInstanceTransformer), changed)
    untouched = {key: (True, []) for key in ARGUMENTS}
    r.check("and reads and checks what is picked exactly as every treasure argument does", reading, untouched)


async def role_lists(w: h.World):
    await w.player(1)
    luffy = await w.give(1, "Monkey D. Luffy")
    nami = await w.give(1, "Nami")
    zoro = await w.give(1, "Roronoa Zoro")
    strong_nami = await w.give(1, "Nami", attack_bonus=20)
    wado = await w.give(1, "Wado Ichimonji")
    gomu = await w.give(1, GOMU)
    await w.give(1, "Shark Superb")
    await w.give(1, "Vinsmoke Sora")
    battle_settings = await w.cog.get_settings()
    retired = next(
        (b for b in h.bd.balls.values() if not b.enabled and bm.role_of(b.pk, battle_settings) in ("weapon", "fruit")),
        None,
    )
    if retired is not None:
        await w.give(1, retired.pk)
    usopp = await w.give(2, "Usopp")

    listed = await w.options(1, "add", "countryball")
    wanted = hexa(luffy, zoro, strong_nami, nami)
    r.check(
        "/battle add lists the player's characters, the rarest first, the better copy first", values(listed), wanted
    )
    r.check("a choice reads like any treasure of the bot", listed[0][0], f"#{luffy:0X} Monkey D. Luffy ATK:+0% HP:+0%")
    names = " | ".join(label for label, _ in listed)
    strays = [name for name in ("Wado", "Gomu", "Shark Superb", "Vinsmoke Sora", "Usopp") if name in names]
    r.check("no weapon, fruit, ship, retired character or card of somebody else in it", strays, [])
    r.check("somebody else gets their own list", values(await w.options(2, "add", "countryball")), hexa(usopp))

    r.check("typing part of a name narrows it", values(await w.options(1, "add", "countryball", "zor")), hexa(zoro))
    by_id = await w.options(1, "add", "countryball", f"{nami:x}")
    r.check("typing a card's id finds that card", values(by_id), hexa(nami))
    exact = await w.options(1, "add", "countryball", "=nami")
    r.check("=Name lists the copies of exactly that character", values(exact), hexa(strong_nami, nami))
    r.check("=Nam is not a name", await w.options(1, "add", "countryball", "=nam"), [])
    r.check("a weapon's name finds nothing under /battle add", await w.options(1, "add", "countryball", "wado"), [])
    # the search by role is the bot's usual one, which takes the dots out of what is typed and not out of
    # the names: a name with a dot in it cannot be found by typing it in full
    dotted = await w.options(1, "add", "countryball", "Monkey D. Luffy")
    partial = await w.options(1, "add", "countryball", "luffy")
    with_dot = [b.country for b in h.bd.groups[h.GROUP["Characters"]].balls if b.enabled and "." in b.country]
    r.note(
        f"typing 'Monkey D. Luffy' in full finds {len(dotted)} card(s), typing 'luffy' finds {len(partial)}: "
        f"{len(with_dot)} active characters have a dot in their name (Monkey D. Luffy, Portgas D. Ace, ...)"
    )

    items = await w.options(1, "equip", "item")
    r.check("/battle equip item lists weapons and fruits only, the rarest first", values(items), hexa(gomu, wado))
    if retired is not None:
        r.ok(f"a retired item ({retired.country}) is not offered", retired.country not in str(items), "")
    r.check("typing narrows it too", values(await w.options(1, "equip", "item", "ichi")), hexa(wado))

    await h.BallInstance.all_objects.filter(pk=zoro).aupdate(deleted=True)
    left = values(await w.options(1, "add", "countryball"))
    r.check("a card that was deleted is no longer offered", left, hexa(luffy, strong_nami, nami))

    await w.player(3)
    for _ in range(30):
        await w.give(3, "Nami")
    many = await w.options(3, "add", "countryball")
    lengths = [len(label) for label, _ in many]
    r.check(
        "thirty candidates: 25 choices, Discord's limit, none over 100 characters",
        (len(many), max(lengths) <= 100),
        (25, True),
    )


async def deck_lists(w: h.World):
    await w.player(11)
    await w.player(12)
    zoro = await w.give(11, "Roronoa Zoro")
    luffy = await w.give(11, "Monkey D. Luffy")
    spare = await w.give(11, "Nami")
    enma = await w.give(11, "Enma")
    usopp = await w.give(12, "Usopp")
    lists = (("remove", "countryball"), ("equip", "character"), ("unequip", "item"))

    async def all_three(n: int) -> list:
        return [await w.options(n, command, name) for command, name in lists]

    r.check("with no battle being set up the deck lists are empty", await all_three(11), [[], [], []])

    # at x2, as in production: the labels carry the figures the battle will be played with
    w.override_settings(health_multiplier=2.0)
    _, fight = await w.propose(11, 12)
    await w.cmd_card(11, "add", countryball=zoro)
    await w.cmd_card(11, "add", countryball=luffy)
    await w.cmd_card(11, "equip", item=enma, character=zoro)
    await w.cmd_card(12, "add", countryball=usopp)

    in_deck = [
        ("Roronoa Zoro — 786 ATK / 1288 HP — holds Enma", f"{zoro:X}"),
        ("Monkey D. Luffy — 310 ATK / 602 HP", f"{luffy:X}"),
    ]
    r.check(
        "/battle equip character lists the deck, with its figures and what is held",
        await w.options(11, "equip", "character"),
        in_deck,
    )
    r.check("/battle remove lists the same", await w.options(11, "remove", "countryball"), in_deck)
    r.ok("a character the player owns but did not add is not in it", f"{spare:X}" not in values(in_deck), "")
    worn = [("Enma — held by Roronoa Zoro (200%)", f"{enma:X}")]
    r.check(
        "/battle unequip lists what is held, by whom and at what share", await w.options(11, "unequip", "item"), worn
    )
    theirs = await all_three(12)
    r.check(
        "the opponent sees their own deck and nothing of ours",
        theirs,
        [[("Usopp — 90 ATK / 196 HP", f"{usopp:X}")]] * 2 + [[]],
    )

    r.check(
        "typing a name narrows the deck list", values(await w.options(11, "equip", "character", "LUF")), hexa(luffy)
    )
    held = await w.options(11, "equip", "character", "enma")
    r.check("typing what is held finds its bearer", values(held), hexa(zoro))
    for typed in (f"{luffy:X}", f"{luffy:x}"):
        r.check(
            f"typing the id {typed} finds the card",
            values(await w.options(11, "remove", "countryball", typed)),
            hexa(luffy),
        )
    r.check("typing something that is not there finds nothing", await w.options(11, "unequip", "item", "wado"), [])

    # a label can run long: a long name holding two long names
    battle_settings = await w.cog.get_settings()
    characters = [b for b in h.bd.groups[h.GROUP["Characters"]].balls if b.enabled]
    longest = max(characters, key=lambda b: (len(b.country), b.pk))
    gear = []
    for group in ("Weapons", "Devil fruits"):
        pool = [b for b in h.bd.groups[h.GROUP[group]].balls if b.enabled]
        gear.append(max(pool, key=lambda b: (len(b.country), b.pk)))
    bearer = await w.give(12, longest.pk)
    await w.cmd_card(12, "add", countryball=bearer)
    for item in gear:
        await w.cmd_card(12, "equip", item=await w.give(12, item.pk), character=bearer)
    label = next(label for label, value in await w.options(12, "equip", "character") if value == f"{bearer:X}")
    card = (await fight.state())["p2_balls"][-1]
    full = f"{longest.country} — {card['attack']} ATK / {card['max_health']} HP — holds " + ", ".join(
        entry["name"] for entry in card["equipment"]
    )
    r.check(f"a label of {len(full)} characters is cut at Discord's 100", (len(full) > 100, label), (True, full[:100]))
    found = await w.options(12, "equip", "character", gear[1].country[-8:])
    r.check("and can still be found by what the cut took away", values(found), hexa(bearer))
    del battle_settings

    # once the battle runs there is no deck being built any more
    await fight.ready(11)
    await fight.ready(12)
    r.check("the battle has started", await fight.status(), "active")
    r.check("during a battle the deck lists are empty", await all_three(11), [[], [], []])
    listed = values(await w.options(11, "add", "countryball"))
    r.check("the lists by role do not depend on a battle", listed, hexa(luffy, zoro, spare))
    w.restore_settings()
    await fight.act(11, "forfeit")


async def main(w: h.World):
    await r.scenario("which list for which argument", wiring, w)
    await r.scenario("lists by role: /battle add and the item of /battle equip", role_lists, w)
    await r.scenario("lists read from the deck", deck_lists, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
