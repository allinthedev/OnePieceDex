"""
Paying for a pack and handing over what is inside.

Both ways into a pack go through here — the `Buy it!` button of `/pack shop` and `/pack tiers`,
and `/pack open` — so a pack configured in the admin behaves the same whichever one a player
uses. The dice themselves are in `rolls`, which has no Django in it.
"""

import logging
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from currency_app.models import BerryTransaction, Item
from django.utils import timezone

from ballsdex.core.game_events import Event, EventContext, bus
from bd_models.models import Ball, BallInstance, Player, balls, specials
from settings.models import settings
from settings.utils import format_currency

from .rolls import Card, PackOdds, luck_bonus, open_packs

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.pack")

# Player.extra_data: {"<item id>": packs of that kind opened in a row with no rare treasure}.
# It lives in extra_data rather than in a column of its own so that adding a pack, or dropping
# one, never needs a migration — the same place /daily keeps its streak.
DRY_PACKS_KEY = "pack_dry_packs"

# a pack of this many treasures or fewer is listed treasure by treasure; above it, identical
# treasures are grouped, or a 30-treasure pack would not fit in an embed
DETAILED_LIMIT = 30

# the highest number /pack open will accept at all. What a player may really open is set per
# pack, through `Item.packs_per_command`; this is only the ceiling of the slash command's own
# number field, which has to be a constant.
MAX_PACKS_PER_COMMAND = 100

# and the real guard: a pack of 30 treasures opened 40 times is 1200 cards in one command,
# which is a lot of work for one button press however small the number next to it looked
MAX_TREASURES_PER_COMMAND = 500


class PackError(Exception):
    """The pack could not be opened. The message is meant to be shown to the player."""


@dataclass
class Opening:
    """What a player got out of one `/pack open`, or one click on `Buy it!`."""

    pack: Item
    amount: int
    instances: list[BallInstance]
    rarities: list[float]
    spent: int
    balance: int
    dry_packs: int

    @property
    def rares(self) -> int:
        """How many of the treasures count as rare for this pack."""
        if self.pack.rare_rarity is None:
            return 0
        return sum(1 for rarity in self.rarities if rarity <= self.pack.rare_rarity)


def pack_odds(pack: Item) -> PackOdds:
    """The pack's dice, as configured in the admin."""
    return PackOdds(
        cards=pack.cards,
        flatten=pack.rarity_flatten,
        rare_rarity=pack.rare_rarity,
        luck_ramp=pack.luck_ramp,
        pity_every=pack.pity_every,
        special_factor=pack.special_chance_factor,
    )


async def pack_pool(pack: Item) -> list[tuple[int, float]]:
    """
    The treasures this pack can hand out, as `(ball_id, rarity)`.

    A pack with a treasure list draws from that list, one with a rarity range draws from every
    enabled, tradeable treasure in the range. Treasures of rarity 0 never spawn, so they are
    left out — unless a treasure list holds nothing else, which is a deliberate list of
    treasures that are not in the wild, and is then drawn from evenly.
    """
    listed = [item_ball.cached_ball async for item_ball in pack.balls.all()]
    if listed:
        pool = [(ball.pk, ball.rarity) for ball in listed if ball.rarity > 0]
        return pool or [(ball.pk, 1.0) for ball in listed]

    if pack.minimum_rarity is None or pack.maximum_rarity is None:
        return []
    return [
        (ball_id, rarity)
        async for ball_id, rarity in Ball.objects.filter(
            enabled=True, tradeable=True, rarity__gt=0, rarity__range=(pack.minimum_rarity, pack.maximum_rarity)
        ).values_list("pk", "rarity")
    ]


def active_specials() -> list[tuple[int, float]]:
    """
    The specials that may ride on a treasure right now, with their catch chance.

    Reads the same cache and applies the same window as `BallSpawnView.get_random_special`, so
    a pack left at a factor of 1.0 rolls specials exactly like catching one does.
    """
    now = timezone.now()
    current = timezone.get_current_timezone()
    return [
        (special.pk, special.rarity)
        for special in specials.values()
        if (special.start_date or datetime.min.replace(tzinfo=current))
        <= now
        <= (special.end_date or datetime.max.replace(tzinfo=current))
    ]


def dry_packs_of(player: Player, pack: Item) -> int:
    """How many packs of this kind the player has opened in a row without a rare treasure."""
    data = player.extra_data if isinstance(player.extra_data, dict) else {}
    counters = data.get(DRY_PACKS_KEY)
    if not isinstance(counters, dict):
        return 0
    try:
        return max(int(counters.get(str(pack.pk), 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


async def _store_dry_packs(player: Player, pack: Item, dry_packs: int) -> None:
    data = player.extra_data if isinstance(player.extra_data, dict) else {}
    counters = data.get(DRY_PACKS_KEY)
    counters = dict(counters) if isinstance(counters, dict) else {}
    if dry_packs:
        counters[str(pack.pk)] = dry_packs
    else:
        # a pack that came out with a rare treasure resets the count, and an entry left sitting
        # at zero would grow extra_data by one key for every pack a player ever opens
        counters.pop(str(pack.pk), None)
    if counters:
        data[DRY_PACKS_KEY] = counters
    else:
        data.pop(DRY_PACKS_KEY, None)
    player.extra_data = data
    await player.asave(update_fields=("extra_data",))


def luck_now(pack: Item, player: Player) -> float:
    """The luck bonus the player's next pack of this kind carries, as a fraction."""
    if pack.rare_rarity is None:
        return 0.0
    return luck_bonus(pack.luck_ramp, dry_packs_of(player, pack))


async def open_packs_for(
    bot: "BallsDexBot",
    player: Player,
    pack: Item,
    amount: int = 1,
    *,
    server_id: int | None = None,
    channel_id: int | None = None,
    pool: list[tuple[int, float]] | None = None,
    forced: list[Card] | None = None,
) -> Opening:
    """
    Charge a player for `amount` of this pack and give them what comes out.

    `forced` skips the dice and hands over exactly those treasures — that is how a
    single-treasure pack whose contents the player picks themselves gets paid for.

    Raises
    ------
    PackError
        The pack could not be opened, with a message explaining why.
    """
    amount = max(int(amount), 1)
    if forced is None and amount > pack.packs_per_command:
        raise PackError(
            f"You can only open {pack.packs_per_command} **{pack.name}** at a time."
            if pack.packs_per_command > 1
            else f"**{pack.name}** can only be opened one at a time."
        )
    treasures = max(pack.cards, 1) * amount if forced is None else len(forced)
    if treasures > MAX_TREASURES_PER_COMMAND:
        most = MAX_TREASURES_PER_COMMAND // max(pack.cards, 1)
        raise PackError(
            f"That is {treasures:,} {settings.plural_collectible_name} in one go, over the ceiling of "
            f"{MAX_TREASURES_PER_COMMAND:,}. Open at most {most} **{pack.name}** at a time."
        )

    total = (pack.prize or 0) * amount
    if total and player.money < total:
        raise PackError(
            f"You don't have enough {settings.currency_display_plural(bot)} to buy "
            f"{f'{amount}x ' if amount > 1 else ''}**{pack.name}**\n"
            f"Your actual balance: {format_currency(player.money, False, bot)}"
        )

    dry_packs = dry_packs_of(player, pack)
    if forced is not None:
        drawn = list(forced)
    else:
        if pool is None:
            pool = await pack_pool(pack)
        if not pool:
            raise PackError(f"**{pack.name}** has no {settings.plural_collectible_name} to give out yet.")
        drawn, dry_packs = open_packs(
            pool, [] if pack.special_id else active_specials(), pack_odds(pack), amount=amount, dry_packs=dry_packs
        )
        if not drawn:
            raise PackError(f"**{pack.name}** has no {settings.plural_collectible_name} to give out yet.")

    if total:
        try:
            await player.remove_money(
                total,
                reason=BerryTransaction.Reason.PACK_BUY,
                description=f"Bought {amount}x pack {pack.name}" if amount > 1 else f"Bought pack {pack.name}",
                server_id=server_id,
            )
        except ValueError:
            # the balance moved between the check above and here
            await player.arefresh_from_db(fields=("money",))
            raise PackError(
                f"You don't have enough {settings.currency_display_plural(bot)} to buy **{pack.name}**\n"
                f"Your actual balance: {format_currency(player.money, False, bot)}"
            )

    try:
        instances = [
            BallInstance(
                player=player,
                ball_id=card.ball_id,
                special_id=pack.special_id or card.special_id,
                health_bonus=random.randint(-settings.max_health_bonus, settings.max_health_bonus),
                attack_bonus=random.randint(-settings.max_attack_bonus, settings.max_attack_bonus),
                catch_date=timezone.now(),
                server_id=server_id,
            )
            for card in drawn
        ]
        await BallInstance.objects.abulk_create(instances)
    except Exception:
        log.exception("pack: could not hand over %sx %r to player %s, refunding", amount, pack.name, player.pk)
        if total:
            await player.add_money(
                total,
                reason=BerryTransaction.Reason.PACK_BUY,
                description=f"Refunded pack {pack.name}, the opening failed",
                server_id=server_id,
            )
        raise PackError(f"Something went wrong opening **{pack.name}**. You were not charged.")

    await _store_dry_packs(player, pack, dry_packs)
    log.info(
        "pack: player %s opened %sx %r (%s %s) for %s",
        player.pk,
        amount,
        pack.name,
        len(instances),
        settings.plural_collectible_name,
        total,
    )

    opening = Opening(
        pack=pack,
        amount=amount,
        instances=instances,
        rarities=[card.rarity for card in drawn],
        spent=total,
        balance=player.money,
        dry_packs=dry_packs,
    )
    for _ in range(amount):
        await bus.dispatch(
            player,
            Event.PACK_BUY,
            context=EventContext(
                instances=instances,
                item_id=pack.pk,
                price=pack.prize or 0,
                amount=-(pack.prize or 0),
                server_id=server_id,
            ),
            channel_id=channel_id,
        )
    return opening


async def treasure_card(bot: "BallsDexBot", instance: BallInstance) -> discord.File:
    """The drawn card of one treasure, rendered off the event loop."""
    # the instance comes out of a bulk insert holding only the ids, so the treasure and its
    # special are filled in from the caches here rather than queried again while drawing
    ball = balls.get(instance.ball_id)
    if ball is not None:
        instance.ball = ball
    if instance.special_id is None:
        instance.special = None
    elif (special := specials.get(instance.special_id)) is not None:
        instance.special = special
    with ThreadPoolExecutor() as pool:
        buffer = await bot.loop.run_in_executor(pool, instance.draw_card)
    return discord.File(buffer, "card.webp")


async def treasure_embed(opening: Opening, user: discord.abc.User) -> discord.Embed:
    """
    A single-treasure opening, shown the way `/pack shop` has always shown one: the card
    itself, with its rarity and stats.
    """
    instance = opening.instances[0]
    ball = balls.get(instance.ball_id) or await Ball.objects.aget(pk=instance.ball_id)
    special = specials.get(instance.special_id) if instance.special_id else None

    embed = discord.Embed(title=f"🎁 You got {ball.country}!", colour=settings.embed_colour)
    description = f"📖 **Rarity:** {ball.rarity}\n❤️ **Health:** {ball.health}\n⚔️ **Attack:** {ball.attack}\n"
    if special:
        description += f"⚡ **Special:** {special.name}\n"
    embed.description = description
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.set_image(url="attachment://card.webp")
    return embed


def _label(bot: "BallsDexBot", instance: BallInstance, rare_rarity: float | None) -> str:
    ball = balls.get(instance.ball_id)
    name = ball.country if ball else str(instance.ball_id)
    emoji = bot.get_emoji(ball.emoji_id) if ball else None
    star = "⭐ " if ball and rare_rarity is not None and ball.rarity <= rare_rarity else ""
    special = specials.get(instance.special_id) if instance.special_id else None
    suffix = f" — {special.emoji or '✨'} **{special.name}**" if special else ""
    return f"{star}{emoji or ''} **{name}**{suffix}"


def opening_lines(bot: "BallsDexBot", opening: Opening) -> list[str]:
    """
    One line per treasure, or, past `DETAILED_LIMIT`, identical treasures grouped together and
    the rarest listed first so the good news is at the top.
    """
    rare_rarity = opening.pack.rare_rarity
    if len(opening.instances) <= DETAILED_LIMIT:
        return [
            f"{_label(bot, instance, rare_rarity)} "
            f"(#{instance.pk:0X}, {instance.attack_bonus:+d}%/{instance.health_bonus:+d}%)"
            for instance in opening.instances
        ]

    counts: dict[str, int] = {}
    rarity_of: dict[str, float] = {}
    for instance in opening.instances:
        label = _label(bot, instance, rare_rarity)
        counts[label] = counts.get(label, 0) + 1
        ball = balls.get(instance.ball_id)
        rarity_of[label] = ball.rarity if ball else float("inf")
    return [
        f"{label} ×{count}" if count > 1 else label
        for label, count in sorted(counts.items(), key=lambda pair: rarity_of[pair[0]])
    ]


def opening_embed(bot: "BallsDexBot", opening: Opening, user: discord.abc.User) -> discord.Embed:
    """The results of a multi-treasure opening, as text: too many cards to draw them all."""
    pack = opening.pack
    embed = discord.Embed(
        title=f"🎉 {pack.name} ×{opening.amount}" if opening.amount > 1 else f"🎉 {pack.name}",
        colour=settings.embed_colour,
    )
    embed.description = (
        f"{user.mention} opened **{opening.amount}x {pack.name}** and got "
        f"{len(opening.instances)} {settings.plural_collectible_name}!\n\n" + "\n".join(opening_lines(bot, opening))
    )[:4000]
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

    # no bot, so no emoji: a footer is plain text to Discord and a custom emoji would show
    # there as <:berry:123456789012345678> rather than as a picture
    footer = f"Spent {format_currency(opening.spent, False)} • Balance {opening.balance:,}"
    if pack.rare_rarity is not None and pack.luck_ramp:
        if opening.dry_packs:
            bonus = round(luck_bonus(pack.luck_ramp, opening.dry_packs) * 100)
            footer += f" • Luck bonus +{bonus}% on your next {pack.name}"
        elif opening.rares:
            footer += " • Luck bonus reset"
    embed.set_footer(text=footer)
    return embed
