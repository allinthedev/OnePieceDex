"""
The /advent commands: look at the calendar, open today's door, and buy open a door you missed.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from discord.utils import format_dt
from django.utils import timezone

from ballsdex.core.utils.broadcast import announce_to_spawn_channels
from bd_models.enums import AnnouncementScope
from bd_models.models import Player
from settings.models import settings

from ..grid import draw_calendar
from ..models import AdventCalendar, AdventOpening, door_date
from ..opening import Opened, Refused, open_door, today_utc

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("advent")


async def current_calendar() -> AdventCalendar | None:
    """
    The calendar being played: the running one, else the most recent, so the grid can still be looked at the
    day before it starts and the week after it ends.
    """
    found = [
        calendar
        async for calendar in AdventCalendar.objects.filter(enabled=True)
        .select_related("event_pass")
        .order_by("-starts_on", "-pk")
    ]
    if not found:
        return None
    for calendar in found:
        if calendar.day_today() is not None:
            return calendar
    return found[0]


class AdventCog(commands.GroupCog, name="Advent", group_name="advent"):
    """One door a day."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def picture(self, calendar: AdventCalendar, opened: set[int], today: int) -> discord.File:
        """The grid, drawn in a thread so a busy calendar never blocks the gateway."""
        subtitle = f"{len(opened)}/{calendar.door_count} opened"
        if today:
            subtitle += f" · today is door {today}"
        with ThreadPoolExecutor() as pool:
            buffer = await self.bot.loop.run_in_executor(
                pool,
                lambda: draw_calendar(
                    calendar.door_count,
                    opened,
                    today,
                    title=calendar.name,
                    subtitle=subtitle,
                    background=calendar.background or None,
                    can_catch_up=bool(calendar.catch_up_price) and timezone.now() <= calendar.closes_at,
                ),
            )
        return discord.File(buffer, "advent.png")

    @app_commands.command()
    async def view(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        The calendar, and which doors you have opened.
        """
        await interaction.response.defer(thinking=True)
        calendar = await current_calendar()
        if calendar is None:
            await interaction.followup.send("No advent calendar is set up.", ephemeral=True)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        opened = {
            day
            async for day in AdventOpening.objects.filter(calendar=calendar, player=player).values_list(
                "day", flat=True
            )
        }
        today = calendar.day_today() or 0
        picture = await self.picture(calendar, opened, today)

        lines = [calendar.description.strip()] if calendar.description.strip() else []
        if today and today not in opened:
            lines.append(f"**Door {today} is waiting for you.** Open it with `/advent open`.")
        elif today:
            lines.append(f"Door {today} is open. Come back tomorrow.")
        elif timezone.now().date() < calendar.starts_on:
            lines.append(f"It starts on {calendar.starts_on:%d %B}.")
        else:
            lines.append("The calendar is over.")

        missed = [
            day
            for day in range(1, (today or calendar.door_count + 1))
            if day not in opened and day <= calendar.door_count
        ]
        if missed and calendar.catch_up_price and timezone.now() <= calendar.closes_at:
            lines.append(
                f"-# {len(missed)} door(s) missed. Each can be bought open for "
                f"**{calendar.catch_up_price:,}** berries with `/advent catchup`, until "
                f"{format_dt(calendar.closes_at, style='D')}."
            )
        elif missed:
            lines.append(f"-# {len(missed)} door(s) missed, and this calendar has no catching up.")

        embed = discord.Embed(title=calendar.label, colour=settings.embed_colour, description="\n".join(lines))
        embed.set_image(url="attachment://advent.png")
        await interaction.followup.send(embed=embed, file=picture)

    @app_commands.command()
    async def open(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Open today's door.
        """
        await interaction.response.defer(thinking=True)
        calendar = await current_calendar()
        if calendar is None:
            await interaction.followup.send("No advent calendar is set up.", ephemeral=True)
            return
        today = calendar.day_today()
        if today is None:
            when = (
                f"It starts on {calendar.starts_on:%d %B}."
                if today_utc() < calendar.starts_on
                else "The calendar is over."
            )
            await interaction.followup.send(when, ephemeral=True)
            return
        await self.hand_over(interaction, calendar, today)

    @app_commands.command()
    @app_commands.describe(day="The door you missed.")
    async def catchup(self, interaction: discord.Interaction["BallsDexBot"], day: app_commands.Range[int, 1, 31]):
        """
        Buy open a door whose day has gone by, in berries.
        """
        await interaction.response.defer(thinking=True)
        calendar = await current_calendar()
        if calendar is None:
            await interaction.followup.send("No advent calendar is set up.", ephemeral=True)
            return
        await self.hand_over(interaction, calendar, day)

    async def hand_over(self, interaction: discord.Interaction["BallsDexBot"], calendar: AdventCalendar, day: int):
        """Open one door and say what came out of it, or why it could not be opened."""
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            result: Opened = await sync_to_async(open_door)(
                calendar.pk, player.pk, day, server_id=interaction.guild_id, channel_id=interaction.channel_id
            )
        except Refused as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        opens_on = door_date(calendar.starts_on, day)
        embed = discord.Embed(
            title=f"Door {day} — {opens_on:%d %B}",
            colour=settings.embed_colour,
            description="\n".join(f"- {line}" for line in result.lines) or "It was empty.",
        )
        if result.message:
            embed.add_field(name="​", value=result.message, inline=False)
        if result.paid:
            embed.set_footer(text=f"Bought open for {result.paid:,} berries.")
        if result.surprise is not None:
            extra = "\n".join(f"- {line}" for line in result.surprise_lines)
            value = result.surprise.description.strip() or "Something extra."
            if extra:
                value += f"\n{extra}"
            if result.boost:
                value += f"\n**{result.boost}** is now running for everyone."
            embed.add_field(name=f"Surprise! {result.surprise.label}", value=value[:1024], inline=False)
        for reached in result.streaks:
            embed.add_field(
                name=f"{reached.streak.doors} doors opened",
                value=(reached.streak.message.strip() + "\n" if reached.streak.message.strip() else "")
                + ("\n".join(f"- {line}" for line in reached.lines) or "—"),
                inline=False,
            )
        embed.add_field(name="So far", value=f"{result.opened_total}/{calendar.door_count} doors", inline=False)
        await interaction.followup.send(embed=embed)

        if result.surprise is not None and calendar.announce_to != AnnouncementScope.NONE:
            await self.shout(interaction, calendar, result)

    async def shout(self, interaction: discord.Interaction["BallsDexBot"], calendar: AdventCalendar, result: Opened):
        """Tell the servers about a surprise. A failure here never spoils the player's own door."""
        if result.surprise is None:
            return
        embed = discord.Embed(
            title=f"{result.surprise.label}",
            colour=settings.embed_colour,
            description=f"**{interaction.user}** opened door {result.day} of {calendar.name} and set this off."
            + (f"\n**{result.boost}** is running for everyone now." if result.boost else ""),
        )
        try:
            sent, missed = await announce_to_spawn_channels(self.bot, embed, scope=calendar.announce_to)
        except Exception:
            log.exception("could not announce an advent surprise")
            return
        log.info("advent surprise announced to %s channels, %s missed", sent, missed)
