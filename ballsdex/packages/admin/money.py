import logging
from typing import Literal

import discord
from asgiref.sync import sync_to_async
from currency_app.ledger import aadjust_money_to, reset_all_balances
from currency_app.models import BerryTransaction
from discord.ext import commands
from django.db import connection
from pack_models.models import PackResource

from ballsdex.core.bot import BallsDexBot
from ballsdex.core.game_events import Event, EventContext, bus
from ballsdex.core.utils import checks
from ballsdex.core.utils.buttons import ConfirmChoiceView
from bd_models.models import Player
from settings.models import settings
from settings.utils import format_currency

log = logging.getLogger(__name__)


@commands.hybrid_group()
@checks.has_permissions("bd_models.view_player")
async def money(ctx: commands.Context[BallsDexBot]):
    """
    Currency management tools
    """
    await ctx.send_help(ctx.command)


@money.command()
@checks.has_permissions("bd_models.view_player")
async def balance(ctx: commands.Context[BallsDexBot], user: discord.User):
    """
    Show the balance of the user provided

    Parameters
    ----------
    user: discord.User
        The user you want to get information about.
    """
    player = await Player.objects.aget_or_none(discord_id=user.id)
    if not player:
        await ctx.send(f"This user does not have a {settings.bot_name} account.", ephemeral=True)
        return

    await ctx.send(
        f"{user.mention} currently has {format_currency(player.money, shortened=False, bot=ctx.bot)}.", ephemeral=True
    )


@money.command()
@checks.has_permissions("bd_models.change_player")
async def add(ctx: commands.Context[BallsDexBot], user: discord.User, amount: int):
    """
    Add coins to the user provided

    Parameters
    ----------
    user: discord.User
        The user you want to add coins to.
    amount: int
        The amount of coins to add.
    """
    player = await Player.objects.aget_or_none(discord_id=user.id)
    if not player:
        await ctx.send(f"This user does not have a {settings.bot_name} account.", ephemeral=True)
        return

    if amount <= 0:
        await ctx.send("The amount must be greater than zero.", ephemeral=True)
        return

    await player.add_money(
        amount,
        reason=BerryTransaction.Reason.ADMIN_ADJUST,
        description=f"/money add by {ctx.author.id}",
        server_id=ctx.guild.id if ctx.guild else None,
    )
    formatted = format_currency(amount, shortened=False, bot=ctx.bot)
    await ctx.send(f"Added {formatted} to {user.mention}.", ephemeral=True)
    # no channel: the command may be used in a staff channel, the player is congratulated where they play
    bus.dispatch_soon(
        player.pk,
        Event.CURRENCY_RECEIVED,
        context=EventContext(partner_discord_id=ctx.author.id, received_currency=amount),
    )
    log.info(f"{ctx.author} ({ctx.author.id}) added {formatted} to {user} ({user.id})", extra={"webhook": True})


@money.command()
@checks.has_permissions("bd_models.change_player")
async def remove(ctx: commands.Context[BallsDexBot], user: discord.User, amount: int):
    """
    Remove coins from the user provided

    Parameters
    ----------
    user: discord.User
        The user you want to remove coins from.
    amount: int
        The amount of coins to remove.
    """
    player = await Player.objects.aget_or_none(discord_id=user.id)
    if not player:
        await ctx.send(f"This user does not have a {settings.bot_name} account.", ephemeral=True)
        return

    if amount <= 0:
        await ctx.send("The amount must be greater than zero.", ephemeral=True)
        return
    try:
        await player.remove_money(
            amount,
            reason=BerryTransaction.Reason.ADMIN_ADJUST,
            description=f"/money remove by {ctx.author.id}",
            server_id=ctx.guild.id if ctx.guild else None,
        )
    except ValueError:
        await ctx.send(
            f"This user does not have enough {settings.currency_display_plural(ctx.bot)} to remove "
            f"(balance={format_currency(player.money, shortened=False, bot=ctx.bot)}).",
            ephemeral=True,
        )
        return
    formatted = format_currency(amount, shortened=False, bot=ctx.bot)
    await ctx.send(f"Removed {formatted} from {user.mention}.", ephemeral=True)
    log.info(f"{ctx.author} ({ctx.author.id}) removed {formatted} from {user} ({user.id})", extra={"webhook": True})


@money.command()
@checks.has_permissions("bd_models.change_player")
async def set(ctx: commands.Context[BallsDexBot], user: discord.User, amount: int):
    """
    Set the balance of the user provided

    Parameters
    ----------
    user: discord.User
        The user you want to set the balance of.
    amount: int
        The amount of coins to set.
    """
    player = await Player.objects.aget_or_none(discord_id=user.id)
    if not player:
        await ctx.send(f"This user has does not have a {settings.bot_name} account.", ephemeral=True)
        return

    if amount < 0:
        await ctx.send("The amount must be greater than or equal to zero.", ephemeral=True)
        return

    await aadjust_money_to(
        player,
        amount,
        reason=BerryTransaction.Reason.ADMIN_ADJUST,
        description=f"/money set by {ctx.author.id}",
        server_id=ctx.guild.id if ctx.guild else None,
    )
    formatted = format_currency(amount, shortened=False, bot=ctx.bot)
    await ctx.send(f"{user.mention} now has {formatted}.", ephemeral=True)
    log.info(
        f"{ctx.author} ({ctx.author.id}) set the balance of {user} ({user.id}) to {formatted}", extra={"webhook": True}
    )


@money.command()
@checks.is_superuser()
async def setdefault(ctx: commands.Context[BallsDexBot], amount: int, force: bool = False):
    """
    Set the default amount of currency provided to new users.

    Parameters
    ----------
    amount: int
        The new default amount to set.
    force: bool
        If true, then ALL users will have their balance reset to the default!
    """
    view = ConfirmChoiceView(ctx)
    msg = f"You are about to set the new default balance to {format_currency(amount, shortened=False, bot=ctx.bot)}.\n"
    if force:
        msg += (
            ":warning: You have chosen to reset ALL PLAYERS balance and set it to the new amount. "
            "This operation cannot be undone, all existing balances will be lost.\n"
        )
    msg += "\nDo you want to continue?"
    await ctx.send(msg, view=view)
    await view.wait()
    if not view.value:
        return

    @sync_to_async
    def wrapper():
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE player ALTER COLUMN money SET DEFAULT {int(amount)}")

    await wrapper()
    if force:
        await sync_to_async(reset_all_balances)(amount, ctx.author.id)

    await ctx.send("New default set.")


@money.command(name="resetdaily")
@checks.has_permissions("bd_models.change_player")
async def resetdaily(
    ctx: commands.Context[BallsDexBot],
    user: discord.User,
    streak: Literal["replay", "advance", "reset"] = "replay",
    packs: bool = False,
):
    """
    Clear the daily cooldown of the user provided, letting them claim again right away

    Parameters
    ----------
    user: discord.User
        The user whose daily cooldown you want to clear.
    streak: Literal["replay", "advance", "reset"]
        replay: same streak day again. advance: the streak moves on. reset: the streak starts over at day 1.
    packs: bool
        Also clear the daily pack cooldown, giving the user a fresh cycle of packs.
    """
    player = await Player.objects.aget_or_none(discord_id=user.id)
    if not player:
        await ctx.send(f"This user does not have a {settings.bot_name} account.", ephemeral=True)
        return

    had_cooldown = player.extra_data.pop("berry_daily_cooldown", None) is not None
    streak_day = player.extra_data.get("daily_streak_day", 0)
    if streak == "reset":
        # dropping the last claim also takes the player out of the grace window, so the next claim is day 1
        player.extra_data.pop("daily_last_claim_at", None)
        player.extra_data.pop("daily_streak_day", None)
    elif streak == "replay" and streak_day:
        # /daily claims the day after the one stored, so step back to land on the day already reached
        player.extra_data["daily_streak_day"] = streak_day - 1
    await player.asave(update_fields=("extra_data",))

    if had_cooldown:
        lines = [f"Cleared the daily cooldown of {user.mention}."]
    else:
        lines = [f"{user.mention} was not on a daily cooldown."]
    if streak == "reset":
        lines.append("Their streak starts over: the next claim is day 1/7.")
    elif streak == "replay":
        lines.append(f"Their next claim lands on day {streak_day or 1}/7 again.")
    else:
        lines.append("Their streak advances on the next claim, granting a free day.")

    if packs:
        resource = await PackResource.objects.filter(player=player).afirst()
        if resource is None or resource.daily_cooldown is None:
            lines.append("They had no daily pack cooldown running.")
        else:
            # a cleared cooldown with no use left opens a new cycle, which carries the pack streak forward
            await resource.remove_daily_cooldown()
            lines.append("Cleared their daily pack cooldown, they get a fresh cycle of packs.")

    await ctx.send("\n".join(lines), ephemeral=True)
    log.info(
        f"{ctx.author} ({ctx.author.id}) cleared the daily cooldown of {user} ({user.id}) "
        f"(streak={streak}, packs={packs})",
        extra={"webhook": True},
    )
