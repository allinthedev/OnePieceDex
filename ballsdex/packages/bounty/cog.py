"""
Wanted posters: the announcement side of them.

Claiming one happens in the catch itself, in `ballsdex.packages.countryballs.countryball`, so
that the card comes out already carrying the special. All this cog does is put the poster up
in every spawn channel once the bounty opens.
"""

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks
from discord.utils import format_dt
from django.utils import timezone

from ballsdex.core.utils.broadcast import announce_to_spawn_channels
from bd_models.enums import AnnouncementScope
from bd_models.models import Bounty
from settings.models import settings
from settings.utils import format_currency

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.bounty")


class Bounties(commands.Cog):
    """Puts wanted posters up when their bounty opens."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def cog_load(self):
        self.put_up_posters.start()

    def cog_unload(self):
        self.put_up_posters.cancel()

    def poster(self, bounty: Bounty) -> discord.Embed:
        """The wanted poster itself."""
        ball = bounty.cached_ball
        embed = discord.Embed(
            title=f"WANTED — {ball.country}",
            colour=settings.embed_colour,
            description=bounty.announcement_text
            or f"A bounty is out on **{ball.country}**. The first to catch one takes it.",
        )
        if bounty.reward:
            embed.add_field(name="Reward", value=f"**{format_currency(bounty.reward, False, self.bot)}**")
        embed.add_field(name="Until", value=format_dt(bounty.ends_at, style="R"))
        if bounty.cached_special:
            embed.add_field(
                name="The card", value=f"Comes out as **{bounty.cached_special.name}**", inline=False
            )
        if ball.wild_card:
            embed.set_thumbnail(url=f"{settings.site_base_url}/media/{ball.wild_card}")
        embed.set_footer(text="Only the first catch collects it.")
        return embed

    @tasks.loop(minutes=2)
    async def put_up_posters(self):
        """
        Announce the bounties that have opened and not been announced yet.

        The date is written before the announcement goes out, and only when the row is still
        unannounced, so two overlapping runs of this loop cannot both post the same poster.

        It is written back to NULL when the poster reached nobody: a send that fails, or that
        finds no channel to post in because the main server or its spawn channel is not set up
        yet, used to leave the bounty marked as announced for good, with nothing ever posted.
        The next run tries again instead.
        """
        now = timezone.now()
        due = Bounty.objects.filter(
            announced_at__isnull=True, claimed_by__isnull=True, starts_at__lte=now, ends_at__gte=now
        ).select_related("ball", "special")
        async for bounty in due:
            claimed_the_announcement = await Bounty.objects.filter(
                pk=bounty.pk, announced_at__isnull=True
            ).aupdate(announced_at=now)
            if not claimed_the_announcement:
                continue
            await self.put_up_one(bounty)

    async def put_up_one(self, bounty: Bounty):
        """
        Post one poster, and hand the bounty back to the next run of the loop if it did not go out.

        A bounty announced nowhere is the one case where reaching no channel is the intent, so it
        stays marked as announced rather than being tried again every two minutes.
        """
        ball = bounty.cached_ball
        try:
            sent, missed = await announce_to_spawn_channels(self.bot, self.poster(bounty), scope=bounty.announce_to)
        except Exception:
            await self.announce_again(bounty)
            log.error(
                f"Wanted poster for {ball.country} ({bounty.reward:,}) could not go out. It stays unannounced "
                f"and the next run will try again.",
                exc_info=True,
                extra={"webhook": True},
            )
            return
        if not sent and bounty.announce_to != AnnouncementScope.NONE:
            await self.announce_again(bounty)
            log.warning(
                f"Wanted poster for {ball.country} ({bounty.reward:,}) reached no channel ({missed} missed). "
                f"Check the main server and its spawn channel; the next run will try again.",
                extra={"webhook": True},
            )
            return
        log.info(
            f"Wanted poster for {ball.country} ({bounty.reward:,}) went out to {sent} channels, {missed} missed.",
            extra={"webhook": True},
        )

    @staticmethod
    async def announce_again(bounty: Bounty):
        """Put the bounty back in the queue of the loop, so its poster is tried again."""
        await Bounty.objects.filter(pk=bounty.pk).aupdate(announced_at=None)

    @put_up_posters.before_loop
    async def before_put_up_posters(self):
        await self.bot.wait_until_ready()
