"""
The Discord role a crew carries, handed out on the main server and nowhere else.

A player picks their crew once and plays for it everywhere, but the role only means something in one place —
the dex's own server, where the channels and the colours are. Giving it out in every server the bot sits in
would need permissions in all of them and would mean nothing in most, so the main server is the whole scope of
this module, on purpose.

Nothing in here ever raises at its caller. A role that cannot be given — the bot missing Manage Roles, the role
sitting above the bot in the list, the player not even being on the server — is logged and moved past: picking
a crew must never fail because of what Discord would or would not allow.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from settings.models import settings

from .models import Crew, CrewMembership

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot
    from bd_models.models import Player

log = logging.getLogger("crew.roles")


def main_guild(bot: "BallsDexBot") -> discord.Guild | None:
    """The server the crew roles live on, or None when none is set up."""
    if not settings.main_server_id:
        return None
    return bot.get_guild(settings.main_server_id)


async def role_ids() -> dict[int, int]:
    """Every crew that carries a role, as {crew id: role id}."""
    return {
        crew_id: role_id
        async for crew_id, role_id in Crew.objects.exclude(role_id__isnull=True).values_list("pk", "role_id")
    }


async def apply(bot: "BallsDexBot", discord_id: int, crew: Crew | None) -> bool:
    """
    Put one member's crew roles right on the main server: their crew's role on, every other crew's role off.

    Returns whether anything was changed. Called when a player picks a crew, when they drop it, and when they
    join the server, so it has to be safe to run again on somebody already in the right state — it is, since it
    works out the difference first and does nothing when there is none.
    """
    guild = main_guild(bot)
    if guild is None:
        return False
    member = guild.get_member(discord_id)
    if member is None:
        return False  # not on the main server, nothing to give them

    wanted_id = crew.role_id if crew is not None else None
    every_role = set((await role_ids()).values())
    if not every_role:
        return False

    held = {role.id for role in member.roles}
    to_remove = [guild.get_role(role_id) for role_id in (held & every_role) - {wanted_id}]
    to_add = []
    if wanted_id and wanted_id not in held:
        role = guild.get_role(wanted_id)
        if role is None:
            log.warning("crew roles: role %s is set on a crew but not on the server", wanted_id)
        else:
            to_add.append(role)
    to_remove = [role for role in to_remove if role is not None]
    if not to_add and not to_remove:
        return False

    try:
        if to_remove:
            await member.remove_roles(*to_remove, reason="Crew change")
        if to_add:
            await member.add_roles(*to_add, reason="Crew change")
    except discord.Forbidden:
        log.warning(
            "crew roles: not allowed to change the roles of %s. The bot needs Manage Roles, and its own "
            "highest role has to sit above the crew roles.",
            discord_id,
        )
        return False
    except discord.HTTPException:
        log.exception("crew roles: could not change the roles of %s", discord_id)
        return False
    return True


async def apply_to_player(bot: "BallsDexBot", player: "Player") -> bool:
    """The same, for a player whose crew is read from the database rather than handed in."""
    membership = await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
    return await apply(bot, int(player.discord_id), membership.crew if membership else None)


async def sync_everyone(bot: "BallsDexBot") -> tuple[int, int]:
    """
    Run over every member of the main server and put their crew role right. Returns (changed, looked at).

    Only the members already in the cache are walked, which is every one of them on a server the bot has the
    members intent for. Meant for the admin command after the roles are first set up, or after someone has been
    moving them around by hand.
    """
    guild = main_guild(bot)
    if guild is None:
        return 0, 0
    crews = {
        discord_id: crew_id
        async for discord_id, crew_id in CrewMembership.objects.values_list("player__discord_id", "crew_id")
    }
    by_crew = {crew.pk: crew async for crew in Crew.objects.exclude(role_id__isnull=True)}
    changed = looked = 0
    for member in guild.members:
        if member.bot:
            continue
        looked += 1
        crew = by_crew.get(crews.get(member.id, 0))
        if await apply(bot, member.id, crew):
            changed += 1
    return changed, looked
