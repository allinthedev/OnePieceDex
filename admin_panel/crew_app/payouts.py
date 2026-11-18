"""
Handing out the rewards of a crew war, exactly once per rung per player.

Every payout writes a `CrewWarPayout` row first, under a unique constraint on (rung, player), so
running the payout twice hands nothing over twice: the second run loses the insert and moves on.
The berries and the cards are given after that row exists and inside the same transaction, so a
failure takes the row with it rather than leaving a rung marked paid for nothing.

Everything here is synchronous, because it is driven from the admin panel: a war is paid out once,
by a person, after they have read the preview.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from currency_app.ledger import adjust_money
from currency_app.models import BerryTransaction
from django.db import IntegrityError, transaction
from django.db.models import Sum

from bd_models.models import BallInstance, frame_entry, mark_no_frame, wants_no_frame
from settings.models import settings
from settings.utils import format_currency

from .models import CrewMembership, CrewWar, CrewWarEntry, CrewWarPayout, CrewWarReward, CrewWarRewardCard

log = logging.getLogger("ballsdex.crew_war")


@dataclass
class Owed:
    """What one player has earned, before anything has been written."""

    player_id: int
    crew_id: int | None
    points: int
    rewards: list[CrewWarReward] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return ", ".join(reward.name for reward in self.rewards)


def crew_places(war: CrewWar) -> dict[int, int]:
    """
    Where each crew finished, by crew id.

    Crews on the same score share a place, so two crews tied at the top are both first and
    nobody is handed second place for a draw they did not lose.
    """
    rows = list(
        CrewWarEntry.objects.filter(war=war).values("crew_id").annotate(total=Sum("points")).order_by("-total")
    )
    places: dict[int, int] = {}
    place = 0
    previous = None
    for index, row in enumerate(rows, start=1):
        if row["total"] != previous:
            place, previous = index, row["total"]
        places[row["crew_id"]] = place
    return places


def ladder(rungs: list[CrewWarReward], points: int) -> list[CrewWarReward]:
    """
    The player rungs one score earns, highest first.

    `rungs` comes in highest-threshold first. Walking down stops at the first rung that does not
    stack: the player keeps that rung and nothing under it, which is what "cumulative with the
    rung below, or not" means on a ladder.
    """
    earned: list[CrewWarReward] = []
    for rung in rungs:
        if rung.threshold > points:
            continue
        earned.append(rung)
        if not rung.cumulative:
            break
    return earned


def plan(war: CrewWar) -> list[Owed]:
    """
    Who is owed what, writing nothing. Read by the preview and by the payout itself.

    A crew rung goes by the flag the player flies *now*, while the standings are worked out from
    the deeds themselves. That is deliberate: the points a player brought a crew stay that crew's,
    but the reward for winning goes to the people wearing the flag at the end.
    """
    rewards = list(war.rewards.prefetch_related("cards"))
    player_rungs = sorted(
        (reward for reward in rewards if not reward.is_crew_reward), key=lambda reward: reward.threshold, reverse=True
    )
    crew_rungs = [reward for reward in rewards if reward.is_crew_reward]
    if not rewards:
        return []

    totals = {
        row["player_id"]: row["total"] or 0
        for row in CrewWarEntry.objects.filter(war=war).values("player_id").annotate(total=Sum("points"))
    }
    flags = dict(CrewMembership.objects.filter(player_id__in=totals).values_list("player_id", "crew_id"))
    places = crew_places(war)

    found: list[Owed] = []
    for player_id, points in sorted(totals.items(), key=lambda item: (-item[1], item[0])):
        if points <= 0:
            continue
        crew_id = flags.get(player_id)
        earned = ladder(player_rungs, points)
        if crew_id is not None:
            place = places.get(crew_id)
            # a rung at place 0 is the "every crew that scored" rung, which is how a war thanks
            # everyone who turned up without naming a winner
            earned += [rung for rung in crew_rungs if rung.threshold == 0 or rung.threshold == place]
        if earned:
            found.append(Owed(player_id=player_id, crew_id=crew_id, points=points, rewards=earned))
    return found


def give_cards(card: CrewWarRewardCard, player_id: int) -> list[BallInstance]:
    """
    Create the copies one card line hands over.

    Bonuses are rolled like a catch rather than fixed at zero, so a war reward is a real card
    rather than a flat one.
    """
    # read straight off the row rather than through the cache: this runs in the panel, where
    # the treasure cache the bot fills is empty and a query is perfectly fine
    ball = card.ball
    no_frame = wants_no_frame(card.frame_key)
    frame = None if no_frame else frame_entry(ball, card.frame_key)
    if card.frame_key and not no_frame and frame is None:
        log.warning("crew war: the frame %s of %s does not exist, the card is given plain", card.frame_key, ball)
    created = []
    for _ in range(max(card.amount, 1)):
        instance = BallInstance(
            player_id=player_id,
            ball_id=ball.pk,
            special_id=card.special_id,
            attack_bonus=random.randint(-settings.max_attack_bonus, settings.max_attack_bonus),
            health_bonus=random.randint(-settings.max_health_bonus, settings.max_health_bonus),
            tradeable=card.tradeable,
            extra_data=dict(frame) if frame else {},
        )
        if no_frame:
            # without this the frames package would give it whatever frame runs today, like a catch
            mark_no_frame(instance)
        instance.save()
        created.append(instance)
    return created


def give(war: CrewWar, reward: CrewWarReward, owed: Owed) -> bool:
    """
    Hand one rung to one player. False when they already had it.
    """
    with transaction.atomic():
        try:
            row = CrewWarPayout.objects.create(
                reward=reward, player_id=owed.player_id, crew_id=owed.crew_id, points=owed.points
            )
        except IntegrityError:
            return False

        lines = []
        if reward.money:
            adjust_money(
                owed.player_id,
                reward.money,
                reason=BerryTransaction.Reason.CREW_WAR,
                description=f"{war.name}: {reward.name}"[: BerryTransaction.DESCRIPTION_MAX_LENGTH],
            )
            lines.append(format_currency(reward.money, False))
        for card in reward.cards.all():
            give_cards(card, owed.player_id)
            lines.append(card.label)

        row.summary = ", ".join(lines)[:256]
        row.save(update_fields=("summary",))
    return True


def hand_out(war: CrewWar) -> tuple[int, int, int]:
    """
    Pay out everything this war owes. Returns `(rungs paid, rungs already paid, players paid)`.

    Safe to run again: anything already handed over is counted as already paid and nothing is
    given twice, so a war whose standings are still settling can be paid out in passes.
    """
    paid = already = 0
    players = set()
    for owed in plan(war):
        for reward in owed.rewards:
            if give(war, reward, owed):
                paid += 1
                players.add(owed.player_id)
            else:
                already += 1
    log.info(
        f"Crew war {war.name}: handed out {paid} reward(s) to {len(players)} player(s), "
        f"{already} were already paid.",
        extra={"webhook": True},
    )
    return paid, already, len(players)
