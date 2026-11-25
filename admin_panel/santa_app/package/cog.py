"""
The /santa commands: sign up, write a list, fill the parcel you owe, and open yours on Christmas morning.

What a player is shown is carefully bounded. You know who you give to, because you have to. You never learn who
gave to you, and you are never told how your parcel came to be filled — by a card, by paying, or by the bot
because nobody filled it. Those three are indistinguishable on purpose.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import format_dt
from django.utils import timezone
from eventpass_app import wallet

from ballsdex.core.utils.broadcast import announce_to_spawn_channels
from ballsdex.core.utils.transformers import BallEnabledTransform, BallInstanceTransform
from ballsdex.core.utils.utils import is_staff
from bd_models.enums import AnnouncementScope
from bd_models.models import Player
from settings.models import settings

from ..exchange import Refused, adraw, afill_the_rest, ajoin, aopen, aset_wish, awrap_card, awrap_paid
from ..models import SantaEntry, SantaGift, SecretSanta

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("santa")

TICK_SECONDS = 300


async def current_santa() -> SecretSanta | None:
    """The run being played: the most recent enabled one, so every stage of it is reachable."""
    return (
        await SecretSanta.objects.filter(enabled=True)
        .select_related("special", "event_pass")
        .order_by("-signup_opens_at", "-pk")
        .afirst()
    )


class SantaCog(commands.GroupCog, name="Secret Santa", group_name="santa"):
    """Give to one, receive from another."""

    admin = app_commands.Group(name="admin", description="Staff commands for the Secret Santa.")

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def cog_load(self):
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    # ── the loop ────────────────────────────────────────────────────────────────────────────────

    @tasks.loop(seconds=TICK_SECONDS)
    async def tick(self):
        """
        Fill the parcels nobody filled, once the wrapping time is up, and announce the opening day.

        The filling is silent by design: nothing is logged to a channel, nothing is announced, and no player is
        ever told it ran.
        """
        async for santa in SecretSanta.objects.filter(enabled=True):
            try:
                await afill_the_rest(santa.pk)
            except Exception:
                log.exception("santa: could not fill the empty parcels of %s", santa.pk)
            try:
                await self.announce_opening(santa)
            except Exception:
                log.exception("santa: could not announce the opening of %s", santa.pk)

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    async def announce_opening(self, santa: SecretSanta):
        """Say once that parcels can be opened. Never anything about a particular parcel."""
        now = timezone.now()
        if santa.announced_at is not None or santa.announce_to == AnnouncementScope.NONE:
            return
        if now < santa.opens_at or now > santa.closes_at:
            return
        waiting = await SantaGift.objects.filter(santa=santa, opened_at__isnull=True).acount()
        if not waiting:
            return
        embed = discord.Embed(
            title=f"{santa.label} — the parcels are open",
            colour=settings.embed_colour,
            description=f"**{waiting}** parcel(s) are waiting. Open yours with `/santa open`.",
        )
        embed.set_footer(text="Nobody is told who gave them theirs.")
        sent, _ = await announce_to_spawn_channels(self.bot, embed, scope=santa.announce_to)
        if sent:
            await SecretSanta.objects.filter(pk=santa.pk).aupdate(announced_at=now)

    # ── signing up and the list ─────────────────────────────────────────────────────────────────

    @app_commands.command()
    async def join(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Sign up for the Secret Santa.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.")
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            await ajoin(santa.pk, player.pk)
        except Refused as error:
            await interaction.followup.send(str(error))
            return
        await interaction.followup.send(
            f"You are in **{santa.name}**. Now write down what you would like, with `/santa wish` — "
            f"{santa.wishlist_size} slots, and whoever draws you picks one of them. Sign-ups close "
            f"{format_dt(santa.signup_closes_at, style='R')}."
        )

    @app_commands.command()
    @app_commands.describe(slot="Which slot on your list.", treasure="What you would like.")
    async def wish(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        slot: app_commands.Range[int, 1, 10],
        treasure: BallEnabledTransform,
    ):
        """
        Put a treasure on your list, in one of its slots.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.")
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            await aset_wish(santa.pk, player.pk, treasure.pk, slot)
        except Refused as error:
            await interaction.followup.send(str(error))
            return
        await interaction.followup.send(f"Slot {slot} of your list is **{treasure.country}**.")

    @app_commands.command()
    async def wishlist(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        What you have asked for.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.")
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        entry = await SantaEntry.objects.filter(santa=santa, player=player).afirst()
        if entry is None:
            await interaction.followup.send("You are not in this one. `/santa join` first.")
            return
        wishes = {wish.position: wish async for wish in entry.wishes.select_related("ball")}
        lines = [
            f"**{slot}.** {wishes[slot].cached_ball.country}" if slot in wishes else f"**{slot}.** *empty*"
            for slot in range(1, santa.wishlist_size + 1)
        ]
        if santa.drawn_at is None:
            lines.append("-# You can change it until the chain is drawn.")
        else:
            lines.append("-# The chain is drawn, so your list is settled now.")
        await interaction.followup.send(
            embed=discord.Embed(title="Your list", colour=settings.embed_colour, description="\n".join(lines))
        )

    @app_commands.command()
    async def target(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Who you are giving to, and what they asked for.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.")
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        entry = await SantaEntry.objects.filter(santa=santa, player=player).afirst()
        if entry is None:
            await interaction.followup.send("You are not in this one.")
            return
        if santa.drawn_at is None:
            await interaction.followup.send(
                f"The chain has not been drawn yet. Sign-ups close {format_dt(santa.signup_closes_at, style='R')}."
            )
            return
        if entry.gives_to_id is None:
            await interaction.followup.send(
                "You were not drawn into the chain — a list has to be written before the draw to be in it. "
                "You owe nobody a parcel."
            )
            return
        receiver = await SantaEntry.objects.filter(pk=entry.gives_to_id).select_related("player").afirst()
        if receiver is None:
            await interaction.followup.send("Whoever you were drawn to give to is no longer taking part.")
            return
        wishes = [wish.cached_ball.country async for wish in receiver.wishes.select_related("ball")]
        mine = await SantaGift.objects.filter(santa=santa, giver=entry).afirst()
        lines = [
            f"You are giving to <@{receiver.player.discord_id}>.",
            "",
            "**They asked for**",
            *([f"- {name}" for name in wishes] or ["- nothing they can be given"]),
        ]
        if mine is not None:
            lines.append("")
            lines.append(f"Your parcel is filled: **{mine.cached_ball.country}**. They open it on the day.")
        else:
            lines.append("")
            lines.append(
                "Fill it with `/santa gift` using one of your own cards"
                + (
                    f", or with `/santa pay` for {wallet.format_tokens(santa.event_pass, santa.price)}."
                    if santa.price
                    else "."
                )
            )
            lines.append(f"-# You have until {format_dt(santa.wrap_until, style='R')}.")
        await interaction.followup.send(
            embed=discord.Embed(title="Your Santa duty", colour=settings.embed_colour, description="\n".join(lines)),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ── filling and opening ─────────────────────────────────────────────────────────────────────

    @app_commands.command()
    @app_commands.describe(card="One of your cards, from their list. It will not come back.")
    async def gift(self, interaction: discord.Interaction["BallsDexBot"], card: BallInstanceTransform):
        """
        Fill your parcel with one of your own cards.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.")
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            gift = await awrap_card(santa.pk, player.pk, card.pk)
        except Refused as error:
            await interaction.followup.send(str(error))
            return
        await interaction.followup.send(
            f"**{gift.cached_ball.country}** is wrapped and on its way. They open it "
            f"{format_dt(santa.opens_at, style='R')}, and they will never know it was you."
        )

    @app_commands.command()
    @app_commands.describe(treasure="Which of their wishes to have made.")
    async def pay(self, interaction: discord.Interaction["BallsDexBot"], treasure: BallEnabledTransform):
        """
        Fill your parcel by paying for it, with the currency of the event.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.")
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            gift = await awrap_paid(santa.pk, player.pk, treasure.pk)
        except Refused as error:
            await interaction.followup.send(str(error))
            return
        await interaction.followup.send(
            f"Paid. **{gift.cached_ball.country}** is wrapped and on its way, and they open it "
            f"{format_dt(santa.opens_at, style='R')}."
        )

    @app_commands.command()
    async def open(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Open the parcel somebody wrapped for you.
        """
        await interaction.response.defer(thinking=True)
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.", ephemeral=True)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            opened = await aopen(santa.pk, player.pk, server_id=interaction.guild_id)
        except Refused as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        ball = opened.gift.cached_ball
        special = santa.cached_special
        embed = discord.Embed(
            title="\N{WRAPPED PRESENT} You got a parcel",
            colour=settings.embed_colour,
            description=f"**{ball.country}**"
            + (f", as a **{special.name}** card" if special else "")
            + f"\nATK {opened.instance.attack_bonus:+d}% · HP {opened.instance.health_bonus:+d}%",
        )
        embed.set_footer(text="Somebody picked it off your list. You will never know who.")
        await interaction.followup.send(embed=embed)

    # ── staff ───────────────────────────────────────────────────────────────────────────────────

    @admin.command(name="draw")
    async def admin_draw(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Draw the chain: everyone who wrote a list, shuffled into one circle of givers.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not await is_staff(interaction):
            await interaction.followup.send("That one is for staff.")
            return
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.")
            return
        try:
            count = await adraw(santa.pk)
        except Refused as error:
            await interaction.followup.send(str(error))
            return
        left_out = await SantaEntry.objects.filter(santa=santa, gives_to__isnull=True).acount()
        log.info("%s drew the chain of %s: %s players", interaction.user, santa.name, count, extra={"webhook": True})
        await interaction.followup.send(
            f"Drawn: a chain of **{count}** players."
            + (f" {left_out} signed up without a list and were left out." if left_out else "")
        )

    @admin.command(name="state")
    async def admin_state(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Where the exchange stands: signed up, drawn, wrapped, opened.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not await is_staff(interaction):
            await interaction.followup.send("That one is for staff.")
            return
        santa = await current_santa()
        if santa is None:
            await interaction.followup.send("No Secret Santa is set up.")
            return
        entries = await SantaEntry.objects.filter(santa=santa).acount()
        drawn = await SantaEntry.objects.filter(santa=santa, gives_to__isnull=False).acount()
        wrapped = await SantaGift.objects.filter(santa=santa).acount()
        opened = await SantaGift.objects.filter(santa=santa, opened_at__isnull=False).acount()
        by_hand = await SantaGift.objects.filter(
            santa=santa, kind__in=(SantaGift.Kind.CARD, SantaGift.Kind.PAID)
        ).acount()
        embed = discord.Embed(title=f"{santa.label} — where it stands", colour=settings.embed_colour)
        embed.add_field(name="Signed up", value=str(entries))
        embed.add_field(name="In the chain", value=str(drawn))
        embed.add_field(name="Parcels filled", value=f"{wrapped}/{drawn}")
        embed.add_field(name="Opened", value=str(opened))
        embed.add_field(name="Filled by a player", value=f"{by_hand}/{wrapped}")
        embed.set_footer(text="The last one is for you only. Players are never shown it.")
        await interaction.followup.send(embed=embed)
