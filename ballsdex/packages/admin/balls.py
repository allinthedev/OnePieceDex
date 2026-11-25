import asyncio
import logging
import random
import re
from collections import Counter
from datetime import date
from typing import TYPE_CHECKING, cast

import discord
from asgiref.sync import sync_to_async
from currency_app.ledger import adjust_money
from currency_app.models import BerryTransaction
from discord.ext import commands
from discord.utils import format_dt
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse

from ballsdex.core.bot import BallsDexBot
from ballsdex.core.utils import checks
from ballsdex.core.utils.buttons import ConfirmChoiceView
from bd_models.models import (
    FRAME_SPECIAL_NAME,
    Ball,
    BallInstance,
    Player,
    Special,
    Trade,
    TradeObject,
    frame_entry,
    special_filter,
)
from bd_models.models import balls as balls_cache
from settings.models import settings
from settings.utils import format_currency

from .flags import BallsCountFlags, BulkGiveFlags, CreateFlags, GiveBallFlags, SpawnFlags

if TYPE_CHECKING:
    from ballsdex.packages.countryballs.cog import CountryBallsSpawner
    from ballsdex.packages.countryballs.countryball import BallSpawnView

log = logging.getLogger("ballsdex.packages.admin.balls")
FILENAME_RE = re.compile(r"^(.+)(\.\S+)$")

# past this many cards in one go, bulkgive says what it is about to do and waits for a yes
BULK_GIVE_CONFIRM_ABOVE = 25
# and past this many it refuses outright: handing out this much in one command is far more
# likely to be a typo in `n:` than something anyone meant
BULK_GIVE_CEILING = 5000


def _is_frame_special(special: Special | None) -> bool:
    """
    The "Frame" special picks out the framed treasures in the commands, it is never given to one: an admin
    choosing it is asking for a framed spawn, not for a treasure of that special.
    """
    return special is not None and special.name.casefold() == FRAME_SPECIAL_NAME.casefold()


def _frame_choices(ball: Ball, special_id: int | None) -> list[str]:
    """
    What can be typed in `frame_name` for this treasure: the frames of every treasure and the ones of the special
    that was picked, as their name, or as their key when they have none. A frame set up over two months has the
    same name every day, so it is listed once.
    """
    from frames.utils import NO_SPECIAL, is_frame_entry, is_named_key, parse_frame_key

    wanted = {None, NO_SPECIAL if special_id is None else special_id}
    choices: set[str] = set()
    for key, entry in ball.capacity_logic.items():
        if not is_frame_entry(entry):
            continue
        parsed = parse_frame_key(key)
        if parsed is None and not is_named_key(key):
            continue
        if parsed is not None and parsed[1] not in wanted:
            continue
        choices.add(str(entry.get("name") or "") or key)
    return sorted(choices)


def _frame_of_the_day(ball: Ball, special_id: int | None) -> dict | None:
    """
    The frame running today for this treasure: the one of the picked special first, then the one of every
    treasure. The chance is ignored, an admin asking for a frame always gets it.
    """
    from frames.utils import NO_SPECIAL, frames_of_day

    today = date.today()
    # several frames can run on the same day now, so the first of the narrower scope is taken
    for scope in (NO_SPECIAL if special_id is None else special_id, None):
        found = frames_of_day(ball.capacity_logic, today, scope)
        if found:
            return found[0]
    return None


async def _spawn_frame(ctx: commands.Context[BallsDexBot], flags: SpawnFlags) -> tuple[bool, dict | None]:
    """
    The frame a forced spawn carries, if any. Returns (go ahead, frame): the admin was already told what is
    wrong when the first item is False.
    """
    if flags.frame_name is None and not _is_frame_special(flags.special):
        return True, None
    if flags.countryball is None:
        await ctx.send(
            "A frame belongs to one treasure: name the `countryball` you want to spawn framed.", ephemeral=True
        )
        return False, None
    try:
        import frames.utils  # noqa: F401
    except ImportError:
        await ctx.send("The `frames` package is not loaded, frames cannot be spawned.", ephemeral=True)
        return False, None

    ball = flags.countryball
    special_id = None if _is_frame_special(flags.special) else (flags.special.pk if flags.special else None)
    frame = frame_entry(ball, flags.frame_name) if flags.frame_name else _frame_of_the_day(ball, special_id)
    if frame is not None:
        return True, frame

    choices = _frame_choices(ball, special_id)
    which = f"`{flags.frame_name}`" if flags.frame_name else "running today"
    if not choices:
        await ctx.send(
            f"No frame {which} for {ball.country}, and it has no frame at all for these settings.", ephemeral=True
        )
        return False, None
    listed = "\n".join(f"- {choice}" for choice in choices[:25])
    more = f"\n…and {len(choices) - 25} more." if len(choices) > 25 else ""
    await ctx.send(f"No frame {which} for {ball.country}. Available here:\n{listed}{more}", ephemeral=True)
    return False, None


async def _no_such_frame(
    ctx: commands.Context[BallsDexBot], ball: Ball, asked: str, special: Special | None
) -> None:
    """
    Tell an admin the frame they named is not on this treasure, and list what is.

    Shared wording with the spawn, so naming a frame that does not exist reads the same whichever
    command it was.
    """
    special_id = None if _is_frame_special(special) else (special.pk if special else None)
    choices = _frame_choices(ball, special_id)
    if not choices:
        await ctx.send(
            f"No frame `{asked}` for {ball.country}, and it has no frame at all for these settings.",
            ephemeral=True,
        )
        return
    listed = "\n".join(f"- {choice}" for choice in choices[:25])
    more = f"\n…and {len(choices) - 25} more." if len(choices) > 25 else ""
    await ctx.send(f"No frame `{asked}` for {ball.country}. Available here:\n{listed}{more}", ephemeral=True)


def _random_from(countryball_cls: type["BallSpawnView"], bot: BallsDexBot, pool: list[Ball]):
    """
    Draw one treasure out of `pool`, weighted by rarity the same way a wild spawn is.

    Returns None when nothing in the pool can be drawn, which lets the caller fall back to the
    whole dex rather than refusing to spawn anything.
    """
    drawable = [ball for ball in pool if ball.rarity > 0]
    if not drawable:
        return None
    chosen = random.choices(drawable, weights=[ball.rarity for ball in drawable], k=1)[0]
    return countryball_cls(bot, chosen)


async def _spawn_group_pool(flags: SpawnFlags) -> list[Ball] | None:
    """The treasures a random spawn may pick from, when it was narrowed to a group."""
    if not flags.group:
        return None
    return [ball async for ball in Ball.objects.filter(enabled=True, rarity__gt=0, groups=flags.group)]


async def _spawn_bomb(
    ctx: commands.Context[BallsDexBot],
    countryball_cls: type["BallSpawnView"],
    countryball: Ball | None,
    channel: discord.TextChannel,
    n: int,
    special: Special | None = None,
    atk_bonus: int | None = None,
    hp_bonus: int | None = None,
    frame: dict | None = None,
    pool: list[Ball] | None = None,
):
    spawned = 0
    message: discord.Message

    async def update_message_loop():
        nonlocal spawned, message
        for i in range(5 * 12 * 10):  # timeout progress after 10 minutes
            await edit_func(
                content=f"Spawn bomb in progress in {channel.mention}, "
                f"{settings.collectible_name.title()}: {countryball or 'Random'}\n"
                f"{spawned}/{n} spawned ({round((spawned / n) * 100)}%)"
            )
            await asyncio.sleep(5)
        await edit_func(content="Spawn bomb seems to have timed out.")

    message = await ctx.send(f"Starting spawn bomb in {channel.mention}...", ephemeral=True)
    edit_func = ctx.interaction.edit_original_response if ctx.interaction else message.edit
    task = ctx.bot.loop.create_task(update_message_loop())
    try:
        for i in range(n):
            if not countryball:
                ball = _random_from(countryball_cls, ctx.bot, pool) if pool else None
                ball = ball or await countryball_cls.get_random(ctx.bot)
            else:
                ball = countryball_cls(ctx.bot, countryball)
            ball.special = special
            ball.atk_bonus = atk_bonus
            ball.hp_bonus = hp_bonus
            if frame is not None:
                # read by the frames package when the spawn draws itself, and kept by the treasure caught from it
                ball.forced_frame = frame
            result = await ball.spawn(channel)
            if not result:
                task.cancel()
                await edit_func(
                    content=f"A {settings.collectible_name} failed to spawn, probably "
                    "indicating a lack of permissions to send messages "
                    f"or upload files in {channel.mention}."
                )
                return
            spawned += 1
        task.cancel()
        await edit_func(
            content=f"Successfully spawned {spawned} {settings.plural_collectible_name} in {channel.mention}!"
        )
    finally:
        task.cancel()


@commands.hybrid_group(name=settings.balls_slash_name)
async def balls(ctx: commands.Context[BallsDexBot]):
    """
    Countryballs management
    """
    await ctx.send_help(ctx.command)


@balls.command()
@checks.has_permissions("bd_models.add_ballinstance")
async def spawn(ctx: commands.Context[BallsDexBot], *, flags: SpawnFlags):
    """
    Force spawn a random or specified countryball.
    """
    # the transformer triggered a response, meaning user tried an incorrect input
    cog = cast("CountryBallsSpawner | None", ctx.bot.get_cog("CountryBallsSpawner"))
    if not cog:
        prefix = settings.prefix if ctx.bot.intents.message_content or not ctx.bot.user else f"{ctx.bot.user.mention} "
        # do not replace `countryballs` with `settings.collectible_name`, it is intended
        await ctx.send(
            "The `countryballs` package is not loaded, this command is unavailable.\n"
            "Please resolve the errors preventing this package from loading. Use "
            f'"{prefix}reload countryballs" to try reloading it.',
            ephemeral=True,
        )
        return

    go_ahead, frame = await _spawn_frame(ctx, flags)
    if not go_ahead:
        return
    # the "Frame" special only means "spawn it framed", giving it to a treasure is what used to break the card
    special = None if _is_frame_special(flags.special) else flags.special

    special_attrs = []
    if flags.group is not None:
        special_attrs.append(f"group={flags.group.name}")
    if special is not None:
        special_attrs.append(f"special={special.name}")
    if frame is not None:
        special_attrs.append(f"frame={frame.get('name') or flags.frame_name or 'of the day'}")
    if flags.atk_bonus is not None:
        special_attrs.append(f"atk={flags.atk_bonus}")
    if flags.hp_bonus is not None:
        special_attrs.append(f"hp={flags.hp_bonus}")
    pool = await _spawn_group_pool(flags)
    if flags.group and not pool:
        await ctx.send(
            f"No {settings.collectible_name} in group `{flags.group.name}` can spawn.", ephemeral=True
        )
        return

    if flags.n > 1:
        await _spawn_bomb(
            ctx,
            cog.countryball_cls,
            flags.countryball,
            flags.channel or ctx.channel,  # type: ignore
            flags.n,
            special,
            flags.atk_bonus,
            flags.hp_bonus,
            frame,
            pool,
        )
        log.info(
            f"{ctx.author} spawned {settings.collectible_name}"
            f" {flags.countryball or 'random'} {flags.n} times in {flags.channel or ctx.channel}"
            + (f" ({', '.join(special_attrs)})." if special_attrs else "."),
            extra={"webhook": True},
        )
        return

    await ctx.defer(ephemeral=True)
    if flags.countryball:
        ball = cog.countryball_cls(ctx.bot, flags.countryball)
    else:
        ball = (_random_from(cog.countryball_cls, ctx.bot, pool) if pool else None) or await (
            cog.countryball_cls.get_random(ctx.bot)
        )
    ball.special = special
    ball.atk_bonus = flags.atk_bonus
    ball.hp_bonus = flags.hp_bonus
    if frame is not None:
        # read by the frames package when the spawn draws itself, and kept by the treasure caught from it
        ball.forced_frame = frame
    result = await ball.spawn(flags.channel or ctx.channel)  # type: ignore

    if result:
        await ctx.send(f"{settings.collectible_name.title()} spawned.", ephemeral=True)
        log.info(
            f"{ctx.author} spawned {settings.collectible_name} {ball.name} "
            f"in {flags.channel or ctx.channel}" + (f" ({', '.join(special_attrs)})." if special_attrs else "."),
            extra={"webhook": True},
        )


@balls.command()
@checks.has_permissions("bd_models.add_ballinstance")
async def give(ctx: commands.Context[BallsDexBot], user: discord.User, *, flags: GiveBallFlags):
    """
    Give the specified countryball to a player.

    Parameters
    ----------
    user: discord.User
        The user you want to give a countryball to
    """
    await ctx.defer(ephemeral=True)

    frame = None
    if flags.frame_name:
        frame = frame_entry(flags.countryball, flags.frame_name)
        if frame is None:
            await _no_such_frame(ctx, flags.countryball, flags.frame_name, flags.special)
            return

    player, created = await Player.objects.aget_or_create(discord_id=user.id)
    instance = await BallInstance.objects.acreate(
        ball=flags.countryball,
        player=player,
        # left empty, the frames package gives whatever frame runs today, as it already did
        extra_data=dict(frame) if frame else {},
        attack_bonus=(
            flags.attack_bonus
            if flags.attack_bonus is not None
            else random.randint(-settings.max_attack_bonus, settings.max_attack_bonus)
        ),
        health_bonus=(
            flags.health_bonus
            if flags.health_bonus is not None
            else random.randint(-settings.max_health_bonus, settings.max_health_bonus)
        ),
        special=flags.special,
    )
    framed = f" • Frame: `{frame.get('name') or flags.frame_name}`" if frame else ""
    await ctx.send(
        f"`{flags.countryball.country}` (`{instance.pk:0X}`) "
        f"{settings.collectible_name} was successfully given to "
        f"`{user}`.\nSpecial: `{flags.special.name if flags.special else None}` • ATK: "
        f"`{instance.attack_bonus:+d}` • HP:`{instance.health_bonus:+d}`{framed}"
    )
    log.info(
        f"{ctx.author} gave {settings.collectible_name} {flags.countryball.country} (`{instance.pk:0X}`) "
        f"to {user}. (Special={flags.special.name if flags.special else None} "
        f"ATK={instance.attack_bonus:+d} HP={instance.health_bonus:+d}{framed}).",
        extra={"webhook": True},
    )


def _bulk_give_pool(flags: BulkGiveFlags):
    """
    Which countryballs a random bulk give may hand out.

    Disabled ones, and ones at a rarity of 0, are left out: they do not spawn, so handing them
    out at random is never what was meant. Naming one in `countryball:` still gives it.
    """
    query = Ball.objects.filter(enabled=True, rarity__gt=0)
    if flags.group:
        query = query.filter(groups=flags.group)
    if flags.min_rarity is not None:
        query = query.filter(rarity__gte=flags.min_rarity)
    if flags.max_rarity is not None:
        query = query.filter(rarity__lte=flags.max_rarity)
    return query


def _bulk_give_specials(flags: BulkGiveFlags) -> str:
    """How specials are being handed out, for the recap and the log."""
    if flags.special:
        return f"`{flags.special.name}` on every card"
    if flags.roll_specials:
        return "rolled per card, like a spawn"
    return "none"


def _bulk_give_scope(flags: BulkGiveFlags) -> str:
    """What the draw was narrowed down to, for the recap and the log."""
    parts = []
    if flags.group:
        parts.append(f"group `{flags.group.name}`")
    if flags.min_rarity is not None:
        parts.append(f"rarity ≥ {flags.min_rarity}")
    if flags.max_rarity is not None:
        parts.append(f"rarity ≤ {flags.max_rarity}")
    return ", ".join(parts) if parts else f"every obtainable {settings.collectible_name}"


async def _bulk_give_targets(
    ctx: commands.Context[BallsDexBot], flags: BulkGiveFlags
) -> list[discord.User | discord.Member] | None:
    """
    Everyone this command is about to give to, or None once it has explained why it cannot.

    A player named twice — passed as `user:` and also holding the role — is only counted once.
    """
    targets: dict[int, discord.User | discord.Member] = {}
    if flags.user:
        targets[flags.user.id] = flags.user
    if flags.role:
        if not ctx.bot.intents.members:
            await ctx.send(
                "Giving to a whole role needs the members intent, and it is off, so I cannot see who holds "
                f"{flags.role.mention}.\nTick **Server Members Intent** on the bot's page in the Discord "
                "developer portal, then add `--enable-members-intent` to the bot's start command and restart "
                "it. Until then, give to players one at a time with `user:`.",
                ephemeral=True,
            )
            return None
        for member in flags.role.members:
            if not member.bot:
                targets.setdefault(member.id, member)
        if not targets:
            await ctx.send(f"Nobody holds {flags.role.mention} right now.", ephemeral=True)
            return None
    if not targets:
        await ctx.send("Tell me who to give to: pass `user:`, `role:`, or both.", ephemeral=True)
        return None
    return list(targets.values())


@balls.command(name="bulkgive")
@checks.has_permissions("bd_models.add_ballinstance")
async def bulkgive(ctx: commands.Context[BallsDexBot], *, flags: BulkGiveFlags):
    """
    Give several countryballs at once, to a player or a role.
    """
    await ctx.defer(ephemeral=True)

    if flags.special and flags.roll_specials:
        await ctx.send(
            "Pick one: `special:` puts that special on every card, `roll_specials:` rolls one per card. "
            "Leaving both out gives plain cards.",
            ephemeral=True,
        )
        return

    targets = await _bulk_give_targets(ctx, flags)
    if targets is None:
        return

    total = len(targets) * flags.n
    if total > BULK_GIVE_CEILING:
        await ctx.send(
            f"That is {total:,} {settings.plural_collectible_name} in one go, over the ceiling of "
            f"{BULK_GIVE_CEILING:,}. Lower `n:`, or narrow the role down.",
            ephemeral=True,
        )
        return

    if flags.countryball:
        pool = [(flags.countryball.pk, flags.countryball.rarity)]
        what = f"`{flags.countryball.country}`"
    else:
        pool = [(pk, rarity) async for pk, rarity in _bulk_give_pool(flags).values_list("pk", "rarity")]
        if not pool:
            await ctx.send(
                f"No {settings.collectible_name} matches that: {_bulk_give_scope(flags)}.", ephemeral=True
            )
            return
        what = f"at random out of {len(pool)} ({_bulk_give_scope(flags)})"

    if total > BULK_GIVE_CONFIRM_ABOVE:
        who = targets[0].mention if len(targets) == 1 else f"**{len(targets)}** players"
        view = ConfirmChoiceView(ctx, accept_message="Confirmed, giving...", cancel_message="Nothing was given.")
        await ctx.send(
            f"About to give **{flags.n}** {settings.plural_collectible_name} to {who} — "
            f"**{total:,}** cards in total, {what}.\nSpecials: {_bulk_give_specials(flags)}.",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.value:
            return

    # imported here rather than at the top: the countryballs package pulls in the spawn machinery,
    # and this module is loaded even on a bot running without it
    from ballsdex.packages.countryballs.countryball import BallSpawnView

    population = [ball_id for ball_id, _ in pool]
    weights = [rarity for _, rarity in pool]
    instances: list[BallInstance] = []
    for target in targets:
        player, _ = await Player.objects.aget_or_create(discord_id=target.id)
        # every player gets their own draw, so a role does not hand the same cards to everyone
        for ball_id in random.choices(population, weights=weights, k=flags.n):
            instances.append(
                BallInstance(
                    ball_id=ball_id,
                    player=player,
                    # rolled per card, so a batch comes out looking like a batch of catches
                    special=BallSpawnView.get_random_special() if flags.roll_specials else flags.special,
                    attack_bonus=(
                        flags.attack_bonus
                        if flags.attack_bonus is not None
                        else random.randint(-settings.max_attack_bonus, settings.max_attack_bonus)
                    ),
                    health_bonus=(
                        flags.health_bonus
                        if flags.health_bonus is not None
                        else random.randint(-settings.max_health_bonus, settings.max_health_bonus)
                    ),
                )
            )
    await BallInstance.objects.abulk_create(instances, batch_size=500)

    lines = [
        f"Gave **{flags.n}** {settings.plural_collectible_name} to "
        + (targets[0].mention if len(targets) == 1 else f"**{len(targets)}** players")
        + f" — **{len(instances):,}** cards, {what}."
    ]
    lines.append(f"Specials: {_bulk_give_specials(flags)}.")
    if flags.roll_specials:
        rolled = Counter(i.special.name for i in instances if i.special)
        lines.append(
            "> " + ", ".join(f"{name} ×{count}" for name, count in rolled.most_common(10))
            if rolled
            else "> None came up, which is what the odds usually say."
        )
    if len(targets) == 1:
        counts = Counter(instance.ball_id for instance in instances)
        names = [
            f"{balls_cache[ball_id].country if ball_id in balls_cache else ball_id}"
            + (f" ×{count}" if count > 1 else "")
            for ball_id, count in counts.most_common(20)
        ]
        lines.append("> " + ", ".join(names) + (" ..." if len(counts) > 20 else ""))
    await ctx.send("\n".join(lines)[:2000], ephemeral=True)

    log.info(
        f"{ctx.author} ({ctx.author.id}) bulk gave {flags.n} {settings.plural_collectible_name} to "
        f"{len(targets)} player(s) ({len(instances)} cards), {what}, specials: {_bulk_give_specials(flags)}.",
        extra={"webhook": True},
    )


@balls.command(name="info")
@checks.has_permissions("bd_models.view_ballinstance")
async def balls_info(ctx: commands.Context[BallsDexBot], countryball_id: str):
    """
    Show information about a countryball.

    Parameters
    ----------
    countryball_id: str
        The ID of the countryball you want to get information about.
    """
    try:
        pk = int(countryball_id, 16)
    except ValueError:
        await ctx.send(f"The {settings.collectible_name} ID you gave is not valid.", ephemeral=True)
        return
    try:
        ball = await BallInstance.objects.prefetch_related("player", "trade_player", "special").aget(id=pk)
    except BallInstance.DoesNotExist:
        await ctx.send(f"The {settings.collectible_name} ID you gave does not exist.", ephemeral=True)
        return
    first_trade_object = (
        await TradeObject.objects.filter(ballinstance=ball).select_related("player").order_by("trade__date").afirst()
    )
    first_owner = first_trade_object.player if first_trade_object else ball.player
    spawned_time = format_dt(ball.spawned_time, style="R") if ball.spawned_time else "N/A"
    catch_time = (
        (ball.catch_date - ball.spawned_time).total_seconds() if ball.catch_date and ball.spawned_time else "N/A"
    )
    admin_url = f"[View online](<{reverse('admin:bd_models_ballinstance_change', args=(ball.pk,))}>)"
    await ctx.send(
        f"**{settings.collectible_name.title()} ID:** {ball.pk}\n"
        f"**Player:** {ball.player}\n"
        f"**First owner:** {first_owner}\n"
        f"**Name:** {ball.countryball}\n"
        f"**Attack:** {ball.attack}\n"
        f"**Attack bonus:** {ball.attack_bonus}\n"
        f"**Health bonus:** {ball.health_bonus}\n"
        f"**Health:** {ball.health}\n"
        f"**Special:** {ball.special.name if ball.special else None}\n"
        f"**Caught at:** {format_dt(ball.catch_date, style='R')}\n"
        f"**Spawned at:** {spawned_time}\n"
        f"**Catch time:** {catch_time} seconds\n"
        f"**Caught in:** {ball.server_id if ball.server_id else 'N/A'}\n"
        f"**Traded:** {ball.trade_player}\n{admin_url}",
        ephemeral=True,
    )
    log.info(f"{ctx.author} got info for {ball}({ball.pk}).", extra={"webhook": True})


@balls.command(name="delete")
@checks.has_permissions("bd_models.delete_ballinstance")
async def balls_delete(ctx: commands.Context[BallsDexBot], countryball_id: str, soft_delete: bool = True):
    """
    Delete a countryball.

    Parameters
    ----------
    countryball_id: str
        The ID of the countryball you want to delete.
    soft_delete: bool
        Whether the countryball should be kept in database or fully wiped.
    """
    try:
        ballIdConverted = int(countryball_id, 16)
    except ValueError:
        await ctx.send(f"The {settings.collectible_name} ID you gave is not valid.", ephemeral=True)
        return
    try:
        ball = await BallInstance.objects.prefetch_related("player").aget(id=ballIdConverted)
    except BallInstance.DoesNotExist:
        await ctx.send(f"The {settings.collectible_name} ID you gave does not exist.", ephemeral=True)
        return

    owner = await ctx.bot.fetch_user(ball.player.discord_id)

    method = "soft" if soft_delete else "hard"
    view = ConfirmChoiceView(
        ctx, accept_message=f"Confirmed, {method} deleting...", cancel_message="Request cancelled."
    )
    await ctx.send(
        f"You are about to {method} delete {ball.description(include_emoji=True, bot=ctx.bot)} "
        f"(ID: `{countryball_id}`) owned by `{owner}`. Are you sure?",
        view=view,
        ephemeral=True,
    )
    await view.wait()
    if not view.value:
        return

    if soft_delete:
        ball.deleted = True
        await ball.asave()
        await ctx.send(f"{settings.collectible_name.title()} {countryball_id} soft deleted.", ephemeral=True)
        log.info(f"{ctx.author} soft deleted {ball}({ball.pk}).", extra={"webhook": True})
    else:
        ball_name = str(ball)
        ball_id = ball.pk
        await ball.adelete()
        await ctx.send(f"{settings.collectible_name.title()} {countryball_id} hard deleted.", ephemeral=True)
        log.info(f"{ctx.author} hard deleted {ball_name}({ball_id}).", extra={"webhook": True})


@balls.command(name="transfer")
@checks.has_permissions("bd_models.change_ballinstance")
async def balls_transfer(ctx: commands.Context[BallsDexBot], countryball_id: str, user: discord.User):
    """
    Transfer a countryball to another user.

    Parameters
    ----------
    countryball_id: str
        The ID of the countryball you want to transfer.
    user: discord.User
        The user you want to transfer the countryball to.
    """
    try:
        ballIdConverted = int(countryball_id, 16)
    except ValueError:
        await ctx.send(f"The {settings.collectible_name} ID you gave is not valid.", ephemeral=True)
        return
    try:
        ball = await BallInstance.objects.prefetch_related("player").aget(id=ballIdConverted)
        original_player = ball.player
    except BallInstance.DoesNotExist:
        await ctx.send(f"The {settings.collectible_name} ID you gave does not exist.", ephemeral=True)
        return

    original_owner = await ctx.bot.fetch_user(original_player.discord_id)

    view = ConfirmChoiceView(ctx, accept_message="Confirmed, transferring...", cancel_message="Request cancelled.")
    await ctx.send(
        f"You are about to transfer {ball.description(include_emoji=True, bot=ctx.bot)} "
        f"(ID: `{countryball_id}`) from `{original_owner}` to `{user}`. Are you sure?",
        view=view,
        ephemeral=True,
    )
    await view.wait()
    if not view.value:
        return

    player, _ = await Player.objects.aget_or_create(discord_id=user.id)
    ball.player = player
    await ball.asave()

    trade = await Trade.objects.acreate(player1=original_player, player2=player)
    await TradeObject.objects.acreate(trade=trade, ballinstance=ball, player=original_player)
    await ctx.send(f"Transfered {ball}({ball.pk}) from {original_player} to {user}.", ephemeral=True)
    log.info(f"{ctx.author} transferred {ball}({ball.pk}) from {original_player} to {user}.", extra={"webhook": True})


@balls.command(name="transferinv")
@checks.has_permissions("bd_models.change_ballinstance")
async def balls_transferinv(
    ctx: commands.Context[BallsDexBot], source: discord.User, dest: discord.User, currency: bool = False
):
    """
    Transfer the full inventory of a user to another.

    Parameters
    ----------
    source: discord.User
        The user whose inventory you want to transfer
    dest: discord.User
        The user who should receive the inventory
    currency: bool
        Whether the player's balance should also be transferred.
    """
    if source == dest:
        await ctx.send("You specified the same source and destination.", ephemeral=True)
        return
    try:
        source_player = await Player.objects.aget(discord_id=source.id)
    except Player.DoesNotExist:
        await ctx.send(f"User {source} does not have a player profile.", ephemeral=True)
        return
    qs = BallInstance.objects.filter(player=source_player)
    balls_count = await qs.acount()
    if balls_count == 0 and (not currency or source_player.money == 0):
        await ctx.send(f"{source}'s inventory is empty.", ephemeral=True)
        return

    view = ConfirmChoiceView(ctx, accept_message="Confirmed, transferring...", cancel_message="Request cancelled.")
    if currency:
        text = (
            f"Are you sure you want to transfer {balls_count} {settings.plural_collectible_name} and "
            f"{format_currency(source_player.money, bot=ctx.bot)} from {source} to {dest}?"
        )
    else:
        text = (
            f"Are you sure you want to transfer {balls_count} {settings.plural_collectible_name} "
            f"from {source} to {dest}?"
        )
    await ctx.send(text, view=view, ephemeral=True)
    await view.wait()
    if not view.value:
        return

    dest_player, _ = await Player.objects.aget_or_create(discord_id=dest.id)
    transferred_money = source_player.money

    @transaction.atomic
    def perform_transfer():
        trade = Trade.objects.create(
            player1=source_player, player2=dest_player, player1_money=source_player.money if currency else 0
        )
        trade_objects: list[TradeObject] = []
        for ball in qs:
            trade_objects.append(TradeObject(trade=trade, ballinstance=ball, player=source_player))
        TradeObject.objects.bulk_create(trade_objects)
        updated = qs.update(player=dest_player, trade_player=source_player)
        if currency:
            transferred = source_player.money
            adjust_money(
                source_player,
                -transferred,
                reason=BerryTransaction.Reason.ADMIN_ADJUST,
                description=f"Account transfer to {dest_player.discord_id}",
            )
            adjust_money(
                dest_player,
                transferred,
                reason=BerryTransaction.Reason.ADMIN_ADJUST,
                description=f"Account transfer from {source_player.discord_id}",
            )
        return updated

    updated = await sync_to_async(perform_transfer)()

    if currency:
        text = (
            f"{updated} {settings.plural_collectible_name} and {format_currency(transferred_money, bot=ctx.bot)} "
            f"transferred from {source} to {dest}."
        )
    else:
        text = f"{updated} {settings.plural_collectible_name} transferred from {source} to {dest}."
    await ctx.send(text, ephemeral=True)
    log.info(
        f"{ctx.author} transferred inventory of {source} ({source.id}, {updated} {settings.plural_collectible_name}, "
        f"{format_currency(transferred_money if currency else 0, bot=ctx.bot)}) to {dest} ({dest.id}).",
        extra={"webhook": True},
    )


@balls.command(name="reset")
@checks.has_permissions("bd_models.delete_ballinstance", "bd_models.change_ballinstance")
async def balls_reset(
    ctx: commands.Context[BallsDexBot], user: discord.User, percentage: int | None = None, soft_delete: bool = True
):
    """
    Reset a player's countryballs.

    Parameters
    ----------
    user: discord.User
        The user you want to reset the countryballs of.
    percentage: int | None
        The percentage of countryballs to delete, if not all. Used for sanctions.
    soft_delete: bool
        If true, the countryballs will be marked as deleted instead of being removed from the
        database.
    """
    player = await Player.objects.aget_or_none(discord_id=user.id)
    if not player:
        await ctx.send("The user you gave does not exist.", ephemeral=True)
        return
    if percentage and not 0 < percentage < 100:
        await ctx.send("The percentage must be between 1 and 99.", ephemeral=True)
        return
    await ctx.defer(ephemeral=True)

    method = "soft" if soft_delete else "hard"
    if not percentage:
        text = f"Are you sure you want to {method} delete {user}'s {settings.plural_collectible_name}?"
    else:
        text = f"Are you sure you want to {method} delete {percentage}% of {user}'s {settings.plural_collectible_name}?"
    view = ConfirmChoiceView(
        ctx,
        accept_message=f"Confirmed, {method} deleting the {settings.plural_collectible_name}...",
        cancel_message="Request cancelled.",
    )
    await ctx.send(text, view=view, ephemeral=True)
    await view.wait()
    if not view.value:
        return
    if percentage:
        balls = [x async for x in BallInstance.objects.filter(player=player)]
        to_delete = random.sample(balls, int(len(balls) * (percentage / 100)))
        for ball in to_delete:
            if soft_delete:
                ball.deleted = True
                await ball.asave()
            else:
                await ball.adelete()
        count = len(to_delete)
    else:
        if soft_delete:
            count = await BallInstance.all_objects.filter(player=player).aupdate(deleted=True)
        else:
            count = await BallInstance.all_objects.filter(player=player).adelete()
    await ctx.send(f"{count} {settings.plural_collectible_name} from {user} have been deleted.", ephemeral=True)
    log.info(
        f"{ctx.author} deleted {percentage or 100}% of {player}'s {settings.plural_collectible_name}.",
        extra={"webhook": True},
    )


@balls.command(name="count")
@checks.has_permissions("bd_models.view_ballinstance")
async def balls_count(ctx: commands.Context[BallsDexBot], *, flags: BallsCountFlags):
    """
    Count the number of countryballs that a player has or how many exist in total.
    """
    filters = {}
    if flags.countryball:
        filters["ball"] = flags.countryball
    if flags.user:
        filters["player__discord_id"] = flags.user.id
    await ctx.defer(ephemeral=True)
    qs = BallInstance.all_objects if flags.deleted else BallInstance.objects
    balls = await qs.filter(special_filter(flags.special) if flags.special else Q(), **filters).acount()
    verb = "is" if balls == 1 else "are"
    country = f"{flags.countryball.country} " if flags.countryball else ""
    plural = "s" if balls > 1 or balls == 0 else ""
    special_str = f"{flags.special.name} " if flags.special else ""
    if flags.user:
        await ctx.send(
            f"{flags.user} has {balls} {special_str}{country}{settings.collectible_name}{plural}.", ephemeral=True
        )
    else:
        await ctx.send(
            f"There {verb} {balls} {special_str}{country}{settings.collectible_name}{plural}.", ephemeral=True
        )


@balls.command(name="create")
@checks.has_permissions("bd_models.add_ball")
async def balls_create(
    ctx: commands.Context[BallsDexBot],
    wild_card: discord.Attachment,
    collection_card: discord.Attachment,
    *,
    flags: CreateFlags,
):
    """
    Create a countryball.

    Parameters
    ----------
    wild_card: discord.Attachment
        Image used to spawn the countryball
    collection_card: discord.Attachment
        Image used when displaying countryballs
    """
    if not flags.emoji_id.isnumeric():
        await ctx.send("The emoji ID isn't a valid number.", ephemeral=True)
        return
    emoji = ctx.bot.get_emoji(int(flags.emoji_id))
    if not emoji:
        await ctx.send(
            "The bot couldn't find the given emoji. Maybe it doesn't exist or the bot doesn't have access to it.",
            ephemeral=True,
        )
        return
    await ctx.defer(ephemeral=True)

    try:
        wild_card_data = await wild_card.read()
        collection_card_data = await collection_card.read()

        ball = await Ball.objects.acreate(
            country=flags.name,
            health=flags.health,
            attack=flags.attack,
            rarity=flags.rarity,
            emoji_id=emoji.id,
            credits=flags.credits,
            capacity_name=flags.capacity_name,
            capacity_description=flags.capacity_description,
            enabled=flags.enabled,
            tradeable=flags.tradeable,
            regime=flags.regime,
            economy=flags.economy,
            wild_card=ContentFile(wild_card_data, wild_card.filename),
            collection_card=ContentFile(collection_card_data, collection_card.filename),
        )
    except IntegrityError:
        log.exception(
            f"Failed creating {settings.collectible_name} because "
            f"a {settings.collectible_name} with that name ({flags.name}) already exists.",
            exc_info=True,
            extra={"webhook": True},
        )
        await ctx.send(
            f"An error occurred while creating the {settings.collectible_name}. Check the error in bot logs.",
            ephemeral=True,
        )
        return
    except Exception:
        log.exception(
            f"Failed creating {settings.collectible_name} with admin command", exc_info=True, extra={"webhook": True}
        )
        await ctx.send(
            f"An error occurred while creating the {settings.collectible_name}. Check the error in bot logs.",
            ephemeral=True,
        )
        return
    else:
        await ctx.bot.load_cache()
        files = [await wild_card.to_file(), await collection_card.to_file()]
        admin_url = f"[View online](<{reverse('admin:bd_models_ball_change', args=(ball.pk,))}>)"
        await ctx.send(
            f"A new {settings.collectible_name} has been created! The internal cache was reloaded.\n"
            f"{admin_url}\n"
            f"{flags.name=} regime={flags.regime.name} economy={flags.economy.name if flags.economy else None} "
            f"{flags.health=} {flags.attack=} {flags.rarity=} {flags.enabled=} {flags.tradeable=} emoji={emoji}",
            files=files,
        )
        log.info(f'{ctx.author} created a new {settings.collectible_name} "{ball.country}"', extra={"webhook": True})
