"""
The reward ladder of The Great Crew War, season 1, and — if you ask for it — the payout itself.

Built for the standings season 1 actually finished on: fifteen crews between 8,615 and 86
points, a top contributor at 1,944, and the bulk of the field around 100 points with the
newcomers around 50. So the ladder has low rungs a 50-point player actually clears, instead of
the single "Rookie" rung a ladder starting at 150 would have left them with.

Run it through the panel container's Django shell; the file is piped in on stdin, so the
container never has to hold it.

    # what it would create and who it would pay, writing nothing
    docker compose exec -T admin-panel python3 -m django shell < scripts/setup_crew_war_s1_rewards.py

    # create the ladder for real (nothing is handed out yet)
    docker compose exec -T -e APPLY=1 admin-panel python3 -m django shell < scripts/setup_crew_war_s1_rewards.py

    # create it and hand it out in the same run
    docker compose exec -T -e APPLY=1 -e PAYOUT=1 admin-panel \
        python3 -m django shell < scripts/setup_crew_war_s1_rewards.py

Everything happens in one transaction, rolled back unless APPLY=1. Nothing is overwritten: a
rung already on the war at the same (scope, threshold) is left exactly as it is, cards and all,
so a second run after a half-finished first one is safe. The payout is idempotent too — each
rung handed to each player is a row under a unique constraint, so running it twice hands
nothing over twice.

Environment:
    APPLY=1         write it. Without this nothing is kept.
    PAYOUT=1        also hand the ladder out, which is the same thing the panel's "Hand out the
                    rewards of the selected wars" action does. Needs APPLY=1. The bot sends the
                    direct messages itself, within a couple of minutes.
    WAR=...         which war, as its id or a piece of its name. Default: 1.
    LADDER_CARD=... the treasure handed over by the card rungs, by name (exact, or a unique
                    substring). Left out, those rungs are created paying berries only and are
                    listed for you to add the cards in the panel.
    CREW_CARD=...   the treasure the three podium crews get, if it should differ from
                    LADDER_CARD. Defaults to LADDER_CARD.
"""

import os

from crew_app.models import Crew, CrewWar, CrewWarEntry, CrewWarPayout, CrewWarReward, CrewWarRewardCard
from crew_app.payouts import crew_places, plan
from django.db import transaction
from django.db.models import Sum

from bd_models.models import Ball, Special

APPLY = os.environ.get("APPLY") == "1"
PAYOUT = os.environ.get("PAYOUT") == "1"
WAR = os.environ.get("WAR", "1").strip()
LADDER_CARD = os.environ.get("LADDER_CARD", "").strip()
CREW_CARD = os.environ.get("CREW_CARD", "").strip() or LADDER_CARD

Scope = CrewWarReward.Scope

# The player ladder stacks all the way up: every rung says "also hand out the one below", so a
# player is paid everything they walked past rather than their top rung alone. The totals that
# comes to are printed by the script, because that is the number that actually matters.
#
# (scope, threshold, name, money, cumulative, message, medal special or None, wants a card)
REWARDS = [
    (Scope.PLAYER, 1, "Rookie", 10_000, True, "You flew the flag all season. That already counts.", None, False),
    (Scope.PLAYER, 50, "Pirate", 20_000, True, "First season, first real share of the loot.", None, False),
    (Scope.PLAYER, 100, "Veteran", 30_000, True, "You pulled your weight from start to finish.", None, False),
    (Scope.PLAYER, 250, "Supernova", 40_000, True, "The Grand Line knows your name now.", None, True),
    (Scope.PLAYER, 500, "Commander", 60_000, True, "Your crew leaned on you and you held.", "Bronze Medal", True),
    (Scope.PLAYER, 1_000, "Warlord", 80_000, True, "Few crews had anyone like you.", "Silver Medal", True),
    (
        Scope.PLAYER,
        1_800,
        "Yonko",
        120_000,
        True,
        "Season one. You did not take part in this war, you were it.",
        "Gold Medal",
        True,
    ),
    # Crew rungs are earned on their own and pile on top of whatever the player's own points
    # brought them. Place 0 is the "every crew that scored" rung, so the bottom of a table of
    # fifteen still gets something for sailing the season.
    (Scope.CREW, 1, "Flag of the Pirate King", 100_000, True, "Season one is yours.", "Gold Medal", True),
    (
        Scope.CREW,
        2,
        "Second fleet standing",
        70_000,
        True,
        "One crew ahead of you, thirteen behind.",
        "Silver Medal",
        True,
    ),
    (Scope.CREW, 3, "Third flag standing", 50_000, True, "You held the podium to the end.", "Bronze Medal", True),
    (Scope.CREW, 4, "Fourth flag standing", 35_000, True, "Just off the podium, clear of the pack.", None, False),
    (Scope.CREW, 5, "Fifth flag standing", 25_000, True, "You finished in the top five of fifteen.", None, False),
    (Scope.CREW, 0, "Took the field", 10_000, True, "You sailed the whole season under your own flag.", None, False),
]

notes: list[str] = []


class Rollback(Exception):
    pass


def say(line: str = "") -> None:
    print(line)


def warn(line: str) -> None:
    notes.append(line)
    print(f"  ! {line}")


def one_ball(name: str) -> Ball | None:
    """A treasure by exact name, or by a substring when it picks out exactly one."""
    if not name:
        return None
    found = Ball.objects.filter(country__iexact=name).first()
    if found:
        return found
    matches = list(Ball.objects.filter(country__icontains=name)[:6])
    if len(matches) == 1:
        return matches[0]
    if not matches:
        warn(f"No treasure is called {name!r}. The card rungs were created without their cards.")
    else:
        warn(f"{name!r} matches several treasures ({', '.join(b.country for b in matches)}). Be exact.")
    return None


def find_war() -> CrewWar | None:
    if WAR.isdigit():
        war = CrewWar.objects.filter(pk=int(WAR)).first()
        if war:
            return war
        warn(f"No war has id {WAR}.")
    matches = list(CrewWar.objects.filter(name__icontains=WAR)[:6])
    if len(matches) == 1:
        return matches[0]
    if matches:
        warn(f"{WAR!r} matches several wars ({', '.join(w.name for w in matches)}). Be exact.")
    else:
        listed = ", ".join(f"{w.pk}: {w.name}" for w in CrewWar.objects.all())
        say(f"  wars on this database: {listed or 'none'}")
    return None


try:
    with transaction.atomic():
        say("=" * 78)
        say(f"CREW WAR SEASON 1 — REWARDS — {'WRITING' if APPLY else 'DRY RUN, nothing will be kept'}")
        say("=" * 78)

        war = find_war()
        if war is None:
            say("")
            say("No war to work on. Set WAR=<id or name> and run it again.")
            raise Rollback

        say("")
        say(f"War: #{war.pk} {war.name}")
        if PAYOUT and not APPLY:
            warn("PAYOUT=1 without APPLY=1 pays nothing: the whole run is rolled back. Add APPLY=1.")

        # -- the standings this ladder is read against ------------------------------------------

        crew_rows = list(
            CrewWarEntry.objects.filter(war=war).values("crew_id").annotate(total=Sum("points")).order_by("-total")
        )
        if not crew_rows:
            warn("Nobody has scored in this war, so the ladder would pay nobody. Check WAR.")
        places = crew_places(war)
        names = dict(Crew.objects.filter(pk__in=[row["crew_id"] for row in crew_rows]).values_list("pk", "name"))
        say("")
        say("Standings")
        for row in crew_rows:
            crew_name = names.get(row["crew_id"], "no crew")
            say(f"  {places.get(row['crew_id'], 0):>2}. {crew_name} — {row['total']:,}")

        # -- the ladder --------------------------------------------------------------------------

        ladder_ball = one_ball(LADDER_CARD)
        crew_ball = ladder_ball if CREW_CARD == LADDER_CARD else one_ball(CREW_CARD)
        medals = {}
        for row in REWARDS:
            medal = row[6]
            if medal and medal not in medals:
                medals[medal] = Special.objects.filter(name__iexact=medal).first()
                if medals[medal] is None:
                    warn(f"There is no special called {medal!r}; those cards are given plain.")

        made = {"rewards": 0, "cards": 0, "kept": 0}
        cardless: list[str] = []
        say("")
        say("Ladder")
        for scope, threshold, name, money, cumulative, message, medal, wants_card in REWARDS:
            rung, fresh = CrewWarReward.objects.get_or_create(
                war=war,
                scope=scope,
                threshold=threshold,
                defaults={"name": name, "money": money, "cumulative": cumulative, "message": message},
            )
            if not fresh:
                made["kept"] += 1
                say(f"  left alone, already there: {rung.label} — {rung.money:,} berries")
                continue
            made["rewards"] += 1
            say(f"  {rung.label} — {money:,} berries{' + 1 card' if wants_card else ''}")
            if not wants_card or rung.cards.exists():
                continue
            ball = crew_ball if scope == Scope.CREW else ladder_ball
            if ball is None:
                cardless.append(f"{name} ({scope} {threshold}): 1x a treasure{f' as {medal}' if medal else ''}")
                continue
            CrewWarRewardCard.objects.create(
                reward=rung,
                ball=ball,
                special=medals.get(medal) if medal else None,
                amount=1,
                tradeable=True,
            )
            made["cards"] += 1
        say(
            f"  -> {made['rewards']} rung(s) created, {made['cards']} card(s) attached, "
            f"{made['kept']} left alone"
        )
        if cardless:
            say("")
            say("  No treasure was named, so these rungs pay berries only. Add their cards in the panel:")
            for line in cardless:
                say(f"    {line}")

        # what a player ends up with, since the rungs stack and nobody reads a ladder that way
        say("")
        say("What the player ladder adds up to, since it stacks")
        running = 0
        for scope, threshold, name, money, *_ in REWARDS:
            if scope != Scope.PLAYER:
                continue
            running += money
            say(f"  {threshold:>5} points -> {name:<10} {running:>9,} berries in all")

        # -- who that pays ------------------------------------------------------------------------

        owed = plan(war)
        total_money = sum(reward.money for one in owed for reward in one.rewards)
        total_cards = sum(card.amount for one in owed for reward in one.rewards for card in reward.cards.all())
        already = CrewWarPayout.objects.filter(reward__war=war).count()
        say("")
        say("Who that pays")
        say(f"  {len(owed)} player(s) owed something, {total_money:,} berries and {total_cards} card(s) in all")
        if already:
            say(f"  {already} rung(s) were handed out before and will not be paid again")
        say("  the twenty biggest:")
        for one in owed[:20]:
            crew_name = names.get(one.crew_id, "no crew")
            money = sum(reward.money for reward in one.rewards)
            say(f"    {one.points:>6,} pts  {crew_name:<24} {money:>9,} berries  {one.summary}")
        if len(owed) > 20:
            say(f"    ... and {len(owed) - 20} more")

        # -- hand it out --------------------------------------------------------------------------

        if PAYOUT:
            from crew_app.payouts import hand_out

            say("")
            say("Handing out")
            paid, seen, players = hand_out(war)
            say(f"  {paid} rung(s) handed to {players} player(s), {seen} were already paid")
            say("  the bot sends the direct messages itself, within a couple of minutes")
        else:
            say("")
            say("Nothing was handed out. Three ways to change that:")
            say("  - tick Auto finish on the war, and the bot pays the ladder out and announces")
            say("    the winner on its own, within two minutes of the end date passing")
            say("  - re-run this with PAYOUT=1")
            say('  - run "Hand out the rewards of the selected wars" from the war list in the panel')

        say("")
        say("-" * 78)
        if notes:
            say("Worth reading before you walk away:")
            for note in notes:
                say(f"  ! {note}")
            say("")
        if not APPLY:
            say("Nothing was written. Run it again with APPLY=1 to keep all of this.")
            raise Rollback
        say("Written.")
except Rollback:
    pass
