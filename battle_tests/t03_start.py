"""4. the start: both players ready, the wager put in escrow on both sides, and what happens when it cannot be."""

import asyncio
import sys

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 3
r = h.Report("t03_start")
GONE = "This battle is no longer available."
BROKE = "One of you can no longer afford the wager. Battle not started."
EMPTY = "Add at least one character with `/battle add` before pressing Ready."
WAITING = "Waiting for the other player to press Ready."


async def plan(w: h.World, a: int, b: int, wager: int = 0):
    """A proposal with one card on each side, nobody ready yet."""
    luffy = await w.give(a, "Monkey D. Luffy")
    kaido = await w.give(b, "Kaido")
    _, fight = await w.propose(a, b, wager=wager)
    await w.cmd_card(a, "add", countryball=luffy)
    await w.cmd_card(b, "add", countryball=kaido)
    return fight, luffy, kaido


async def normal_start(w: h.World):
    await w.player(1, money=100)
    await w.player(2, money=100)
    fight, _, _ = await plan(w, 1, 2, wager=60)
    proposal_view = fight.proposal.view

    i = await w.click(3, proposal_view, "ready", message=fight.proposal)
    r.check("an outsider cannot press Ready", i.first, "You aren't a part of this battle.")
    i = await fight.ready(2)
    r.check("the first Ready waits", i.first, WAITING)
    r.check("no berries move on the first Ready", (await w.money(1), await w.money(2)), (100, 100))
    i = await fight.ready(2)
    again = (i.first, await fight.status())
    r.check(
        "pressing Ready twice changes nothing",
        again,
        ("You're already ready: waiting for the other player.", "proposed"),
    )
    i = await fight.ready(1)
    session = await fight.session()
    r.check("both ready: the battle is active", session.status, "active")
    r.check("the wager is taken from both", (await w.money(1), await w.money(2)), (40, 40))
    held = [(-60, "battle_wager_hold"), (-60, "battle_wager_hold")]
    r.check("and the ledger says what for", await w.ledger(1, 2), held, bug="B24")
    opening = (session.state["active"], session.state["turn"], session.state["log"])
    r.check("the author plays first, at turn 0", opening, ("p1", 0, []))
    closed = "Battle started!" in fight.proposal.text() and fight.proposal.view is None
    r.ok("the proposal is closed", closed, "")
    r.check("and its buttons are let go of", proposal_view.is_finished(), True, bug="B23")
    board = fight.board
    posted = board is not None and "Tester1**'s turn — Turn 0" in board.text()
    r.ok("a board is posted with the turn buttons", posted, board.text()[:60] if board else "")
    r.check("the state remembers where the board is", session.state.get("board_id"), board.id)
    view = board.view
    r.check("the turn belongs to the author", (view.active_user_id, view.other_user_id), (w.user(1).id, w.user(2).id))
    r.check("the buttons know which turn they are for", view.turn, 0)
    r.check("the Capacity button carries the card's own name", view.capacity.label, "Stretchy")
    r.check("the clock is the cog's, not the view's", (view.timeout, fight.session_id in w.cog._timers), (None, True))
    r.check("the interaction was answered", i.answered, True)

    # clicks that were already on their way when the battle started
    i = await w.click(1, proposal_view, "ready", message=fight.proposal, force=True)
    r.check("Ready on a battle that already started", i.first, GONE)
    i = await w.click(1, proposal_view, "cancel", message=fight.proposal, force=True)
    r.check("Cancel on a battle that already started", i.first, GONE)
    escrow = (await w.money(1), await w.money(2), await fight.status())
    r.check("and the wager stays in escrow", escrow, (40, 40, "active"))
    await fight.act(1, "forfeit")


async def cannot_pay(w: h.World):
    await w.player(11, money=100)
    await w.player(12, money=10)
    fight, luffy, _ = await plan(w, 11, 12, wager=60)
    r.ok("the opponent's purse is not looked at when proposing", fight is not None, "")
    await fight.ready(11)
    i = await fight.ready(12)
    session = await fight.session()
    r.check("the opponent cannot pay: the battle does not start", (i.first, session.status), (BROKE, "proposed"))
    r.check("nobody was charged, the one who could pay included", (await w.money(11), await w.money(12)), (100, 10))
    r.check("the ledger holds nothing of it", await w.ledger(11, 12), [])
    r.check("both are un-readied", (session.state["p1_ready"], session.state["p2_ready"]), (False, False))
    leftovers = [key for key in ("turn", "active", "log") if key in session.state]
    r.check("the plan is a plan again, with nothing of a battle in its state", leftovers, [])
    r.check("the proposal no longer shows anybody as ready", "✅" in fight.proposal.text(), False, bug="B15")
    i = await w.cmd_card(11, "remove", countryball=luffy)
    r.ok("decks can be changed again", i.said("Removed"), i.first)
    await w.cmd_card(11, "add", countryball=luffy)

    await w.player(12, money=60)
    await fight.ready(11)
    await fight.ready(12)
    started = (await fight.status(), await w.money(11), await w.money(12))
    r.check("once the berries are there it starts", started, ("active", 40, 0))
    await fight.act(11, "forfeit")

    # the author spent the stake between the proposal and the start
    await w.player(13, money=100)
    await w.player(14, money=100)
    fight, _, _ = await plan(w, 13, 14, wager=100)
    await w.player(13, money=99)
    await fight.ready(14)
    i = await fight.ready(13)
    r.check("the author cannot pay any more: same refusal", i.first, BROKE)
    untouched = (await w.money(13), await w.money(14), await fight.status())
    r.check("nobody was charged then either", untouched, (99, 100, "proposed"))
    await w.close_everything()


async def empty_decks(w: h.World):
    await w.player(21)
    await w.player(22)
    luffy = await w.give(21, "Monkey D. Luffy")
    kaido = await w.give(22, "Kaido")

    _, fight = await w.propose(21, 22)
    i = await fight.ready(21)
    r.check("Ready with an empty deck is refused on the spot", i.first, EMPTY, bug="B05")
    r.check("and leaves its player not ready", (await fight.state())["p1_ready"], False, bug="B05")
    await w.cmd_card(22, "add", countryball=kaido)
    i = await fight.ready(22)
    r.check("the other one, who has a deck, can be ready", i.first, WAITING)
    i = await w.cmd_card(21, "add", countryball=luffy)
    r.ok("the player who pressed Ready too early can still fill their deck", i.said("Added"), i.first, bug="B05")
    await fight.ready(21)
    r.check("and the battle then starts", await fight.status(), "active")
    await fight.act(21, "forfeit")


async def at_the_same_time(w: h.World):
    # both press Ready together: "ready? go!"
    await w.player(31, money=100)
    await w.player(32, money=100)
    fight, _, _ = await plan(w, 31, 32, wager=10)
    await asyncio.gather(fight.ready(31), fight.ready(32))
    session = await fight.session()
    flags = (session.status, session.state["p1_ready"], session.state["p2_ready"])
    r.check("both pressing Ready at the same moment: the battle starts", flags, ("active", True, True), bug="B03")
    r.check("with the wager taken once from each", (await w.money(31), await w.money(32)), (90, 90))
    r.check("and one board", len(fight.boards()), 1)
    await fight.act(31, "forfeit")

    # one is ready already; the other presses, and the first one presses again at that moment.
    # Discord takes 100 ms to answer; the impatient author clicks again 30 ms after the opponent did
    await w.player(33, money=100)
    await w.player(34, money=100)
    fight, _, _ = await plan(w, 33, 34, wager=10)
    await fight.ready(33)
    w.latency = 0.1
    _, second = await asyncio.gather(fight.ready(34), w.later(0.03, fight.ready(33)))
    w.latency = 0.0
    r.check("the battle started", await fight.status(), "active")
    r.check(
        "the wager was taken ONCE from each (100 - 10)", (await w.money(33), await w.money(34)), (90, 90), bug="B07"
    )
    r.check("there is ONE board for the battle", len(fight.boards()), 1, bug="B07")
    r.check("ONE set of turn buttons is listening", len(fight.turn_views()), 1, bug="B07")
    r.ok("the second click is told the battle has gone on without it", second.first in (GONE, ""), second.texts())
    await fight.act(33, "forfeit")
    total = await w.money(33) + await w.money(34)
    r.check("berries are conserved over the battle (200 staked in all, +50 of win reward)", total, 250, bug="B07")

    # Ready and a change of deck at the same moment
    await w.player(35)
    await w.player(36)
    fight, luffy, kaido = await plan(w, 35, 36)
    nami = await w.give(36, "Nami")
    await fight.ready(35)
    ready, added = await asyncio.gather(fight.ready(36), w.cmd_card(36, "add", countryball=nami))
    session = await fight.session()
    names = [b["name"] for b in session.state["p2_balls"]]
    # whichever lands first, the result has to be one of the two it can honestly be
    if added.said("Added"):
        outcome = (session.status, names) == ("active", ["Kaido", "Nami"])
    else:
        too_late = "You don't have a battle being set up right now!"
        outcome = (session.status, names, added.first) == ("active", ["Kaido"], too_late)
    r.ok(
        "Ready and /battle add at once: the battle starts with a deck that matches what was said",
        outcome,
        (names, added.first),
    )
    await w.close_everything()


async def main(w: h.World):
    await r.scenario("a normal start", normal_start, w)
    await r.scenario("a wager that cannot be paid", cannot_pay, w)
    await r.scenario("empty decks", empty_decks, w)
    await r.scenario("clicks landing together", at_the_same_time, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
