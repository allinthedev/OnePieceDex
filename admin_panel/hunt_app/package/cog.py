"""
The player side of poneglyph hunts: see the stones, hand a set in, hold the stone.

Nothing about progress is stored until a set is handed in. Whether a player can claim is
worked out from the treasures they own at that moment, and the claim itself is the only write.
The database, not the button, is what stops the same stone being claimed twice.
"""

import logging
from typing import TYPE_CHECKING

import discord
from crew_app.models import Crew, CrewMembership, CrewWarRule
from crew_app.scoring import score_quietly
from currency_app.models import BerryTransaction
from discord import app_commands
from discord.ext import commands, tasks
from django.db import IntegrityError
from django.utils import timezone

from ballsdex.core.utils.broadcast import announce_to_spawn_channels
from bd_models.models import BallInstance, Player
from hunt_app.models import Hunt, HuntCompletion, Poneglyph, PoneglyphClaim
from settings.models import settings
from settings.utils import format_currency

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.hunt")

HELD = "✅"
MISSING = "⬜"


def media_url(field) -> str | None:
    """The public URL of an uploaded image, or None when nothing was uploaded."""
    return f"{settings.site_base_url}/media/{field.name}" if field else None


async def crew_of(player: Player) -> Crew | None:
    membership = await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
    return membership.crew if membership else None


async def stones_held(hunt: Hunt, player: Player, crew: Crew | None) -> set[int]:
    """The ids of the poneglyphs already held, by the crew in a crew hunt or by the player."""
    claims = PoneglyphClaim.objects.filter(poneglyph__hunt=hunt)
    claims = claims.filter(crew=crew) if hunt.is_crew_hunt else claims.filter(player=player, crew__isnull=True)
    return {poneglyph_id async for poneglyph_id in claims.values_list("poneglyph_id", flat=True)}


async def progress_of(poneglyph: Poneglyph, player: Player) -> list[tuple[str, int, int, bool]]:
    """
    What the player has towards this stone: `(label, owned, needed, consumed)` per line.
    """
    rows = []
    async for requirement in poneglyph.requirements.select_related("ball", "special").all():
        owned = await requirement.matching(player).acount()
        label = requirement.cached_ball.country
        if special := requirement.cached_special:
            label += f" ({special.name})"
        rows.append((label, owned, requirement.amount, requirement.consume))
    return rows


class PoneglyphView(discord.ui.View):
    """One stone on its own: what it asks for, what the player has, and the hand-in button."""

    def __init__(self, cog: "HuntCog", hunt: Hunt, poneglyph: Poneglyph, player: Player, crew: Crew | None):
        super().__init__(timeout=180)
        self.cog = cog
        self.hunt = hunt
        self.poneglyph = poneglyph
        self.player = player
        self.crew = crew
        self.rows: list[tuple[str, int, int, bool]] = []
        self.held = False

    async def load(self):
        self.rows = await progress_of(self.poneglyph, self.player)
        self.held = self.poneglyph.pk in await stones_held(self.hunt, self.player, self.crew)
        complete = bool(self.rows) and all(owned >= needed for _, owned, needed, _ in self.rows)
        self.hand_in.disabled = self.held or not complete
        if self.held:
            self.hand_in.label = "Already held"
        elif self.hunt.is_crew_hunt and self.crew is None:
            self.hand_in.disabled = True
            self.hand_in.label = "Pick a crew first"
        return self

    def embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"{HELD if self.held else MISSING} {self.poneglyph.name}",
            colour=settings.embed_colour,
            description=self.poneglyph.hint or None,
        )
        if self.rows:
            embed.add_field(
                name="Bring these",
                value="\n".join(
                    f"{HELD if owned >= needed else MISSING} **{label}** — {min(owned, needed)}/{needed}"
                    + (" *(consumed)*" if consumed else "")
                    for label, owned, needed, consumed in self.rows
                )[:1024],
                inline=False,
            )
        else:
            embed.add_field(name="Bring these", value="Nothing has been set for this stone yet.", inline=False)
        if url := media_url(self.hunt.poneglyph_image):
            embed.set_thumbnail(url=url)
        return embed

    @discord.ui.button(label="Hand the set in", style=discord.ButtonStyle.success)
    async def hand_in(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        claimed, message = await self.cog.claim(
            self.hunt, self.poneglyph, self.player, self.crew, interaction.guild_id
        )
        # the player hears the outcome first: everything below is decoration, and decoration
        # must never be the reason an answer never arrives
        await interaction.followup.send(message, ephemeral=True)
        if not claimed:
            return

        button.disabled = True
        button.label = "Held"
        try:
            # this view was sent ephemerally, so it can only be edited back through the
            # follow-up. Message.edit has no real message to act on and answers 404
            await interaction.followup.edit_message(interaction.message.id, view=self)
        except (discord.HTTPException, AttributeError):
            pass


class StoneSelect(discord.ui.Select):
    def __init__(self, view: "HuntView"):
        self.hunt_view = view
        super().__init__(
            placeholder="Open a poneglyph",
            options=[
                discord.SelectOption(
                    label=stone.name[:100],
                    value=str(stone.pk),
                    emoji=HELD if stone.pk in view.held else MISSING,
                    description=(stone.hint[:100] or None),
                )
                for stone in view.stones[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction["BallsDexBot"]):
        stone = next(s for s in self.hunt_view.stones if str(s.pk) == self.values[0])
        view = await PoneglyphView(
            self.hunt_view.cog, self.hunt_view.hunt, stone, self.hunt_view.player, self.hunt_view.crew
        ).load()
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)


class HuntView(discord.ui.View):
    def __init__(self, cog: "HuntCog", hunt: Hunt, stones: list[Poneglyph], held: set[int], player, crew):
        super().__init__(timeout=180)
        self.cog = cog
        self.hunt = hunt
        self.stones = stones
        self.held = held
        self.player = player
        self.crew = crew
        if stones:
            self.add_item(StoneSelect(self))

    def embed(self, user: discord.abc.User) -> discord.Embed:
        complete = bool(self.stones) and len(self.held) == len(self.stones)
        embed = discord.Embed(
            title=self.hunt.name, colour=settings.embed_colour, description=self.hunt.description or None
        )
        emoji = self.hunt.poneglyph_emoji or "🗿"
        holder = self.crew.label if self.hunt.is_crew_hunt and self.crew else user.display_name
        embed.add_field(
            name="Stones held",
            value=f"{emoji} **{len(self.held)}/{len(self.stones)}** — {holder}",
            inline=False,
        )
        if self.stones:
            embed.add_field(
                name="Poneglyphs",
                value="\n".join(
                    f"{HELD if stone.pk in self.held else MISSING} {stone.name}" for stone in self.stones
                )[:1024],
                inline=False,
            )
        if self.hunt.is_crew_hunt and self.crew is None:
            embed.add_field(
                name="No crew",
                value="This hunt is run between crews. Pick one in `/player settings` before handing anything in.",
                inline=False,
            )

        rewards = []
        if self.hunt.reward_money:
            rewards.append(format_currency(self.hunt.reward_money, False, self.cog.bot))
        if ball := self.hunt.cached_reward_ball:
            special = self.hunt.cached_reward_special
            rewards.append(f"**{ball.country}**" + (f" ({special.name})" if special else ""))
        if rewards:
            embed.add_field(name="Reward for all of them", value=" and ".join(rewards), inline=False)
        if self.hunt.ends_at:
            embed.add_field(name="Closes", value=discord.utils.format_dt(self.hunt.ends_at, style="R"))

        image = self.hunt.completed_image if complete and self.hunt.completed_image else self.hunt.image
        if url := media_url(image):
            embed.set_image(url=url)
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        return embed


class HuntCog(commands.Cog):
    """Poneglyph hunts."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def cog_load(self):
        self.announce_stones.start()

    def cog_unload(self):
        self.announce_stones.cancel()

    async def claim(
        self, hunt: Hunt, poneglyph: Poneglyph, player: Player, crew: Crew | None, server_id: int | None
    ) -> tuple[bool, str]:
        """
        Hand a set in and take the stone. Returns whether it changed hands, and what to tell
        the player either way.

        The requirements are counted again here: a treasure can leave a collection between
        opening the stone and pressing the button, and the button is not what decides.
        """
        if not hunt.is_live() or not poneglyph.is_open():
            return False, "This hunt is closed."
        if hunt.is_crew_hunt and crew is None:
            return False, "Pick a crew in `/player settings` first."

        to_consume: list[int] = []
        async for requirement in poneglyph.requirements.all():
            owned = [pk async for pk in requirement.matching(player).values_list("pk", flat=True)]
            if len(owned) < requirement.amount:
                return False, f"You are short on {requirement.cached_ball.country}."
            if requirement.consume:
                to_consume += owned[: requirement.amount]

        try:
            await PoneglyphClaim.objects.acreate(
                poneglyph=poneglyph, player=player, crew=crew if hunt.is_crew_hunt else None
            )
        except IntegrityError:
            # the unique constraint is what actually stops a second claim, not the button
            return False, "That stone is already held."

        if to_consume:
            await BallInstance.objects.filter(pk__in=to_consume).adelete()

        emoji = hunt.poneglyph_emoji or "🗿"
        holder = crew.label if hunt.is_crew_hunt and crew else "you"
        lines = [f"{emoji} **{poneglyph.name}** is now held by {holder}."]
        if to_consume:
            lines.append(f"-# {len(to_consume)} {settings.plural_collectible_name} were handed over.")

        await score_quietly(player.pk, CrewWarRule.Source.PONEGLYPH_CLAIMED)
        total = await hunt.poneglyphs.acount()
        held = len(await stones_held(hunt, player, crew))
        lines.append(f"{emoji} {held}/{total}")
        if held >= total:
            lines.append(await self.finish(hunt, player, crew, server_id))
        log.info(
            f"{player.discord_id} claimed poneglyph {poneglyph.name} of {hunt.name} "
            f"(crew={crew.name if crew else None}, consumed={len(to_consume)}).",
            extra={"webhook": True},
        )
        return True, "\n".join(lines)

    async def finish(self, hunt: Hunt, player: Player, crew: Crew | None, server_id: int | None) -> str:
        """Hand over the reward for a whole hunt, once."""
        try:
            completion = await HuntCompletion.objects.acreate(
                hunt=hunt, player=player, crew=crew if hunt.is_crew_hunt else None
            )
        except IntegrityError:
            return ""
        lines = [hunt.completion_message or f"**{hunt.name}** is complete."]
        if ball := hunt.cached_reward_ball:
            instance = await BallInstance.objects.acreate(
                player=player,
                ball_id=ball.pk,
                special_id=hunt.reward_special_id,
                attack_bonus=0,
                health_bonus=0,
                server_id=server_id,
            )
            completion.reward_instance = instance
            await completion.asave(update_fields=("reward_instance",))
            lines.append(f"You received **{ball.country}**.")
        if hunt.reward_money:
            await player.add_money(
                hunt.reward_money,
                reason=BerryTransaction.Reason.ACHIEVEMENT,
                description=f"Hunt reward: {hunt.name}",
                server_id=server_id,
            )
            lines.append(f"You received {format_currency(hunt.reward_money, False, self.bot)}.")
        await score_quietly(player.pk, CrewWarRule.Source.HUNT_COMPLETED)
        if hunt.announce_completion:
            await self.announce_completion(hunt, player, crew)
        log.info(f"Hunt {hunt.name} finished by {crew.name if crew else player.discord_id}.", extra={"webhook": True})
        return "\n".join(lines)

    async def announce_completion(self, hunt: Hunt, player: Player, crew: Crew | None) -> None:
        """
        Tell every spawn channel that a hunt has been finished.

        A crew gets its own victory picture when it has one, which is the point of having one
        per crew: the whole server sees whose flag just went up. Without it, the hunt's own
        completion picture stands in.
        """
        emoji = hunt.poneglyph_emoji or "🗿"
        winner = crew.label if crew else f"<@{player.discord_id}>"
        embed = discord.Embed(
            title=f"{emoji} {hunt.name} — complete!",
            colour=settings.embed_colour,
            description=hunt.completion_message or f"{winner} put every poneglyph back together.",
        )
        embed.add_field(name="Finished by", value=winner, inline=False)
        rewards = []
        if hunt.reward_money:
            rewards.append(format_currency(hunt.reward_money, False, self.bot))
        if ball := hunt.cached_reward_ball:
            rewards.append(f"**{ball.country}**")
        if rewards:
            embed.add_field(name="Reward", value=" and ".join(rewards), inline=False)

        picture = (crew.victory_image if crew and crew.victory_image else None) or hunt.completed_image
        if url := media_url(picture):
            embed.set_image(url=url)

        sent, missed = await announce_to_spawn_channels(self.bot, embed, scope=hunt.announce_to)
        log.info(
            f"Hunt {hunt.name} completion announced to {sent} channels, {missed} missed.",
            extra={"webhook": True},
        )

    @app_commands.command(name="hunt")
    @app_commands.describe(name="Which hunt, when more than one is running")
    async def hunt(self, interaction: discord.Interaction["BallsDexBot"], name: str | None = None):
        """
        See the poneglyphs of a hunt, and hand a set in to take one.
        """
        await interaction.response.defer(thinking=True)
        live = [hunt async for hunt in Hunt.objects.all() if hunt.is_live()]
        if not live:
            await interaction.followup.send("No hunt is running right now.")
            return
        if name:
            live = [hunt for hunt in live if hunt.name.casefold() == name.casefold()] or live
        hunt = live[0]

        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        crew = await crew_of(player) if hunt.is_crew_hunt else None
        stones = [stone async for stone in hunt.poneglyphs.all() if stone.is_open()]
        held = await stones_held(hunt, player, crew)

        view = HuntView(self, hunt, stones, held, player, crew)
        await interaction.followup.send(embed=view.embed(interaction.user), view=view)

    @hunt.autocomplete("name")
    async def hunt_autocomplete(self, interaction: discord.Interaction["BallsDexBot"], current: str):
        names = [hunt.name async for hunt in Hunt.objects.all() if hunt.is_live()]
        return [
            app_commands.Choice(name=name, value=name) for name in names if current.casefold() in name.casefold()
        ][:25]

    @tasks.loop(minutes=5)
    async def announce_stones(self):
        """
        Announce the poneglyphs that have opened, with the treasures they ask for.

        The date is written before the message goes out, and only when the row is still
        unannounced, so two overlapping runs cannot both announce the same stone.
        """
        now = timezone.now()
        due = Poneglyph.objects.filter(announced_at__isnull=True).select_related("hunt")
        async for stone in due:
            if not stone.hunt.is_live(now) or not stone.is_open(now):
                continue
            if not await Poneglyph.objects.filter(pk=stone.pk, announced_at__isnull=True).aupdate(announced_at=now):
                continue
            wanted = [
                f"**{requirement.cached_ball.country}**"
                + (f" ({special.name})" if (special := requirement.cached_special) else "")
                + (f" ×{requirement.amount}" if requirement.amount > 1 else "")
                async for requirement in stone.requirements.select_related("ball", "special").all()
            ]
            embed = discord.Embed(
                title=f"{stone.hunt.poneglyph_emoji or '🗿'} {stone.name}",
                colour=settings.embed_colour,
                description=stone.hint or f"A poneglyph of **{stone.hunt.name}** has surfaced.",
            )
            embed.add_field(
                name="It asks for", value="\n".join(wanted) or "Nothing has been set for it yet.", inline=False
            )
            embed.add_field(name="Hand it in with", value="`/hunt`", inline=False)
            if url := media_url(stone.hunt.poneglyph_image):
                embed.set_thumbnail(url=url)
            sent, missed = await announce_to_spawn_channels(self.bot, embed, scope=stone.hunt.announce_to)
            log.info(
                f"Poneglyph {stone.name} announced to {sent} channels, {missed} missed.", extra={"webhook": True}
            )

    @announce_stones.before_loop
    async def before_announce_stones(self):
        await self.bot.wait_until_ready()
