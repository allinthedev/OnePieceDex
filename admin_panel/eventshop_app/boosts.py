"""
What the running boosts add up to, in a form the spawn and the catch can read without a query.

A spawn rolls a treasure and a catch rolls a special on the hot path: a database round trip there would show up
as lag on every single spawn, in every server. So the live boosts are folded into one small snapshot, refreshed
by the shop cog every half minute, and read straight out of memory — by code that is not even async.

Nothing here applies anywhere but the main server. A boost is bought from any server and always lands on the
main one, so every reader passes the server it is spawning or catching in and gets nothing back elsewhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from settings.models import settings

from .models import ActiveBoost, Boost, BoostKind

log = logging.getLogger("eventshop.boosts")

# the rarity weighting is never flattened past this: an exponent of 0 would draw every treasure equally, which
# hands out the rarest cards in the dex like commons
MIN_EXPONENT = 0.05


@dataclass(frozen=True)
class Boosts:
    """Everything in force at one moment, already reduced to the numbers the rolls need."""

    rarity_exponent: float = 1.0
    berry_factor: float = 1.0
    special_factor: float = 1.0
    special_factors: dict[int, float] = field(default_factory=dict)
    until: dict[str, object] = field(default_factory=dict)

    @property
    def anything(self) -> bool:
        return bool(
            self.rarity_exponent != 1.0
            or self.berry_factor != 1.0
            or self.special_factor != 1.0
            or self.special_factors
        )

    def special_weight(self, special_id: int | None) -> float:
        """
        How much the chance of this special is multiplied by: its own boost, then the one on every special.
        """
        if special_id is None:
            return 1.0
        return self.special_factors.get(special_id, 1.0) * self.special_factor


NONE = Boosts()
_current: Boosts = NONE


def current(guild_id: int | None) -> Boosts:
    """
    The boosts in force in this server: the live ones on the main server, nothing anywhere else.

    A caller that does not know which server it is in gets nothing, which is the safe way round: an admin
    spawning a card by hand is not meant to be riding somebody's paid hour.
    """
    if not guild_id or not settings.main_server_id or guild_id != settings.main_server_id:
        return NONE
    return _current


def snapshot() -> Boosts:
    """What the last refresh found, whatever server it applies to. For the shop and the admin pages."""
    return _current


async def refresh() -> Boosts:
    """Rebuild the snapshot from the rows that are still running. Called by the shop cog on a loop."""
    global _current
    now = timezone.now()
    rarity_exponent = 1.0
    berry_factor = 1.0
    special_factor = 1.0
    special_factors: dict[int, float] = {}
    until: dict[str, object] = {}

    running = ActiveBoost.objects.filter(ends_at__gt=now, started_at__lte=now).exclude(kind=BoostKind.SPAWN_PARTY)
    async for boost in running:
        share = max(boost.magnitude, 0.0) / 100
        if boost.kind == BoostKind.RARITY:
            # the strongest flattening wins rather than compounding: two hours bought at once should not
            # quietly turn into a flat dex
            rarity_exponent = min(rarity_exponent, max(1.0 - share, MIN_EXPONENT))
        elif boost.kind == BoostKind.BERRIES:
            berry_factor *= 1.0 + share
        elif boost.kind == BoostKind.SPECIAL:
            if boost.special_id:
                special_factors[boost.special_id] = special_factors.get(boost.special_id, 1.0) * (1.0 + share)
            else:
                special_factor *= 1.0 + share
        else:
            continue
        kept = until.get(boost.kind)
        if kept is None or boost.ends_at > kept:  # type: ignore[operator]
            until[boost.kind] = boost.ends_at

    _current = Boosts(
        rarity_exponent=rarity_exponent,
        berry_factor=berry_factor,
        special_factor=special_factor,
        special_factors=special_factors,
        until=until,
    )
    return _current


def flatten(weights: list[float], exponent: float) -> list[float]:
    """
    The spawn weights, flattened by `exponent`.

    A lower rarity is a rarer treasure, so rarity is the weight: raising every weight to a power below 1 pulls
    them together and the rare end of the dex gains. An exponent of 1 hands the weights straight back, which is
    what every server but a boosted one gets. Mirrors `rarity_flatten` on a pack, on purpose.
    """
    if exponent >= 1.0:
        return weights
    return [weight**exponent if weight > 0 else weight for weight in weights]


def buy_or_extend(boost: Boost, player_id: int | None = None, *, label: str = "") -> ActiveBoost:
    """
    Put a boost in force, or add its time to the one of its kind already running.

    Extending keeps the longer end and the stronger magnitude, so buying a small hour on top of a big one never
    makes the big one worse. A burst of spawns is not a duration: it always makes its own row, which the cog
    then works through.
    """
    now = timezone.now()
    if boost.kind == BoostKind.SPAWN_PARTY:
        return ActiveBoost.objects.create(
            boost=boost,
            kind=boost.kind,
            magnitude=boost.magnitude,
            label=label or boost.name,
            started_at=now,
            # the window the burst has to go out in, not an effect anyone feels
            ends_at=now + timedelta(minutes=max(boost.duration_minutes, 15)),
            spawns_left=boost.spawns,
            channel_id=boost.channel_id,
            bought_by_id=player_id,
        )

    with transaction.atomic():
        running = (
            ActiveBoost.objects.select_for_update()
            .filter(kind=boost.kind, special_id=boost.special_id, ends_at__gt=now)
            .order_by("-ends_at")
            .first()
        )
        if running is not None:
            running.ends_at = running.ends_at + boost.duration
            running.magnitude = max(running.magnitude, boost.magnitude)
            running.save(update_fields=("ends_at", "magnitude"))
            return running
        return ActiveBoost.objects.create(
            boost=boost,
            kind=boost.kind,
            magnitude=boost.magnitude,
            special_id=boost.special_id,
            label=label or boost.name,
            started_at=now,
            ends_at=now + boost.duration,
            channel_id=boost.channel_id,
            bought_by_id=player_id,
        )


def describe(kind: str, magnitude: float, spawns: int) -> str:
    """One line saying what a boost does, shared by the staff pages, the shop and the announcement."""
    if kind == BoostKind.SPECIAL:
        return f"+{magnitude:g}% chance of the special"
    if kind == BoostKind.RARITY:
        return f"rarer treasures (flattening {magnitude:g}%)"
    if kind == BoostKind.BERRIES:
        return f"+{magnitude:g}% berries per catch"
    if kind == BoostKind.SPAWN_PARTY:
        return f"{spawns} spawns, one after another"
    return ""
