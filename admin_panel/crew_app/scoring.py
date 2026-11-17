"""
Turning what players do into points for their crew.

This listens to the game event bus and writes a line per deed. A player with no crew scores
nothing, and so does any deed with no rule set for it — a war only counts what an admin has
said it counts, which is what stops a new event type quietly inflating everyone's score.
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Sum
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


async def live_war() -> "tuple[CrewWar, dict[str, CrewWarRule]] | None":
    """The war being scored right now and its rules by source, or None when none is running."""
    cached = cache.get(_CACHE_KEY)
    if cached is None:
        war = await CrewWar.objects.filter(enabled=True).afirst()
        rules = {}
        if war is not None:
            rules = {rule.source: rule async for rule in CrewWarRule.objects.filter(war=war)}
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
    rule = rules.get(source)
    if rule is None or not rule.points:
        return 0
    if rule.minimum_value and berries_moved(context) < rule.minimum_value:
        return 0
    membership = await CrewMembership.objects.filter(player_id=player_id).afirst()
    if membership is None:
        return 0

    if rule.daily_cap:
        since = timezone.now() - timedelta(days=1)
        taken = await CrewWarEntry.objects.filter(
            war=war, player_id=player_id, source=source, created_at__gte=since
        ).aaggregate(total=Sum("points"))
        if (taken["total"] or 0) >= rule.daily_cap:
            return 0

    await CrewWarEntry.objects.acreate(
        war=war, crew_id=membership.crew_id, player_id=player_id, source=source, points=rule.points
    )
    log.debug("crew war: %s scored %s for %s", player_id, rule.points, source)
    return rule.points


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
