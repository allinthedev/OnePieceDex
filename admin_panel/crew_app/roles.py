"""
The Discord role a crew carries, handed out on the main server and nowhere else.

A player picks their crew once and plays for it everywhere, but the role only means something in one place —
the dex's own server, where the channels and the colours are. Giving it out in every server the bot sits in
would need permissions in all of them and would mean nothing in most, so the main server is the whole scope of
this module, on purpose.

Nothing here reads `guild.members`. That list is only filled when the privileged members intent is on, and a
bot in more than a hundred servers cannot simply switch it on — it needs Discord to approve it. Being
Administrator on the server does not help: permissions say what the bot may do, the intent says what Discord
sends it. So members are looked up one by one instead, from the players the database says are in a crew.

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

# how many members one gateway query asks for at a time; Discord allows a hundred
QUERY_BATCH = 100


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


async def find_member(guild: discord.Guild, discord_id: int) -> discord.Member | None:
    """
    One member of the main server, cache first and Discord second.

    Without the members intent the cache is nearly empty, so the fetch is the path that actually runs. It costs
    one request and returns None for somebody who is not on the server, which is an ordinary answer here rather
    than a failure.
    """
    member = guild.get_member(discord_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(discord_id)
    except discord.NotFound:
        return None
    except discord.HTTPException:
        log.exception("crew roles: could not look up %s on the main server", discord_id)
        return None


async def apply_to_member(
    guild: discord.Guild, member: discord.Member, crew: Crew | None, every_role: set[int]
) -> bool:
    """
    Put one member's crew roles right: their crew's role on, every other crew's role off.

    Returns whether anything changed. Safe to run on somebody already in the right state, since it works out
    the difference first and does nothing when there is none.
    """
    wanted_id = crew.role_id if crew is not None else None
    held = {role.id for role in member.roles}
    to_remove = [guild.get_role(role_id) for role_id in (held & every_role) - {wanted_id}]
    to_remove = [role for role in to_remove if role is not None]
    to_add = []
    if wanted_id and wanted_id not in held:
        role = guild.get_role(wanted_id)
        if role is None:
            log.warning("crew roles: role %s is set on a crew but not on the server", wanted_id)
        else:
            to_add.append(role)
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
            member.id,
        )
        return False
    except discord.HTTPException:
        log.exception("crew roles: could not change the roles of %s", member.id)
        return False
    return True


async def apply(bot: "BallsDexBot", discord_id: int, crew: Crew | None) -> bool:
    """Put one player's crew roles right on the main server, looking them up if they are not cached."""
    guild = main_guild(bot)
    if guild is None:
        return False
    every_role = set((await role_ids()).values())
    if not every_role:
        return False
    member = await find_member(guild, discord_id)
    if member is None:
        return False  # not on the main server, nothing to give them
    return await apply_to_member(guild, member, crew, every_role)


async def apply_to_player(bot: "BallsDexBot", player: "Player") -> bool:
    """The same, for a player whose crew is read from the database rather than handed in."""
    membership = await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
    return await apply(bot, int(player.discord_id), membership.crew if membership else None)


async def sync_everyone(bot: "BallsDexBot") -> tuple[int, int, int]:
    """
    Put the crew role right for everyone the database says is in a crew.

    Returns (changed, found on the server, in a crew at all) — the gap between the last two is the people
    who picked a crew but have never set foot on the main server, which is normal and worth seeing.

    Driven by the membership table rather than by the server's member list, because that list is empty without
    the privileged members intent. Members are asked for in batches over the gateway, which fills the cache for
    the ones who are on the server; anyone the batch did not bring back is simply not there.
    """
    guild = main_guild(bot)
    if guild is None:
        return 0, 0, 0
    by_crew = {crew.pk: crew async for crew in Crew.objects.exclude(role_id__isnull=True)}
    if not by_crew:
        return 0, 0, 0
    every_role = {crew.role_id for crew in by_crew.values() if crew.role_id}

    wanted: list[tuple[int, Crew]] = []
    async for discord_id, crew_id in CrewMembership.objects.filter(crew_id__in=by_crew).values_list(
        "player__discord_id", "crew_id"
    ):
        crew = by_crew.get(crew_id)
        if crew is not None:
            wanted.append((int(discord_id), crew))

    changed = looked = 0
    for start in range(0, len(wanted), QUERY_BATCH):
        batch = wanted[start : start + QUERY_BATCH]
        try:
            # one gateway round trip for up to a hundred of them, which fills the cache for the next step
            await guild.query_members(user_ids=[discord_id for discord_id, _ in batch], cache=True)
        except Exception:
            # asking by ID is allowed without the members intent, but if it is refused the lookups below
            # still work one at a time — slower, never wrong
            log.debug("crew roles: batch lookup refused, falling back to one request each")
        for discord_id, crew in batch:
            member = await find_member(guild, discord_id)
            if member is None:
                continue
            looked += 1
            if await apply_to_member(guild, member, crew, every_role):
                changed += 1
    return changed, looked, len(wanted)
