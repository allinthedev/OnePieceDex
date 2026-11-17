"""
The dice behind packs: which treasures come out of one, and whether a special rides along.

Nothing in here imports Django or Discord, so the odds a pack is configured with can be
replayed and checked on their own. Every number these functions need is passed in through
`PackOdds`, which the caller fills from `currency_app.models.Item`.

Rarity, in this dex, is a spawn weight: the LOWER the number, the RARER the treasure. A rarity
of 0 means the treasure is not obtainable, and those are dropped here as well as by the
caller's query — clamping them to a tiny weight instead, the way a naive `max(rarity, 0.001)`
would, hands out treasures that are not supposed to exist in the wild.
"""

import random
from typing import NamedTuple, Sequence

_RNG = random.Random()


class Card(NamedTuple):
    """One treasure that came out of a pack."""

    ball_id: int
    rarity: float
    special_id: int | None = None


class PackOdds(NamedTuple):
    """
    How a pack is loaded. The defaults describe a single-treasure pack drawn exactly like a
    spawn, which is what every pack in the shop was before these knobs existed.
    """

    cards: int = 1
    flatten: float = 1.0
    rare_rarity: float | None = None
    luck_ramp: float = 0.0
    pity_every: int = 0
    special_factor: float = 1.0


def luck_bonus(ramp: float, dry_packs: int) -> float:
    """
    The extra weight rare treasures carry right now, as a fraction (0.4 = +40%).

    `dry_packs` is how many packs of this kind the player opened in a row without a rare
    treasure in them.
    """
    return max(float(ramp or 0), 0.0) * max(int(dry_packs or 0), 0)


def pick_card(
    pool: Sequence[tuple[int, float]],
    flatten: float = 1.0,
    *,
    rng: random.Random = _RNG,
    rare_rarity: float | None = None,
    only_rare: bool = False,
    luck: float = 0.0,
) -> tuple[int, float] | None:
    """
    Draw one treasure out of `pool`, a sequence of `(ball_id, rarity)`.

    The draw is weighted like a spawn, then bent by `flatten`: 1.0 leaves spawn odds alone,
    above 1 pushes rare treasures further out of reach, below 1 brings them closer.

    `luck` adds that fraction of weight to every treasure at `rare_rarity` or below, and
    `only_rare` restricts the draw to those treasures — that is the guarantee's draw.

    Returns None when the pool holds nothing that can be drawn.
    """
    entries = [(ball_id, rarity) for ball_id, rarity in pool if rarity > 0]
    if only_rare:
        if rare_rarity is None:
            return None
        entries = [entry for entry in entries if entry[1] <= rare_rarity]
    if not entries:
        return None

    # Weights are scaled by the commonest treasure in the pool before being raised to
    # `flatten`. Since `random.choices` normalises them anyway, dividing every weight by the
    # same constant leaves the odds untouched — but it keeps the exponent working on numbers
    # in (0, 1] instead of on rarities that run into the hundreds, where a large `flatten`
    # typed into the admin would overflow to infinity rather than simply make rare
    # treasures scarce.
    heaviest = max(rarity for _, rarity in entries)
    weights: list[float] = []
    for _, rarity in entries:
        weight = (rarity / heaviest) ** flatten
        if luck and rare_rarity is not None and rarity <= rare_rarity:
            weight *= 1 + luck
        weights.append(weight)
    if sum(weights) <= 0:  # every weight underflowed, which only an absurd `flatten` can do
        return None
    return rng.choices(entries, weights=weights, k=1)[0]


def roll_special(
    specials: Sequence[tuple[int, float]], *, rng: random.Random = _RNG, factor: float = 1.0
) -> int | None:
    """
    Roll the special riding on one treasure, out of `(special_id, chance)` pairs.

    `chance` is the special's own catch chance (0.01 = one in a hundred), and `factor`
    multiplies all of them: 1.0 reproduces `BallSpawnView.get_random_special()` exactly,
    0.5 makes specials twice as rare as catching, 0 never rolls one.

    Returns a special id, or None for a plain treasure.
    """
    chances = [(special_id, max(float(chance), 0.0) * max(float(factor), 0.0)) for special_id, chance in specials]
    common = 1.0 - sum(chance for _, chance in chances)
    if common < 0:
        # the specials already account for every catch, so no plain treasure is left to roll
        common = 0.0
    weights = [chance for _, chance in chances] + [common]
    if sum(weights) <= 0:
        return None
    population: list[int | None] = [special_id for special_id, _ in chances] + [None]
    return rng.choices(population, weights=weights, k=1)[0]


def open_pack(
    pool: Sequence[tuple[int, float]],
    specials: Sequence[tuple[int, float]],
    odds: PackOdds = PackOdds(),
    *,
    dry_packs: int = 0,
    rng: random.Random = _RNG,
) -> tuple[list[Card], int]:
    """
    Open one pack. Returns the treasures in it and the player's new dry-pack count.

    When the pack comes out with no treasure at `odds.rare_rarity` or below and the player
    has been dry for `odds.pity_every - 1` packs already, the last treasure is redrawn from
    the rare ones only, so the guarantee lands on the pack it was promised for.

    With no `rare_rarity` set there is nothing to be dry about: the luck bonus and the
    guarantee do nothing and the count stays at 0.
    """
    luck = luck_bonus(odds.luck_ramp, dry_packs) if odds.rare_rarity is not None else 0.0
    drawn: list[Card] = []
    for _ in range(max(int(odds.cards), 1)):
        pick = pick_card(pool, odds.flatten, rng=rng, rare_rarity=odds.rare_rarity, luck=luck)
        if pick is None:
            break
        drawn.append(Card(pick[0], pick[1], roll_special(specials, rng=rng, factor=odds.special_factor)))

    if odds.rare_rarity is None:
        return drawn, 0

    got_rare = any(card.rarity <= odds.rare_rarity for card in drawn)
    if drawn and not got_rare and odds.pity_every and dry_packs + 1 >= odds.pity_every:
        pick = pick_card(pool, odds.flatten, rng=rng, rare_rarity=odds.rare_rarity, only_rare=True)
        if pick is not None:
            drawn[-1] = Card(pick[0], pick[1], roll_special(specials, rng=rng, factor=odds.special_factor))
            got_rare = True
    return drawn, 0 if got_rare else dry_packs + 1


def open_packs(
    pool: Sequence[tuple[int, float]],
    specials: Sequence[tuple[int, float]],
    odds: PackOdds = PackOdds(),
    *,
    amount: int = 1,
    dry_packs: int = 0,
    rng: random.Random = _RNG,
) -> tuple[list[Card], int]:
    """
    Open `amount` packs of the same kind in a row, carrying the dry-pack count from one to
    the next, so a player opening five at once gets the same luck and the same guarantee as
    one opening them one at a time. Returns everything drawn, and the count to store.
    """
    everything: list[Card] = []
    for _ in range(max(int(amount), 1)):
        drawn, dry_packs = open_pack(pool, specials, odds, dry_packs=dry_packs, rng=rng)
        everything += drawn
    return everything, dry_packs
