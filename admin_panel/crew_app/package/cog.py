"""The player side of crews: who you fly with, and how the war is going."""

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from django.db.models import Sum

from bd_models.models import Player
from crew_app.models import Crew, CrewMembership, CrewWar, CrewWarEntry
from crew_app.scoring import standings, top_players
from settings.models import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.crew")

MEDALS = ("🥇", "🥈", "🥉")


class CrewCog(commands.GroupCog, group_name="crew"):
    """Crews and the war between them."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @app_commands.command(name="info")
    async def info(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Show the crew you fly with, and what you have brought it.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        membership = await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
        if membership is None:
            await interaction.followup.send(
                "You have not picked a crew yet. Choose one in `/player settings`.", ephemeral=True
            )
            return

        crew = membership.crew
        embed = discord.Embed(
            title=crew.label, colour=settings.embed_colour, description=crew.description or None
        )
        embed.add_field(name="Members", value=str(await crew.members.acount()))
        embed.add_field(name="Flying since", value=discord.utils.format_dt(membership.joined_at, style="D"))

        war = await self.current_war()
        if war is not None:
            mine = await CrewWarEntry.objects.filter(war=war, player=player).aaggregate(total=Sum("points"))
            ours = await CrewWarEntry.objects.filter(war=war, crew=crew).aaggregate(total=Sum("points"))
            embed.add_field(
                name=war.name,
                value=f"Your crew: **{ours['total'] or 0}** points\nYou brought: **{mine['total'] or 0}**",
                inline=False,
            )
        if crew.image:
            embed.set_image(url=f"{settings.site_base_url}/media/{crew.image.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="war")
    async def war(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        The standings of the crew war, and who is carrying their crew.
        """
        await interaction.response.defer(thinking=True)
        war = await self.current_war()
        if war is None:
            await interaction.followup.send("No crew war is running right now.")
            return

        crews = {crew.pk: crew async for crew in Crew.objects.all()}
        table = await standings(war)
        embed = discord.Embed(
            title=war.name, colour=settings.embed_colour, description=war.description or None
        )
        if table:
            embed.add_field(
                name="Standings",
                value="\n".join(
                    f"{MEDALS[rank] if rank < len(MEDALS) else f'**{rank + 1}.**'} "
                    f"{crews[crew_id].label if crew_id in crews else crew_id} — **{points}**"
                    for rank, (crew_id, points) in enumerate(table)
                )[:1024],
                inline=False,
            )
        else:
            embed.add_field(name="Standings", value="Nobody has scored yet.", inline=False)

        best = await top_players(war, limit=5)
        if best:
            names = []
            for rank, (player_id, points) in enumerate(best):
                discord_id = await Player.objects.filter(pk=player_id).values_list("discord_id", flat=True).afirst()
                names.append(f"{rank + 1}. <@{discord_id}> — **{points}**")
            embed.add_field(name="Top contributors", value="\n".join(names), inline=False)

        if war.ends_at:
            embed.add_field(name="Ends", value=discord.utils.format_dt(war.ends_at, style="R"), inline=False)
        if war.image:
            embed.set_image(url=f"{settings.site_base_url}/media/{war.image.name}")
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def current_war(self) -> CrewWar | None:
        """
        The war being scored right now, if there is one.

        Walked rather than filtered in the query, because whether a war is live depends on two
        nullable dates and the model, not on something the database can be asked for cheaply.
        """
        async for war in CrewWar.objects.filter(enabled=True):
            if war.is_live():
                return war
        return None
