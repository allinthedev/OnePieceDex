import logging
from typing import TYPE_CHECKING

from discord import app_commands

from .cog import Admin

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.admin")

# Discord refuses any command whose JSON payload passes this, and refuses the whole tree along
# with it — one oversized command stops every other command from syncing.
COMMAND_SIZE_LIMIT = 8000
# stripping starts just below the limit, so descriptions are only given up when they genuinely
# do not fit. The margin is small because the tree is already nearly full: anyone adding a flag
# should expect to trip this and should shorten something rather than raise the number.
COMMAND_SIZE_BUDGET = 7900


def _measure(command: app_commands.Command | app_commands.Group) -> int:
    """Names, descriptions and choices of one command and everything under it, as Discord adds them up."""
    total = len(command.name) + len(command.description)
    if isinstance(command, app_commands.Group):
        for child in command.commands:
            total += _measure(child)
        return total
    for param in command.parameters:
        total += len(param.name) + len(param.description)
        for choice in param.choices:
            total += len(choice.name) + len(str(choice.value))
    return total


def command_size(cog: Admin) -> int:
    """
    How long `/admin` is in the terms Discord measures it: every name, description and choice
    under the group, added together.

    This used to walk the cog's own app commands, which missed almost everything — the
    subgroups are attached to the group in `Admin.__init__` rather than declared on the class,
    so `walk_app_commands` never saw them. The figure came out far too low and the guard below
    never fired, which is how an oversized `/admin` could take the whole command tree down with
    it. Walking the group itself is what makes the count match what Discord refuses.

    Returns 0 if the group cannot be read, which leaves the descriptions alone rather than
    stripping them over a measurement that did not work.
    """
    try:
        return _measure(cog.admin.app_command)  # type: ignore[union-attr,arg-type]
    except Exception:
        log.exception("Could not measure the size of /admin, leaving its descriptions alone.")
        return 0


def strip_descriptions(cog: Admin):
    for command in cog.walk_app_commands():
        command.description = "."
        if isinstance(command, app_commands.Group):
            continue
        for param in command.parameters:
            param._Parameter__parent.description = "."  # type: ignore


async def setup(bot: "BallsDexBot"):
    n = Admin(bot)
    size = command_size(n)
    if size > COMMAND_SIZE_BUDGET:
        strip_descriptions(n)
        log.warning(
            "/admin is %s characters, over the %s budget (Discord refuses %s): descriptions stripped so the "
            "command tree can still sync. Shorten some descriptions to get them back.",
            size,
            COMMAND_SIZE_BUDGET,
            COMMAND_SIZE_LIMIT,
        )
    else:
        log.debug("/admin is %s characters, under the %s budget.", size, COMMAND_SIZE_BUDGET)
    await bot.add_cog(n)
