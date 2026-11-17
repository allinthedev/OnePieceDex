"""
What the Hotel de Vente is worth paying for a treasure, so the panel can show it.

This exists to answer one question without playing the game: what is this treasure worth
before I put it in a shop? It runs the Hotel's own formula, so the figure is the real one
rather than an estimate. The only unknown at this point is the stat roll, so the spread
between the worst and the best stats is reported next to the flat price.

The Hotel de Vente is an optional extension. With it absent there is nothing to price
against and every function here returns None.
"""

from dataclasses import dataclass
from types import SimpleNamespace

from django.core.cache import cache

# the panel reads these on every row of a treasure list, so the three numbers behind them are
# cached rather than queried per row. Short-lived: an admin changing them wants to see it.
_CACHE_KEY = "hotel_pricing_numbers"
_CACHE_SECONDS = 60

# the stat bonus the Hotel reads is the average of attack and health, clamped to this range
_WORST_STATS = -40
_BEST_STATS = 40


@dataclass
class TreasureValue:
    """What the Hotel pays for one treasure of a given rarity."""

    flat: int
    """Price at 0/0 stats — the figure to compare treasures with."""

    worst: int
    """Price at the worst possible stats."""

    best: int
    """Price at the best possible stats."""

    sellable: bool
    """False for the rarity the Hotel refuses outright, whatever the stats."""


def _numbers():
    """`(min_price, max_price, excluded_rarity, stat percent at -40/0/+40)`, or None."""

    def load():
        try:
            from auction_house_app.models import AuctionSettings, StatBonusModifier
        except ImportError:
            return ()
        auction_settings = AuctionSettings.load()
        modifiers = dict(StatBonusModifier.objects.values_list("value", "percent"))
        return (
            auction_settings.min_price,
            auction_settings.max_price,
            auction_settings.excluded_rarity,
            modifiers.get(_WORST_STATS, 0),
            modifiers.get(0, 0),
            modifiers.get(_BEST_STATS, 0),
        )

    return cache.get_or_set(_CACHE_KEY, load, timeout=_CACHE_SECONDS) or None


def base_price(rarity: float, min_price: int, max_price: int) -> int | None:
    """
    The Hotel's base price for a rarity, or None when its curve does not reach that far.

    The curve is only defined above a rarity of roughly 0.963. Below it the formula raises a
    negative number to a fractional power and comes back with a complex number, and right on
    it the exponent divides by zero. Nothing in the dex sits in that range today, and the
    Hotel refuses to deal in it anyway, so it is reported as "no price" rather than being
    allowed to break an admin page.
    """
    try:
        from auction_house_app import pricing
    except ImportError:
        return None
    try:
        return pricing.base_value(rarity, SimpleNamespace(min_price=min_price, max_price=max_price))
    except (TypeError, ZeroDivisionError):
        return None


def value_of(rarity: float | None) -> TreasureValue | None:
    """What the Hotel pays for a treasure of this rarity, or None if it cannot be worked out."""
    numbers = _numbers()
    if numbers is None or rarity is None:
        return None

    min_price, max_price, excluded, worst_pct, flat_pct, best_pct = numbers
    unsellable = TreasureValue(flat=0, worst=0, best=0, sellable=False)
    if rarity == excluded:
        return unsellable
    base = base_price(rarity, min_price, max_price)
    if base is None:
        return unsellable
    return TreasureValue(
        flat=max(min_price, round(base * (1 + flat_pct / 100))),
        worst=max(min_price, round(base * (1 + worst_pct / 100))),
        best=max(min_price, round(base * (1 + best_pct / 100))),
        sellable=rarity != excluded,
    )


def short_label(rarity: float | None) -> str:
    """One cell's worth: the flat price, for a list of treasures."""
    value = value_of(rarity)
    if value is None:
        return "—"
    if not value.sellable:
        return "not sellable"
    return f"{value.flat:,}"


def detail_lines(rarity: float | None) -> list[str]:
    """The same thing spelled out, for a treasure's own page."""
    value = value_of(rarity)
    if value is None:
        return ["No price: the Hotel de Vente is not installed."]
    if not value.sellable:
        return [
            "The Hotel will not price this rarity, so this treasure cannot be sold or listed at all.",
            "Give it a rarity of 1 or more to put a price on it.",
        ]
    return [
        f"{value.flat:,} berries at 0/0 stats — what the Hotel pays for it.",
        f"Between {value.worst:,} and {value.best:,} depending on the stats it rolls.",
        "A special on top multiplies this by its own modifier, set on the Hotel's pages.",
    ]
