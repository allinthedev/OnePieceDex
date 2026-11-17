"""
Turning what players do into points for their crew.

This listens to the game event bus and writes a line per deed. A player with no crew scores
nothing, and so does any deed with no rule set for it — a war only counts what an admin has
said it counts, which is what stops a new event type quietly inflating everyone's score.
"""

import logging
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from ballsdex.core.game_events import Event, EventContext

from .models import CrewMembership, CrewWar, CrewWarEntry, CrewWarRule

log = logging.getLogger("ballsdex.crew_war")

SUBSCRIBER = "crew_war"

# the bus events this scores, and the rule they map to. Anything not here is ignored.
EVENT_SOURCES = {
    Event.BATTLE_PLAYED: CrewWarRule.Source.BATTLE_PLAYED,
    Event.BATTLE_WIN: CrewWarRule.Source.BATTLE_WIN,
    Event.BOSS_PLAYED: CrewWarRule.Source.BOSS_PLAYED,
    Event.BOSS_WIN: CrewWarRule.Source.BOSS_WIN,
}


async def score(player_id: int, source: str, *, war: CrewWar | None = None) -> int:
    """
    Give a player's crew the points one deed is worth. Returns what was actually added.

    Returns 0 when there is no war running, when the player has no crew, when the war has no
    rule for this deed, or when the player has already taken everything the daily cap allows.
    """
    war = war or await CrewWar.objects.filter(enabled=True).afirst()
    if war is None or not war.is_live():
        return 0
    membership = await CrewMembership.objects.filter(player_id=player_id).afirst()
    if membership is None:
        return 0
    rule = await CrewWarRule.objects.filter(war=war, source=source).afirst()
    if rule is None or not rule.points:
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
    source = EVENT_SOURCES.get(event)
    if source is None:
        return
    try:
        await score(player_id, source)
    except Exception:
        # a war that cannot be scored must never take a battle or a boss fight down with it
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
