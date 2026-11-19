"""
Create The Void Century War: the war and its barème, the reward ladder, the hunt and its four
poneglyphs, and the six wanted posters.

Run it through the panel container's Django shell, which needs nothing rebuilt: the file is
piped in on stdin, so the container never has to hold it.

    # what it would create, writing nothing
    docker compose exec -T admin-panel python3 -m django shell < setup_void_century_war.py

    # and for real
    docker compose exec -T -e APPLY=1 admin-panel python3 -m django shell < setup_void_century_war.py

Everything happens in one transaction, rolled back unless APPLY=1. Nothing is ever overwritten:
a war, a hunt, a stone or a poster that already carries the same name or window is reported and
left exactly as it is, so a second run after a half-finished first one is safe.

One thing it will not do: break a war that is still running. The scoring reads a single war —
the enabled one with the latest start date — and stops counting altogether when that one is not
inside its window. So a war starting on Sunday, enabled today, silently takes the running war's
place and nothing scores for it until Sunday. When another war is still live, this one is
therefore created turned OFF, and the script says when to tick it on. The running war is never
touched, whatever DISABLE_OTHERS says.

Environment:
    APPLY=1           write it. Without this nothing is kept.
    LADDER_CARD=...   the treasure handed over by the card rungs, by name (exact or unique
                      substring). Left out, the rungs are created paying berries only and the
                      cards are listed for you to add in the panel.
    HUNT_CARD=...     the treasure the finished hunt hands over, same rule.
    DISABLE_OTHERS=1  turn off the other wars that are enabled but no longer running. A war
                      that is still live is never touched: see below.
    SEED=...          changes which treasures the stones and the posters draw. The default is
                      fixed, so the dry run and the real run pick the same ones.
"""

import os
import random
from datetime import datetime
from datetime import timezone as dt_timezone

from collector_app.models import CollectorTierLevel
from crew_app.models import CrewWar, CrewWarReward, CrewWarRewardCard, CrewWarRule
from django.core.exceptions import ValidationError
from django.db import transaction
from hunt_app.models import Hunt, Poneglyph, PoneglyphRequirement

from bd_models.enums import AnnouncementScope
from bd_models.models import Ball, Bounty, Special
from settings.models import Settings

APPLY = os.environ.get("APPLY") == "1"
DISABLE_OTHERS = os.environ.get("DISABLE_OTHERS") == "1"
LADDER_CARD = os.environ.get("LADDER_CARD", "").strip()
HUNT_CARD = os.environ.get("HUNT_CARD", "").strip()
random.seed(os.environ.get("SEED", "void-century"))


def utc(day: int, hour: int, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=dt_timezone.utc)


WAR_NAME = "The Void Century War — Season 1"
HUNT_NAME = "The Void Century"
WAR_START = utc(22, 19)
WAR_END = utc(29, 19)

WAR_DESCRIPTION = (
    "Seven days, four stones, one table. Every poneglyph claimed, every bounty collected, every "
    "boss put down and every card crafted scores for the flag you fly. The crew that reads the "
    "most of the Void Century takes the top of the board — and the players who carried their crew "
    "are paid whether their crew wins or not."
)

HUNT_DESCRIPTION = (
    "Four stones surfaced across the Grand Line the night the war opened, and the sea gives you "
    "one week to read them. Two are already up. A third surfaces Wednesday, and the fourth "
    "without a word. Each one asks for a set no single crewmate is likely to hold: gather, trade, "
    "hand in. Every member who claims a stone is paid the full reward, and the whole crew takes a "
    "fifth on top — so the rare early sets are worth exactly as much as the last, easy one."
)

Source = CrewWarRule.Source

# (source, points, daily cap, minimum value, collector tier level or None)
RULES = [
    (Source.HUNT_COMPLETED, 150, 0, 0, None),
    (Source.BOUNTY_CLAIMED, 75, 0, 0, None),
    (Source.PONEGLYPH_CLAIMED, 40, 0, 0, None),
    (Source.BOSS_WIN, 50, 0, 0, None),
    (Source.BOSS_PLAYED, 10, 0, 0, None),
    (Source.BATTLE_WIN, 5, 25, 0, None),
    (Source.BATTLE_PLAYED, 2, 10, 0, None),
    (Source.CRAFT, 30, 90, 0, "Elemental"),
    (Source.CRAFT, 15, 60, 0, None),
    (Source.CATCH_SPECIAL, 5, 50, 0, None),
    (Source.CATCH, 1, 40, 0, None),
    (Source.FRIEND, 5, 10, 0, None),
    # no minimum on trade and gift: they move no berries, so any minimum stops them scoring
    (Source.TRADE, 3, 15, 0, None),
    (Source.GIFT, 1, 5, 0, None),
    (Source.MERCHANT_BUY, 5, 20, 0, None),
    (Source.AUCTION_WON, 5, 20, 10_000, None),
    (Source.SHOP_BUY, 3, 15, 0, None),
    (Source.PACK_BUY, 3, 15, 0, None),
    (Source.AUCTION_CREATE, 2, 10, 10_000, None),
    (Source.SELL, 1, 10, 5_000, None),
    (Source.AUCTION_BID, 1, 5, 10_000, None),
    (Source.WEEKLY_PACK, 15, 15, 0, None),
    (Source.PLAYED, 10, 10, 0, None),
    (Source.DAILY_BERRIES, 5, 5, 0, None),
    (Source.DAILY_PACK, 5, 5, 0, None),
]

Scope = CrewWarReward.Scope

# (scope, threshold, name, money, cumulative, message, medal special or None, wants a card)
REWARDS = [
    (Scope.PLAYER, 1, "Rookie", 15_000, True, "You flew the flag. That already counts.", None, False),
    (Scope.PLAYER, 150, "Pirate", 35_000, True, "You carried your share of the stones.", None, False),
    (Scope.PLAYER, 400, "Supernova", 75_000, True, "The Grand Line knows your name now.", None, True),
    (Scope.PLAYER, 900, "Warlord", 150_000, True, "Few crews had someone like you.", "Silver Medal", True),
    (
        Scope.PLAYER,
        1_800,
        "Yonko",
        300_000,
        True,
        "One week. You did not join this war, you were it.",
        "Gold Medal",
        True,
    ),
    (Scope.CREW, 1, "They read the Void Century", 150_000, True, "", "Gold Medal", True),
    (Scope.CREW, 2, "Second to the stones", 100_000, True, "", "Silver Medal", True),
    (Scope.CREW, 3, "Third flag standing", 60_000, True, "", "Bronze Medal", True),
    (Scope.CREW, 0, "Took the field", 15_000, True, "", None, False),
]

# (name, position, opens at, draw count, min rarity, max rarity, announce to, hint)
STONES = [
    (
        "The Stone of Ohara",
        1,
        None,
        3,
        140,
        224,
        "",
        "The archaeologists copied it before the ships came. What they wrote down was only a list "
        "of names, and the list is still being gathered.",
    ),
    (
        "The Stone of Zou",
        2,
        None,
        3,
        90,
        140,
        "",
        "A thousand years on an elephant's back, and the ones who guard it only let you read it "
        "if you arrive carrying the right company.",
    ),
    (
        "The Stone of Wano",
        3,
        utc(25, 19),
        3,
        30,
        90,
        "",
        "The one that was never meant to be found. It asks for the sort of cards a crew has to "
        "pool to even see.",
    ),
    (
        "The Last Stone",
        4,
        utc(27, 19),
        2,
        5,
        30,
        AnnouncementScope.NONE,
        "Nobody announced this one. Somebody still read it first.",
    ),
]

# (starts at, ends at, reward, min rarity, max rarity, announcement text)
BOUNTIES = [
    (
        utc(22, 19),
        utc(24, 19),
        100_000,
        150,
        224,
        "A first name went up on the board the hour the war opened. Low price, no hiding place — "
        "somebody will have this one before Tuesday.",
    ),
    (
        utc(23, 19),
        utc(25, 19),
        120_000,
        120,
        180,
        "The first poster is not even cold and the Marines have printed another. Two live at once "
        "from tonight, and that is how the rest of the week looks.",
    ),
    (
        utc(24, 19),
        utc(26, 19),
        150_000,
        80,
        150,
        "Another name, another crew about to be seventy-five points richer. Forty-eight hours, "
        "first catch only — and the one from Monday expires tomorrow night.",
    ),
    (
        utc(25, 19),
        utc(27, 19),
        200_000,
        60,
        120,
        "Midweek, and the price keeps climbing. Whoever has been catching every evening is the one "
        "collecting these. Whoever waits for the big one will find somebody already there.",
    ),
    (
        utc(26, 19),
        utc(28, 19),
        250_000,
        40,
        80,
        "Two hundred and fifty thousand, and the rarest head on the board so far. The last poster "
        "before the big one — and the big one goes up tomorrow night.",
    ),
    (
        utc(27, 19),
        utc(29, 18),
        500_000,
        20,
        40,
        "The last poster of the war, and the biggest. Half a million berries on one head, and the "
        "board closes Sunday at 20:00 whether anybody collects it or not.",
    ),
]


class Rollback(Exception):
    """Raised at the end of a dry run, so the transaction leaves nothing behind."""


notes: list[str] = []
made = {"rules": 0, "rewards": 0, "cards": 0, "stones": 0, "requirements": 0, "bounties": 0}


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


def draw(count: int, low: float, high: float, taken: set[int]) -> list[Ball]:
    """
    Treasures picked at random inside a rarity band, the way the panel's own action picks them.

    Disabled treasures and ones at rarity 0 are left out: they never spawn, so asking for them
    would make a stone impossible and a poster unclaimable.
    """
    pool = list(
        Ball.objects.filter(enabled=True, rarity__gt=0, rarity__gte=low, rarity__lte=high)
        .exclude(pk__in=taken)
        .values_list("pk", flat=True)
    )
    if len(pool) < count:
        warn(f"Only {len(pool)} treasure(s) between rarity {low} and {high}, {count} needed. Widen the band.")
        count = len(pool)
    chosen = random.sample(pool, count) if count else []
    taken.update(chosen)
    return list(Ball.objects.filter(pk__in=chosen))


try:
    with transaction.atomic():
        say("=" * 78)
        say(f"THE VOID CENTURY WAR — {'WRITING' if APPLY else 'DRY RUN, nothing will be kept'}")
        say("=" * 78)

        # -- the things that have to be true before any of this is worth creating ---------------

        say("")
        say("Before anything else")
        panel = Settings.objects.first()
        if panel is None or not panel.main_server_id:
            warn(
                "No main server is set, so every announcement set to 'the main server only' goes "
                "nowhere. Fill Main server id on the settings page, then run b.reloadconf."
            )
        else:
            say(f"  main server: {panel.main_server_id}")

        others = list(CrewWar.objects.filter(enabled=True).exclude(name=WAR_NAME))
        running = [other for other in others if other.is_live()]
        stale = [other for other in others if not other.is_live()]
        # a war starting later than a running one takes its place the moment it is enabled, and
        # scores nothing until its own window opens. So this one waits, turned off, by hand.
        start_enabled = not running
        for other in running:
            ends = f"{other.ends_at:%a %d %b %H:%M} UTC" if other.ends_at else "no end set"
            warn(
                f"{other.name!r} is still running ({ends}). This war was created TURNED OFF so it "
                "cannot take its place: enabled today it would stop that war scoring at once, and "
                "score nothing itself until Sunday. Tick Enabled on it once that war is over."
            )
        if stale:
            if DISABLE_OTHERS:
                CrewWar.objects.filter(pk__in=[other.pk for other in stale]).update(enabled=False)
                say(f"  turned off {len(stale)} war(s) past their window: {', '.join(o.name for o in stale)}")
            else:
                warn(
                    f"{len(stale)} war(s) are enabled but outside their window "
                    f"({', '.join(o.name for o in stale)}). They stop this one scoring if they start "
                    "later than it. Re-run with DISABLE_OTHERS=1, or untick them in the panel."
                )

        ladder_ball = one_ball(LADDER_CARD)
        hunt_ball = one_ball(HUNT_CARD)
        wanted = Special.objects.filter(name__iexact="Wanted").first()
        if wanted is None:
            warn("No special called 'Wanted', so the posters were created without one.")
        medals = {
            name: Special.objects.filter(name__iexact=name).first()
            for name in ("Gold Medal", "Silver Medal", "Bronze Medal")
        }
        for name, special in medals.items():
            if special is None:
                warn(f"No special called {name!r}. The rung that wanted it was created without it.")

        # -- the war -----------------------------------------------------------------------------

        say("")
        say("The war")
        war, fresh = CrewWar.objects.get_or_create(
            name=WAR_NAME,
            defaults={
                "description": WAR_DESCRIPTION,
                "enabled": start_enabled,
                "starts_at": WAR_START,
                "ends_at": WAR_END,
                "announce_to": AnnouncementScope.ALL,
            },
        )
        if fresh:
            say(f"  created: {war.name}" + ("" if start_enabled else "  (TURNED OFF, see above)"))
            say(f"    {WAR_START:%a %d %b %H:%M} -> {WAR_END:%a %d %b %H:%M} UTC, result announced everywhere")
        else:
            state = "enabled" if war.enabled else "turned off"
            say(f"  already there, left as it is: {war.name} ({war.starts_at} -> {war.ends_at}, {state})")

        tiers = {level.name: level for level in CollectorTierLevel.objects.all()}
        for source, points, cap, minimum, tier_name in RULES:
            tier = tiers.get(tier_name) if tier_name else None
            if tier_name and tier is None:
                warn(f"No collector tier level called {tier_name!r}; the targeted {source} rule was skipped.")
                continue
            rule, fresh_rule = CrewWarRule.objects.get_or_create(
                war=war,
                source=source,
                ball=None,
                special=None,
                collector=None,
                tier_level=tier,
                defaults={"points": points, "daily_cap": cap, "minimum_value": minimum},
            )
            if fresh_rule:
                try:
                    rule.clean()
                except ValidationError as error:
                    warn(f"{source} was refused: {error.message_dict}")
                    rule.delete()
                    continue
                made["rules"] += 1
        say(f"  rules: {made['rules']} created, {CrewWarRule.objects.filter(war=war).count()} in all")

        cardless: list[str] = []
        for scope, threshold, name, money, cumulative, message, medal, wants_card in REWARDS:
            rung, fresh_rung = CrewWarReward.objects.get_or_create(
                war=war,
                scope=scope,
                threshold=threshold,
                defaults={"name": name, "money": money, "cumulative": cumulative, "message": message},
            )
            if fresh_rung:
                made["rewards"] += 1
            if not wants_card or rung.cards.exists():
                continue
            if ladder_ball is None:
                cardless.append(f"{name} ({scope} {threshold}): 1x a treasure{f' as {medal}' if medal else ''}")
                continue
            CrewWarRewardCard.objects.create(
                reward=rung,
                ball=ladder_ball,
                special=medals.get(medal) if medal else None,
                amount=1,
                tradeable=True,
            )
            made["cards"] += 1
        say(f"  ladder: {made['rewards']} rung(s) created, {made['cards']} card(s) attached")
        if cardless:
            say("    no LADDER_CARD given, so these rungs pay berries only. Add the cards in the panel:")
            for line in cardless:
                say(f"      {line}")

        # -- the hunt ----------------------------------------------------------------------------

        say("")
        say("The hunt")
        hunt, fresh_hunt = Hunt.objects.get_or_create(
            name=HUNT_NAME,
            defaults={
                "description": HUNT_DESCRIPTION,
                "mode": Hunt.Mode.CREW,
                "enabled": True,
                "starts_at": WAR_START,
                "ends_at": WAR_END,
                "announce_to": AnnouncementScope.MAIN,
                "poneglyph_emoji": "🗿",
                "reward_money": 250_000,
                "reward_ball": hunt_ball,
                "crew_share": 20,
                "crew_reward_ball": True,
                "completion_message": "The Void Century is yours to read. Seven days, and your crew got there first.",
                "announce_completion": True,
            },
        )
        if fresh_hunt:
            say(f"  created: {hunt.name} — crew race, 250,000 berries, 20% to the crew")
            if hunt_ball is None:
                say("    no HUNT_CARD given: set the reward treasure in the panel, or it pays berries only")
            say("    check 'treasure for every member': on, it mints one copy per member of every crew")
        else:
            say(f"  already there, left as it is: {hunt.name}")

        taken: set[int] = set()
        for name, position, opens_at, count, low, high, announce, hint in STONES:
            stone, fresh_stone = Poneglyph.objects.get_or_create(
                hunt=hunt,
                name=name,
                defaults={
                    "hint": hint,
                    "position": position,
                    "opens_at": opens_at,
                    "announce_to": announce,
                    "draw_count": count,
                    "draw_min_rarity": low,
                    "draw_max_rarity": high,
                },
            )
            if fresh_stone:
                made["stones"] += 1
            when = f"{opens_at:%a %d %b %H:%M} UTC" if opens_at else "with the hunt"
            silent = " — announced nowhere" if announce == AnnouncementScope.NONE else ""
            if stone.requirements.exists():
                say(f"  {name}: already set up, left as it is")
                continue
            drawn = draw(count, low, high, taken)
            PoneglyphRequirement.objects.bulk_create(
                [PoneglyphRequirement(poneglyph=stone, ball=ball, amount=1) for ball in drawn]
            )
            made["requirements"] += len(drawn)
            say(f"  {name}: opens {when}{silent}")
            for ball in drawn:
                say(f"      {ball.country} (rarity {ball.rarity:g})")

        # -- the posters -------------------------------------------------------------------------

        say("")
        say("The wanted posters")
        for index, (starts_at, ends_at, reward, low, high, text) in enumerate(BOUNTIES, start=1):
            if Bounty.objects.filter(starts_at=starts_at, ends_at=ends_at, reward=reward).exists():
                say(f"  #{index}: already there, left as it is")
                continue
            picked = draw(1, low, high, taken)
            if not picked:
                continue
            ball = picked[0]
            Bounty.objects.create(
                ball=ball,
                reward=reward,
                special=wanted,
                starts_at=starts_at,
                ends_at=ends_at,
                announce_to=AnnouncementScope.MAIN,
                announcement_text=text,
            )
            made["bounties"] += 1
            say(
                f"  #{index}: {ball.country} (rarity {ball.rarity:g}) — {reward:,} berries, "
                f"{starts_at:%a %d %b %H:%M} -> {ends_at:%a %d %b %H:%M} UTC"
            )

        # -- what is left for you ---------------------------------------------------------------

        say("")
        say("-" * 78)
        say(
            f"{made['rules']} rules, {made['rewards']} rungs, {made['cards']} reward cards, "
            f"{made['stones']} stones with {made['requirements']} treasures, {made['bounties']} posters."
        )
        if notes:
            say("")
            say("Worth reading before you walk away:")
            for note in notes:
                say(f"  ! {note}")
        say("")
        say("Still to do by hand, in the panel:")
        if not start_enabled:
            say("  - TICK ENABLED on the war, once the one still running is over. Until you do,")
            say("    nothing of this scores at all. Everything else is already in place.")
        say("  - the war banner, and the hunt's banner, completion picture and stone picture")
        say("  - each crew's victory picture, which only ever plays on a win")
        say("  - the reward treasures, if you did not name them above")
        say("  - read the drawn treasures above and swap any that look wrong")
        if not APPLY:
            say("")
            say("Nothing was written. Run it again with APPLY=1 to keep all of this.")
            raise Rollback
        say("")
        say("Written.")
except Rollback:
    pass
