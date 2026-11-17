import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.boss")


async def setup(bot: "BallsDexBot"):
    log.info("Loading Boss package...")
    from .cog import Boss

    await bot.add_cog(Boss(bot))
    log.info("Boss package loaded successfully!")
