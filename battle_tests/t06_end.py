"""
7. the end of a battle: the wager paid out, the anti-abuse earnings, the BattleRecord row, the events sent on
the game event bus, the forfeit, a turn timing out, and the leaderboard with its win-loss record.
"""

import asyncio
import sys
from datetime import timedelta

sys.path.insert(0, "/work/battle_tests")
import harness as h  # noqa: E402

BLOCK = 6
r = h.Report("t06_end")
bm = h.bm
OVER = "This battle is over."


async def last_record(w: h.World, a: int):
    mine = bm.BattleRecord.objects.filter(player1__discord_id=w.user(a).id)
    return await mine.select_related("winner").alatest("pk")


async def records(w: h.World, a: int) -> int:
    return await bm.BattleRecord.objects.filter(player1__discord_id=w.user(a).id).acount()


async def quick_win(w: h.World, winner: int, loser: int, wager: int = 0):
    """Luffy against Nami: over in one Attack."""
    fight = await w.fight(winner, loser, ["Monkey D. Luffy"], ["Nami"], wager=wager)
    await fight.act(winner, "attack")
    return fight


async def payout(w: h.World):
    h.script_random()
    a = await w.player(1, money=100)
    b = await w.player(2, money=100)
    w.events.clear()
    fight = await quick_win(w, 1, 2, wager=60)
    r.check("the session is finished", await fight.status(), "finished")
    paid = (await w.money(1), await w.money(2))
    r.check("the winner takes both stakes and the win reward; the loser is out of 60", paid, (100 - 60 + 120 + 50, 40))
    record = await last_record(w, 1)
    row = (record.player1_id, record.player2_id, record.winner_id, record.wager_amount, record.winner_earnings)
    r.check("the BattleRecord row", (*row, record.turns), (a.pk, b.pk, a.pk, 60, 50, 1))
    r.check("and only one", await records(w, 1), 1)
    text = fight.board.text()
    parts = ("Battle: Complete!", "**Winner: Tester1**", "Turns: 1", "Wager won: 120 berries")
    parts += ("Battle reward: 50 berries",)
    r.ok("the final board gives winner, turns, pot and reward", all(part in text for part in parts), text[:110])
    r.ok("and both final decks", "Tester1's final deck" in text and "~~ Nami~~ 💀" in text, "")
    left = [type(v).__name__ for v in w.store.live if getattr(v, "session_id", None) == fight.session_id]
    r.check("nothing of the battle is left listening once it is over", (fight.board.view, left), (None, []), bug="B23")
    kept = fight.session_id in w.cog._timers or fight.session_id in w.cog._turns or fight.session_id in w.cog._locks
    r.check("nor kept in the cog's memory", kept, False)

    ledger = await w.ledger(1, 2)
    r.check(
        "the ledger holds the four movements: two stakes, the pot, the reward",
        sorted(x for x, _ in ledger),
        [-60, -60, 50, 120],
    )
    reasons = sorted({reason for _, reason in ledger})
    r.check("each under its own reason", reasons, ["battle_payout", "battle_wager_hold"], bug="B24")

    channel = w.channel.id
    r.check(
        "BATTLE_WIN goes to the winner, with no card lost, and the channel",
        w.events_of("battle_win"),
        [(a.pk, 0, channel)],
    )
    played = [(a.pk, 0, channel), (b.pk, 1, channel)]
    r.check("BATTLE_PLAYED goes to both, each with what they lost", w.events_of("battle_played"), played)

    # a win that cost a card: Nami falls to Ace, Luffy finishes him
    w.events.clear()
    c = await w.player(3)
    fight = await w.fight(1, 3, ["Nami", "Monkey D. Luffy"], ["Portgas D. Ace"])
    turns = await fight.play_out()
    record = await last_record(w, 1)
    r.check("the author wins in 3 turns after losing a card", (record.winner_id, record.turns, turns), (a.pk, 3, 3))
    r.check("BATTLE_WIN carries the card lost on the way", w.events_of("battle_win"), [(a.pk, 1, channel)])
    played = [(a.pk, 1, channel), (c.pk, 1, channel)]
    r.check("BATTLE_PLAYED: one card lost on each side", w.events_of("battle_played"), played)


async def anti_abuse(w: h.World):
    h.script_random()
    a = await w.player(11, money=0)
    for n in (12, 13, 14, 15):
        await w.player(n, money=0)

    await quick_win(w, 11, 12)
    r.check(
        "1st win of the day: the flat 50", (await w.money(11), (await last_record(w, 11)).winner_earnings), (50, 50)
    )

    fight = await quick_win(w, 11, 12)
    record = await last_record(w, 11)
    second = (await w.money(11), record.winner_earnings, record.winner_id)
    r.check("2nd win against the same opponent the same day: recorded, pays nothing", second, (50, 0, a.pk))
    r.ok("and the board does not announce a reward", "Battle reward" not in fight.board.text(), "")

    await quick_win(w, 12, 11)
    r.check("the cap is per winner: the opponent's own first win against them pays", await w.money(12), 50)

    await quick_win(w, 11, 13)
    r.check("a win against somebody else pays the flat 50 again (3rd win of the day)", await w.money(11), 100)

    # 4th win of the day: past the guaranteed three, paid on how the two decks compare
    await quick_win(w, 11, 14)
    # Luffy 310+301 = 611 against Nami 89+91 = 180: 0.29, floored at 0.5 of the base 30
    r.check("4th win, against a much weaker deck: 30 x 0.5", await w.money(11) - 100, 15)

    fight = await w.fight(11, 15, ["Monkey D. Luffy"], ["Nami", "Usopp", "Nami", "Usopp"])
    await fight.play_out()
    record = await last_record(w, 11)
    # four small cards weigh 2 x 180 + 2 x 188 = 736 against 611: 30 x 1.2046
    heavier = (record.winner_id, record.winner_earnings)
    r.check("5th win, against a deck that weighs more: 30 x 736/611", heavier, (a.pk, round(30 * 736 / 611)))

    heavy = [{"attack": 1000, "max_health": 1000}]
    light = [{"attack": 100, "max_health": 100}]
    loser = await w.player(16)
    r.check("the scale is capped at 2: 60 at most", await w.cog._compute_earnings(a, loser, light, heavy), 60)
    r.check("and floored at 0.5: 15 at least", await w.cog._compute_earnings(a, loser, heavy, light), 15)

    # the day is a rolling 24 hours
    yesterday = h.timezone.now() - timedelta(hours=25)
    await bm.BattleRecord.objects.filter(winner=a).aupdate(created_at=yesterday)
    before = await w.money(11)
    await quick_win(w, 11, 12)
    r.check("25 hours later the same opponent pays the flat 50 again", await w.money(11) - before, 50)

    paid = [x.winner_earnings async for x in bm.BattleRecord.objects.filter(winner=a).order_by("pk")]
    r.note(f"player 11 over the scenario: {len(paid)} wins, paid {paid}")
    r.note("the unpaid 2nd win still used one of the 3 guaranteed wins of the day: 2 of them paid the flat 50, not 3")


async def forfeit(w: h.World):
    h.script_random()
    channel = w.channel.id
    deck_a, deck_b = ["Monkey D. Luffy", "Nami"], ["Kaido", "Usopp"]

    # the player who is NOT to play gives up: nobody has to wait for an opponent to be allowed out
    a = await w.player(21, money=100)
    b = await w.player(22, money=100)
    w.events.clear()
    fight = await w.fight(21, 22, deck_a, deck_b, wager=30)
    old_view = fight.board.view
    i = await fight.act(22, "forfeit")
    r.check(
        "forfeit by the player whose turn it is not ends the battle",
        (await fight.status(), i.answered),
        ("finished", True),
        bug="B20",
    )
    text = fight.board.text()
    told = "**Winner: Tester21** (forfeit)" in text and "Turns: 0" in text and "Wager won: 60 berries" in text
    r.ok("the other player is the winner, by forfeit", told, text[:90])
    r.check("the pot goes to them", (await w.money(21), await w.money(22)), (100 - 30 + 60 + 50, 70))
    record = await last_record(w, 21)
    row = (record.winner_id, record.turns, record.wager_amount, record.winner_earnings)
    r.check("the record", row, (a.pk, 0, 30, 50))
    r.check("the buttons are dead", (old_view.is_finished(), fight.board.view), (True, None))
    r.check(
        "BATTLE_WIN on a forfeit is never a flawless win: one loss counted",
        w.events_of("battle_win"),
        [(a.pk, 1, channel)],
    )
    played = [(a.pk, 1, channel), (b.pk, 1, channel)]
    r.check("and BATTLE_PLAYED says the same, for both players", w.events_of("battle_played"), played)
    i = await fight.act(21, "attack", force_view=old_view)
    r.check("a click that was on its way when the battle ended is told so", i.first, OVER, bug="B19")
    r.note("a forfeit before any turn pays the full win reward (50 here), once per opponent and per day")

    # the player whose turn it is gives up
    await w.player(23)
    b = await w.player(24)
    fight = await w.fight(23, 24, deck_a, deck_b)
    await fight.act(23, "forfeit")
    record = await last_record(w, 23)
    r.check(
        "forfeit on one's own turn: the other player wins", (record.winner_id, await fight.status()), (b.pk, "finished")
    )

    # /battle leave, the way out that needs no button
    a = await w.player(25, money=100)
    await w.player(26, money=100)
    fight = await w.fight(25, 26, deck_a, deck_b, wager=20)
    await fight.act(25, "attack")
    i = await w.cmd(26, "leave")
    r.check(
        "/battle leave gives a running battle up",
        (i.first, await fight.status()),
        ("You forfeited the battle.", "finished"),
        bug="B12",
    )
    record = await last_record(w, 25)
    settled = (record.winner_id, record.turns, await w.money(25), await w.money(26))
    r.check("settled like any forfeit", settled, (a.pk, 1, 100 - 20 + 40 + 50, 80))
    board = fight.board
    r.ok("the board shows the result and loses its buttons", "(forfeit)" in board.text() and board.view is None, "")

    # both give up at the same moment
    await w.player(27)
    await w.player(28)
    fight = await w.fight(27, 28, deck_a, deck_b)
    first, second = await asyncio.gather(fight.act(27, "forfeit"), fight.act(28, "forfeit"))
    r.check("two forfeits at once: one battle recorded", await records(w, 27), 1, bug="B21")
    r.check("and the second one is told it is over", sorted([first.first, second.first]), ["", OVER])


async def timeout(w: h.World):
    h.script_random()
    w.override_settings(turn_timeout_seconds=1)
    await w.player(31, money=100)
    b = await w.player(32, money=100)
    w.events.clear()
    fight = await w.fight(31, 32, ["Monkey D. Luffy", "Nami"], ["Kaido", "Usopp"], wager=10)
    clock = (fight.board.view.timeout, fight.session_id in w.cog._timers)
    r.check("the turn clock is the cog's: the buttons have no timeout of their own", clock, (None, True))
    await asyncio.sleep(1.4)
    state = await fight.state()
    played = (state["turn"], state["active"], state["log"])
    wanted = (1, "p2", ["Turn 1: **Monkey D. Luffy** hits **Kaido** for **294**"])
    r.check("a turn nobody plays resolves as an Attack", played, wanted)
    r.ok("the board moved on to the other player", "Tester32**'s turn — Turn 1" in fight.board.text(), "")
    i = await fight.act(32, "attack")  # Kaido on Luffy: 314 on 301, Nami steps in
    r.check("the other player can play normally after it", ((await fight.state())["turn"], i.answered), (2, True))
    for _ in range(30):
        if await fight.status() != "active":
            break
        await asyncio.sleep(0.5)
    r.check("left alone, the battle plays itself to the end", await fight.status(), "finished")
    # turn 3 Nami on Kaido (82 on the 96 left), turn 4 Kaido on Nami: the second player wins
    record = await last_record(w, 31)
    settled = (record.winner_id, record.turns, await w.money(31), await w.money(32))
    r.check("and is settled like any other: record, pot, reward", settled, (b.pk, 4, 90, 100 - 10 + 20 + 50))
    board = fight.board
    r.ok("the final board is up, without buttons", "Battle: Complete!" in board.text() and board.view is None, "")
    sent = [(name, channel) for _, name, _, channel in w.events if name.startswith("battle")]
    channel = w.channel.id
    wanted = [("battle_win", channel), ("battle_played", channel), ("battle_played", channel)]
    r.check("the events of a battle ended by the clock carry the channel", sent, wanted)
    r.check("the clock is put away", fight.session_id in w.cog._timers, False)
    await asyncio.sleep(1.3)
    after = (await records(w, 31), (await fight.state())["turn"])
    r.check("and nothing more happens once the battle is over", after, (1, 4))

    # the panel refuses a turn shorter than 10 seconds, 0 included: there is no battle without a clock
    refused = {}
    for seconds in (0, 9, 10):
        try:
            bm.BattleSettings(turn_timeout_seconds=seconds).clean()
            refused[seconds] = False
        except Exception as error:
            refused[seconds] = type(error).__name__
    wanted = {0: "ValidationError", 9: "ValidationError", 10: False}
    r.check("the panel takes a turn length of 10 seconds and nothing under", refused, wanted)

    # and should a 0 reach the cog all the same, it is one second, not a busy loop
    w.override_settings(turn_timeout_seconds=0)
    fight = await w.fight(33, 34, ["Monkey D. Luffy", "Nami"], ["Kaido", "Usopp"])
    await asyncio.sleep(0.5)
    early = (await fight.state())["turn"]
    await asyncio.sleep(0.9)
    r.check("a turn length of 0 is played as a turn of one second", (early, (await fight.state())["turn"]), (0, 1))
    w.restore_settings()
    await fight.act(33, "forfeit")


async def leaderboard(w: h.World):
    foreign = (await h.aforeign_rows())["records"]
    mine_only = foreign == 0 and await bm.BattleRecord.objects.acount() == 0
    if mine_only:
        i = await w.cmd(41, "leaderboard")
        r.check("no battle recorded yet", i.first, "No battles have been recorded yet.")
    else:
        r.note(f"{foreign} battle record(s) that are not the tests': the exact order is not checked")

    players = {n: await w.player(n) for n in range(41, 48)}
    results = [(41, 46, 41)] * 3 + [(42, 43, 42)] * 2
    results += [(44, 42, 42), (43, 42, 43), (43, 44, 43), (44, 45, 44), (45, 46, 45), (47, 46, 47)]
    for p1, p2, winner in results:
        await bm.BattleRecord.objects.acreate(player1=players[p1], player2=players[p2], winner=players[winner], turns=3)
    w.bot.unknown_users.add(w.user(47).id)

    i = await w.cmd(41, "leaderboard")
    board = i.sent[0]
    text = board.text()
    r.ok("the leaderboard is posted", "Battle Leaderboard" in text, text[:60])
    if mine_only:
        r.ok("1st: 3 wins, no loss", "### 🥇\n> Tester41\n> **3W - 0L** • Win rate: 100.0%" in text, "")
        r.ok("2nd: 3 wins too, but one loss", "### 🥈\n> Tester42\n> **3W - 1L** • Win rate: 75.0%" in text, "")
        r.ok("3rd: 2 wins, 2 losses", "### 🥉\n> Tester43\n> **2W - 2L** • Win rate: 50.0%" in text, "")
        first_page = "Tester45" not in text and "Tester44" not in text and "-# Page 1/2" in text
        r.ok("three entries on the first page", first_page, "")
    r.ok("a player with no win is not listed, whatever they lost", "Tester46" not in text, "")

    # the page buttons carry the number of the page they lead to
    buttons = {item.label: item for item in board.view.walk_children() if getattr(item, "label", None)}
    following = buttons.get("2")
    r.ok("more than three entries: page buttons", following is not None, sorted(buttons))
    if following is None:
        return
    other = await w.dispatch(42, board.view, following, message=board)
    r.check("only the one who asked can turn the pages", other.first, "You are not allowed to interact with this.")
    await w.dispatch(41, board.view, following, message=board)
    text = board.text()
    if mine_only:
        fifth = "### 5\n> Tester45\n> **1W - 1L** • Win rate: 50.0%" in text
        ordered = fifth and text.index("Tester45") < text.index("Tester44") and "**1W - 2L**" in text
        r.ok("page 2: a win and a loss comes before a win and two losses", ordered, text[-150:])
        skipped = "Tester47" not in text and "### 4" not in text
        r.ok("a winner Discord cannot fetch is skipped, their rank is left out", skipped, "")
    stray = [name for name in ("Tester41", "Tester42", "Tester43") if name in text]
    r.check("page 2 shows page 2 only", stray, [], bug="B22")
    back = next(item for item in board.view.walk_children() if getattr(item, "label", None) == "1")
    await w.dispatch(41, board.view, back, message=board)
    text = board.text()
    r.check("back on page 1, each player is listed once", text.count("Tester41"), 1, bug="B22")
    w.bot.unknown_users.clear()


async def main(w: h.World):
    await r.scenario("leaderboard", leaderboard, w)
    mine = bm.BattleRecord.objects.filter(player1__discord_id__gte=w.base, player1__discord_id__lt=w.base + 1000)
    await mine.adelete()
    await r.scenario("payout, record and events", payout, w)
    await r.scenario("anti-abuse earnings", anti_abuse, w)
    await r.scenario("forfeit", forfeit, w)
    await r.scenario("a turn timing out", timeout, w)
    r.check("no callback raised along the way", [repr(e) for e in w.errors], [])


h.run(BLOCK, main)
r.finish()
