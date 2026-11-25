"""
Putting a card in the sleigh, and getting cards back out of it.

A gift is irreversible, so everything that could refuse it is checked before the card is touched, and the whole
move — the giver's card consumed, the sleigh's card written — happens in one transaction. The crew points are
written afterwards, into the war's own ledger: a war that is not running simply scores nothing, which must never
be a reason the gift itself falls over.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from asgiref.sync import sync_to_async
from crew_app.models import Crew, CrewMembership, CrewWarRule
from crew_app.scoring import award, live_war
from django.db import transaction
from django.utils import timezone

from bd_models.models import BallInstance, mark_no_frame

from .models import Sleigh, SleighCard

log = logging.getLogger("sleigh")

# how long a card stays locked by a trade before the lock is treated as stale, as the trade package does
TRADE_LOCK = timedelta(minutes=30)


class Refused(Exception):
    """A gift that cannot be made, carrying the line to show the player."""


@dataclass
class Given:
    """What came of one gift, for the command to tell the player and the server about."""

    card: SleighCard
    points: int = 0
    crew_label: str = ""
    # every gift ever given to this sleigh, which is what fills it — not what is still sitting in it
    total: int = 0
    today: int = 0
    filled: bool = False


def start_of_day(at=None) -> datetime:
    """Midnight UTC of the day `at` falls in — where a player's daily allowance turns over."""
    at = (at or timezone.now()).astimezone(dt_timezone.utc)
    return datetime(at.year, at.month, at.day, tzinfo=dt_timezone.utc)


def _put_in(sleigh_id: int, player_id: int, instance_pk: int) -> tuple[SleighCard, Sleigh, int, int]:
    """
    Consume the player's card and write the sleigh's. Returns (card, sleigh, gifts in all, given today).

    The instance is locked for the duration, so the same card cannot be given twice by two clicks at once: the
    second one finds it already deleted.
    """
    now = timezone.now()
    with transaction.atomic():
        sleigh = Sleigh.objects.select_related("special").filter(pk=sleigh_id).first()
        if sleigh is None or not sleigh.is_open(now):
            raise Refused("The sleigh is closed.")

        instance = (
            BallInstance.objects.select_for_update()
            .select_related("ball")
            .filter(pk=instance_pk, player_id=player_id, deleted=False)
            .first()
        )
        if instance is None:
            raise Refused("That card is not yours, or it is already gone.")
        if instance.special_id is not None:
            raise Refused(
                "A card that already carries a special cannot go in the sleigh. A framed one can — the frame "
                "comes along with it."
            )
        if not instance.tradeable or not instance.ball.tradeable:
            raise Refused("That card cannot be given away.")
        if instance.favorite:
            raise Refused(
                "That one is one of your favourites. Unfavourite it first: a card in the sleigh never comes back."
            )
        if instance.locked and instance.locked > now - TRADE_LOCK:
            raise Refused("That card is locked in a trade right now.")

        today = SleighCard.objects.filter(sleigh=sleigh, given_by_id=player_id, given_at__gte=start_of_day(now)).count()
        if today >= sleigh.per_day:
            word = "card" if sleigh.per_day == 1 else "cards"
            raise Refused(
                f"You have already put your {word} in today. The sleigh takes {sleigh.per_day} a day, and the "
                f"day turns over at midnight UTC."
            )

        crew_id = CrewMembership.objects.filter(player_id=player_id).values_list("crew_id", flat=True).first()
        rarity = instance.ball.rarity
        card = SleighCard.objects.create(
            sleigh=sleigh,
            ball_id=instance.ball_id,
            given_by_id=player_id,
            crew_id=crew_id,
            attack_bonus=instance.attack_bonus,
            health_bonus=instance.health_bonus,
            frame=dict(instance.extra_data) if isinstance(instance.extra_data, dict) else {},
            rarity=rarity,
            points=0,
        )
        # consumed the way the rest of the dex consumes a card, and unfavourited so it cannot haunt a filter
        BallInstance.objects.filter(pk=instance.pk).update(deleted=True, favorite=False)
        total = SleighCard.objects.filter(sleigh=sleigh).count()
    return card, sleigh, total, today + 1


async def give(sleigh_id: int, player_id: int, instance_pk: int) -> Given:
    """
    Put one of a player's cards in the sleigh and score it for their crew.

    Raises `Refused` with the reason when the gift cannot be made. Once it has been made it is final, so the
    points are the only part that can quietly come to nothing — when no war is running, or the giver has no crew.
    """
    card, sleigh, total, today = await sync_to_async(_put_in)(sleigh_id, player_id, instance_pk)
    result = Given(card=card, total=total, today=today, filled=bool(sleigh.goal) and total >= sleigh.goal)

    if card.crew_id is None:
        return result
    worth = sleigh.points_for(card.rarity)
    try:
        live = await live_war()
        if live is None:
            return result
        war, _ = live
        await award(
            war,
            player_id,
            card.crew_id,
            worth,
            note=f"Sleigh: {card.cached_ball.country}",
            source=CrewWarRule.Source.SLEIGH_GIFT,
        )
    except Exception:
        log.exception("sleigh: could not score the gift of card %s", card.pk)
        return result

    card.points = worth
    await card.asave(update_fields=("points",))
    result.points = worth
    crew = await Crew.objects.filter(pk=card.crew_id).afirst()
    result.crew_label = crew.label if crew else ""
    return result


def _take_out(sleigh_id: int, count: int) -> list[SleighCard]:
    """
    Claim `count` cards at random out of the sleigh, marking them taken so nothing can take them twice.

    Marked released here rather than by the caller: whoever wins the update owns the card, which is what keeps
    two overlapping waves from spawning the same gift.
    """
    taken: list[SleighCard] = []
    with transaction.atomic():
        inside = list(
            SleighCard.objects.select_for_update()
            .filter(sleigh_id=sleigh_id, released_at__isnull=True, claimed_by__isnull=True)
            .order_by("?")[: max(count, 0)]
        )
        now = timezone.now()
        for card in inside:
            if SleighCard.objects.filter(pk=card.pk, released_at__isnull=True, claimed_by__isnull=True).update(
                released_at=now
            ):
                card.released_at = now
                taken.append(card)
    return taken


async def release(sleigh_id: int, count: int) -> list[SleighCard]:
    """Take cards out to be spawned for anyone to catch. The caller does the spawning."""
    return await sync_to_async(_take_out)(sleigh_id, count)


def _hand_over(sleigh_id: int, count: int, to_player_id: int, server_id: int | None) -> list[SleighCard]:
    """
    Give `count` random cards out of the sleigh straight to one player, as the cards they were.

    The frame and the bonuses come back exactly as they went in, and a card that went in plain stays plain — the
    frames package would otherwise dress it in whatever frame runs today, which is not the card anyone gave.
    """
    given: list[SleighCard] = []
    with transaction.atomic():
        sleigh = Sleigh.objects.select_related("special").filter(pk=sleigh_id).first()
        if sleigh is None:
            raise Refused("That sleigh is gone.")
        inside = list(
            SleighCard.objects.select_for_update()
            .filter(sleigh_id=sleigh_id, released_at__isnull=True, claimed_by__isnull=True)
            .order_by("?")[: max(count, 0)]
        )
        now = timezone.now()
        for card in inside:
            if not SleighCard.objects.filter(pk=card.pk, released_at__isnull=True, claimed_by__isnull=True).update(
                claimed_by_id=to_player_id, claimed_at=now
            ):
                continue
            instance = BallInstance(
                player_id=to_player_id,
                ball_id=card.ball_id,
                special_id=sleigh.special_id,
                attack_bonus=card.attack_bonus,
                health_bonus=card.health_bonus,
                tradeable=True,
                server_id=server_id,
                extra_data=dict(card.frame) if isinstance(card.frame, dict) else {},
            )
            if not instance.extra_data:
                mark_no_frame(instance)
            instance.save()
            SleighCard.objects.filter(pk=card.pk).update(claimed_instance=instance)
            card.claimed_by_id = to_player_id
            card.claimed_at = now
            card.claimed_instance = instance
            given.append(card)
    return given


async def hand_over(sleigh_id: int, count: int, to_player_id: int, *, server_id: int | None = None) -> list[SleighCard]:
    """Hand random cards from the sleigh to one player — a King of the Seas prize, a war reward."""
    return await sync_to_async(_hand_over)(sleigh_id, count, to_player_id, server_id)
