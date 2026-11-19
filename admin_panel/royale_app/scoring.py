"""
Turning one end-of-match report into crew war points.

Nothing here knows about HTTP: `validate` takes the parsed body and says what is wrong with it,
`ingest` writes the match down and puts the deeds on the game event bus. That split is what lets
the whole path be exercised without a socket.

Why the bus rather than calling the crew war directly: a royale kill is a deed like a catch or a
trade, and every system that rewards deeds — the crew war today, the achievements and the event
pass tomorrow — should see it without this module knowing they exist.

Why five deeds are dispatched when only one is scored: an event nobody has written a rule for
costs a cached lookup and scores nothing (`crew_app.scoring.score` checks the rule before the
player). So sending all of them now means adding "a chest is worth 2" later is one row in the
admin panel, with no deploy on either bot. Sending only kills would have made it a deploy.

The same five again for a crew war raid, under events of their own: a kill in a war is a
different deed from a kill in an ordinary match, and a war has to be able to price it
differently. Which set a report raises is decided by its `mode` and by nothing else — the
report still carries no crew id, and this module still never decides who a deed counts for.
"""

import logging

from crew_app.models import CrewWarEntry, CrewWarRule
from django.db.models import Sum
from django.utils import timezone

from ballsdex.core.game_events import Event, EventContext, bus
from bd_models.models import Player

from .models import RoyaleMatch

log = logging.getLogger("ballsdex.royale_bridge")

# The report format this understands. A report announcing a higher version is still read for the
# fields below rather than refused: Royale is told to keep sending the facts it has, and a field
# this bot has never heard of is simply not scored.
VERSION = 1

# Royale caps a match at 40 pirates. These are not that cap — they are the point past which a
# body is provably not a real match, and a retry could never fix it.
#
# They are deliberately generous, because refusing a report is final: Royale drops it on a 400
# and the match is never scored. Kills are naturally bounded by the lobby, but chests and
# bounties are not bounded by anything, so a long match must not lose its points to a tight
# limit here. `MAX_DEEDS` is the real guard against a dispatch storm; the per-deed figure only
# catches a number that is obvious nonsense.
MAX_PLAYERS = 100
MAX_PER_DEED = 1000
MAX_DEEDS = 2000

# The counted fields of a player's line. The number in the field is how many times the deed
# happened, so three kills are three events and the war's daily cap can limit them one by one.
DEED_FIELDS = ("kills", "chests_opened", "bounties_claimed")

# The mode Royale stamps on a crew war raid. An ordinary match says "normal", and a co-op raid
# reports nothing at all.
WAR_MODE = "crewwar"

# What each mode raises on the bus. A crew war raid has five events of its own, so that a kill
# in a war can be priced differently from a kill in an ordinary match — which is the whole
# reason `mode` travels in the report at all.
#
# A mode this bot has never heard of raises nothing. The match is still written down, so the
# mistake shows up in the panel as a match worth zero rather than being quietly paid at
# ordinary rates: a report is only ever worth what an admin has said it is worth.
MODE_EVENTS = {
    "normal": {
        "played": Event.ROYALE_PLAYED,
        "win": Event.ROYALE_WIN,
        "kills": Event.ROYALE_KILL,
        "chests_opened": Event.ROYALE_CHEST,
        "bounties_claimed": Event.ROYALE_BOUNTY,
    },
    WAR_MODE: {
        "played": Event.ROYALE_WAR_PLAYED,
        "win": Event.ROYALE_WAR_WIN,
        "kills": Event.ROYALE_WAR_KILL,
        "chests_opened": Event.ROYALE_WAR_CHEST,
        "bounties_claimed": Event.ROYALE_WAR_BOUNTY,
    },
}

# the ledger lines a match can produce, read back after scoring to say what it actually gave
ROYALE_SOURCES = (
    CrewWarRule.Source.ROYALE_PLAYED,
    CrewWarRule.Source.ROYALE_WIN,
    CrewWarRule.Source.ROYALE_KILL,
    CrewWarRule.Source.ROYALE_CHEST,
    CrewWarRule.Source.ROYALE_BOUNTY,
    CrewWarRule.Source.ROYALE_WAR_PLAYED,
    CrewWarRule.Source.ROYALE_WAR_WIN,
    CrewWarRule.Source.ROYALE_WAR_KILL,
    CrewWarRule.Source.ROYALE_WAR_CHEST,
    CrewWarRule.Source.ROYALE_WAR_BOUNTY,
)


class ReportError(Exception):
    """A body that no retry could fix. The message is handed back to Royale in `error`."""


def _as_int(value, field: str, *, low: int = 0, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReportError(f"{field} must be a whole number, got {type(value).__name__}")
    if value < low or (high is not None and value > high):
        raise ReportError(f"{field} is out of range: {value}")
    return value


def validate(body) -> dict:
    """
    The report, checked. Raises `ReportError` with a reason a human can act on.

    Only what is actually read is checked. A field Royale sends that this bot does not score is
    carried into the stored report and otherwise left alone, so the two bots can drift a little
    without the bridge falling over.
    """
    if not isinstance(body, dict):
        raise ReportError("the body must be a JSON object")
    if "version" not in body:
        raise ReportError("no version")
    _as_int(body["version"], "version", low=1)

    match_id = body.get("match_id")
    if not isinstance(match_id, str) or not match_id.strip():
        raise ReportError("match_id must be a non-empty string")
    if len(match_id) > 128:
        raise ReportError(f"match_id is longer than 128 characters ({len(match_id)})")

    players = body.get("players")
    if not isinstance(players, list):
        raise ReportError("players must be a list")
    if len(players) > MAX_PLAYERS:
        raise ReportError(f"{len(players)} players is more than a match can hold")

    deeds = 0
    for index, line in enumerate(players):
        if not isinstance(line, dict):
            raise ReportError(f"players[{index}] is not an object")
        _as_int(line.get("discord_id"), f"players[{index}].discord_id", low=1)
        for field in DEED_FIELDS:
            if field in line:
                deeds += _as_int(line[field], f"players[{index}].{field}", low=0, high=MAX_PER_DEED)
    if deeds > MAX_DEEDS:
        raise ReportError(f"{deeds} deeds is more than a match can produce")

    return body


async def ingest(body: dict) -> tuple[RoyaleMatch, bool]:
    """
    Write the match down, then score it. Returns the row and whether this report was new.

    The row is written BEFORE anything is handed out, which is the whole of the idempotence: a
    report that arrives twice finds its row already there and scores nothing the second time. A
    crash in the middle therefore under-scores a match rather than paying it twice, which is the
    side to err on.
    """
    match_id = body["match_id"].strip()
    players = body.get("players") or []
    guild_id = body.get("guild_id")
    channel_id = body.get("channel_id")

    row, created = await RoyaleMatch.objects.aget_or_create(
        match_id=match_id,
        defaults={
            "guild_id": guild_id if isinstance(guild_id, int) else None,
            "channel_id": channel_id if isinstance(channel_id, int) else None,
            "mode": str(body.get("mode") or "")[:32],
            "island": str(body.get("island") or "")[:64],
            "rounds": body.get("rounds") if isinstance(body.get("rounds"), int) else 0,
            "players_reported": len(players),
            "kills_reported": sum(int(x.get("kills") or 0) for x in players),
            "report": body,
        },
    )
    if not created:
        log.info("royale bridge: %s had already been scored, nothing given again", match_id)
        return row, False

    events = MODE_EVENTS.get(row.mode)
    if events is None:
        log.warning(
            "royale bridge: %s arrived with mode %r, which raises nothing here — the match is "
            "written down and scores zero",
            match_id,
            row.mode,
        )

    since = timezone.now()
    known: list[int] = []
    for line in players:
        discord_id = line["discord_id"]
        player = await Player.objects.filter(discord_id=discord_id).afirst()
        if player is None:
            # Royale is only played on this bot's own server, so this should not happen — but a
            # Discord member who has never run a command here has no row, and that must not cost
            # the rest of the match its points.
            log.info("royale bridge: %s played %s but has never used this bot", discord_id, match_id)
            continue
        known.append(player.pk)
        if events is not None:
            await _dispatch_player(player, line, guild_id, channel_id, events)

    points = await CrewWarEntry.objects.filter(
        source__in=ROYALE_SOURCES,
        player_id__in=known,
        created_at__gte=since,
    ).aaggregate(total=Sum("points"))

    row.players_known = len(known)
    row.points_awarded = points["total"] or 0
    await row.asave(update_fields=("players_known", "points_awarded"))
    log.info(
        "royale bridge: %s scored — %s of %s players known, %s points",
        match_id,
        row.players_known,
        row.players_reported,
        row.points_awarded,
    )
    return row, True


async def _dispatch_player(player: Player, line: dict, guild_id, channel_id, events: dict) -> None:
    """Every deed one player's line carries, put on the bus, in this match's own events."""
    context = EventContext(server_id=guild_id if isinstance(guild_id, int) else None)
    where = channel_id if isinstance(channel_id, int) else None

    await bus.dispatch(player, events["played"], context=context, channel_id=where)
    # `is True` and not truthiness: the string "false" is truthy, and a win is worth points
    if line.get("winner") is True:
        await bus.dispatch(player, events["win"], context=context, channel_id=where)
    for field in DEED_FIELDS:
        event = events[field]
        for _ in range(int(line.get(field) or 0)):
            await bus.dispatch(player, event, context=context, channel_id=where)
