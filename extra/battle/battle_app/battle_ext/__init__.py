import logging
from typing import TYPE_CHECKING

from . import sessions
from .cog import Battle

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.battle")


async def _refund_orphaned_sessions() -> list[int]:
    """
    What a restart leaves behind: every battle still open, started or not.

    The buttons of a battle live in the process that posted them. Once that process is gone nothing will
    ever play those battles again, however recent they are, and their players would be told they are
    "already in another battle" until somebody closed them by hand. So they are all called off, and a
    wager already taken goes back to both players.
    """
    closed = await sessions.acancel_all(stale_only=False)
    if closed:
        log.info("Called off %s battle(s) left open by the last run: %s", len(closed), closed)
    return closed


async def _refund_stale_sessions() -> list[int]:
    """
    What a reload of the package may close: only the battles nobody has touched for half an hour.

    A reload keeps the process, and with it the boards and their buttons: a battle being played goes on
    being played, and calling it off under its players would be the bug.
    """
    closed = await sessions.acancel_all(stale_only=True)
    if closed:
        log.info("Called off %s abandoned battle(s): %s", len(closed), closed)
    return closed


async def setup(bot: "BallsDexBot"):
    cog = Battle(bot)
    # the package is loaded before the bot has connected at startup, and long after on a reload
    if bot.is_ready():
        await _refund_stale_sessions()
        await cog.resume_timers()
    else:
        await _refund_orphaned_sessions()
    await bot.add_cog(cog)
