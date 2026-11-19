from typing import TYPE_CHECKING

from .webhook import start_webhook_server, stop_webhook_server

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await start_webhook_server(bot)


async def teardown(bot: "BallsDexBot"):
    await stop_webhook_server()
