"""
8. robustness: the state read back after a restart, orphaned sessions, clicks that land together or at the
wrong moment, the shop and the items pushed where they should not go, messages that disappear.
"""

import asyncio
import json
import sys
from datetime import timedelta

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 7
r = h.Report("t07_robustness")
bm = h.bm
engine = h.engine
PLAYED = "That turn has already been played."
OVER = "This battle is over."
DECK_A = ["Monkey D. Luffy", "Nami"]
DECK_B = ["Kaido", "Usopp"]


async def records(w: h.World, n: int) -> int:
    return await bm.BattleRecord.objects.filter(player1__discord_id=w.user(n).id).acount()


async def purses(w: h.World, a: int, b: int) -> tuple[int, int]:
    return await w.money(a), await w.money(b)


async def stored_state(w: h.World):
    worn = {"slot": "weapon", "instance_id": 9, "ball_id": 8, "name": "W", "emoji": "", "attack": 40, "health": 40}
    ball = engine.BattleBall(
        instance_id=1,
        ball_id=2,
        name="X",
        owner_id=3,
        health=40,
        max_health=100,
        attack=70,
        rarity=12.5,
        capacity_effect="heal_percent",
        capacity_value=30.0,
        base_attack=50,
        base_health=80,
        heal_uses=1,
        equipment=[{**worn, "percent": 50, "group_ids": [1, 29]}],
    )
    through_json = json.loads(json.dumps(ball.to_dict()))
    r.ok("a card survives the trip through JSON unchanged", engine.BattleBall.from_dict(through_json) == ball, "")
    through_json["something_a_later_version_added"] = {"x": 1}
    r.ok("a key from a later version is ignored", engine.BattleBall.from_dict(through_json) == ball, "")
    old = {key: value for key, value in ball.to_dict().items() if key in ("instance_id", "ball_id", "name")}
    old.update(owner_id=3, health=40, max_health=100, attack=70, rarity=12.5, dead=False)
    card = engine.BattleBall.from_dict(old)
    defaults = (card.base_attack, card.equipment, card.capacity_effect, card.heal_uses)
    r.check("a card written before equipment existed reads back with defaults", defaults, (0, [], "", 0))
    card.equipment = [{"slot": "weapon", "attack": 40, "health": 40, "percent": 50}]
    h.loadout.apply_equipment(card, 10)
    rebuilt = (card.base_attack, card.base_health, card.attack, card.max_health)
    r.check("and can be equipped: what it had becomes its base", rebuilt, (70, 100, 90, 120))

    # the same through the real commands, on a proposal whose state holds such an old card
    await w.player(1)
    await w.player(2)
    zoro = await w.give(1, "Roronoa Zoro")
    wado = await w.give(1, "Wado Ichimonji")
    _, fight = await w.propose(1, 2)
    await w.cmd_card(1, "add", countryball=zoro)
    for name in DECK_B:
        await w.cmd_card(2, "add", countryball=await w.give(2, name))
    session = await fight.session()
    for side in ("p1", "p2"):
        for stored in session.state[f"{side}_balls"]:
            for key in ("base_attack", "base_health", "equipment", "capacity_effect", "capacity_value"):
                del stored[key]
    await session.asave(update_fields=("state",))
    i = await w.cmd_card(1, "equip", item=wado, character=zoro)
    card = fight.card(await fight.state(), "p1")
    equipped = (i.said("now holds"), card["attack"], card["base_attack"])
    r.check("an old card in a stored proposal takes equipment", equipped, (True, 296 + 460, 296))
    h.script_random()
    await fight.ready(1)
    await fight.ready(2)
    await fight.act(1, "attack")
    await fight.act(2, "attack")
    state = await fight.state()
    played = (state["turn"], state["p2_balls"][0]["dead"], "equipment" in state["p2_balls"][1])
    r.check("and the battle plays on it (old cards on the other side included)", played, (2, True, True))
    await fight.act(1, "forfeit")


async def restart(w: h.World):
    """What is left of a battle when the process, or only the package, starts again."""
    h.script_random()
    await w.player(11, money=100)
    await w.player(12, money=100)
    fight = await w.fight(11, 12, DECK_A, DECK_B, wager=50)
    before = (await fight.session()).updated_at
    await asyncio.sleep(0.05)
    await fight.act(11, "attack")
    after = (await fight.session()).updated_at
    r.check(
        "playing a turn moves the session's updated_at", after > before + timedelta(milliseconds=30), True, bug="B09"
    )

    # the bot restarts one minute into the battle: the package is set up before the bot has connected
    old_cog = w.cog
    await w.reload(ready=False)
    r.check("a new cog took over", w.cog is not old_cog and w.bot.get_cog("Battle") is w.cog, True)
    closed = (await fight.status(), *await purses(w, 11, 12))
    r.check(
        "after a restart the running battle is closed and the wager given back",
        closed,
        ("cancelled", 100, 100),
        bug="B02",
    )
    refunds = [entry for entry in await w.ledger(11, 12) if entry[0] > 0]
    wanted = [(50, "battle_wager_refund"), (50, "battle_wager_refund")]
    r.check("the refund is recorded as one, once for each", refunds, wanted, bug="B24")
    i = await w.cmd(11, "start", opponent=w.user(12), max_size=None, wager=0)
    r.check("after a restart the two players can battle again", i.said("is proposing a battle"), True, bug="B02")
    await w.reload(ready=False)
    plans = await bm.BattleSession.objects.filter(player1__discord_id=w.user(11).id, status="proposed").acount()
    r.check("a restart closes the plans too, with no berries moving", (plans, *await purses(w, 11, 12)), (0, 100, 100))

    # a reload of the package keeps the process: the boards still answer and their battles go on
    await w.player(13, money=100)
    await w.player(14, money=100)
    fight = await w.fight(13, 14, DECK_A, DECK_B, wager=50)
    long_ago = h.timezone.now() - timedelta(minutes=31)
    await bm.BattleSession.objects.filter(pk=fight.session_id).aupdate(created_at=long_ago, updated_at=long_ago)
    await fight.act(13, "attack")  # played this very second, in a battle that began 31 minutes ago
    board = fight.board
    old_cog = w.cog
    await w.reload(ready=True)
    kept = (await fight.status(), *await purses(w, 13, 14))
    r.check("a long battle still being played is not cancelled by a reload", kept, ("active", 50, 50), bug="B09")
    r.check("the new cog gave it its clock back", fight.session_id in w.cog._timers, True)
    r.check("and the old cog's clocks were stopped", old_cog._timers, {})
    i = await w.click(14, board.view, "heal", message=board)
    state = await fight.state()
    r.check(
        "a click on the board posted before the reload plays the turn",
        (i.answered, state["turn"]),
        (True, 2),
        bug="B19",
    )
    r.check("on that same board", fight.board.id, board.id)
    # the buttons clicked were posted by the cog that was unloaded: the new one has to let go of them too
    r.check("and ONE set of turn buttons is listening afterwards", len(fight.turn_views()), 1)

    # the clock, once it is the new cog's: nobody plays, the turn goes by on its own
    w.override_settings(turn_timeout_seconds=1)
    await w.cog.resume_timers()
    await asyncio.sleep(1.4)
    r.check("a turn nobody plays after the reload is played by the new clock", (await fight.state())["turn"], 3)
    w.restore_settings()
    await fight.act(13, "forfeit")

    # what a reload does close: the battles nobody has touched for half an hour
    await w.player(15, money=100)
    await w.player(16, money=100)
    fight = await w.fight(15, 16, DECK_A, DECK_B, wager=50)
    await bm.BattleSession.objects.filter(pk=fight.session_id).aupdate(updated_at=long_ago)
    await w.player(17, money=30)
    await w.player(18, money=30)
    _, proposal = await w.propose(17, 18, wager=20)
    await bm.BattleSession.objects.filter(pk=proposal.session_id).aupdate(updated_at=long_ago)
    done = await bm.BattleSession.objects.acreate(
        channel_id=1, player1=await w.player(17), player2=await w.player(18), wager_amount=20, status="finished"
    )
    await bm.BattleSession.objects.filter(pk=done.pk).aupdate(updated_at=long_ago)
    await w.player(19)
    await w.player(20)
    _, fresh = await w.propose(19, 20)
    closed = await h.battle_ext._refund_stale_sessions()
    r.check(
        "a reload closes exactly the two abandoned ones",
        sorted(closed),
        sorted([fight.session_id, proposal.session_id]),
    )
    abandoned = (await fight.status(), *await purses(w, 15, 16))
    r.check("a battle untouched for 31 minutes is cancelled and refunded", abandoned, ("cancelled", 100, 100))
    await h.battle_ext._refund_stale_sessions()
    r.check("running it again refunds nothing more", await purses(w, 15, 16), (100, 100))
    plan = (await proposal.status(), *await purses(w, 17, 18))
    r.check("an old proposal is cancelled without moving berries", plan, ("cancelled", 30, 30))
    r.check("a finished battle is left alone", (await bm.BattleSession.objects.aget(pk=done.pk)).status, "finished")
    r.check("and so is a plan made a moment ago", await fresh.status(), "proposed")
    await w.close_everything()


async def together(w: h.World):
    h.script_random()
    # the same turn played twice at the same moment (two devices, or a click and the clock)
    await w.player(21, money=100)
    await w.player(22, money=100)
    fight = await w.fight(21, 22, DECK_A, DECK_B, wager=50)
    first, second = await asyncio.gather(fight.act(21, "attack"), fight.act(21, "heal"))
    state = await fight.state()
    r.check("two actions on one turn: one is played", (state["turn"], len(state["log"])), (1, 1), bug="B21")
    r.check("and the other is told so", sorted([first.first, second.first]), ["", PLAYED], bug="B21")
    r.check("ONE set of buttons is left listening for the next turn", len(fight.turn_views()), 1, bug="B21")
    await fight.act(22, "forfeit")

    # no clock is left behind by the click that came second
    w.override_settings(turn_timeout_seconds=2)
    fight = await w.fight(23, 24, DECK_A, DECK_B)
    await fight.act(23, "attack")  # from here on a turn lasts 2 seconds
    await fight.act(24, "heal")
    await asyncio.gather(fight.act(23, "heal"), fight.act(23, "heal"))  # t0: turn 3 is played, once
    await asyncio.sleep(1.0)
    await fight.act(24, "heal")  # t0+1: turn 4 is played, player 23 now has until t0+3
    await asyncio.sleep(1.5)  # t0+2.5
    r.check("nobody is made to play before their own clock runs out", (await fight.state())["turn"], 4, bug="B21")
    w.restore_settings()
    await fight.act(23, "forfeit")

    # the final blow landing twice
    await w.player(25, money=100)
    await w.player(26, money=100)
    fight = await w.fight(25, 26, ["Monkey D. Luffy"], ["Nami"], wager=50)
    first, second = await asyncio.gather(fight.act(25, "attack"), fight.act(25, "attack"))
    r.check("the battle is recorded once", await records(w, 25), 1, bug="B21")
    r.check(
        "the winner gets the pot once: 100 - 50 + 100 + 50 of reward", await purses(w, 25, 26), (200, 50), bug="B21"
    )
    r.check("the second blow is told the battle is over", sorted([first.first, second.first]), ["", OVER])

    # a click and the clock on the same turn
    w.override_settings(turn_timeout_seconds=1)
    fight = await w.fight(27, 28, DECK_A, DECK_B)
    await asyncio.sleep(0.99)
    await fight.act(27, "heal")
    await asyncio.sleep(0.3)
    state = await fight.state()
    r.check(
        "a click landing as the clock runs out: the turn is played once", (state["turn"], len(state["log"])), (1, 1)
    )
    w.restore_settings()
    await fight.act(27, "forfeit")


async def items(w: h.World):
    h.script_random()
    prefix = h.ITEM_PREFIX
    potion = await bm.BattleItem.objects.acreate(
        name=prefix + "Potion", price=20, effect_type="extra_heal", effect_value=20
    )
    player = await w.player(31, money=100)
    await w.player(32, money=100)
    await bm.PlayerBattleItem.objects.acreate(player=player, item=potion, quantity=3)

    async def owned() -> int:
        row = await bm.PlayerBattleItem.objects.filter(player=player, item=potion).afirst()
        return row.quantity if row else 0

    # the item menu stays open for a minute, long after the turn it was opened in
    fight = await w.fight(31, 32, DECK_A, DECK_B)
    early = (await fight.act(31, "item")).sent[0]
    late = (await fight.act(31, "item")).sent[0]
    await fight.act(31, "attack")  # Kaido 390 -> 96; it is now player 32's turn
    await w.choose(31, early.view, potion.pk, message=early)
    state = await fight.state()
    untouched = (state["turn"], state["active"], state["p2_balls"][0]["heal_uses"])
    r.check("an item picked during the opponent's turn does not play that turn", untouched, (1, "p2", 0), bug="B01")
    r.check("the menu says why", early.content, PLAYED, bug="B01")
    r.check("and the item is not used up for nothing", await owned(), 3, bug="B01")

    await fight.act(32, "heal")  # turn 2: back to player 31, two turns after the menus were opened
    await w.choose(31, late.view, potion.pk, message=late)
    state = await fight.state()
    r.check(
        "nor does a menu opened two turns ago play today's turn",
        (state["turn"], late.content, await owned()),
        (2, PLAYED, 3),
    )

    menu = (await fight.act(31, "item")).sent[0]
    await w.choose(31, menu.view, potion.pk, message=menu)
    state = await fight.state()
    used = (state["turn"], state["active"], menu.content, await owned())
    r.check(
        "picked in the turn it was opened in, it is played and used up", used, (3, "p2", f"Used **{prefix}Potion**.", 2)
    )

    # the last copy disappears between the opening of the menu and the pick
    await fight.act(32, "heal")
    menu = (await fight.act(31, "item")).sent[0]
    await bm.PlayerBattleItem.objects.filter(player=player).adelete()
    await w.choose(31, menu.view, potion.pk, message=menu)
    state = await fight.state()
    gone = (menu.content, state["turn"], state["active"], [repr(e) for e in w.errors])
    r.check(
        "an item that is gone: said plainly, nothing played, no error",
        gone,
        (f"You have no **{prefix}Potion** left.", 4, "p1", []),
        bug="B17",
    )
    await fight.act(31, "forfeit")

    # the shop
    await w.player(31, money=100)
    _, fight = await w.propose(31, 32)
    shop = (await w.click(31, fight.proposal.view, "shop", message=fight.proposal)).sent[0]
    await asyncio.gather(
        w.choose(31, shop.view, potion.pk, message=shop), w.choose(31, shop.view, potion.pk, message=shop)
    )
    paid = 100 - await w.money(31)
    r.check("two purchases at once: two items, paid twice", (await owned(), paid), (2, 40), bug="B18")
    await w.player(31, money=30)
    await asyncio.gather(
        w.choose(31, shop.view, potion.pk, message=shop), w.choose(31, shop.view, potion.pk, message=shop)
    )
    r.check(
        "two purchases at once with berries for one: one item, nothing owed",
        (await owned(), await w.money(31)),
        (3, 10),
    )
    w.errors.clear()
    await bm.BattleItem.objects.filter(pk=potion.pk).aupdate(enabled=False)
    i = await w.choose(31, shop.view, potion.pk, message=shop)
    r.check("an item withdrawn while the shop was open", i.first, "That item is no longer available.")
    if (await h.aforeign_rows())["shop_items"] == 0:
        i = await w.click(31, fight.proposal.view, "shop", message=fight.proposal)
        r.check("a shop with nothing on sale", i.first, "The battle shop is empty right now.")
    await w.close_everything()
    await h.awipe_marked_rows()


async def vanishing(w: h.World):
    h.script_random()
    # the board is deleted in the middle of a battle (a moderator, a purge)
    await w.player(41, money=100)
    await w.player(42, money=100)
    fight = await w.fight(41, 42, DECK_A, DECK_B, wager=50)
    old = fight.board
    old.deleted = True
    i = await fight.act(41, "attack")
    session = await fight.session()
    new = fight.board
    moved = (session.status, session.state["turn"], session.state["active"], new is not old, new.deleted)
    r.check("a deleted board: the battle goes on, on a new message", moved, ("active", 1, "p2", True, False), bug="B04")
    r.check("the state follows the board", session.state["board_id"], new.id, bug="B04")
    buttons = (len(fight.turn_views()), new.view.active_user_id, i.error)
    r.check("with one set of buttons, for the next player, and no error", buttons, (1, w.user(42).id, None), bug="B04")
    await fight.act(42, "heal")
    r.check("and it is played there", ((await fight.state())["turn"], fight.board is new), (2, True), bug="B04")

    # the same when it is the clock that finds the board gone
    w.override_settings(turn_timeout_seconds=1)
    await fight.act(41, "heal")  # turn 3 is played; from here on a turn lasts 1 second
    fight.board.deleted = True
    await asyncio.sleep(1.4)
    session = await fight.session()
    newer = fight.board
    clocked = (session.status, session.state["turn"], newer is not new, newer.deleted)
    r.check("a deleted board found by the clock: a new message again", clocked, ("active", 4, True, False), bug="B04")

    # and when there is nowhere left to post: the battle is called off rather than left in the dark
    newer.deleted = True
    w.channel.broken = True
    await asyncio.sleep(1.4)
    called_off = (await fight.status(), *await purses(w, 41, 42))
    r.check(
        "nowhere to post any more: the battle is cancelled and the wager given back",
        called_off,
        ("cancelled", 100, 100),
    )
    i = await w.cmd(41, "start", opponent=w.user(42), max_size=None, wager=0)
    w.channel.broken = False
    r.ok("and its players are free", i.said("is proposing a battle"), i.first[:50])
    w.restore_settings()
    await w.close_everything()

    # the last blow on a deleted board: the end must still be settled, and told
    await w.player(43, money=100)
    await w.player(44, money=100)
    fight = await w.fight(43, 44, ["Monkey D. Luffy"], ["Nami"], wager=50)
    fight.board.deleted = True
    await fight.act(43, "attack")
    settled = (await fight.status(), *await purses(w, 43, 44))
    r.check("a battle ending on a deleted board is still settled", settled, ("finished", 200, 50))
    told = [m for m in w.channel.messages.values() if not m.deleted and "**Winner: Tester43**" in m.text()]
    r.check("and its result is posted on a new message", len(told), 1)

    # the proposal is deleted before anybody is ready
    _, fight = await w.propose(43, 44)
    fight.proposal.deleted = True
    card = await w.give(43, "Monkey D. Luffy")
    i = await w.cmd_card(43, "add", countryball=card)
    r.ok("deck commands survive a deleted proposal", i.said("Added"), i.first)
    names = sorted(command.name for command in w.cog.walk_app_commands())
    r.check("the commands of the cog", names, ["add", "equip", "leaderboard", "leave", "remove", "start", "unequip"])
    i = await w.cmd(44, "leave")
    left = (i.first, await fight.status())
    r.check(
        "/battle leave is the way out that needs no message",
        left,
        ("The battle has been cancelled.", "cancelled"),
        bug="B12",
    )

    # a player Discord no longer knows
    fight = await w.fight(45, 46, DECK_A, DECK_B)
    w.bot.unknown_users.add(w.user(46).id)
    await fight.act(45, "attack")
    r.ok("a player whose account cannot be fetched is shown by id", f"Player {w.user(46).id}" in fight.board.text(), "")
    w.bot.unknown_users.clear()
    await fight.act(46, "forfeit")

    # the session is closed from outside while its board is up
    fight = await w.fight(45, 46, DECK_A, DECK_B)
    board = fight.board
    await bm.BattleSession.objects.filter(pk=fight.session_id).aupdate(status="cancelled")
    i = await fight.act(45, "attack")
    r.check("a click on the board of a closed battle gets an answer", (i.answered, i.first), (True, OVER), bug="B19")
    r.check("and takes the buttons off that board", board.view, None)
    w.cog._forget(fight.session_id)


async def fifteen_minutes(w: h.World):
    """
    The first board of a battle is the follow-up of the click that started it. Discord forgets the token of
    that click after fifteen minutes, and with it the right to edit the board that way.
    """
    h.script_random()
    w.override_settings(turn_timeout_seconds=1)
    await w.player(61, money=100)
    await w.player(62, money=100)
    fight = await w.fight(61, 62, DECK_A, DECK_B, wager=50)
    board = fight.board
    r.check("the board is held as a message of its channel, not as a follow-up", type(board).__name__, "ChannelRoute")
    w.expire_tokens()
    await asyncio.sleep(1.4)
    state = await fight.state()
    in_place = (state["turn"], fight.board.id, len(fight.boards()), "Turn 1" in board.text())
    r.check("fifteen minutes later the clock still edits that board in place", in_place, (1, board.id, 1, True))
    await asyncio.sleep(1.0)
    w.restore_settings()
    i = await w.cmd(62, "leave")
    r.check(
        "and the battle can still be left", (i.first, await fight.status()), ("You forfeited the battle.", "finished")
    )
    r.ok("its result going on that same board", "Battle: Complete!" in board.text() and len(fight.boards()) == 0, "")


async def stalling(w: h.World):
    h.script_random()
    w.override_settings(turn_timeout_seconds=1)
    fight = await w.fight(51, 52, DECK_A, DECK_B)
    for _ in range(4):
        await asyncio.sleep(0.6)
        await fight.act(51, "item")
    state = await fight.state()
    r.check(
        "a turn ends after its 1 s clock whatever the player clicks meanwhile (2.4 s went by)",
        state["turn"] >= 1,
        True,
        bug="B20",
    )
    waiting = 52 if state["active"] == "p1" else 51
    await fight.act(waiting, "forfeit")
    r.check("the player kept waiting can forfeit out of turn", await fight.status(), "finished", bug="B20")
    w.restore_settings()


async def main(w: h.World):
    await r.scenario("the stored state", stored_state, w)
    await r.scenario("restart and reload", restart, w)
    await r.scenario("actions landing together", together, w)
    await r.scenario("items and shop pushed around", items, w)
    await r.scenario("messages and sessions that vanish", vanishing, w)
    await r.scenario("fifteen minutes later", fifteen_minutes, w)
    await r.scenario("stalling", stalling, w)
    r.check("no callback raised outside the cases above", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
