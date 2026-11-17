"""
What a pack's contents are worth in berries, and the price that follows from it.

This is only ever a suggestion: `Item.prize` stays the editable price the shop charges. The
figure here exists so that price can be set against what the Hotel de Vente says a treasure
is worth, instead of being guessed.

The expected value accounts for the luck bonus and the guarantee, which matter: ignoring them
understates a small, generous pack by around a quarter. The dry-pack streak a player is on is
a Markov chain — a pack with no rare treasure moves them one step up, any pack with one sends
them back to zero, and the guarantee forces a return to zero — so the value is averaged over
that chain's stationary distribution. Checked against 60 000 simulated openings per pack,
which it matches to within 0.3%.

The Hotel de Vente is an optional extension. With it absent there is nothing to price against
and every function here returns None.
"""

import itertools
from dataclasses import dataclass
from functools import lru_cache

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from bd_models import treasure_value
from bd_models.models import Ball, Special
from settings.models import settings

from .models import CurrencySettings, Item

# past this many dry packs the luck bonus has long since saturated; only reached by a pack that
# has a luck bonus but no guarantee to cap it
_MAX_DRY_STREAK = 400


@dataclass
class PackValue:
    """What one pack of this kind is worth, and what it should therefore cost."""

    contents: int
    """Expected berry value of the treasures in it, priced as a player would list them."""

    liquid: int
    """The part of it a player could actually sell to the Hotel: specials cannot be sold."""

    recommended: int
    """`contents` plus the house margin — the suggested price."""

    margin_percent: int


# a page of packs values every row with the same settings, so they are read once and held
# briefly rather than queried per pack. Short-lived: an admin changing them wants to see it.
_CACHE_SECONDS = 60


def _auction():
    """
    `(min_price, max_price, special modifiers, stat modifiers)` of the Hotel, or None when it
    is not installed. Cached, because none of it changes between two rows of the same page.
    """

    def load():
        try:
            from auction_house_app.models import AuctionSettings, SpecialPriceModifier, StatBonusModifier
        except ImportError:
            return ()
        auction_settings = AuctionSettings.load()
        return (
            auction_settings.min_price,
            auction_settings.max_price,
            dict(SpecialPriceModifier.objects.values_list("special_id", "percent")),
            dict(StatBonusModifier.objects.values_list("value", "percent")),
        )

    return cache.get_or_set("pack_value_auction", load, timeout=_CACHE_SECONDS) or None


def _margin() -> int:
    """The house margin added to a pack's contents, in percent."""
    return cache.get_or_set(
        "pack_value_margin", lambda: CurrencySettings.load().pack_price_margin_percent, timeout=_CACHE_SECONDS
    )


def _active_specials() -> list[tuple[int, float]]:
    """The specials that may ride on a treasure right now, with their catch chance."""

    def load():
        now = timezone.now()
        return list(
            Special.objects.filter(
                Q(start_date__isnull=True) | Q(start_date__lte=now),
                Q(end_date__isnull=True) | Q(end_date__gte=now),
            ).values_list("pk", "rarity")
        )

    return cache.get_or_set("pack_value_specials", load, timeout=_CACHE_SECONDS)


@lru_cache(maxsize=4)
def _stat_law(
    max_attack: int, max_health: int, modifiers: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, float], ...]:
    """
    The law of a treasure's stat percentage, exactly.

    Attack and health bonuses are each drawn uniformly, and the Hotel reads the rounded average
    of the two, so every pair is enumerated rather than sampled.
    """
    table = dict(modifiers)
    counts: dict[int, int] = {}
    pairs = itertools.product(range(-max_attack, max_attack + 1), range(-max_health, max_health + 1))
    for attack, health in pairs:
        average = max(-40, min(40, round((attack + health) / 2)))
        percent = table.get(average, 0)
        counts[percent] = counts.get(percent, 0) + 1
    total = sum(counts.values())
    return tuple((percent, count / total) for percent, count in counts.items())


def _pool(pack: Item) -> list[tuple[int, float]]:
    """
    The treasures this pack can hand out, as `(ball_id, rarity)`.

    The synchronous twin of `pack_ext.opening.pack_pool`, which is what actually fills packs;
    the two have to agree for the figures here to mean anything.
    """
    listed = list(pack.balls.all())
    if listed:
        pool = [(row.ball_id, row.cached_ball.rarity) for row in listed]
        return [entry for entry in pool if entry[1] > 0] or [(ball_id, 1.0) for ball_id, _ in pool]
    if pack.minimum_rarity is None or pack.maximum_rarity is None:
        return []
    return list(
        Ball.objects.filter(
            enabled=True, tradeable=True, rarity__gt=0, rarity__range=(pack.minimum_rarity, pack.maximum_rarity)
        ).values_list("pk", "rarity")
    )


def _special_multiplier(pack: Item, special_modifiers: dict[int, int]) -> tuple[float, float]:
    """
    What the specials do to a pack's value: `(price multiplier, share of treasures sellable)`.

    A special treasure cannot be sold to the Hotel at all, which is what the second number is
    about — it does not change what the treasure is worth, only whether it can be cashed in.
    """
    if pack.special_id:
        return 1 + special_modifiers.get(pack.special_id, 0) / 100, 0.0

    active = _active_specials()
    factor = max(pack.special_chance_factor, 0.0)
    chance = 0.0
    percent = 0.0
    for special_id, rarity in active:
        own = max(rarity, 0.0) * factor
        chance += own
        percent += own * special_modifiers.get(special_id, 0)
    return 1 + percent / 100, 1 - min(chance, 1.0)


def _levels(pool, values, flatten, rare_rarity, luck):
    """
    Per-treasure figures at one luck level: mean value, rare rate, and the mean value of a
    treasure that is not rare.
    """
    heaviest = max(rarity for _, rarity in pool)
    weights = [
        (rarity / heaviest) ** flatten * (1 + luck if rare_rarity is not None and rarity <= rare_rarity else 1.0)
        for _, rarity in pool
    ]
    total = sum(weights)
    mean = sum(weight / total * values[ball_id] for (ball_id, _), weight in zip(pool, weights))
    if rare_rarity is None:
        return mean, 0.0, mean
    rare_rate = sum(w for w, (_, rarity) in zip(weights, pool) if rarity <= rare_rarity) / total
    if rare_rate >= 1:
        return mean, 1.0, mean
    plain = sum(
        weight / total * values[ball_id] for (ball_id, rarity), weight in zip(pool, weights) if rarity > rare_rarity
    )
    return mean, rare_rate, plain / (1 - rare_rate)


def _rare_only_mean(pool, values, flatten, rare_rarity) -> float:
    """Mean value of the guarantee's draw, which is restricted to the rare treasures."""
    rares = [(ball_id, rarity) for ball_id, rarity in pool if rarity <= rare_rarity]
    if not rares:
        return 0.0
    heaviest = max(rarity for _, rarity in pool)
    weights = [(rarity / heaviest) ** flatten for _, rarity in rares]
    total = sum(weights)
    return sum(weight / total * values[ball_id] for (ball_id, _), weight in zip(rares, weights))


def _expected_treasures(pack: Item, pool, values) -> float:
    """Expected value of the treasures in one pack, luck bonus and guarantee included."""
    cards = max(pack.cards, 1)
    rare_rarity = pack.rare_rarity
    if rare_rarity is None or (not pack.luck_ramp and not pack.pity_every):
        return cards * _levels(pool, values, pack.rarity_flatten, rare_rarity, 0.0)[0]

    rare_value = _rare_only_mean(pool, values, pack.rarity_flatten, rare_rarity)
    horizon = pack.pity_every or _MAX_DRY_STREAK
    # the chance of reaching each dry-pack streak, and what a pack is worth once there
    reach, value_at = [], []
    weight = 1.0
    for dry in range(horizon):
        mean, rare_rate, plain = _levels(pool, values, pack.rarity_flatten, rare_rarity, pack.luck_ramp * dry)
        stays_dry = (1 - rare_rate) ** cards
        value = cards * mean
        if pack.pity_every and dry + 1 >= pack.pity_every:
            # this pack was promised a rare treasure: its last one is redrawn among the rares
            value += stays_dry * (rare_value - plain)
            stays_dry = 0.0
        reach.append(weight)
        value_at.append(value)
        weight *= stays_dry
        if weight < 1e-12:
            break
    total = sum(reach)
    return sum(weight / total * value_at[dry] for dry, weight in enumerate(reach))


def value_of(pack: Item) -> PackValue | None:
    """
    What this pack's contents are worth and what it should cost, or None when it cannot be
    worked out — no Hotel de Vente installed, or a pack with nothing to give.
    """
    auction = _auction()
    if auction is None or pack.pk is None:
        return None
    min_price, max_price, special_modifiers, stat_modifiers = auction

    pool = _pool(pack)
    if not pool:
        return None

    stat_law = _stat_law(settings.max_attack_bonus, settings.max_health_bonus, tuple(sorted(stat_modifiers.items())))
    values = {}
    for ball_id, rarity in pool:
        # a treasure the Hotel's curve does not reach is worth its floor and no more: it can
        # still come out of the pack, so leaving it out would understate what the pack holds
        base = treasure_value.base_price(rarity, min_price, max_price) or min_price
        values[ball_id] = sum(
            share * max(min_price, round(base * (1 + percent / 100))) for percent, share in stat_law
        )

    treasures = _expected_treasures(pack, pool, values)
    multiplier, sellable = _special_multiplier(pack, special_modifiers)
    contents = treasures * multiplier
    margin = _margin()
    return PackValue(
        contents=round(contents),
        liquid=round(treasures * sellable),
        recommended=round(contents * (1 + margin / 100)),
        margin_percent=margin,
    )
