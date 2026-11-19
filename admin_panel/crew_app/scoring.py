"""
Turning what players do into points for their crew.

This listens to the game event bus and writes a line per deed. A player with no crew scores
nothing, and so does any deed with no rule set for it — a war only counts what an admin has
said it counts, which is what stops a new event type quietly inflating everyone's score.
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Q, Sum
from django.utils import timezone

from ballsdex.core.game_events import Event, EventContext

from .models import CrewMembership, CrewWar, CrewWarEntry, CrewWarRule

log = logging.getLogger("ballsdex.crew_war")

SUBSCRIBER = "crew_war"

Source = CrewWarRule.Source

# the bus events this scores, and the rule they map to. Anything not here is ignored, which is
# why a new event type cannot quietly start handing out points.
EVENT_SOURCES = {
    Event.BATTLE_PLAYED: Source.BATTLE_PLAYED,
    Event.BATTLE_WIN: Source.BATTLE_WIN,
    Event.BOSS_PLAYED: Source.BOSS_PLAYED,
    Event.BOSS_WIN: Source.BOSS_WIN,
    Event.CATCH: Source.CATCH,
    Event.CRAFT: Source.CRAFT,
    Event.TRADE: Source.TRADE,
    Event.GIFT: Source.GIFT,
    Event.FRIEND: Source.FRIEND,
    Event.AUCTION_CREATE: Source.AUCTION_CREATE,
    Event.AUCTION_BID: Source.AUCTION_BID,
    Event.AUCTION_WON: Source.AUCTION_WON,
    Event.SELL: Source.SELL,
    Event.SHOP_BUY: Source.SHOP_BUY,
    Event.PACK_BUY: Source.PACK_BUY,
    Event.MERCHANT_BUY: Source.MERCHANT_BUY,
    Event.CURRENCY_STREAK: Source.DAILY_BERRIES,
    Event.PACK_STREAK: Source.DAILY_PACK,
    Event.PACK_WEEKLY: Source.WEEKLY_PACK,
    Event.ACTIVITY: Source.PLAYED,
    # a command another system has asked about is dispatched as COMMAND and never as
    # ACTIVITY, so both have to map here or 'played' would miss the busiest commands
    Event.COMMAND: Source.PLAYED,
}

# the rules of a war change rarely and are read on every catch, sale and bid, so they are held
# briefly rather than queried each time. Short enough that an admin changing a war sees it.
_CACHE_SECONDS = 30
_CACHE_KEY = "crew_war_live"


def invalidate():
    """Forget the cached war, so the next deed scored reads the rules afresh."""
    cache.delete(_CACHE_KEY)


async def live_war() -> "tuple[CrewWar, dict[str, list[CrewWarRule]]] | None":
    """
    The war being scored right now and its rules by source, or None when none is running.

    A source can hold several rules: one naming nothing, and one per treasure, special or
    collector named. They are kept most-specific first, which is all `matching_rule` needs to
    pick the right one.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is None:
        war = await CrewWar.objects.filter(enabled=True).afirst()
        rules: dict[str, list[CrewWarRule]] = {}
        if war is not None:
            query = CrewWarRule.objects.filter(war=war).select_related("ball", "special", "collector", "tier_level")
            async for rule in query:
                rules.setdefault(rule.source, []).append(rule)
            for found in rules.values():
                found.sort(key=lambda rule: (-rule.named, -rule.points))
        cached = (war, rules)
        cache.set(_CACHE_KEY, cached, _CACHE_SECONDS)
    war, rules = cached
    # checked outside the cache so a war reaching its end stops scoring on time rather than
    # up to half a minute late
    if war is None or not war.is_live():
        return None
    return war, rules


def berries_moved(context: EventContext | None) -> int:
    """
    What a deed was worth in berries, for the rules that ask for a minimum.

    Different events put the figure in different places — a sale fills `price`, a berry movement
    fills `amount`, a gift fills `received_currency` — and none of them fills more than one, so
    the largest is the one that was set.
    """
    if context is None:
        return 0
    return max(context.price, abs(context.amount), context.received_currency)


def matching_rule(
    rules: "dict[str, list[CrewWarRule]]", source: str, context: EventContext | None
) -> "CrewWarRule | None":
    """
    The one rule that pays for this deed, or None when the war does not pay for it.

    The rules of a source are sorted most-specific first, so the first one that matches is the
    one that names the most, and only it scores. A war saying "a catch is worth 1" and "a catch
    of Luffy is worth 50" therefore pays 50 for a Luffy, not 51.
    """
    for rule in rules.get(source, ()):
        if rule.points and rule.matches(context):
            return rule
    return None


def sources_for(event: Event, context: EventContext) -> tuple[str, ...]:
    """
    The deeds one event counts as. Usually one, and never any for an event nobody scores.

    A special treasure is the exception: catching one is a catch like any other and also a catch
    of a special, so a war can pay for the second without paying twice for every spawn.
    """
    source = EVENT_SOURCES.get(event)
    if source is None:
        return ()
    if source == Source.CATCH and any(getattr(x, "special_id", None) for x in context.instances):
        return (source, Source.CATCH_SPECIAL)
    return (source,)


async def score(player_id: int, source: str, *, context: EventContext | None = None) -> int:
    """
    Give a player's crew the points one deed is worth. Returns what was actually added.

    Returns 0 when there is no war running, when the war has no rule for this deed, when the
    deed is worth fewer berries than the rule asks for, when the player has no crew, or when
    they have already taken everything the daily cap allows.

    The rule is checked before the player, because most deeds a dex produces have no rule and
    that way they cost nothing but a dictionary lookup.
    """
    live = await live_war()
    if live is None:
        return 0
    war, rules = live
    rule = matching_rule(rules, source, context)
    if rule is None:
        return 0
    if rule.minimum_value and berries_moved(context) < rule.minimum_value:
        return 0
    membership = await CrewMembership.objects.filter(player_id=player_id).afirst()
    if membership is None:
        return 0

    if rule.daily_cap and await taken_today(war, player_id, rule) >= rule.daily_cap:
        return 0

    await CrewWarEntry.objects.acreate(
        war=war,
        crew_id=membership.crew_id,
        player_id=player_id,
        source=source,
        rule=rule,
        points=rule.points,
    )
    log.debug("crew war: %s scored %s for %s", player_id, rule.points, source)
    return rule.points


async def taken_today(war: CrewWar, player_id: int, rule: CrewWarRule) -> int:
    """
    What this player has already taken from this rule in the last day, for the daily cap.

    Counted per rule rather than per source, so a rule naming one treasure gets its own
    allowance instead of eating the generic one's.
    """
    since = timezone.now() - timedelta(days=1)
    rows = CrewWarEntry.objects.filter(war=war, player_id=player_id, created_at__gte=since)
    if rule.is_targeted:
        rows = rows.filter(rule=rule)
    else:
        # deeds scored before rules could name a treasure carry their source and no rule, and
        # they are the generic rule's own history
        rows = rows.filter(Q(rule=rule) | Q(rule__isnull=True, source=rule.source))
    taken = await rows.aaggregate(total=Sum("points"))
    return taken["total"] or 0


async def award(war: CrewWar, player_id: int, crew_id: int, points: int, *, note: str = "") -> CrewWarEntry:
    """
    Write points no rule paid for: a tournament the staff ran, a King of the Seas, an apology.

    Kept with the rest of the ledger rather than in the command that calls it, so a line given
    by hand looks exactly like one the bus scored - same war, same crew, same table.
    """
    entry = await CrewWarEntry.objects.acreate(
        war=war,
        crew_id=crew_id,
        player_id=player_id,
        source=Source.MANUAL,
        points=points,
        note=note[:128],
    )
    log.info("crew war: %s given %s points by hand (%s)", player_id, points, note or "no reason")
    return entry


async def score_quietly(player_id: int, source: str) -> int:
    """
    `score`, but a failure is logged rather than raised.

    For the deeds scored straight from the code that performs them — a bounty, a poneglyph —
    where the war must never be the reason a catch or a claim falls over.
    """
    try:
        return await score(player_id, source)
    except Exception:
        log.exception("crew war: could not score %s for player %s", source, player_id)
        return 0


async def handle_event(player_id: int, event: Event, context: EventContext, channel_id: int | None):
    """Subscriber of the game event bus."""
    for source in sources_for(event, context):
        try:
            await score(player_id, source, context=context)
        except Exception:
            # a war that cannot be scored must never take a catch or a battle down with it
            log.exception("crew war: could not score %s for player %s", event, player_id)


async def standings(war: CrewWar) -> list[tuple[int, int]]:
    """`(crew id, points)` for every crew with a score, best first."""
    rows = (
        CrewWarEntry.objects.filter(war=war)
        .values("crew_id")
        .annotate(total=Sum("points"))
        .order_by("-total", "crew_id")
    )
    return [(row["crew_id"], row["total"]) async for row in rows]


async def top_players(war: CrewWar, limit: int = 10) -> list[tuple[int, int]]:
    """`(player id, points)` for the biggest contributors of the war, best first."""
    rows = (
        CrewWarEntry.objects.filter(war=war)
        .values("player_id")
        .annotate(total=Sum("points"))
        .order_by("-total", "player_id")[:limit]
    )
    return [(row["player_id"], row["total"]) async for row in rows]


def _entries(war: CrewWar, crew_id: int | None = None):
    """
    The deeds counted for a table.

    A crew is filtered on the deed's own crew, not on who the player flies with now: points
    brought to a crew stay that crew's, which is the only reading that makes switching sides
    anything other than a way to move a score around.
    """
    rows = CrewWarEntry.objects.filter(war=war)
    return rows.filter(crew_id=crew_id) if crew_id is not None else rows


async def discord_ranking(war: CrewWar, *, crew_id: int | None = None, limit: int = 0) -> list[tuple[int, int]]:
    """`(discord id, points)`, best first — the shape the shared leaderboard takes."""
    rows = (
        _entries(war, crew_id)
        .values("player__discord_id")
        .annotate(total=Sum("points"))
        .order_by("-total", "player__discord_id")
    )
    if limit:
        rows = rows[:limit]
    return [(row["player__discord_id"], row["total"]) async for row in rows]


async def player_points(war: CrewWar, player_id: int) -> int:
    """What one player has brought to this war, across every crew they have flown for."""
    total = await _entries(war).filter(player_id=player_id).aaggregate(total=Sum("points"))
    return total["total"] or 0


async def place_of(war: CrewWar, points: int, *, crew_id: int | None = None) -> int:
    """
    Where a score sits in a table: one more than the number of players above it.

    Ties therefore share a place, which is what a player expects of a leaderboard — two players
    on 300 points are both second, and nobody is arbitrarily third.
    """
    above = _entries(war, crew_id).values("player_id").annotate(total=Sum("points")).filter(total__gt=points)
    return await above.acount() + 1


async def players_scored(war: CrewWar, *, crew_id: int | None = None) -> int:
    """How many players have scored at all, for "12th of 60"."""
    return await _entries(war, crew_id).values("player_id").distinct().acount()


async def last_gain(war: CrewWar, player_id: int) -> CrewWarEntry | None:
    """The most recent deed this player was paid for, loaded ready to be named."""
    return (
        await _entries(war)
        .filter(player_id=player_id)
        .select_related("rule", "rule__ball", "rule__special", "rule__collector", "rule__tier_level")
        .order_by("-created_at")
        .afirst()
    )


def name_of(entry: CrewWarEntry) -> str:
    """
    What a scored deed was, in words.

    Reads the rule only when it was already loaded — `last_gain` brings it along — so this never
    turns into a query from async code. Deeds scored before rules could name a treasure carry no
    rule at all, and there the source stands in.
    """
    rule = entry._state.fields_cache.get("rule")
    if rule is not None:
        return rule.label
    # a line given by hand has no rule and carries its own reason instead
    return entry.note or entry.get_source_display()
