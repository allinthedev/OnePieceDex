"""
Opening a door: when it is allowed, what it costs, and what comes out.

The row saying a player opened a door is written **before** anything is handed out, so the unique constraint on
it is what stops a door being opened twice — two clicks in the same instant included. Everything after it runs
in the same transaction, so a door that fails halfway is a door that was never opened.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import timezone as dt_timezone

from currency_app.ledger import adjust_money
from currency_app.models import BerryTransaction
from django.db import IntegrityError, transaction
from django.utils import timezone
from eventpass_app.rewards import give_bundle

from .models import AdventCalendar, AdventOpening, AdventStreak, AdventStreakGrant, AdventSurprise, door_date

log = logging.getLogger("advent")


class Refused(Exception):
    """A door that cannot be opened, carrying the line to show the player."""


@dataclass
class StreakReached:
    streak: AdventStreak
    lines: list[str] = field(default_factory=list)


@dataclass
class Opened:
    """What came out of one door, for the command to tell the player about."""

    day: int
    paid: int = 0
    lines: list[str] = field(default_factory=list)
    message: str = ""
    surprise: AdventSurprise | None = None
    surprise_lines: list[str] = field(default_factory=list)
    boost: str = ""
    streaks: list[StreakReached] = field(default_factory=list)
    opened_total: int = 0

    @property
    def summary(self) -> str:
        return ", ".join(self.lines) or "nothing"


def today_utc(at=None):
    at = at or timezone.now()
    return at.astimezone(dt_timezone.utc).date()


def open_door(
    calendar_id: int, player_id: int, day: int, *, server_id: int | None = None, channel_id: int | None = None
) -> Opened:
    """
    Open one door for one player. Raises `Refused` with the reason when it cannot happen.

    A door whose day has gone by costs berries, and only while the calendar still allows catching up. A door
    whose day has not come yet cannot be opened at any price — that is the whole point of a calendar.
    """
    now = timezone.now()
    today = today_utc(now)

    with transaction.atomic():
        calendar = AdventCalendar.objects.select_related("event_pass").filter(pk=calendar_id, enabled=True).first()
        if calendar is None:
            raise Refused("That calendar is closed.")
        if not 1 <= day <= calendar.door_count:
            raise Refused(f"This calendar has doors 1 to {calendar.door_count}.")

        door = calendar.doors.select_related("reward").filter(day=day).first()
        if door is None:
            raise Refused(f"Door {day} has not been set up yet.")

        opens_on = door_date(calendar.starts_on, day)
        if today < opens_on:
            raise Refused(f"Door {day} opens on {opens_on:%d %B}. Not before.")
        late = today > opens_on

        if late:
            if not calendar.catch_up_price:
                raise Refused(f"Door {day} is gone, and this calendar has no catching up.")
            if now > calendar.closes_at:
                raise Refused("It is too late to catch up on this calendar.")

        # the row first: whoever writes it owns the door, and the rest of this block is theirs alone
        try:
            opening = AdventOpening.objects.create(
                calendar=calendar, player_id=player_id, day=day, paid=calendar.catch_up_price if late else 0
            )
        except IntegrityError as error:
            raise Refused(f"You have already opened door {day}.") from error

        result = Opened(day=day, paid=calendar.catch_up_price if late else 0, message=door.message)

        if late:
            try:
                adjust_money(
                    player_id,
                    -calendar.catch_up_price,
                    reason=BerryTransaction.Reason.ADVENT_CATCH_UP,
                    description=f"{calendar.name}: door {day}"[: BerryTransaction.DESCRIPTION_MAX_LENGTH],
                )
            except ValueError as error:
                raise Refused(
                    f"Opening door {day} late costs {calendar.catch_up_price:,} berries, and you do not have them."
                ) from error

        if door.reward is not None:
            given = give_bundle(player_id, calendar.event_pass, door.reward, server_id=server_id, channel_id=channel_id)
            result.lines.extend(given.lines)

        _roll_surprise(result, calendar, player_id, server_id, channel_id)
        result.opened_total = AdventOpening.objects.filter(calendar=calendar, player_id=player_id).count()
        _award_streaks(result, calendar, player_id, server_id, channel_id)

        opening.summary = result.summary[:256]
        opening.surprise = result.surprise
        opening.save(update_fields=("summary", "surprise"))

    return result


def _roll_surprise(
    result: Opened, calendar: AdventCalendar, player_id: int, server_id: int | None, channel_id: int | None
) -> None:
    """
    Maybe fire a surprise on top of the door. It never replaces what the door gave.

    A surprise set to fire once per player is left out of the draw once they have had it, rather than drawn and
    thrown away — otherwise the chance of getting anything would quietly fall as a player collects them.
    """
    if not calendar.surprise_chance or random.random() >= calendar.surprise_chance:
        return
    had = set(
        AdventOpening.objects.filter(calendar=calendar, player_id=player_id, surprise__isnull=False).values_list(
            "surprise_id", flat=True
        )
    )
    pool = [
        surprise
        for surprise in calendar.surprises.select_related("reward", "boost").filter(enabled=True)
        if surprise.weight > 0 and not (surprise.once_per_player and surprise.pk in had)
    ]
    if not pool:
        return
    surprise = random.choices(pool, weights=[item.weight for item in pool], k=1)[0]
    result.surprise = surprise

    if surprise.reward is not None:
        given = give_bundle(player_id, calendar.event_pass, surprise.reward, server_id=server_id, channel_id=channel_id)
        result.surprise_lines.extend(given.lines)
    if surprise.boost is not None and surprise.boost.enabled:
        # the same path a purchase takes, so an hour already running is extended rather than doubled
        from eventshop_app.boosts import buy_or_extend

        running = buy_or_extend(surprise.boost, player_id, label=surprise.boost.name)
        result.boost = surprise.boost.label
        log.info("advent surprise %s started boost %s", surprise.pk, running.pk)


def _award_streaks(
    result: Opened, calendar: AdventCalendar, player_id: int, server_id: int | None, channel_id: int | None
) -> None:
    """
    Hand over every streak reward this opening has just reached.

    Counted on doors opened, so a player who paid to catch up has caught up. A grant row per streak is what
    stops the same milestone paying twice, which matters because the count is recomputed on every opening.
    """
    reached = calendar.streaks.select_related("reward").filter(doors__lte=result.opened_total).order_by("doors")
    for streak in reached:
        try:
            # its own savepoint: an IntegrityError inside the outer transaction would otherwise poison it, and
            # the next query of this loop would fail rather than simply skipping a milestone already given
            with transaction.atomic():
                grant = AdventStreakGrant.objects.create(streak=streak, player_id=player_id)
        except IntegrityError:
            continue  # already had it
        given = give_bundle(player_id, calendar.event_pass, streak.reward, server_id=server_id, channel_id=channel_id)
        grant.summary = (", ".join(given.lines) or "nothing")[:256]
        grant.save(update_fields=("summary",))
        result.streaks.append(StreakReached(streak=streak, lines=given.lines))


def state_of(calendar_id: int, player_id: int) -> tuple[AdventCalendar | None, set[int], int]:
    """
    The calendar, the days this player has opened, and which door today is. For the grid and the status line.
    """
    calendar = AdventCalendar.objects.select_related("event_pass").filter(pk=calendar_id).first()
    if calendar is None:
        return None, set(), 0
    opened = set(AdventOpening.objects.filter(calendar=calendar, player_id=player_id).values_list("day", flat=True))
    return calendar, opened, calendar.day_today() or 0
