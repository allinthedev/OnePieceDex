from typing import TYPE_CHECKING

from ballsdex.core.game_events import bus

from ..scoring import SUBSCRIBER, handle_event
from .cog import CrewCog

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    bus.subscribe(SUBSCRIBER, handle_event)
    await bot.add_cog(CrewCog(bot))


async def teardown(bot: "BallsDexBot"):
    bus.unsubscribe(SUBSCRIBER)
