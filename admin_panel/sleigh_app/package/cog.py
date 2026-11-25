"""
The /sleigh commands: put a card in, see how full it is, and — for staff — hand the gifts back out.

The waves that empty it are run by the loop in here: one spawn at a time, counted in the database, so a restart
in the middle of a wave picks up where it left off instead of spawning the same gift twice.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import format_dt
from django.db.models import Count, F, Sum
from django.utils import timezone

from ballsdex.core.utils.broadcast import announce_to_spawn_channels, main_spawn_channel
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.core.utils.utils import is_staff
from bd_models.enums import AnnouncementScope
from bd_models.models import Player
from settings.models import settings

from ..gifts import Refused, hand_over, release, start_of_day
from ..gifts import give as put_in_sleigh
from ..models import Sleigh, SleighCard, SleighWave

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("sleigh")

TICK_SECONDS = 60
BAR_WIDTH = 20


def bar(done: int, total: int) -> str:
    """A progress bar, drawn with blocks so it reads the same on every client."""
    if total <= 0:
        return ""
    filled = min(int(BAR_WIDTH * done / total), BAR_WIDTH)
    return "\N{FULL BLOCK}" * filled + "\N{LIGHT SHADE}" * (BAR_WIDTH - filled)


async def current_sleigh() -> Sleigh | None:
    """
    The sleigh being played: the open one, else the most recent, so it can still be looked at before it opens
    and while it is emptying itself.
    """
    found = [
        sleigh
        async for sleigh in Sleigh.objects.filter(enabled=True).select_related("special").order_by("-opens_at", "-pk")
    ]
    if not found:
        return None
    now = timezone.now()
    for sleigh in found:
        if sleigh.is_open(now):
            return sleigh
    return found[0]


class SleighCog(commands.GroupCog, name="Sleigh", group_name="sleigh"):
    """Everyone's cards, in one pot."""

    admin = app_commands.Group(name="admin", description="Staff commands for the sleigh.")

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def cog_load(self):
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    # ── emptying it again ───────────────────────────────────────────────────────────────────────

    @tasks.loop(seconds=TICK_SECONDS)
    async def tick(self):
        try:
            await self.plan_waves()
        except Exception:
            log.exception("sleigh: could not plan the waves")
        try:
            await self.run_waves()
        except Exception:
            log.exception("sleigh: could not run a wave")

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    async def plan_waves(self):
        """
        Once a sleigh's emptying time has come, work out how its leftovers are split and write the waves down.

        Written once and never again: the split is decided on what was inside at that moment, so a card given in
        the last minute before it empties still goes out, and nothing is counted twice.
        """
        now = timezone.now()
        due = Sleigh.objects.filter(empty_at__isnull=False, empty_at__lte=now)
        async for sleigh in due:
            if await SleighWave.objects.filter(sleigh=sleigh).aexists():
                continue
            inside = await SleighCard.objects.filter(
                sleigh=sleigh, released_at__isnull=True, claimed_by__isnull=True
            ).acount()
            if not inside:
                continue
            count = max(sleigh.wave_count, 1)
            base, extra = divmod(inside, count)
            waves = []
            for position in range(1, count + 1):
                # the remainder goes to the earliest waves, so the last one is never the biggest
                cards = base + (1 if position <= extra else 0)
                if not cards:
                    continue
                waves.append(
                    SleighWave(sleigh=sleigh, position=position, due_at=sleigh.wave_due(position), cards=cards)
                )
            await SleighWave.objects.abulk_create(waves)
            log.info("sleigh %s: %s cards split into %s waves", sleigh.pk, inside, len(waves))

    async def run_waves(self):
        """
        Let one card of each due wave go out. One per tick, so a wave arrives as a trickle players can follow
        rather than twenty messages at once.
        """
        now = timezone.now()
        spawner = self.bot.get_cog("CountryBallsSpawner")
        if spawner is None:
            return
        due = SleighWave.objects.filter(due_at__lte=now).select_related("sleigh", "sleigh__special")
        async for wave in due:
            if wave.done:
                continue
            channel = await main_spawn_channel(self.bot, wave.sleigh.spawn_channel_id)
            if channel is None:
                continue
            if wave.announced_at is None:
                await self.announce_wave(wave, channel)
            # the slot is claimed before the card is taken out: a card can never leave the sleigh for a
            # wave that had no room left for it
            if not await SleighWave.objects.filter(pk=wave.pk, sent__lt=wave.cards).aupdate(sent=wave.sent + 1):
                continue
            taken = await release(wave.sleigh_id, 1)
            if not taken:
                # nothing left inside: close the wave rather than retry it every minute forever
                await SleighWave.objects.filter(pk=wave.pk).aupdate(sent=wave.cards)
                continue
            card = taken[0]
            ball = spawner.countryball_cls(self.bot, card.cached_ball)
            ball.special = wave.sleigh.cached_special
            ball.atk_bonus = card.attack_bonus
            ball.hp_bonus = card.health_bonus
            if card.frame:
                # read by the frames package when the spawn draws itself, and kept by the card caught from it
                ball.forced_frame = dict(card.frame)
            try:
                await ball.spawn(channel)
            except Exception:
                # the gift goes back in the sleigh rather than vanishing between the two
                await SleighCard.objects.filter(pk=card.pk).aupdate(released_at=None)
                await SleighWave.objects.filter(pk=wave.pk, sent__gt=0).aupdate(sent=wave.sent)
                log.exception("sleigh: could not spawn gift %s, it stays in the sleigh", card.pk)

    async def announce_wave(self, wave: SleighWave, channel: discord.TextChannel):
        """Say a wave is starting, once."""
        embed = discord.Embed(
            title=f"{wave.sleigh.label} — wave {wave.position}",
            colour=settings.embed_colour,
            description=f"**{wave.cards}** gift(s) are going back out, one after another. First come, first caught.",
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.warning("sleigh: could not announce wave %s", wave.pk)
            return
        await SleighWave.objects.filter(pk=wave.pk).aupdate(announced_at=timezone.now())

    # ── the commands ────────────────────────────────────────────────────────────────────────────

    @app_commands.command()
    async def view(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        How full the sleigh is, and what you have put in.
        """
        await interaction.response.defer(thinking=True)
        sleigh = await current_sleigh()
        if sleigh is None:
            await interaction.followup.send("No sleigh is set up.", ephemeral=True)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        inside = await SleighCard.objects.filter(
            sleigh=sleigh, released_at__isnull=True, claimed_by__isnull=True
        ).acount()
        total = await SleighCard.objects.filter(sleigh=sleigh).acount()
        mine = await SleighCard.objects.filter(sleigh=sleigh, given_by=player).acount()
        today = await SleighCard.objects.filter(sleigh=sleigh, given_by=player, given_at__gte=start_of_day()).acount()

        lines = [sleigh.description.strip()] if sleigh.description.strip() else []
        if sleigh.goal:
            lines.append(f"`{bar(total, sleigh.goal)}` **{total}/{sleigh.goal}**")
            if total >= sleigh.goal:
                lines.append("**The sleigh is full.** Everything in it still goes back out.")
        else:
            lines.append(f"**{total}** gift(s) given.")
        if sleigh.is_open():
            left = max(sleigh.per_day - today, 0)
            lines.append(
                f"You can still put **{left}** in today."
                if left
                else "You have given everything you can today. The day turns over at midnight UTC."
            )
            lines.append(f"-# Closes {format_dt(sleigh.closes_at, style='R')}. A gift never comes back.")
        elif timezone.now() < sleigh.opens_at:
            lines.append(f"It opens {format_dt(sleigh.opens_at, style='R')}.")
        else:
            lines.append("It is closed. What is left goes back out as spawns.")

        embed = discord.Embed(title=sleigh.label, colour=settings.embed_colour, description="\n".join(lines))
        embed.add_field(name="Still inside", value=f"{inside}")
        embed.add_field(name="Your gifts", value=f"{mine}")
        if sleigh.cached_special:
            embed.add_field(name="They become", value=sleigh.cached_special.name)
        # the first wave that still has something to send
        next_wave = await SleighWave.objects.filter(sleigh=sleigh, sent__lt=F("cards")).order_by("position").afirst()
        if next_wave is not None:
            embed.add_field(name="Next wave", value=format_dt(next_wave.due_at, style="R"), inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    @app_commands.describe(card="The card you are giving. It will not come back.")
    async def give(self, interaction: discord.Interaction["BallsDexBot"], card: BallInstanceTransform):
        """
        Put one of your cards in the sleigh. It becomes a Christmas card for whoever gets it.
        """
        await interaction.response.defer(thinking=True)
        sleigh = await current_sleigh()
        if sleigh is None:
            await interaction.followup.send("No sleigh is set up.", ephemeral=True)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            result = await put_in_sleigh(sleigh.pk, player.pk, card.pk)
        except Refused as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        ball = result.card.cached_ball
        lines = [f"**{ball.country}** is in the sleigh. It will come out as a **{sleigh.special.name}** card."]
        if result.points:
            lines.append(f"**+{result.points}** points for {result.crew_label or 'your crew'} — rare gifts pay more.")
        elif result.card.crew_id is None:
            lines.append("-# Join a crew and your gifts would score for it.")
        else:
            lines.append("-# No crew war is running, so it scored nothing.")
        if sleigh.goal:
            lines.append(f"`{bar(result.total, sleigh.goal)}` **{result.total}/{sleigh.goal}**")
        embed = discord.Embed(title="Thank you", colour=settings.embed_colour, description="\n".join(lines))
        await interaction.followup.send(embed=embed)

        if result.filled and sleigh.announce_to != AnnouncementScope.NONE:
            await self.announce_full(sleigh, interaction.user)

    async def announce_full(self, sleigh: Sleigh, user: discord.User | discord.Member):
        """Say the sleigh is full. A failure here never spoils the gift that filled it."""
        embed = discord.Embed(
            title=f"{sleigh.label} is full",
            colour=settings.embed_colour,
            description=f"**{user}** put in the gift that filled it. Everything inside goes back out to the "
            f"whole crew of this dex.",
        )
        try:
            await announce_to_spawn_channels(self.bot, embed, scope=sleigh.announce_to)
        except Exception:
            log.exception("sleigh: could not announce that it is full")

    @app_commands.command()
    async def top(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Who has given the most.
        """
        await interaction.response.defer(thinking=True)
        sleigh = await current_sleigh()
        if sleigh is None:
            await interaction.followup.send("No sleigh is set up.", ephemeral=True)
            return
        rows = [
            row
            async for row in SleighCard.objects.filter(sleigh=sleigh, given_by__isnull=False)
            .values("given_by__discord_id")
            .annotate(gifts=Count("pk"), points=Sum("points"))
            .order_by("-points", "-gifts")[:10]
        ]
        if not rows:
            await interaction.followup.send("Nobody has given anything yet.")
            return
        lines = [
            f"**{index}.** <@{row['given_by__discord_id']}> — {row['gifts']} gift(s), {row['points'] or 0} points"
            for index, row in enumerate(rows, start=1)
        ]
        embed = discord.Embed(
            title=f"{sleigh.label} — the most generous", colour=settings.embed_colour, description="\n".join(lines)
        )
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    # ── staff ───────────────────────────────────────────────────────────────────────────────────

    @admin.command(name="give")
    @app_commands.describe(user="Who gets them.", count="How many random gifts to hand over.")
    async def admin_give(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        user: discord.User,
        count: app_commands.Range[int, 1, 20] = 1,
    ):
        """
        Hand random gifts out of the sleigh to one player — a King of the Seas prize, a war reward.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not await is_staff(interaction):
            await interaction.followup.send("That one is for staff.")
            return
        sleigh = await current_sleigh()
        if sleigh is None:
            await interaction.followup.send("No sleigh is set up.")
            return
        player, _ = await Player.objects.aget_or_create(discord_id=user.id)
        try:
            given = await hand_over(sleigh.pk, count, player.pk, server_id=interaction.guild_id)
        except Refused as error:
            await interaction.followup.send(str(error))
            return
        if not given:
            await interaction.followup.send("The sleigh is empty.")
            return
        what = ", ".join(card.cached_ball.country for card in given)
        log.info(
            "%s handed %s sleigh gift(s) to %s: %s", interaction.user, len(given), user, what, extra={"webhook": True}
        )
        await interaction.followup.send(f"Gave **{user}** {len(given)} gift(s): {what}")

    @admin.command(name="spawn")
    @app_commands.describe(count="How many gifts to send out.", channel="Where. The usual spawn channel if left out.")
    async def admin_spawn(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        count: app_commands.Range[int, 1, 20] = 1,
        channel: discord.TextChannel | None = None,
    ):
        """
        Send random gifts out of the sleigh as spawns, for anyone to catch.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not await is_staff(interaction):
            await interaction.followup.send("That one is for staff.")
            return
        sleigh = await current_sleigh()
        if sleigh is None:
            await interaction.followup.send("No sleigh is set up.")
            return
        spawner = self.bot.get_cog("CountryBallsSpawner")
        if spawner is None:
            await interaction.followup.send("The spawner is not loaded.")
            return
        where = channel or await main_spawn_channel(self.bot, sleigh.spawn_channel_id)
        if where is None:
            await interaction.followup.send("No channel to spawn in: name one, or set the main server up.")
            return
        taken = await release(sleigh.pk, count)
        if not taken:
            await interaction.followup.send("The sleigh is empty.")
            return
        for card in taken:
            ball = spawner.countryball_cls(self.bot, card.cached_ball)
            ball.special = sleigh.cached_special
            ball.atk_bonus = card.attack_bonus
            ball.hp_bonus = card.health_bonus
            if card.frame:
                ball.forced_frame = dict(card.frame)
            await ball.spawn(where)
        what = ", ".join(card.cached_ball.country for card in taken)
        log.info(
            "%s sent %s sleigh gift(s) out in %s: %s",
            interaction.user,
            len(taken),
            where,
            what,
            extra={"webhook": True},
        )
        await interaction.followup.send(f"Sent {len(taken)} gift(s) out in {where.mention}: {what}")
