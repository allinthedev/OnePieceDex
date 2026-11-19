"""
Telling Grand Line Royale who flies which flag.

The other direction of the bridge. Royale needs this for one rule only — you may not strike
someone of your own crew — and it asks once, when a match starts.

Two things keep this from becoming a second source of truth. Royale asks about **the players in
its lobby**, never for the whole table, so nothing more than it needs ever leaves. And it holds
the answer for the length of one match and never writes it down, so there is no copy here to
drift from the real one. Crew membership stays what `crew_app` says it is.

A player with no crew, and a player this bot has never seen, both come back as `null`: Royale
treats either the same way — a faction of one, scoring nothing — so there is nothing for it to
do with the difference.
"""

import logging

from crew_app.models import CrewMembership

log = logging.getLogger("ballsdex.royale_bridge")

# A Royale lobby holds at most 40. This is the point past which the question is not a lobby's.
MAX_LOOKUP = 200


class LookupError_(Exception):
    """A request no retry could fix. The message goes back to Royale in `error`."""


def validate_lookup(body) -> list[int]:
    """The discord ids asked about, checked. Raises `LookupError_` with a reason."""
    if not isinstance(body, dict):
        raise LookupError_("the body must be a JSON object")
    ids = body.get("discord_ids")
    if not isinstance(ids, list):
        raise LookupError_("discord_ids must be a list")
    if not ids:
        raise LookupError_("discord_ids is empty")
    if len(ids) > MAX_LOOKUP:
        raise LookupError_(f"{len(ids)} ids is more than a lobby can hold")
    found = []
    for index, value in enumerate(ids):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise LookupError_(f"discord_ids[{index}] is not a discord id")
        found.append(value)
    return found


async def crews_of(discord_ids: list[int]) -> dict[str, dict | None]:
    """
    `{"<discord id>": {"crew_id", "name", "emoji", "label"} or None}`, one key per id asked.

    Keyed by the id as a string because that is what it will be once this has been through JSON,
    and a caller matching on the number it sent would otherwise miss every one of them.

    One query, with the crew brought along: a lobby of forty must not become forty round trips.
    """
    rows = CrewMembership.objects.filter(player__discord_id__in=discord_ids).select_related("crew", "player")
    by_id: dict[str, dict | None] = {str(x): None for x in discord_ids}
    async for row in rows:
        crew = row.crew
        by_id[str(row.player.discord_id)] = {
            "crew_id": crew.pk,
            "name": crew.name,
            "emoji": crew.emoji,
            "label": crew.label,
        }
    return by_id
