"""
Is a crew war ready to end? Reads everything the announcement and the payout depend on and
says what is missing. Writes nothing, ever — run it as often as you like.

    docker compose exec -T -e WAR=1 admin-panel python3 -m django shell < scripts/check_crew_war_ready.py

The thing worth knowing before reading the output: the announcement is driven by the payout, not
by the clock. `ends_at` only stops the scoring. The bot's loop looks for wars that have at least
one reward handed out and have never been announced, and speaks then — so a war whose rewards
are never handed out is never announced, however long you wait.

With **Auto finish** on, the bot closes the war itself: a couple of minutes after the end date
passes it hands the ladder out, and the announcement follows in the same pass. Off, both wait
for someone to run "Hand out the rewards" in the panel. Either way the order is the same — the
clock runs out, the ladder goes out, and then the bot announces the winner in the channels and
sends every paid player their direct message.

Environment:
    WAR=...   which war, as its id or a piece of its name. Default: 1.
"""

import os

from crew_app.models import Crew, CrewWar, CrewWarEntry, CrewWarPayout, CrewWarReward
from crew_app.payouts import crew_places, plan
from django.db.models import Sum
from django.utils import timezone
from settings.models import Settings

from bd_models.enums import AnnouncementScope

WAR = os.environ.get("WAR", "1").strip()

problems: list[str] = []
todo: list[str] = []


def say(line: str = "") -> None:
    print(line)


def bad(line: str) -> None:
    problems.append(line)
    print(f"  [X] {line}")


def ok(line: str) -> None:
    print(f"  [v] {line}")


def note(line: str) -> None:
    todo.append(line)
    print(f"  [!] {line}")


def find_war() -> CrewWar | None:
    if WAR.isdigit():
        war = CrewWar.objects.filter(pk=int(WAR)).first()
        if war:
            return war
    matches = list(CrewWar.objects.filter(name__icontains=WAR)[:6])
    if len(matches) == 1:
        return matches[0]
    if matches:
        say(f"  {WAR!r} matches several wars: {', '.join(w.name for w in matches)}")
    else:
        listed = ", ".join(f"{w.pk}: {w.name}" for w in CrewWar.objects.all())
        say(f"  no war matches {WAR!r}. On this database: {listed or 'none'}")
    return None


say("=" * 78)
say("IS THIS CREW WAR READY TO END?")
say("=" * 78)

war = find_war()
if war is None:
    say("")
    say("Nothing to check. Set WAR=<id or name>.")
else:
    now = timezone.now()

    # -- the clock -----------------------------------------------------------------------------

    say("")
    say(f"The war — #{war.pk} {war.name}")
    say(f"  enabled: {war.enabled}")
    say(f"  starts:  {war.starts_at:%a %d %b %Y %H:%M} UTC" if war.starts_at else "  starts:  no start set")
    if war.ends_at:
        left = war.ends_at - now
        hours = left.total_seconds() / 3600
        say(f"  ends:    {war.ends_at:%a %d %b %Y %H:%M} UTC")
        if hours > 0:
            say(f"  left:    {hours:.1f} hour(s)")
        else:
            say(f"  left:    over since {-hours:.1f} hour(s) ago")
    else:
        note("No end date is set, so this war never stops scoring on its own.")
    say(f"  scoring right now: {war.is_live(now)}")

    # -- does it close itself? -----------------------------------------------------------------

    say("")
    say("Closing itself at the end of the clock")
    if not war.auto_finish:
        note(
            "Auto finish is OFF: nothing happens when the clock runs out. You have to run 'Hand out "
            "the rewards' in the panel, or the script with PAYOUT=1, or nobody is paid and nothing "
            "is announced. Tick Auto finish on the war page to have the bot do it."
        )
    elif not war.ends_at:
        bad("Auto finish is on but the war has no end date, so there is no moment for it to fire.")
    elif war.finished_at:
        note(
            f"Auto finish already fired on {war.finished_at:%d %b %H:%M} UTC and fires once. Clear "
            "'Finished at' to have the ladder handed out again — which pays nobody twice."
        )
    else:
        ok("Auto finish is on: the bot pays the ladder out within 2 minutes of the end date.")

    # -- the announcement ----------------------------------------------------------------------

    say("")
    say("The announcement of the winner")
    if war.announced_at:
        bad(
            f"This war was already announced on {war.announced_at:%d %b %H:%M} UTC, and it is announced "
            "once. Clear 'Announced at' on the war page if you want the result posted again."
        )
    else:
        ok("Never announced yet, so it will be posted once the rewards are handed out.")

    if war.announce_to == AnnouncementScope.NONE:
        bad(
            "'Announce to' is set to 'Nowhere, announce nothing': the winner will never be posted "
            "in any channel. Set it to 'Every spawn channel' or 'The main server only'."
        )
    elif war.announce_to == AnnouncementScope.MAIN:
        panel = Settings.objects.first()
        if panel is None or not panel.main_server_id:
            bad(
                "'Announce to' is 'The main server only' but no main server is set on the settings "
                "page, which makes it behave like 'Nowhere'. Fill Main server id, then run b.reloadconf."
            )
        else:
            ok(f"Posted in the main server only ({panel.main_server_id}).")
    else:
        ok("Posted in every spawn channel.")

    # -- the picture ---------------------------------------------------------------------------

    crew_rows = list(
        CrewWarEntry.objects.filter(war=war).values("crew_id").annotate(total=Sum("points")).order_by("-total")
    )
    places = crew_places(war)
    crews = {crew.pk: crew for crew in Crew.objects.filter(pk__in=[row["crew_id"] for row in crew_rows])}
    leader = crews.get(crew_rows[0]["crew_id"]) if crew_rows else None

    say("")
    say("The picture on the announcement")
    if leader is None:
        bad("Nobody has scored, so there is no winner to announce. Check WAR.")
    elif leader.victory_image:
        ok(f"{leader.name} is leading and has its own victory picture.")
    elif war.image:
        note(
            f"{leader.name} is leading but has no victory picture, so the war's own banner is used. "
            "Add one on the crew page if you want their flag on the announcement."
        )
    else:
        note("Neither the leading crew nor the war has a picture, so the announcement goes out without one.")

    # -- the standings -------------------------------------------------------------------------

    say("")
    say(f"Standings — {len(crew_rows)} crew(s) have scored")
    for row in crew_rows[:6]:
        crew = crews.get(row["crew_id"])
        say(f"  {places.get(row['crew_id'], 0):>2}. {crew.name if crew else 'crew ?'} — {row['total']:,}")
    if len(crew_rows) > 6:
        say(f"  ... and {len(crew_rows) - 6} more")

    # -- the ladder ----------------------------------------------------------------------------

    say("")
    say("The reward ladder")
    rungs = list(war.rewards.prefetch_related("cards"))
    if not rungs:
        bad(
            "This war has no reward ladder at all, so the payout would hand nothing over and the "
            "winner would never be announced. Run setup_crew_war_s1_rewards.py with APPLY=1."
        )
    else:
        players = [r for r in rungs if not r.is_crew_reward]
        crew_rungs = [r for r in rungs if r.is_crew_reward]
        ok(f"{len(rungs)} rung(s): {len(players)} on a player's points, {len(crew_rungs)} on a crew's place.")
        if not players:
            note("No rung goes by a player's own points, so only whole crews are paid.")
        if not crew_rungs:
            note("No rung goes by a crew's place, so winning the war pays nothing by itself.")
        empty = [r for r in rungs if not r.money and not r.cards.exists()]
        for rung in empty:
            bad(f"{rung.label} pays nothing at all: no berries and no card.")
        cardless = [r for r in rungs if not r.cards.exists()]
        if cardless:
            say(f"  berries only, no card ({len(cardless)}): {', '.join(r.name for r in cardless)}")

    # -- what the payout would do ----------------------------------------------------------------

    say("")
    say("What handing it out would do, right now")
    owed = plan(war)
    paid_already = CrewWarPayout.objects.filter(reward__war=war).count()
    money = sum(reward.money for one in owed for reward in one.rewards)
    cards = sum(card.amount for one in owed for reward in one.rewards for card in reward.cards.all())
    if not owed and not paid_already:
        bad("Nobody is owed anything. Either the ladder is empty or its lowest rung is out of reach.")
    else:
        ok(f"{len(owed)} player(s) owed {money:,} berries and {cards} card(s).")
    if paid_already:
        note(
            f"{paid_already} rung(s) have already been handed out. Those are not paid twice, and if the "
            "war was announced along with them it is not announced again."
        )
    if owed:
        say("  the five biggest:")
        for one in owed[:5]:
            crew = crews.get(one.crew_id)
            total = sum(reward.money for reward in one.rewards)
            say(f"    {one.points:>6,} pts  {(crew.name if crew else 'no crew'):<24} {total:>9,} berries")

    # -- the bot -------------------------------------------------------------------------------

    say("")
    say("The bot, which is what actually speaks")
    say("  This script cannot see whether the bot is up. Check it yourself:")
    say("    - `docker compose ps bot` says running")
    say("    - `/crew war` answers in Discord. The loop that announces lives in that same cog,")
    say("      so if the command answers, the loop is running and fires every 2 minutes.")

    # -- the verdict ---------------------------------------------------------------------------

    say("")
    say("-" * 78)
    if problems:
        say(f"{len(problems)} thing(s) would stop this working:")
        for line in problems:
            say(f"  [X] {line}")
    elif war.auto_finish and not war.finished_at:
        say("Nothing is in the way, and nothing is left for you to do. A couple of minutes after")
        say("the end date the bot pays the ladder out, posts the winner in the channels and sends")
        say("every paid player a direct message.")
    else:
        say("Nothing is in the way. Hand the rewards out when the clock runs out and the bot")
        say("does the rest within two minutes: the winner in the channels, a direct message")
        say("to every paid player.")
    if todo:
        say("")
        say("Worth knowing, but nothing is broken:")
        for line in todo:
            say(f"  [!] {line}")
    say("")
    say("Remember: the payout is what makes the bot speak, not the clock. Auto finish only")
    say("decides whether the bot runs that payout for you or waits for you to do it.")
