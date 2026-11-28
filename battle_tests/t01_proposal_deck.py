"""1. the proposal (`/battle start`, `/battle leave`) and 2. the deck (`/battle add`, `/battle remove`)."""

import asyncio
import sys
from datetime import timedelta

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 1
r = h.Report("t01_proposal_deck")
bm = h.bm
BUSY = "You're already in another battle right now."
NO_ROLE = "Only characters can fight: ships, crews and the like sit battles out for now."
FROZEN = "You cannot change your deck, you're already ready."


async def start(w: h.World, author: int, opponent: int, max_size=None, wager: int = 0):
    return await w.cmd(author, "start", opponent=w.user(opponent), max_size=max_size, wager=wager)


async def proposal(w: h.World):
    await w.player(1, money=100)
    await w.player(2, money=100)
    await w.player(3)

    i = await start(w, 1, 1)
    r.check("start against oneself is refused", i.first, "You must pick another player.")
    w.user(50, bot=True)
    i = await start(w, 1, 50)
    r.check("start against a bot is refused", i.first, "You must pick another player.")
    written = await bm.BattleSession.objects.filter(player1__discord_id=w.user(1).id).acount()
    r.check("no session was written by either", written, 0)

    i = await start(w, 1, 2, wager=101)
    r.ok("a wager the author cannot pay is refused", i.said("You don't have enough") and i.said("101"), i.first)
    i = await start(w, 1, 2, max_size=-1)
    r.ok("a deck of -1 is refused", i.said("at least 1"), i.first)

    i, fight = await w.propose(1, 2, wager=100)
    r.ok("a valid proposal is posted with its buttons", fight is not None, i.first[:80])
    state = await fight.state()
    r.check("deck size falls back on the setting", state["deck_size"], 4)
    r.check("the message id is stored for later refreshes", state.get("message_id"), fight.proposal.id)
    r.ok("the wager is shown", "**Wager:** 100" in i.first, "")
    r.check("nothing is taken at the proposal", (await w.money(1), await w.money(2)), (100, 100))

    i = await start(w, 1, 3)
    r.check("the author cannot propose a second battle", i.first, BUSY)
    i = await start(w, 3, 2)
    r.ok("a player already proposed to is busy for others", i.said("is already in another battle"), i.first)

    # the invited player has accepted nothing: starting a battle of their own turns the invitation down
    old_view = fight.proposal.view
    i = await start(w, 2, 3)
    r.check(
        "a player who was only INVITED can start a battle of their own",
        i.said("is proposing a battle"),
        True,
        bug="B10",
    )
    r.check("which closes the invitation", await fight.status(), "cancelled", bug="B10")
    r.check(
        "the invitation says so and loses its buttons",
        (fight.proposal.embed.description, fight.proposal.view, old_view.is_finished()),
        ("The invitation was turned down: this battle plan is closed.", None, True),
    )
    i = await w.cmd(2, "leave")
    r.check("/battle leave cancels a plan", i.first, "The battle has been cancelled.", bug="B12")
    i = await w.cmd(2, "leave")
    r.check("/battle leave with nothing to leave", i.first, "You aren't in a battle right now.")

    # once the invited player has taken the battle up, they are in it
    _, fight = await w.propose(1, 2)
    await w.cmd_card(2, "add", countryball=await w.give(2, "Usopp"))
    i = await start(w, 2, 3)
    r.check("an invited player who has added a card is in that battle", i.first, BUSY)
    r.check("and the plan stands", await fight.status(), "proposed")

    i = await w.click(3, fight.proposal.view, "cancel", message=fight.proposal)
    r.check("an outsider cannot press the buttons", i.first, "You aren't a part of this battle.")
    old_view = fight.proposal.view
    await w.click(2, old_view, "cancel", message=fight.proposal)
    r.check("the opponent can cancel", await fight.status(), "cancelled")
    r.ok(
        "the proposal says so, loses its buttons and stops listening",
        "The battle has been cancelled." in fight.proposal.text() and fight.proposal.view is None,
        "",
    )
    r.check("its buttons are no longer kept in memory", old_view.is_finished(), True, bug="B23")
    i = await start(w, 1, 3)
    r.ok("once cancelled, both are free again", i.said("is proposing a battle"), i.first[:60])
    await w.close_everything()

    # the size of a deck
    _, fight = await w.propose(1, 2, max_size=2)
    r.check("max_size is taken as given", (await fight.state())["deck_size"], 2)
    await w.close_everything()
    _, fight = await w.propose(1, 2, max_size=0)
    r.check("max_size 0 falls back on the setting", (await fight.state())["deck_size"], 4)
    await w.close_everything()
    _, fight = await w.propose(1, 2, max_size=10)
    r.check("a deck of 10 is accepted", fight is not None and (await fight.state())["deck_size"], 10)
    await w.close_everything()
    i = await start(w, 1, 2, max_size=11)
    r.check("a deck of 11 is refused", i.first, "A deck holds 10 characters at most.", bug="B14")
    i = await start(w, 1, 2, max_size=100000)
    r.check("an absurd deck size is refused", i.first, "A deck holds 10 characters at most.", bug="B14")

    # two proposals sent at the very same moment
    for n in (4, 5, 6):
        await w.player(n)
    first, second = await asyncio.gather(start(w, 4, 5), start(w, 4, 6))
    live = await bm.BattleSession.objects.filter(player1__discord_id=w.user(4).id, status="proposed").acount()
    r.check("two /battle start at once leave the author in ONE battle", live, 1, bug="B11")
    r.check("and the other one is told why", sorted([first.first == BUSY, second.first == BUSY]), [False, True])
    await w.close_everything()

    # a plan nobody touches does not hold its players for ever
    for n in (7, 8, 9):
        await w.player(n)
    _, fight = await w.propose(7, 8)
    await w.cmd_card(8, "add", countryball=await w.give(8, "Usopp"))
    long_ago = h.timezone.now() - timedelta(minutes=31)
    await bm.BattleSession.objects.filter(pk=fight.session_id).aupdate(updated_at=long_ago)
    i = await start(w, 9, 8)
    r.ok("a plan untouched for 31 minutes does not block a new battle", i.said("is proposing a battle"), i.first[:60])
    r.check(
        "and is closed, with a word on its message",
        (await fight.status(), fight.proposal.embed.description),
        ("cancelled", "This battle plan sat untouched for too long and was closed."),
    )
    await w.close_everything()


async def deck(w: h.World):
    await w.player(11)
    await w.player(12)
    luffy = await w.give(11, "Monkey D. Luffy")
    zoro = await w.give(11, "Roronoa Zoro")
    nami = await w.give(11, "Nami")
    wado = await w.give(11, "Wado Ichimonji")
    gomu = await w.give(11, "Gomu Gomu no Mi (Gum Gum)")
    ship = await w.give(11, "Shark Superb")
    sora = await w.give(11, "Vinsmoke Sora")
    # an enabled treasure that plays no part at all: in none of the three role groups
    battle_settings = await w.cog.get_settings()
    bystander = next(
        ball
        for ball in h.bd.balls.values()
        if ball.enabled and bm.role_of(ball.pk, battle_settings) is None and ball.country != "Shark Superb"
    )
    other = await w.give(11, bystander.pk)
    foreign = await w.give(12, "Usopp")

    i = await w.cmd_card(11, "add", countryball=luffy)
    r.check("add with no battle being set up", i.first, "You don't have a battle being set up right now!")

    _, fight = await w.propose(11, 12, max_size=2)
    i = await w.cmd_card(11, "add", countryball=wado)
    hint = i.said("A weapon does not fight on its own") and i.said("/battle equip")
    r.ok("a weapon is refused, and told where it goes", hint, i.first)
    i = await w.cmd_card(11, "add", countryball=gomu)
    r.ok("a devil fruit is refused, and told where it goes", i.said("A devil fruit does not fight on its own"), i.first)
    i = await w.cmd_card(11, "add", countryball=ship)
    r.check("a ship is refused", i.first, NO_ROLE)
    i = await w.cmd_card(11, "add", countryball=other)
    r.check(f"another treasure with no role ({bystander.country}) is refused", i.first, NO_ROLE)
    i = await w.cmd_card(11, "add", countryball=sora)
    retired = "**Vinsmoke Sora** has been retired from the dex and sits battles out."
    r.check("a retired treasure is refused", i.first, retired)
    r.check("nothing got into the deck", (await fight.state())["p1_balls"], [])

    try:
        await w.cmd_card(11, "add", countryball=foreign)
        r.ok("somebody else's card is refused before the command runs", False)
    except h.commands.BadArgument as error:
        r.ok("somebody else's card is refused before the command runs", True, str(error))

    i = await w.cmd_card(11, "add", countryball=luffy)
    r.ok("a character is accepted", i.said("Added") and i.said("Monkey D. Luffy"), i.first)
    card = (await fight.state())["p1_balls"][0]
    r.check("its stats are the card's own", (card["attack"], card["max_health"], card["health"]), (310, 301, 301))
    r.check("base stats are kept apart", (card["base_attack"], card["base_health"]), (310, 301))
    travels = (card["rarity"], card["capacity_name"], card["owner_id"])
    r.check("rarity, capacity name and owner travel with it", travels, (5.0, "Stretchy", w.user(11).id))
    r.ok("the proposal message now lists it", "Monkey D. Luffy" in fight.proposal.text(), "")

    i = await w.cmd_card(11, "add", countryball=luffy)
    r.ok("the same card twice is refused", i.said("the same") and i.said("twice"), i.first)
    i = await w.cmd_card(11, "add", countryball=zoro)
    r.ok("a second character is accepted", i.said("Added"), i.first)
    i = await w.cmd_card(11, "add", countryball=nami)
    r.ok("a full deck refuses a third", i.said("cannot add more than 2"), i.first)

    i = await w.cmd_card(11, "remove", countryball=nami)
    r.ok("removing a card that is not in the deck", i.said("is not in your deck"), i.first)
    i = await w.cmd_card(11, "remove", countryball=zoro)
    r.ok("removing a card", i.said("Removed") and len((await fight.state())["p1_balls"]) == 1, i.first)
    i = await w.cmd_card(11, "add", countryball=nami)
    r.ok("the freed place can be filled again", i.said("Added"), i.first)

    # the other side's deck is its own
    await w.cmd_card(12, "add", countryball=foreign)
    state = await fight.state()
    decks = ([b["name"] for b in state["p1_balls"]], [b["name"] for b in state["p2_balls"]])
    r.check("each side fills its own deck", decks, (["Monkey D. Luffy", "Nami"], ["Usopp"]))

    # bonuses of the card itself and of its special
    await w.cmd_card(11, "remove", countryball=nami)
    boosted = await w.give(11, "Nami", attack_bonus=20, health_bonus=-20, special="Shiny")
    await w.cmd_card(11, "add", countryball=boosted)
    card = (await fight.state())["p1_balls"][1]
    # Nami is 89/91: +20% attack is 89+17, -20% health is 91-18, and a Shiny adds 1000 to both
    stats = (card["attack"], card["max_health"])
    r.check("card bonuses and the Shiny bonus are applied", stats, (89 + 17 + 1000, 91 - 18 + 1000))

    # once ready, the deck is frozen
    i = await fight.ready(11)
    r.check("first Ready waits for the other", i.first, "Waiting for the other player to press Ready.")
    r.ok("the proposal shows who is ready", "✅ Tester11's deck" in fight.proposal.text(), "")
    i = await w.cmd_card(11, "add", countryball=zoro)
    r.check("add after Ready is refused", i.first, FROZEN)
    i = await w.cmd_card(11, "remove", countryball=luffy)
    r.check("remove after Ready is refused", i.first, FROZEN)
    names = [b["name"] for b in (await fight.state())["p1_balls"]]
    r.check("the deck did not move", names, ["Monkey D. Luffy", "Nami"])
    await w.close_everything()


async def lost_cards(w: h.World):
    """A deck is a copy taken when each card was added: what was given away since must not fight."""
    await w.player(21)
    await w.player(22)
    zoro = await w.give(21, "Roronoa Zoro")
    wado = await w.give(21, "Wado Ichimonji")
    luffy = await w.give(21, "Monkey D. Luffy")
    usopp = await w.give(22, "Usopp")

    # the only card of the deck leaves before Ready
    _, fight = await w.propose(21, 22)
    await w.cmd_card(21, "add", countryball=zoro)
    await w.cmd_card(22, "add", countryball=usopp)
    await w.hand_over(zoro, 22)
    i = await fight.ready(21)
    gone = "No longer yours, so taken out of your deck: Roronoa Zoro. Press Ready again once your deck is set."
    r.check("a card given away after /battle add is taken out at Ready", i.first, gone, bug="B13")
    state = await fight.state()
    r.check("the deck is empty and its player not ready", (state["p1_balls"], state["p1_ready"]), ([], False))
    r.ok("the proposal shows the empty deck", "Tester21's deck\nEmpty" in fight.proposal.text(), "")
    i = await fight.ready(21)
    empty = "Add at least one character with `/battle add` before pressing Ready."
    r.check("and an empty deck cannot be ready", i.first, empty, bug="B05")
    await w.close_everything()
    await w.hand_over(zoro, 21)

    # a card that no longer exists at all (sold, crafted away)
    sold = await w.give(21, "Nami")
    _, fight = await w.propose(21, 22)
    await w.cmd_card(21, "add", countryball=zoro)
    await w.cmd_card(21, "add", countryball=sold)
    await h.BallInstance.all_objects.filter(pk=sold).aupdate(deleted=True)
    i = await fight.ready(21)
    r.ok("a card deleted after /battle add is taken out too", i.said("taken out of your deck: Nami."), i.first)
    await w.close_everything()

    # an item leaves: its bearer stays, without it
    _, fight = await w.propose(21, 22)
    await w.cmd_card(21, "add", countryball=zoro)
    await w.cmd_card(21, "equip", item=wado, character=zoro)
    await w.cmd_card(22, "add", countryball=usopp)
    await w.hand_over(wado, 22)
    i = await fight.ready(21)
    r.ok("an item given away is taken off its bearer", i.said("taken out of your deck: Wado Ichimonji."), i.first)
    card = (await fight.state())["p1_balls"][0]
    r.check("who is back to their own stats", (card["attack"], card["max_health"], card["equipment"]), (296, 238, []))
    await w.close_everything()

    # the card leaves after its player pressed Ready: caught when the other one presses
    _, fight = await w.propose(21, 22)
    await w.cmd_card(21, "add", countryball=zoro)
    await w.cmd_card(21, "add", countryball=luffy)
    await w.cmd_card(22, "add", countryball=usopp)
    await fight.ready(21)
    await w.hand_over(luffy, 22)
    i = await fight.ready(22)
    r.ok(
        "a card given away after Ready is caught when the battle would start",
        i.said("The other player no longer owns Monkey D. Luffy") and i.said("they have to press Ready again"),
        i.first,
        bug="B13",
    )
    session = await fight.session()
    names = [b["name"] for b in session.state["p1_balls"]]
    flags = (session.state["p1_ready"], session.state["p2_ready"])
    r.check(
        "the battle did not start, and only the card's owner is un-readied",
        (session.status, names, flags),
        ("proposed", ["Roronoa Zoro"], (False, True)),
    )
    await fight.ready(21)
    r.check("once they press Ready again it starts with what is left", await fight.status(), "active")
    await fight.act(21, "forfeit")


async def together(w: h.World):
    """Both players build their decks at the same time: that is the normal case, not a corner one."""
    await w.player(31)
    await w.player(32)
    zoro = await w.give(31, "Roronoa Zoro")
    wado = await w.give(31, "Wado Ichimonji")
    usopp = await w.give(32, "Usopp")
    nami = await w.give(32, "Nami")

    lost = 0
    rounds = 6
    for _ in range(rounds):
        _, fight = await w.propose(31, 32)
        mine, theirs = await asyncio.gather(
            w.cmd_card(31, "add", countryball=zoro), w.cmd_card(32, "add", countryball=usopp)
        )
        state = await fight.state()
        both_told = mine.said("Added") and theirs.said("Added")
        if both_told and (len(state["p1_balls"]), len(state["p2_balls"])) != (1, 1):
            lost += 1
        await w.close_everything()
    r.check(f"both players adding at once ({rounds} tries): cards silently lost", lost, 0, bug="B03")

    _, fight = await w.propose(31, 32)
    await w.cmd_card(31, "add", countryball=zoro)
    await w.cmd_card(32, "add", countryball=usopp)
    await asyncio.gather(
        w.cmd_card(31, "equip", item=wado, character=zoro), w.cmd_card(32, "add", countryball=nami), fight.ready(32)
    )
    state = await fight.state()
    r.check(
        "an equip, an add and a Ready at once: all three are in the state",
        (len(state["p1_balls"][0]["equipment"]), len(state["p2_balls"]) >= 1, state["p2_ready"]),
        (1, True, True),
        bug="B03",
    )
    await w.close_everything()


async def helpers(w: h.World):
    # the deck display must fit an embed field whatever the deck
    gear = [
        {"slot": "weapon", "name": "Wado Ichimonji", "emoji": "", "percent": 200},
        {"slot": "fruit", "name": "Goro Goro no Mi (Thunder Thunder)", "emoji": "", "percent": 50},
    ]
    card = {
        "name": 'Donquixote Rosinante "Corazon"',
        "emoji": "<:emoji:123456789012345678>",
        "dead": False,
        "health": 1234,
        "max_health": 1234,
        "equipment": gear,
    }
    text = h.battle_cog.deck_lines([dict(card) for _ in range(40)])
    r.ok("a huge deck in full gear still fits an embed field", len(text) <= 1024, f"{len(text)} characters")
    r.check("an empty deck reads Empty", h.battle_cog.deck_lines([]), "Empty")


async def main(w: h.World):
    await r.scenario("proposal", proposal, w)
    await r.scenario("deck", deck, w)
    await r.scenario("cards that left their owner", lost_cards, w)
    await r.scenario("both players at once", together, w)
    await r.scenario("display helpers", helpers, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
