"""
The health multiplier: every fighter's health, and the health of what it holds, multiplied when it enters a
deck. Attack is left alone, so a card lasts as many times longer.

Every other test file holds the multiplier at 1 (see `World.defaults`), so that their figures are the cards'
own. This is the file that turns the knob, to 2, to 3 and to a fraction, each time by name: none of its
figures depends on what the database holds that day.
"""

import sys

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 9
r = h.Report("t09_health")
bm = h.bm
SAME_TIER = 0.95
ENMA = "Enma"
GOMU = "Gomu Gomu no Mi (Gum Gum)"


def stats(card: dict) -> tuple:
    return card["attack"], card["max_health"], card["health"]


def base(card: dict) -> tuple:
    return card["base_attack"], card["base_health"]


def rejected_by_the_database(value: float) -> bool:
    """Try a value on the settings row inside a transaction that is rolled back whatever happens."""
    from django.db import IntegrityError, transaction

    try:
        with transaction.atomic():
            bm.BattleSettings.objects.filter(pk=1).update(health_multiplier=value)
            transaction.set_rollback(True)
    except IntegrityError:
        return True
    return False


async def the_setting(w: h.World):
    # whatever the knob is set to today: the tests below name the multiplier they play with
    default = bm.BattleSettings._meta.get_field("health_multiplier").default
    real = await h.battle_cog.Battle.get_settings(w.cog)  # the cog's own method, not the tests' stand-in
    held = real.health_multiplier
    r.note(f"health multiplier: x{held:g} in the database, x{default:g} as the default of the model")
    r.check("the cog's own get_settings reads the database's value, which is the model's default", held, default)
    r.check("and that value is one the panel would take", 0.5 <= held <= 10, True)
    verdicts = {}
    for value in (0.4, 0.5, 2.0, 10, 10.5):
        try:
            bm.BattleSettings(health_multiplier=value).clean()
            verdicts[value] = "taken"
        except Exception as error:
            verdicts[value] = type(error).__name__
    wanted = {0.4: "ValidationError", 0.5: "taken", 2.0: "taken", 10: "taken", 10.5: "ValidationError"}
    r.check("the panel takes 0.5 to 10 and nothing outside", verdicts, wanted)
    outside = [await h.sync_to_async(rejected_by_the_database)(value) for value in (0.4, 10.5, 7.5)]
    r.check("the database itself refuses 0.4 and 10.5, and takes 7.5", outside, [True, True, False])
    after = await bm.BattleSettings.aload()
    r.check("and none of those tries left a trace", after.health_multiplier, held)


async def at_entry(w: h.World):
    w.override_settings(health_multiplier=2.0)
    await w.player(1)
    await w.player(2)
    luffy = await w.give(1, "Monkey D. Luffy")
    zoro = await w.give(1, "Roronoa Zoro")
    shiny = await w.give(1, "Nami", attack_bonus=20, health_bonus=-20, special="Shiny")
    kaido = await w.give(2, "Kaido")
    usopp = await w.give(2, "Usopp")
    _, fight = await w.propose(1, 2)

    await w.cmd_card(1, "add", countryball=luffy)
    card = fight.card(await fight.state(), "p1", 0)
    r.check("at x2 Luffy (310/301) enters with twice his health and his own attack", stats(card), (310, 602, 602))
    r.check("the doubled health is his base, what equipment is added to", base(card), (310, 602))
    r.ok("the proposal shows it", "Monkey D. Luffy `██████████` 602/602" in fight.proposal.text(), "")

    await w.cmd_card(1, "add", countryball=shiny)
    card = fight.card(await fight.state(), "p1", 1)
    # Nami 89/91, +20% attack, -20% health, and 1000 for the Shiny: all of the health side is doubled
    wanted = (89 + 17 + 1000, (91 - 18 + 1000) * 2)
    r.check("card bonus and special bonus are inside what is multiplied", stats(card)[:2], wanted)

    if await bm.Buff.objects.filter(ball_id=h.BALL["Usopp"]).aexists():
        r.note("a real Buff row exists for Usopp: the Buff bonus is not tested on top of it")
    else:
        await bm.Buff.objects.acreate(ball_id=h.BALL["Usopp"], health=111, attack=222, capacity_value=h.BUFF_MARK)
        await w.cmd_card(2, "add", countryball=usopp)
        card = fight.card(await fight.state(), "p2", 0)
        r.check("so is a Buff's flat health (Usopp 90/98 +222/+111)", stats(card)[:2], (312, (98 + 111) * 2))
        await h.awipe_marked_rows()

    # the knob is turned while the deck is being built: only what enters afterwards follows
    w.override_settings(health_multiplier=3.0)
    await w.cmd_card(1, "add", countryball=zoro)
    state = await fight.state()
    r.check(
        "at x3 Zoro (296/238) enters with three times his health", stats(fight.card(state, "p1", 2)), (296, 714, 714)
    )
    r.check("Luffy, who entered at x2, keeps what he entered with", stats(fight.card(state, "p1", 0)), (310, 602, 602))
    w.override_settings(health_multiplier=1.5)
    await w.cmd_card(2, "add", countryball=kaido)
    card = (await fight.state())["p2_balls"][-1]
    r.check("a fraction is rounded to a whole health: 390 x 1.5", stats(card), (330, 585, 585))
    w.restore_settings()
    await w.close_everything()


async def equipment(w: h.World):
    w.override_settings(health_multiplier=2.0)
    await w.player(11)
    await w.player(12)
    zoro = await w.give(11, "Roronoa Zoro")
    enma = await w.give(11, ENMA)
    luffy = await w.give(11, "Monkey D. Luffy")
    gomu = await w.give(11, GOMU)
    wado = await w.give(11, "Wado Ichimonji")
    await w.give(12, "Usopp")
    _, fight = await w.propose(11, 12)

    # Enma is 245/203 and Zoro's own: 200% of 245, and 200% of 203 doubled
    await w.cmd_card(11, "add", countryball=zoro)
    i = await w.cmd_card(11, "equip", item=enma, character=zoro)
    told = "**Roronoa Zoro** now holds **Enma**: +490 ATK, +812 HP (200% of its stats)."
    r.check("the equip message counts the item's health doubled", i.first, told)
    card = fight.card(await fight.state(), "p1", 0)
    r.check("Zoro with Enma at x2: 296 + 490, and 476 + 812", stats(card), (786, 1288, 1288))
    entry = card["equipment"][0]
    stored = (entry["attack"], entry["health"], entry["percent"])
    r.check("the item is stored with its own attack and its doubled health", stored, (245, 406, 200))
    text = fight.proposal.text()
    r.ok("the proposal shows the lot", "Roronoa Zoro `██████████` 1288/1288" in text and "┗ Enma (200%)" in text, "")

    # the full set: 10% on the total, health side doubled all the way
    await w.cmd_card(11, "add", countryball=luffy)
    i = await w.cmd_card(11, "equip", item=gomu, character=luffy)
    r.ok("Luffy + Gomu Gomu at x2: +1260 ATK, +2120 HP", i.said("+1260 ATK, +2120 HP (200% of its stats)"), i.first)
    i = await w.cmd_card(11, "equip", item=wado, character=luffy)
    r.ok("Luffy + Wado at x2: +69 ATK, +138 HP", i.said("+69 ATK, +138 HP (30% of its stats)"), i.first)
    card = fight.card(await fight.state(), "p1", 1)
    wanted = (round((310 + 1260 + 69) * 1.1), round((602 + 2120 + 138) * 1.1))
    r.check("the set bonus is taken on the multiplied total: 1803 and 3146", stats(card)[:2], wanted)
    await w.cmd_card(11, "unequip", item=wado)
    card = fight.card(await fight.state(), "p1", 1)
    r.check("without the weapon: 1570 and 602 + 2120", stats(card), (1570, 2722, 2722))
    await w.cmd_card(11, "unequip", item=gomu)
    card = fight.card(await fight.state(), "p1", 1)
    r.check("with nothing left Luffy is back to 310/602", (*stats(card), card["equipment"]), (310, 602, 602, []))

    # an item that leaves its owner: the bearer is rebuilt from what is left, still doubled
    await w.hand_over(enma, 12)
    await fight.ready(11)
    card = fight.card(await fight.state(), "p1", 0)
    r.check("Zoro without the Enma that was given away: 296/476", stats(card), (296, 476, 476))
    await w.close_everything()

    # the same sword at x3: 200% of 203 tripled, on a Zoro who enters at 714
    w.override_settings(health_multiplier=3.0)
    zoro = await w.give(13, "Roronoa Zoro")
    enma = await w.give(13, ENMA)
    await w.give(14, "Usopp")
    _, fight = await w.propose(13, 14)
    await w.cmd_card(13, "add", countryball=zoro)
    i = await w.cmd_card(13, "equip", item=enma, character=zoro)
    told = "**Roronoa Zoro** now holds **Enma**: +490 ATK, +1218 HP (200% of its stats)."
    r.check("at x3 the same Enma gives +490 ATK, +1218 HP", i.first, told)
    card = fight.card(await fight.state(), "p1", 0)
    r.check("and Zoro stands at 786 and 714 + 1218", stats(card), (786, 1932, 1932))
    w.restore_settings()
    await w.close_everything()


async def in_battle(w: h.World):
    rng = h.script_random()
    w.override_settings(health_multiplier=2.0)
    fight = await w.fight(21, 22, ["Monkey D. Luffy"], ["Kaido"])
    text = fight.board.text()
    r.ok("the board shows the multiplied health", "602/602" in text and "780/780" in text, "")
    await fight.act(21, "attack")
    state = await fight.state()
    hit = round(310 * SAME_TIER)
    told = f"Turn 1: **Monkey D. Luffy** hits **Kaido** for **{hit}**"
    r.check(
        "a hit is what it was: attack is not multiplied",
        (780 - state["p2_balls"][0]["health"], state["log"][-1]),
        (hit, told),
    )
    rng.spread = 0.0
    await fight.act(22, "heal")
    state = await fight.state()
    healed = (state["p2_balls"][0]["health"] - (780 - hit), state["log"][-1])
    r.check(
        "a Heal is a share of the multiplied health: 25% of 780",
        healed,
        (195, "Turn 2: **Kaido** heals for **195** HP!"),
    )
    rng.spread = 1.0
    await fight.act(21, "forfeit")

    # the point of it all: the same two cards, both attacking with the best roll every turn
    lengths = {}
    for multiplier, players in ((1.0, (23, 24)), (2.0, (25, 26)), (3.0, (27, 28))):
        w.override_settings(health_multiplier=multiplier)
        fight = await w.fight(*players, ["Monkey D. Luffy"], ["Kaido"])
        lengths[multiplier] = await fight.play_out()
    r.check("Luffy against Kaido lasts 2 turns at x1, 4 at x2, 6 at x3", lengths, {1.0: 2, 2.0: 4, 3.0: 6})

    # the multiplier is read when a card enters the deck: turning it during the battle changes nothing
    w.override_settings(health_multiplier=2.0)
    fight = await w.fight(29, 30, ["Monkey D. Luffy"], ["Kaido"])
    w.override_settings(health_multiplier=5.0)
    await fight.act(29, "attack")
    await fight.act(30, "attack")
    state = await fight.state()
    kept = (state["p1_balls"][0]["max_health"], state["p2_balls"][0]["max_health"])
    r.check("a battle that has started keeps the health it started with", kept, (602, 780))
    w.restore_settings()
    await fight.act(29, "forfeit")


async def earnings(w: h.World):
    """The reward past the guaranteed wins compares attack + health of the two decks: health counts double."""
    h.script_random()
    w.override_settings(health_multiplier=2.0)
    winner = await w.player(31)
    for n in (32, 33, 34):
        await bm.BattleRecord.objects.acreate(player1=winner, player2=await w.player(n), winner=winner, turns=1)

    fight = await w.fight(31, 35, ["Monkey D. Luffy"], ["Nami"])
    await fight.play_out()
    mine = bm.BattleRecord.objects.filter(player1=winner)
    record = await mine.alatest("pk")
    # Luffy 310 + 602 against Nami 89 + 182: 0.30, floored at 0.5 of the base 30, as at x1
    r.check("4th win of the day against a much weaker deck: still 30 x 0.5", record.winner_earnings, 15)

    fight = await w.fight(31, 36, ["Monkey D. Luffy"], ["Nami", "Usopp", "Nami", "Usopp"])
    turns = await fight.play_out()
    record = await mine.all().alatest("pk")
    heavier = 2 * (89 + 182) + 2 * (90 + 196)
    wanted = round(30 * heavier / (310 + 602))
    r.check(
        "5th win against a deck that weighs more: 30 x 1114/912",
        (record.winner_id, record.winner_earnings),
        (winner.pk, wanted),
    )
    r.note(f"that win pays {wanted} at x2 and paid 36 at x1 (736/611): health weighs double in attack + health")
    r.note(f"and it took {turns} turns, as at x1: each of the four small cards still falls in one hit")
    w.restore_settings()


async def main(w: h.World):
    await r.scenario("the setting and its bounds", the_setting, w)
    await r.scenario("health when a card enters the deck", at_entry, w)
    await r.scenario("equipment", equipment, w)
    await r.scenario("in a battle", in_battle, w)
    await r.scenario("earnings", earnings, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
