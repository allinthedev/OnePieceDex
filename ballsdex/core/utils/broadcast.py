"""
Posting one message in every server's spawn channel.

Shared by the things that announce themselves to everybody — a restocked shop, a wanted poster
— so they all behave the same under load and in the face of a server that cannot be reached.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

import discord

from bd_models.enums import AnnouncementScope
from bd_models.models import GuildConfig
from settings.models import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.core.utils.broadcast")

# a handful of servers at a time: announcing to hundreds all at once runs into the rate limit,
# and a rate limited announcement arrives late everywhere rather than quickly anywhere
CONCURRENCY = 10


async def announce_to_spawn_channels(
    bot: "BallsDexBot",
    embed: discord.Embed,
    *,
    scope: str = AnnouncementScope.ALL,
    concurrency: int = CONCURRENCY,
) -> tuple[int, int]:
    """
    Post an embed in the spawn channels the scope asks for. Returns `(sent, missed)`.

    A server whose channel has been deleted, or where the bot is no longer allowed to post, is
    counted as missed. One of those never stops the announcement reaching everybody else.

    Parameters
    ----------
    scope: str
        An `AnnouncementScope`: every spawn channel, the main server's only, or nowhere. The
        main server is the one named on the settings page; with none named, nothing is sent,
        because posting everywhere would be a worse guess than posting nowhere.
    """
    if scope == AnnouncementScope.NONE:
        return 0, 0

    channels = GuildConfig.objects.filter(enabled=True, spawn_channel__isnull=False)
    if scope == AnnouncementScope.MAIN:
        if not settings.main_server_id:
            log.warning("Announcement limited to the main server, but no main server is set. Nothing was sent.")
            return 0, 0
        channels = channels.filter(guild_id=settings.main_server_id)

    channel_ids = [channel_id async for channel_id in channels.values_list("spawn_channel", flat=True)]
    sent = missed = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def deliver(channel_id: int):
        nonlocal sent, missed
        channel = bot.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            missed += 1
            return
        async with semaphore:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                missed += 1
            else:
                sent += 1

    await asyncio.gather(*(deliver(channel_id) for channel_id in channel_ids))
    log.info("Announcement reached %s spawn channels, %s could not be reached.", sent, missed)
    return sent, missed
