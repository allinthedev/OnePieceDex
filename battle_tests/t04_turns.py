"""
5. the turns: every action, the dodge, the hand-over of the turn, a card dying and the next one stepping in,
the end of the battle. Randomness is scripted, so every number below is the one the rules give.

Luffy 310/301 (T5) and Kaido 330/390 (T9) are in the same rarity tier, with no relation between them: every
hit between the two is multiplied by 0.95 and nothing else.
"""

import sys

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 4
r = h.Report("t04_turns")
bm = h.bm
SAME_TIER = 0.95
RARER = 0.925  # the defender is one tier rarer than the attacker
COMMONER = 0.975  # the defender is one tier more common
CREW = 0.75  # two Straw Hats hold back
NOT_YOURS = "It's not your turn."
PLAYED = "That turn has already been played."


def hit(attack: int, variance: float = 1.0, relation: float = 1.0, tier: float = SAME_TIER, action: float = 1.0) -> int:
    """The damage of one hit, multiplied in the order the engine multiplies."""
    return max(1, round(attack * variance * relation * tier * action))


def hp(state, side, index=0):
    return state[f"{side}_balls"][index]["health"]


async def attack_and_handover(w: h.World):
    rng = h.script_random()
    fight = await w.fight(1, 2, ["Monkey D. Luffy", "Nami"], ["Kaido", "Usopp"])

    i = await fight.act(2, "attack")
    r.check("the other player clicks first: refused, and told why", (i.first, i.answered), (NOT_YOURS, True))
    i = await fight.act(3, "attack")
    r.check("an outsider clicks: refused", i.first, "You aren't a part of this battle.")
    state = await fight.state()
    r.check("neither changed anything", (state["turn"], state["active"], hp(state, "p2")), (0, "p1", 390))

    first_view = fight.board.view
    i = await fight.act(1, "attack")
    state = await fight.state()
    r.check("Attack at the top of the range: 310 x 1.0 x 0.95 = 294", 390 - hp(state, "p2"), hit(310))
    r.check("the turn is counted and handed over", (state["turn"], state["active"]), (1, "p2"))
    r.check("the log tells it", state["log"], ["Turn 1: **Monkey D. Luffy** hits **Kaido** for **294**"])
    refreshed = "Tester2**'s turn — Turn 1" in fight.board.text() and "Kaido" in fight.board.text()
    r.ok("the board is refreshed for the other player", refreshed, "")
    view = fight.board.view
    handed = (first_view.is_finished(), view.active_user_id, view.turn)
    r.check("the old buttons are dead, new ones are up for the other player's turn", handed, (True, w.user(2).id, 1))
    r.check("the click was answered", i.answered, True)
    i = await w.click(1, first_view, "attack", message=fight.board)
    r.check("a second click on the old buttons reaches nothing", i.dead, True)
    i = await fight.act(1, "heal", force_view=first_view)
    r.check("and one that was already on its way is turned away", i.first, PLAYED, bug="B01")
    state = await fight.state()
    r.check("without playing anything", (state["turn"], state["active"]), (1, "p2"), bug="B01")

    i = await fight.act(1, "attack")
    r.check("the author clicking again during the other's turn", i.first, NOT_YOURS)

    rng.spread = 0.0
    await fight.act(2, "attack")
    state = await fight.state()
    r.check("Attack at the bottom of the range: 330 x 0.6 x 0.95 = 188", 301 - hp(state, "p1"), hit(330, variance=0.6))
    r.check("back to the author at turn 2", (state["turn"], state["active"]), (2, "p1"))
    await fight.act(1, "forfeit")


async def crit_and_dodge(w: h.World):
    rng = h.script_random()
    fight = await w.fight(11, 12, ["Monkey D. Luffy", "Nami"], ["Kaido", "Usopp"])

    rng.queue(0.99, 0.49)  # not dodged, then the gamble lands (chance 0.5)
    await fight.act(11, "crit")
    state = await fight.state()
    # Kaido has 390: 310 x 2 x 0.95 = 589 puts him down
    landed = "Turn 1: **Monkey D. Luffy** lands a **CRITICAL HIT** on **Kaido** for **589** — Kaido is defeated!"
    r.check("a Crit Gamble that lands hits for double", state["log"][-1], landed)
    r.check("the card is dead at 0", (state["p2_balls"][0]["dead"], hp(state, "p2")), (True, 0))
    struck = "~~ Kaido~~ 💀" in fight.board.text() and "Usopp" in fight.board.text()
    r.ok("the board strikes it out and shows the next one", struck, "")
    r.check("the next card's Capacity is on the button", fight.board.view.capacity.label, "Sniper")

    rng.queue(0.99, 0.5)  # not dodged, the gamble misses
    await fight.act(12, "crit")
    state = await fight.state()
    # Usopp (T33) on Luffy (T5): one tier rarer, and two Straw Hats
    missed = hit(90, relation=CREW, tier=RARER, action=0.5)
    r.check("a Crit Gamble that misses hits for half: 90 x 0.5 x 0.925 x 0.75 = 31", 301 - hp(state, "p1"), missed)
    r.ok("and says nothing of a critical hit", "CRITICAL" not in state["log"][-1], state["log"][-1])

    rng.queue(0.149)  # under the 0.15 dodge chance
    before = hp(state, "p2", 1)
    await fight.act(11, "attack")
    state = await fight.state()
    dodged = (hp(state, "p2", 1), state["log"][-1])
    r.check("a dodged attack does nothing", dodged, (before, "Turn 3: **Usopp** dodges Monkey D. Luffy's attack!"))
    r.check("but the turn is spent", (state["turn"], state["active"]), (3, "p2"))

    rng.queue(0.15)  # exactly the chance: not under it
    before = hp(state, "p1")
    await fight.act(12, "attack")
    state = await fight.state()
    r.ok("a roll equal to the dodge chance is a hit", hp(state, "p1") < before, "")

    rng.queue(0.0)
    before = hp(state, "p2", 1)
    await fight.act(11, "crit")
    state = await fight.state()
    r.check("a Crit Gamble can be dodged too", hp(state, "p2", 1), before)
    await fight.act(12, "forfeit")


async def heal(w: h.World):
    rng = h.script_random()
    fight = await w.fight(21, 22, ["Monkey D. Luffy", "Roronoa Zoro"], ["Kaido", "Usopp"])

    await fight.act(21, "attack")  # Kaido 390 -> 96
    rng.spread = 0.0
    await fight.act(22, "heal")
    state = await fight.state()
    low = (hp(state, "p2") - 96, state["log"][-1])
    r.check(
        "Heal at the bottom of the range: 25% of 390",
        low,
        (round(390 * 0.25), "Turn 2: **Kaido** heals for **98** HP!"),
    )
    r.check("one heal is counted against the card", state["p2_balls"][0]["heal_uses"], 1)
    r.check("healing takes the turn", (state["turn"], state["active"]), (2, "p1"))

    rng.spread = 1.0
    await fight.act(21, "heal")  # Luffy is unhurt
    state = await fight.state()
    wasted = (hp(state, "p1"), state["log"][-1])
    r.check("a heal at full health restores nothing", wasted, (301, "Turn 3: **Monkey D. Luffy** heals for **0** HP!"))
    r.check("and still costs one of the two heals", state["p1_balls"][0]["heal_uses"], 1)

    await fight.act(22, "heal")
    state = await fight.state()
    top = (hp(state, "p2") - 194, state["p2_balls"][0]["heal_uses"])
    r.check("Heal at the top of the range: 45% of 390", top, (round(390 * 0.45), 2))

    await fight.act(21, "attack")  # Kaido 370 -> 76
    view = fight.board.view
    r.check(
        "with both heals used the Heal button is greyed out",
        (view.heal.disabled, view.capacity.disabled),
        (True, False),
    )
    i = await fight.act(22, "heal")
    r.check("so a click on it reaches nothing", (i.dead, (await fight.state())["turn"]), (True, 5))
    await fight.act(22, "heal", force_view=view)  # a click that was already on its way
    state = await fight.state()
    r.check("a third Heal heals nothing", hp(state, "p2"), 76)
    fallback = (
        "Turn 6: **Kaido** has no more heals left this battle and attacks instead!\n"
        f"**Kaido** hits **Monkey D. Luffy** for **{hit(330)}** — Monkey D. Luffy is defeated!"
    )
    r.check('and "attacks instead" is a real attack', state["log"][-1], fallback, bug="B06")
    r.check("which the opponent takes: 330 x 0.95 = 314 on 301", state["p1_balls"][0]["dead"], True, bug="B06")
    r.check("the turn went by", (state["turn"], state["active"]), (6, "p1"))
    r.check("the next card, which has its heals, keeps the button", fight.board.view.heal.disabled, False)

    await fight.act(21, "attack")  # Zoro (T18) on Kaido (T9): 296 x 0.925 = 274 on 76, Usopp steps in
    await fight.act(22, "attack")  # Usopp on Zoro, two Straw Hats of the same tier: 90 x 0.75 x 0.95 = 64
    await fight.act(21, "heal")
    state = await fight.state()
    capped = (hp(state, "p1", 1), state["log"][-1])
    told = f"Turn 9: **Roronoa Zoro** heals for **{hit(90, relation=CREW)}** HP!"
    r.check("a Heal never goes past the maximum (45% of 238 is 107, 64 were missing)", capped, (238, told))
    await fight.act(22, "heal")
    state = await fight.state()
    own = (state["p2_balls"][1]["heal_uses"], "heals for" in state["log"][-1])
    r.check("heals are counted per card: the next card has its own", own, (1, True))
    await fight.act(21, "forfeit")


async def capacity(w: h.World):
    rng = h.script_random()
    used = ("Monkey D. Luffy", "Kaido", "Nami", "Usopp", "Roronoa Zoro")
    taken = [name for name in used if await bm.Buff.objects.filter(ball_id=h.BALL[name]).aexists()]
    if taken:
        r.note(f"a real Buff row exists for {taken}: the Capacity effects are not tested on top of it")
        return

    # no Buff row at all: the plain special attack, 1.5x by default
    fight = await w.fight(31, 32, ["Monkey D. Luffy"], ["Kaido", "Usopp"])
    await fight.act(31, "capacity")
    state = await fight.state()
    plain = "Turn 1: **Monkey D. Luffy** unleashes **Stretchy** on **Kaido** for **442** — Kaido is defeated!"
    r.check("no Buff row: Capacity is the default 1.5x attack (310 x 1.5 x 0.95 = 442)", state["log"][-1], plain)
    r.check("it is counted", state["p1_balls"][0]["capacity_uses"], 1)
    await fight.act(32, "attack")
    view = fight.board.view
    r.check("once used the Capacity button is greyed out", (view.capacity.disabled, view.heal.disabled), (True, False))
    i = await fight.act(31, "capacity")
    r.check("so a click on it reaches nothing", i.dead, True)
    await fight.act(31, "capacity", force_view=view)  # a click that was already on its way
    session = await fight.session()
    fallback = (
        "Turn 3: **Monkey D. Luffy** has already used its Capacity this battle and attacks instead!\n"
        f"**Monkey D. Luffy** hits **Usopp** for **{hit(310, relation=CREW, tier=COMMONER)}** — Usopp is defeated!"
    )
    r.check('a second Capacity "attacks instead", for real', session.state["log"][-1], fallback, bug="B06")
    r.check("and that attack can end the battle", session.status, "finished", bug="B06")

    # the effect is read from the treasure's Buff row
    mark = h.BUFF_MARK
    flat = {"capacity_effect": "flat_damage", "capacity_value": 200 + mark}
    try:
        await bm.Buff.objects.acreate(ball_id=h.BALL["Monkey D. Luffy"], **flat)
        saved = "saved"
    except Exception as error:
        saved = f"{type(error).__name__}: {error}"
    r.check("a Buff row can be saved (what the admin does)", saved, "saved", bug="B08")
    if saved != "saved":
        await bm.Buff.objects.abulk_create([bm.Buff(ball_id=h.BALL["Monkey D. Luffy"], **flat)])
    await bm.Buff.objects.acreate(ball_id=h.BALL["Kaido"], capacity_effect="heal_percent", capacity_value=40 + mark)
    await bm.Buff.objects.acreate(ball_id=h.BALL["Nami"], capacity_effect="damage_multiplier", capacity_value=3 + mark)
    await bm.Buff.objects.acreate(ball_id=h.BALL["Usopp"], health=111, attack=222, capacity_value=mark)
    try:
        await bm.Buff.objects.acreate(ball_id=h.BALL["Roronoa Zoro"], capacity_effect="flat_damage", capacity_value=0)
        refused = "saved"
    except Exception as error:
        refused = type(error).__name__
    r.check("an effect with no value is refused by the model", refused, "ValidationError")

    fight = await w.fight(33, 34, ["Monkey D. Luffy", "Nami"], ["Kaido", "Usopp"])
    state = await fight.state()
    card = state["p1_balls"][0]
    travels = (card["capacity_effect"], card["capacity_value"])
    r.check("the effect travels with the card", travels, ("flat_damage", 200 + mark))
    card = state["p2_balls"][1]
    boosted = (card["attack"], card["max_health"], card["base_attack"], card["base_health"])
    r.check("flat Buff bonuses are added to the stats (Usopp 90/98 +222/+111)", boosted, (312, 209, 312, 209))

    rng.spread = 0.0  # a fixed amount must not care about the attack roll
    await fight.act(33, "capacity")
    state = await fight.state()
    wanted = round((200 + mark) * SAME_TIER)
    r.check("flat_damage: the amount, times the tier, whatever the attack", 390 - hp(state, "p2"), wanted)
    told = f"Turn 1: **Monkey D. Luffy** unleashes **Stretchy** on **Kaido** for **{wanted}**!"
    r.check("its line in the log", state["log"][-1], told)
    rng.spread = 1.0
    await fight.act(34, "capacity")
    state = await fight.state()
    healed = round(390 * (40 + mark) / 100)
    told = f"Turn 2: **Kaido** uses **Strongest creature** and heals for **{healed}** HP!"
    after = 390 - wanted + healed
    r.check("heal_percent: that share of the maximum", (hp(state, "p2"), state["log"][-1]), (after, told))
    counters = (state["p2_balls"][0]["heal_uses"], state["p2_balls"][0]["capacity_uses"])
    r.check("a healing Capacity does not eat a Heal", counters, (0, 1))

    await fight.act(33, "attack")  # Kaido 356 -> 62
    rng.queue(0.99, 0.0)
    await fight.act(34, "crit")  # 330 x 2 x 0.95 = 627: Luffy is down, Nami steps in
    state = await fight.state()
    r.check(
        "Luffy is down, Nami is next",
        (state["p1_balls"][0]["dead"], fight.board.view.capacity.label),
        (True, "Cat burglar"),
    )
    await fight.act(33, "capacity")
    state = await fight.state()
    # Nami (tier 1) on Kaido (tier 0): 0.925
    wanted = round(89 * RARER * (3 + mark))
    told = f"Turn 5: **Nami** unleashes **Cat burglar** on **Kaido** for **{wanted}** — Kaido is defeated!"
    r.check("damage_multiplier: the attack times that", state["log"][-1], told)
    await fight.act(34, "forfeit")

    # a Buff on a special gives its bonus to every card of that special that has no Buff of its own
    festive_heal = {"capacity_effect": "heal_percent", "capacity_value": 10 + mark}
    await bm.Buff.objects.acreate(special_id=h.SPECIAL["Christmas 2025"], health=7, attack=9, **festive_heal)
    festive = [{"ball": "Roronoa Zoro", "special": "Christmas 2025"}, {"ball": "Nami", "special": "Christmas 2025"}]
    fight = await w.fight(35, 36, festive, ["Roronoa Zoro"])
    state = await fight.state()
    zoro, nami = state["p1_balls"]
    reached = (zoro["attack"], zoro["max_health"], zoro["capacity_effect"])
    r.check(
        "a special's Buff reaches a card with no Buff of its own (Zoro 296/238 +9/+7)",
        reached,
        (305, 245, "heal_percent"),
    )
    own = (nami["attack"], nami["capacity_effect"])
    r.check("the treasure's own Buff wins over the special's", own, (89, "damage_multiplier"))
    await fight.act(35, "forfeit")
    await h.awipe_marked_rows()

    # the setting says the dodge chance applies to "any damaging action"
    await bm.Buff.objects.acreate(ball_id=h.BALL["Kaido"], capacity_effect="heal_percent", capacity_value=10 + mark)
    w.override_settings(dodge_chance=1.0)
    rng.roll = 0.5
    fight = await w.fight(37, 38, ["Roronoa Zoro"], ["Kaido", "Usopp"])
    await fight.act(37, "attack")
    await fight.act(38, "crit")
    state = await fight.state()
    r.check(
        "with a dodge chance of 100%, Attack and Crit Gamble never land", (hp(state, "p1"), hp(state, "p2")), (238, 390)
    )
    await fight.act(37, "capacity")  # no Buff row: the plain 1.5x attack
    state = await fight.state()
    r.check("and a damaging Capacity is dodged like any other hit", hp(state, "p2"), 390, bug="B16")
    spent = (state["log"][-1], state["p1_balls"][0]["capacity_uses"])
    r.check("it is spent all the same", spent, ("Turn 3: **Kaido** dodges Roronoa Zoro's **3 sword style**!", 1))
    await fight.act(38, "capacity")
    state = await fight.state()
    told = "Turn 4: **Kaido** uses **Strongest creature** and heals for **0** HP!"
    r.check("a healing Capacity is never dodged", state["log"][-1], told)
    w.restore_settings()
    rng.roll = 0.99
    await fight.act(38, "forfeit")
    await h.awipe_marked_rows()


async def shop_items(w: h.World):
    rng = h.script_random()
    prefix = h.ITEM_PREFIX
    make = bm.BattleItem.objects.acreate
    boost = await make(name=prefix + "Rage", price=30, effect_type="attack_boost", effect_value=1.5)
    sure = await make(name=prefix + "Focus", price=40, effect_type="guaranteed_crit", effect_value=1)
    potion = await make(name=prefix + "Potion", price=20, effect_type="extra_heal", effect_value=20)
    await make(name=prefix + "Hidden", price=1, effect_type="extra_heal", effect_value=1, enabled=False)

    await w.player(41, money=100)
    await w.player(42, money=0)
    _, fight = await w.propose(41, 42)
    i = await w.click(41, fight.proposal.view, "shop", message=fight.proposal)
    listed = i.said("**Battle Shop**") and i.said("Balance: 100") and i.said(f"**{prefix}Rage** — 30")
    r.ok("the shop lists what is on sale with the balance", listed, i.first[:70])
    r.ok("and not what is disabled", not i.said("Hidden"), "")
    r.check("only the player sees it", i.sent[0].ephemeral, True)
    shop = i.sent[0]
    for item in (boost, sure, potion):
        await w.choose(41, shop.view, item.pk, message=shop)
    told = "You now have **1**" in shop.text() and "Balance: 10" in shop.text()
    r.ok("buying says what is owned and what is left", told, shop.text())
    r.check("the berries are gone", await w.money(41), 10)
    reasons = sorted({reason for _, reason in await w.ledger(41)})
    r.check("the purchases are recorded as battle items bought", reasons, ["battle_item_buy"], bug="B24")
    mine = bm.PlayerBattleItem.objects.filter(player__discord_id=w.user(41).id)
    owned = {x.item_id: x.quantity async for x in mine}
    r.check("one of each is owned", owned, {boost.pk: 1, sure.pk: 1, potion.pk: 1})
    bought = await w.choose(41, shop.view, boost.pk, message=shop)
    refused = bought.said("You don't have enough") and await w.money(41) == 10
    r.ok("no berries left: the purchase is refused", refused, bought.texts())

    for n, deck in ((41, ["Monkey D. Luffy", "Nami"]), (42, ["Kaido", "Portgas D. Ace", "Sakazuki (Akainu)"])):
        for name in deck:
            await w.cmd_card(n, "add", countryball=await w.give(n, name))
    await fight.ready(41)
    await fight.ready(42)

    i = await fight.act(42, "item")
    r.check("the Item button is the active player's only", i.first, NOT_YOURS)
    i = await fight.act(41, "item")
    menu = i.sent[0]
    labels = sorted(option.label for option in menu.view.children[0].options)
    names = sorted(f"{prefix}{name} (x1)" for name in ("Rage", "Focus", "Potion"))
    r.check("the Item button lists what is owned", labels, names)
    used = await w.choose(41, menu.view, boost.pk, message=menu)
    state = await fight.state()
    boosted = (state["log"][-1], state["turn"], state["active"])
    wanted = ("Turn 1: **Monkey D. Luffy** hits **Kaido** for **442** — Kaido is defeated!", 1, "p2")
    r.check("attack_boost: an Attack times the item (310 x 1.5 x 0.95 = 442)", boosted, wanted)
    r.check("the item is used up", await mine.filter(item=boost).aexists(), False)
    r.check(
        "the menu says so and closes", (menu.content, menu.view, used.answered), (f"Used **{prefix}Rage**.", None, True)
    )

    i = await fight.act(42, "item")
    r.check("no items: the Item button says so", i.first, "You don't have any battle items.")
    await fight.act(42, "attack")  # Ace (T22) on Luffy (T5): 179 x 0.925 = 166, Luffy is left with 135

    rng.roll = 0.99  # a gamble would miss on its own
    i = await fight.act(41, "item")
    await w.choose(41, i.sent[0].view, sure.pk, message=i.sent[0])
    state = await fight.state()
    landed = (
        f"Turn 3: **Monkey D. Luffy** lands a **CRITICAL HIT** on **Portgas D. Ace** for "
        f"**{hit(310, tier=COMMONER, action=2.0)}** — Portgas D. Ace is defeated!"
    )
    r.check("guaranteed_crit: the gamble always lands (310 x 2 x 0.975 = 604)", state["log"][-1], landed)

    await fight.act(42, "heal")  # Akainu steps in and wastes his turn
    state = await fight.state()
    left = 301 - hit(179, tier=RARER)
    r.check("Luffy has been hurt once", hp(state, "p1"), left)
    rng.spread = 0.0
    i = await fight.act(41, "item")
    await w.choose(41, i.sent[0].view, potion.pk, message=i.sent[0])
    state = await fight.state()
    healed = (hp(state, "p1") - left, state["p1_balls"][0]["heal_uses"])
    r.check("extra_heal: a Heal with the item's percent on top (25% + 20% of 301)", healed, (round(301 * 0.45), 1))
    r.check("nothing is left of the three", await mine.all().acount(), 0)
    await fight.act(42, "forfeit")

    # a healing item on a card that has no heal left would be thrown away
    player = await w.player(43)
    await bm.PlayerBattleItem.objects.acreate(player=player, item=potion, quantity=1)
    fight = await w.fight(43, 44, ["Monkey D. Luffy"], ["Kaido", "Usopp"])
    for _ in range(2):
        await fight.act(43, "heal")
        await fight.act(44, "heal")
    i = await fight.act(43, "item")
    menu = i.sent[0]
    await w.choose(43, menu.view, potion.pk, message=menu)
    state = await fight.state()
    told = f"**Monkey D. Luffy** has no heals left this battle: **{prefix}Potion** would be wasted."
    r.check("a healing item with no heal left is refused", menu.content, told)
    kept = (await bm.PlayerBattleItem.objects.aget(player=player, item=potion)).quantity
    r.check("it is neither used up nor does it cost the turn", (kept, state["turn"], state["active"]), (1, 4, "p1"))
    await fight.act(43, "forfeit")
    await h.awipe_marked_rows()


async def death_and_end(w: h.World):
    h.script_random()
    fight = await w.fight(51, 52, ["Nami", "Monkey D. Luffy"], ["Usopp", "Kaido"], wager=0)
    # Nami 89/91 and Usopp 90/98 are both T33: 0.75 between Straw Hats, 0.95 for the tier
    await fight.act(51, "attack")
    state = await fight.state()
    r.check("two Straw Hats hold back: 89 x 0.75 x 0.95 = 63", 98 - hp(state, "p2"), hit(89, relation=CREW))
    turns = 1 + await fight.play_out()
    session = await fight.session()
    state = session.state
    r.check("the battle ends by itself", session.status, "finished")
    dead = {side: [b["dead"] for b in state[f"{side}_balls"]] for side in ("p1", "p2")}
    r.ok("exactly one side has every card down", sorted(all(v) for v in dead.values()) == [False, True], dead)
    r.ok("cards fell in deck order", all(dead[s] == sorted(dead[s], reverse=True) for s in dead), dead)
    r.check("the log keeps the last five lines only", len(state["log"]), 5)
    r.check("every turn was counted", state["turn"], turns)
    text = fight.board.text()
    winner = 51 if all(dead["p2"]) else 52
    announced = f"**Winner: Tester{winner}**" in text and f"Turns: {turns}" in text and "Battle: Complete!" in text
    r.ok("the board announces the winner and the turns", announced, text[:80])
    r.check("the buttons are gone", fight.board.view, None)
    mine = bm.BattleRecord.objects.filter(player1__discord_id=w.user(51).id)
    record = await mine.select_related("winner").alatest("pk")
    r.check(
        "the record names the winner and the turns",
        (record.winner.discord_id, record.turns),
        (w.user(winner).id, turns),
    )
    i = await w.cmd(51, "start", opponent=w.user(52), max_size=None, wager=0)
    r.ok("both players are free for a new battle", i.said("is proposing a battle"), i.first[:50])
    await w.close_everything()


async def main(w: h.World):
    await r.scenario("attack and hand-over of the turn", attack_and_handover, w)
    await r.scenario("crit gamble and dodge", crit_and_dodge, w)
    await r.scenario("heal and its limit", heal, w)
    await r.scenario("capacity, once, read from Buff", capacity, w)
    await r.scenario("shop items", shop_items, w)
    await r.scenario("a card dies, the next steps in, the battle ends", death_and_end, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
