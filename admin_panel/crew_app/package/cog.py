"""The player side of crews: who you fly with, how the war is going, and what it pays."""

import logging
from typing import TYPE_CHECKING

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands, tasks
from django.db.models import Sum
from django.utils import timezone

from ballsdex.core.game_events import Event, EventContext, bus
from ballsdex.core.utils.broadcast import announce_to_spawn_channels
from ballsdex.core.utils.checks import app_check, has_permissions
from ballsdex.core.utils.leaderboard import EXTRA_ROWS, LEADERBOARD_SIZE, send_leaderboard
from bd_models.models import Player
from crew_app.models import Crew, CrewMembership, CrewWar, CrewWarEntry, CrewWarPayout, CrewWarReward, CrewWarRule
from crew_app.payouts import hand_out, ladder
from crew_app.roles import apply_to_player, main_guild, sync_everyone
from crew_app.scoring import (
    award,
    discord_ranking,
    last_gain,
    name_of,
    place_of,
    player_points,
    players_scored,
    standings,
    top_players,
)
from settings.models import settings
from settings.utils import format_currency

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.crew")

MEDALS = ("🥇", "🥈", "🥉")
# what one embed field holds, and how many of them the table of crews may spend on itself: an
# embed is capped at 6000 characters all told, and the rest of it has to fit too
FIELD_LIMIT = 1024
STANDINGS_FIELDS = 5
BLANK = "​"  # a zero-width space: an embed field has to be given a name, and this reads as none
REACHED = "✅"
LOCKED = "⬜"
REPLACED = "↩️"


def medal(place: int) -> str:
    """The marker for a place in a table: a medal for the podium, the number for the rest."""
    return MEDALS[place - 1] if 1 <= place <= len(MEDALS) else f"**{place}.**"


def placed(table: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """
    `(place, key, points)` for a sorted table, where a draw shares a place.

    Two crews tied at the top are both first, and the crew behind them is third. Anything else
    hands a place to one of them for a draw neither of them lost.
    """
    rows = []
    place = 0
    previous = None
    for index, (key, points) in enumerate(table, start=1):
        if points != previous:
            place, previous = index, points
        rows.append((place, key, points))
    return rows


def chunked(lines: list[str], limit: int = FIELD_LIMIT) -> list[list[str]]:
    """
    Pack lines into blocks no longer than one embed field holds, breaking only between lines.

    A table of 46 crews runs well past a field's 1024 characters, and a table simply cut there
    loses the crews at the bottom without saying so — which is how half a dex goes missing.
    """
    blocks: list[list[str]] = [[]]
    length = 0
    for line in lines:
        if blocks[-1] and length + len(line) + 1 > limit:
            blocks.append([])
            length = 0
        blocks[-1].append(line)
        length += len(line) + 1
    return [block for block in blocks if block]


class CrewCog(commands.GroupCog, group_name="crew"):
    """Crews and the war between them."""

    admin = app_commands.Group(name="admin", description="Crew war administration.")

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        # wars that reached their end date with an empty ladder, so the complaint about each one
        # is made once rather than every couple of minutes. Deliberately not written down: a
        # restart saying it again is the point, and a ladder filled in late clears it by paying.
        self._nothing_to_pay: set[int] = set()

    async def cog_load(self):
        self.announce_rewards.start()

    def cog_unload(self):
        self.announce_rewards.cancel()

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
        embed = discord.Embed(title=crew.label, colour=settings.embed_colour, description=crew.description or None)
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
        embed = discord.Embed(title=war.name, colour=settings.embed_colour, description=war.description or None)
        if table:
            embed.add_field(
                name="Standings",
                value="\n".join(
                    f"{medal(place)} {crews[crew_id].label if crew_id in crews else crew_id} — **{points:,}**"
                    for place, crew_id, points in placed(table)
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
                names.append(f"{rank + 1}. <@{discord_id}> — **{points:,}**")
            embed.add_field(name="Top contributors", value="\n".join(names), inline=False)

        # a war scores nothing an admin has not asked it to, so this list is the war's own and
        # worth showing: without it the only way to learn what pays is to be told in a channel
        rules = [
            rule
            async for rule in CrewWarRule.objects.filter(war=war)
            .exclude(points=0)
            .select_related("ball", "special", "collector", "tier_level")
            .order_by("-points", "source")
        ]
        if rules:
            kept: list[str] = []
            for rule in rules:
                line = f"{rule.label} — **{rule.points:+d}**"
                if rule.daily_cap:
                    line += f" *(up to {rule.daily_cap} a day)*"
                if rule.minimum_value:
                    line += f" *(from {rule.minimum_value:,} berries)*"
                # an embed field stops at 1024 characters, and with every deed scored the list
                # reaches it. The smallest earners are the ones worth dropping, which is why
                # the rules were read best-paying first.
                if len("\n".join([*kept, line, "…"])) > 1024:
                    kept.append("…")
                    break
                kept.append(line)
            embed.add_field(name="How to score", value="\n".join(kept), inline=False)

        if await CrewWarReward.objects.filter(war=war).aexists():
            embed.add_field(name="​", value="-# `/crew rewards` for what the war pays out.", inline=False)
        if war.ends_at:
            embed.add_field(name="Ends", value=discord.utils.format_dt(war.ends_at, style="R"), inline=False)
        if war.image:
            embed.set_image(url=f"{settings.site_base_url}/media/{war.image.name}")
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="leaderboard")
    @app_commands.describe(crew="One crew, to see its own top 20 instead of the table of crews")
    async def leaderboard(self, interaction: discord.Interaction["BallsDexBot"], crew: str | None = None):
        """
        The crew war table, or the top 20 of one crew.
        """
        await interaction.response.defer(thinking=True)
        war = await self.current_war()
        if war is None:
            await interaction.followup.send("No crew war is running right now.")
            return
        if crew is None:
            await interaction.followup.send(
                embed=await self.crew_table(war), allowed_mentions=discord.AllowedMentions.none()
            )
            return

        found = await Crew.objects.filter(name__iexact=crew).afirst()
        if found is None:
            await interaction.followup.send(f"There is no crew called **{crew}**.", ephemeral=True)
            return
        ranking = await discord_ranking(war, crew_id=found.pk, limit=LEADERBOARD_SIZE + EXTRA_ROWS)
        if not ranking:
            await interaction.followup.send(f"Nobody has scored for **{found.name}** yet.", ephemeral=True)
            return
        brought = await CrewWarEntry.objects.filter(war=war, crew=found).aaggregate(total=Sum("points"))
        members = await players_scored(war, crew_id=found.pk)
        await send_leaderboard(
            interaction,
            title=f"{found.name} — {war.name}",
            subtitle=f"{brought['total'] or 0:,} points brought by {members:,} member(s)",
            ranking=ranking,
            describe=lambda points: f"Points: {points:,}",
        )

    @leaderboard.autocomplete("crew")
    async def crew_autocomplete(self, interaction: discord.Interaction["BallsDexBot"], current: str):
        names = [
            name
            async for name in Crew.objects.order_by("position", "name").values_list("name", flat=True)
            if current.casefold() in name.casefold()
        ]
        return [app_commands.Choice(name=name, value=name) for name in names[:25]]

    @app_commands.command(name="user")
    @app_commands.describe(user="Whose card to show. Yours when left empty.")
    async def user(self, interaction: discord.Interaction["BallsDexBot"], user: discord.User | None = None):
        """
        A player's card in the crew war: their flag, their points and where they stand.
        """
        await interaction.response.defer(thinking=True)
        target = user or interaction.user
        embed = discord.Embed(title=target.display_name, colour=settings.embed_colour)
        embed.set_thumbnail(url=target.display_avatar.url)

        player = await Player.objects.filter(discord_id=target.id).afirst()
        membership = None
        if player is not None:
            membership = await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
        if membership is None:
            embed.description = "Flies no flag yet. A crew is picked in `/player settings`."
            await interaction.followup.send(embed=embed)
            return

        crew = membership.crew
        embed.description = f"Flying {crew.label} since {discord.utils.format_dt(membership.joined_at, style='D')}"
        war = await self.current_war()
        if war is None:
            embed.add_field(name="The war", value="No crew war is running right now.", inline=False)
            await interaction.followup.send(embed=embed)
            return

        points = await player_points(war, player.pk)
        latest = await last_gain(war, player.pk)
        if latest is None:
            # nothing scored means no place to stand in: a made-up "last of 60" would read as a
            # ranking rather than as an absence
            embed.add_field(name="Points", value="**0**")
            embed.add_field(
                name="Not on the table yet",
                value="Nothing scored for this war so far. `/crew war` lists what pays.",
                inline=False,
            )
        else:
            embed.add_field(name="Points", value=f"**{points:,}**")
            embed.add_field(name="Overall", value=f"**{await place_of(war, points)}** of {await players_scored(war)}")
            embed.add_field(
                name=f"Within {crew.name}"[:256],
                value=f"**{await place_of(war, points, crew_id=crew.pk)}** of "
                f"{await players_scored(war, crew_id=crew.pk)}",
            )
            embed.add_field(
                name="Last earned",
                value=f"**{latest.points:+d}** — {name_of(latest)}\n"
                f"{discord.utils.format_dt(latest.created_at, style='R')}",
                inline=False,
            )
        if crew.image:
            embed.set_image(url=f"{settings.site_base_url}/media/{crew.image.name}")
        embed.set_footer(text=war.name)
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="rewards")
    async def rewards(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        What the crew war pays out, and how far up the ladder you are.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        war = await self.current_war()
        if war is None:
            await interaction.followup.send("No crew war is running right now.", ephemeral=True)
            return
        rungs = [
            rung
            async for rung in CrewWarReward.objects.filter(war=war)
            .prefetch_related("cards__ball", "cards__special")
            .order_by("scope", "threshold")
        ]
        if not rungs:
            await interaction.followup.send(f"**{war.name}** has no rewards set yet.", ephemeral=True)
            return

        player = await Player.objects.filter(discord_id=interaction.user.id).afirst()
        points = await player_points(war, player.pk) if player is not None else 0
        membership = None
        if player is not None:
            membership = await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
        crew = membership.crew if membership is not None else None
        place = None
        if crew is not None:
            places = {crew_id: place for place, crew_id, _ in placed(await standings(war))}
            place = places.get(crew.pk)

        embed = discord.Embed(
            title=f"{war.name} — rewards",
            colour=settings.embed_colour,
            description="Handed out when the war ends. You keep what you have reached even if you slide back "
            "down the table afterwards — the ladder is read once, at the end.",
        )
        mine = [rung for rung in rungs if not rung.is_crew_reward]
        theirs = [rung for rung in rungs if rung.is_crew_reward]
        if mine:
            # the same walk the payout does, so the ticks say what the player will actually get
            # rather than what they have merely passed: a rung that does not stack hides the
            # ones under it, and showing those as earned would be a promise nobody keeps
            earned = {rung.pk for rung in ladder(sorted(mine, key=lambda r: r.threshold, reverse=True), points)}

            def status(rung):
                if rung.pk in earned:
                    return REACHED
                return REPLACED if points >= rung.threshold else LOCKED

            text = self.ladder_text(mine, status)
            if REPLACED in text:
                text += f"\n-# {REPLACED} reached, but a higher rung replaces it."
            embed.add_field(name=f"For your own points — you have **{points:,}**", value=text, inline=False)
        if theirs:
            standing = f" — {crew.name} is {self.place_text(place)}" if crew is not None and place else ""
            embed.add_field(
                name=f"For your crew's place{standing}"[:256],
                value=self.ladder_text(
                    theirs, lambda rung: REACHED if place is not None and rung.threshold in (0, place) else LOCKED
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @admin.command(name="points")
    @app_check(has_permissions("crew_app.add_crewwarentry"))
    @app_commands.describe(
        user="Who earned them. The points go to the crew they fly with.",
        points="How many to add. A negative number takes points off.",
        reason="What they were for. Shown to the player as what they last earned.",
    )
    async def admin_points(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        user: discord.User,
        points: int,
        reason: str | None = None,
    ):
        """
        Give a player's crew points by hand, for what no rule can see.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        war = await self.current_war()
        if war is None:
            await interaction.followup.send("No crew war is running, so there is nothing to score for.")
            return
        if not points:
            await interaction.followup.send("Zero points would write a line and change nothing.")
            return

        player = await Player.objects.filter(discord_id=user.id).afirst()
        membership = (
            await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
            if player is not None
            else None
        )
        if player is None or membership is None:
            await interaction.followup.send(
                f"{user.display_name} flies no flag, so there is no crew to pay. They pick one in `/player settings`.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        crew = membership.crew
        await award(war, player.pk, crew.pk, points, note=reason or "")
        mine = await player_points(war, player.pk)
        ours = await CrewWarEntry.objects.filter(war=war, crew=crew).aaggregate(total=Sum("points"))
        log.info(
            "crew war: %s gave %s %+d point(s) for %s", interaction.user.id, user.id, points, reason or "no reason"
        )
        told = f"Written as: {reason}" if reason else "No reason given."
        await interaction.followup.send(
            f"**{points:+d}** to {crew.label}, through {user.display_name}. "
            f"They are now on **{mine:,}** and their crew on **{ours['total'] or 0:,}**. {told}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    def ladder_text(self, rungs: list[CrewWarReward], status) -> str:
        """
        One line per rung, marked by `status(rung)`, truncated to fit an embed field.
        """
        kept: list[str] = []
        for rung in rungs:
            pays = []
            if rung.money:
                pays.append(format_currency(rung.money, False, self.bot))
            pays += [card.label for card in rung.cards.all()]
            if rung.is_crew_reward:
                asked = self.place_text(rung.threshold)
            else:
                asked = f"{rung.threshold:,} point" + ("" if rung.threshold == 1 else "s")
            line = f"{status(rung)} **{rung.name}** — {asked}"
            line += f"\n-# {' · '.join(pays) or 'nothing set yet'}"
            if not rung.is_crew_reward and not rung.cumulative:
                line += " *(this rung only, nothing below it)*"
            if len("\n".join([*kept, line, "…"])) > 1024:
                kept.append("…")
                break
            kept.append(line)
        return "\n".join(kept)

    @staticmethod
    def place_text(threshold: int) -> str:
        """How a crew rung reads: a finishing place, or every crew that scored."""
        if not threshold:
            return "any crew that scored"
        if threshold <= len(MEDALS):
            return f"{MEDALS[threshold - 1]} place {threshold}"
        return f"place {threshold}"

    # ── the Discord role a crew carries ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Give a returning player their crew's role back when they join the main server.

        Without this, anyone who picked a crew before ever setting foot on the main server — or who left and
        came back — would be in a crew the server cannot see.
        """
        if member.bot or not settings.main_server_id or member.guild.id != settings.main_server_id:
            return
        player = await Player.objects.filter(discord_id=member.id).afirst()
        if player is None:
            return
        try:
            await apply_to_player(self.bot, player)
        except Exception:
            log.exception("crew roles: could not set up %s on joining", member.id)

    @admin.command(name="syncroles")
    @app_check(has_permissions("crew_app.change_crew"))
    async def admin_syncroles(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Put everyone's crew role right on the main server, in one pass.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not settings.main_server_id:
            await interaction.followup.send(
                "No main server is set on the settings page, so there is nowhere to give crew roles."
            )
            return
        if main_guild(self.bot) is None:
            await interaction.followup.send(
                "The main server is set, but the bot is not on it — or has not cached it yet."
            )
            return
        carrying = await Crew.objects.exclude(role_id__isnull=True).acount()
        if not carrying:
            await interaction.followup.send(
                "No crew has a Discord role set. Put a role ID on a crew in the admin panel first."
            )
            return
        changed, found, total = await sync_everyone(self.bot)
        log.info(
            "%s resynced the crew roles: %s changed, %s of %s crew members found on the server.",
            interaction.user,
            changed,
            found,
            total,
            extra={"webhook": True},
        )
        missing = total - found
        await interaction.followup.send(
            f"**{total}** player(s) are in a crew, **{found}** of them are on this server, and "
            f"**{changed}** had their role changed."
            + (
                f"\n-# {missing} have never joined this server, so there is nobody to give a role to."
                if missing
                else ""
            )
        )

    async def crew_table(self, war: CrewWar) -> discord.Embed:
        """The table of crews, which is what the leaderboard shows with no crew named."""
        crews = {crew.pk: crew async for crew in Crew.objects.all()}
        table = await standings(war)
        embed = discord.Embed(
            title=f"{war.name} — crews", colour=settings.embed_colour, description=war.description or None
        )
        if not table:
            embed.add_field(name="Standings", value="Nobody has scored yet.", inline=False)
            return embed
        total = sum(points for _, points in table) or 1
        lines = [
            f"{medal(place)} {crews[crew_id].label if crew_id in crews else crew_id} — "
            f"**{points:,}** *({points / total * 100:.0f}%)*"
            for place, crew_id, points in placed(table)
        ]
        # a dex running fifty crews has a table longer than one field, so it is spread over
        # several rather than cut off at the first thousand characters
        blocks = chunked(lines)
        for index, block in enumerate(blocks[:STANDINGS_FIELDS]):
            embed.add_field(name="Standings" if index == 0 else BLANK, value="\n".join(block), inline=False)
        left = sum(len(block) for block in blocks[STANDINGS_FIELDS:])
        if left:
            embed.add_field(name=BLANK, value=f"-# and {left} more crew(s) further down.", inline=False)
        embed.add_field(
            name=BLANK,
            value="-# `/crew leaderboard <crew>` for the top 20 of one crew, `/crew user` for a player's card.",
            inline=False,
        )
        if war.image:
            embed.set_image(url=f"{settings.site_base_url}/media/{war.image.name}")
        return embed

    # -- telling everyone, once the rewards have been handed out ---------------------------------

    @tasks.loop(minutes=2)
    async def announce_rewards(self):
        """
        Close the wars whose clock has run out, say who won, and tell each player what they got.

        The announcement is driven by the rows the payout writes rather than by a date, because
        the payout is what decides a war is over. A war with Auto finish on closes itself here,
        in the step before: the ladder goes out, and the announcement that follows in the same
        pass then has something to speak about. A war without it waits for an admin to read the
        preview and hand the rewards out, exactly as before.
        """
        now = timezone.now()
        await self.finish_due_wars(now)
        await self.announce_results(now)
        await self.tell_players(now)

    async def finish_due_wars(self, now) -> None:
        """
        Hand out the ladder of every war that asked to close itself and whose end date has passed.

        The date is stamped after a payout that handed something over, never before and never
        without. Paying twice is harmless — every rung handed to a player is a row under a unique
        constraint, so a second pass hands nothing over — while a stamp written too early would
        lose the whole ladder in silence. So a crash halfway through is picked up again two
        minutes later, and so is a war whose clock ran out before anyone wrote its ladder: it
        pays itself the moment the rungs appear, which is the whole point of asking the bot to
        close it. The complaint about an empty ladder is therefore made once, not every pass.

        `enabled` is deliberately not looked at: a war is usually closed to scoring the moment it
        is over, and that should not be what stops it paying out.
        """
        due = CrewWar.objects.filter(
            auto_finish=True, finished_at__isnull=True, ends_at__isnull=False, ends_at__lte=now
        )
        async for war in due:
            try:
                paid, already, players = await sync_to_async(hand_out)(war)
            except Exception:
                log.exception("crew war: %s could not pay itself out, trying again shortly", war.name)
                continue
            if not paid and not already:
                # nothing to hand over, so the war is left unfinished rather than marked closed:
                # a ladder written late still pays out on a later pass instead of needing the
                # date cleared by hand.
                if war.pk not in self._nothing_to_pay:
                    self._nothing_to_pay.add(war.pk)
                    log.warning(
                        f"Crew war {war.name} is past its end date with nothing to hand out: its "
                        "ladder is empty, or nobody reached the lowest rung. Nothing is announced "
                        "either. Write the ladder and it pays itself within a couple of minutes.",
                        extra={"webhook": True},
                    )
                continue
            self._nothing_to_pay.discard(war.pk)
            await CrewWar.objects.filter(pk=war.pk).aupdate(finished_at=now)
            log.info(
                f"Crew war {war.name} reached its end date and paid itself out: {paid} reward(s) "
                f"to {players} player(s), {already} were already paid.",
                extra={"webhook": True},
            )

    async def announce_results(self, now) -> None:
        """One announcement per war, the first time any of its rewards has been paid."""
        due = CrewWar.objects.filter(announced_at__isnull=True, rewards__payouts__isnull=False).distinct()
        async for war in due:
            # the date is written before the message goes out, and only while the row is still
            # unannounced, so two overlapping runs cannot both announce the same war
            if not await CrewWar.objects.filter(pk=war.pk, announced_at__isnull=True).aupdate(announced_at=now):
                continue
            try:
                await self.announce_result(war)
            except Exception:
                log.exception("crew war: could not announce the result of %s", war.name)
            await self.tell_the_winners(war)

    async def tell_the_winners(self, war: CrewWar) -> None:
        """
        Say on the bus that the winning crew won, once per war, to each of its members.

        The flag flown now is what counts, like the crew rungs of the ladder: the reward for
        winning goes to the people wearing the colours at the end. A failure here never undoes
        the payout or the announcement, both of which already happened.
        """
        try:
            table = await standings(war)
            if not table:
                return
            winner_id = table[0][0]
            members = [
                member
                async for member in CrewMembership.objects.filter(crew_id=winner_id).values_list(
                    "player_id", flat=True
                )
            ]
            for member in members:
                await bus.dispatch(member, Event.CREW_WAR_WIN, context=EventContext(points=table[0][1]))
        except Exception:
            log.exception("crew war: could not tell the winners of %s", war.name)

    async def announce_result(self, war: CrewWar) -> None:
        """The end of a war, in the spawn channels its scope allows."""
        crews = {crew.pk: crew async for crew in Crew.objects.all()}
        table = await standings(war)
        winner = crews.get(table[0][0]) if table else None
        embed = discord.Embed(
            title=f"{war.name} — the war is over",
            colour=settings.embed_colour,
            description=f"**{winner.label}** takes it." if winner else "Nobody scored a single point.",
        )
        if table:
            embed.add_field(
                name="Final standings",
                value="\n".join(
                    f"{medal(place)} {crews[crew_id].label if crew_id in crews else crew_id} — **{points:,}**"
                    for place, crew_id, points in placed(table)
                )[:1024],
                inline=False,
            )
        best = await top_players(war, limit=3)
        if best:
            names = []
            for rank, (player_id, points) in enumerate(best, start=1):
                discord_id = await Player.objects.filter(pk=player_id).values_list("discord_id", flat=True).afirst()
                names.append(f"{medal(rank)} <@{discord_id}> — **{points:,}**")
            embed.add_field(name="Carried their crew", value="\n".join(names), inline=False)
        embed.add_field(
            name="​", value="-# The rewards are out. Check your direct messages, or `/crew rewards`.", inline=False
        )
        # the winning crew's own victory picture, which is the point of having one per crew: the
        # whole server sees whose flag went up. The war's banner stands in without one.
        picture = (winner.victory_image if winner and winner.victory_image else None) or war.image
        if picture:
            embed.set_image(url=f"{settings.site_base_url}/media/{picture.name}")
        sent, missed = await announce_to_spawn_channels(self.bot, embed, scope=war.announce_to)
        log.info(f"Crew war {war.name} result announced to {sent} channels, {missed} missed.", extra={"webhook": True})

    async def tell_players(self, now) -> None:
        """
        One message per player, listing every rung they were paid rather than one per rung.

        A player is marked as told before the message is sent, never after: one whose messages
        are closed is then left alone instead of being written to every two minutes, and they
        can still read `/crew rewards`. An admin can send it again from the payout list.
        """
        due = (
            CrewWarPayout.objects.filter(announced_at__isnull=True)
            .select_related("player", "crew", "reward", "reward__war")
            .order_by("player_id", "pk")
        )
        owed: dict[int, list[CrewWarPayout]] = {}
        async for row in due:
            owed.setdefault(row.player_id, []).append(row)
        for rows in owed.values():
            claimed = await CrewWarPayout.objects.filter(
                pk__in=[row.pk for row in rows], announced_at__isnull=True
            ).aupdate(announced_at=now)
            if not claimed:
                continue
            try:
                await self.tell_player(rows)
            except Exception:
                log.exception("crew war: could not tell player %s about their rewards", rows[0].player_id)

    async def tell_player(self, rows: list[CrewWarPayout]) -> None:
        """Send one player the list of what the war paid them."""
        war = rows[0].reward.war
        crew = rows[0].crew
        discord_id = rows[0].player.discord_id
        user = self.bot.get_user(discord_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(discord_id)
            except (discord.NotFound, discord.HTTPException):
                log.warning("crew war: %s cannot be reached at all", discord_id)
                return

        embed = discord.Embed(
            title=f"{war.name} — your rewards",
            colour=settings.embed_colour,
            description=f"You brought **{rows[0].points:,}** points"
            + (f" to {crew.label}." if crew is not None else ".")
            + "\nThe war is over, and this is what it paid you.",
        )
        for row in rows:
            lines = [row.summary or "—"]
            if row.reward.message:
                lines.append(f"-# {row.reward.message}")
            embed.add_field(name=row.reward.label[:256], value="\n".join(lines)[:1024], inline=False)
        try:
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            # messages closed, or the bot shares no server with them any more. The reward is
            # already theirs, so this is worth a line in the log and nothing more
            log.info("crew war: could not message %s about their rewards", discord_id)
            return
        log.info(f"Crew war {war.name}: told {discord_id} about {len(rows)} reward(s).")

    @announce_rewards.before_loop
    async def before_announce_rewards(self):
        await self.bot.wait_until_ready()

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
