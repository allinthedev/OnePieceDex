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
from ballsdex.core.utils.buttons import ConfirmChoiceView
from bd_models.models import BallInstance, Player
from hunt_app.models import Hunt, HuntCompletion, Poneglyph, PoneglyphClaim
from settings.models import settings
from settings.utils import format_currency

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.hunt")

HELD = "✅"
MISSING = "⬜"
# a stone that has not surfaced yet, and one whose window has passed. Both are listed rather
# than hidden: a hunt reads as a calendar that way, and a latecomer can see what they missed
LOCKED = "🔒"
CLOSED = "⌛"


def stone_icon(stone: Poneglyph, held: bool, at=None) -> str:
    """The single character standing for what this stone is doing right now."""
    if held:
        return HELD
    if not stone.has_surfaced(at):
        return LOCKED
    if stone.has_closed(at):
        return CLOSED
    return MISSING


def stone_note(stone: Poneglyph, at=None) -> str:
    """What to say beside a stone's name in an embed: when it opens, or when it closed."""
    if not stone.has_surfaced(at):
        return f" — surfaces {discord.utils.format_dt(stone.opens_at, style='R')}"
    if stone.has_closed(at):
        return f" — closed {discord.utils.format_dt(stone.closes_at, style='R')}"
    if stone.closes_at:
        return f" — until {discord.utils.format_dt(stone.closes_at, style='R')}"
    return ""


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
        self.surfaced = True
        self.closed = False

    async def load(self):
        now = timezone.now()
        self.surfaced = self.poneglyph.has_surfaced(now)
        self.closed = self.poneglyph.has_closed(now)
        self.held = self.poneglyph.pk in await stones_held(self.hunt, self.player, self.crew)
        # a stone that has not surfaced keeps its set to itself: that is the whole point of a
        # release date, and reading it off a disabled button would give the game away
        self.rows = await progress_of(self.poneglyph, self.player) if self.surfaced else []
        complete = bool(self.rows) and all(owned >= needed for _, owned, needed, _ in self.rows)

        self.hand_in.disabled = True
        if self.held:
            self.hand_in.label = "Already held"
        elif not self.surfaced:
            self.hand_in.label = "Not surfaced yet"
        elif self.closed:
            self.hand_in.label = "This stone has closed"
        elif self.hunt.is_crew_hunt and self.crew is None:
            self.hand_in.label = "Pick a crew first"
        elif complete:
            self.hand_in.disabled = False
        return self

    def embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"{stone_icon(self.poneglyph, self.held)} {self.poneglyph.name}",
            colour=settings.embed_colour,
            description=self.poneglyph.hint or None,
        )
        if not self.surfaced:
            embed.add_field(
                name="Not surfaced yet",
                value="This stone has not been read yet. It surfaces "
                f"{discord.utils.format_dt(self.poneglyph.opens_at, style='R')}, and only then does it say "
                "what it asks for.",
                inline=False,
            )
            if url := media_url(self.hunt.poneglyph_image):
                embed.set_thumbnail(url=url)
            return embed
        if self.closed:
            embed.add_field(
                name="Closed",
                value=f"This stone closed {discord.utils.format_dt(self.poneglyph.closes_at, style='R')}. "
                "Whatever it asked for, it is no longer taking it.",
                inline=False,
            )
        elif self.poneglyph.closes_at:
            embed.add_field(
                name="Closes",
                value=discord.utils.format_dt(self.poneglyph.closes_at, style="R"),
                inline=False,
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

    def confirmation(self) -> str:
        """
        What the player is about to agree to.

        Consumed treasures are spelled out one by one: handing a set in is the only thing in the
        hunt that destroys anything, and "are you sure" is worth nothing if it does not say what
        is about to go.
        """
        consumed = [(label, needed) for label, _, needed, consume in self.rows if consume]
        lines = [f"Hand the set in for **{self.poneglyph.name}**?"]
        if consumed:
            lines.append(f"These are **handed over for good** and will leave your {settings.plural_collectible_name}:")
            lines += [f"- **{label}** ×{needed}" for label, needed in consumed]
        else:
            lines.append(f"-# Nothing is consumed — you keep every {settings.collectible_name}.")
        if self.hunt.is_crew_hunt and self.crew is not None:
            lines.append(f"-# The stone goes to **{self.crew.name}**, not to you alone.")
        return "\n".join(lines)[:2000]

    @discord.ui.button(label="Hand the set in", style=discord.ButtonStyle.success)
    async def hand_in(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        confirm = ConfirmChoiceView(
            interaction, accept_message="Handing it in…", cancel_message="Nothing was handed in."
        )
        await interaction.response.send_message(self.confirmation(), view=confirm, ephemeral=True)
        await confirm.wait()
        if not confirm.value:
            return
        # the confirming click has already answered its own message, so the outcome of the claim
        # goes out as a follow-up of that click rather than of the button above
        answer = confirm.interaction_response
        claimed, message = await self.cog.claim(
            self.hunt, self.poneglyph, self.player, self.crew, interaction.guild_id
        )
        # the player hears the outcome first: everything below is decoration, and decoration
        # must never be the reason an answer never arrives
        await answer.followup.send(message, ephemeral=True)
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
                    emoji=stone_icon(stone, stone.pk in view.held),
                    description=self.describe(stone)[:100] or None,
                )
                for stone in view.stones[:25]
            ],
        )

    @staticmethod
    def describe(stone: Poneglyph) -> str:
        """
        The grey line under a stone's name in the menu.

        A select option carries no markup, so the dates here are written out plainly rather than
        left to Discord to render the way the embed does.
        """
        if not stone.has_surfaced():
            return f"Surfaces {stone.opens_at:%d %b, %H:%M} UTC"
        if stone.has_closed():
            return f"Closed {stone.closes_at:%d %b, %H:%M} UTC"
        return stone.hint or ""

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
            now = timezone.now()
            embed.add_field(
                name="Poneglyphs",
                value="\n".join(
                    f"{stone_icon(stone, stone.pk in self.held, now)} {stone.name}"
                    + ("" if stone.pk in self.held else stone_note(stone, now))
                    for stone in self.stones
                )[:1024],
                inline=False,
            )
            # the legend only earns its line when there is something in the list to decode
            marks = [f"{LOCKED} not surfaced yet"] if any(not x.has_surfaced(now) for x in self.stones) else []
            if any(x.has_closed(now) for x in self.stones):
                marks.append(f"{CLOSED} closed")
            if marks:
                embed.add_field(name="\u200b", value="-# " + " · ".join(marks), inline=False)
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
        if not hunt.is_live():
            return False, "This hunt is closed."
        if not poneglyph.has_surfaced():
            return False, "That stone has not surfaced yet."
        if poneglyph.has_closed():
            return False, "That stone has closed, and is no longer taking anything."
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
        # every stone of the hunt, open or not: a locked one shows when it surfaces and a closed
        # one shows that it has gone, which is what turns the list into the hunt's calendar
        stones = [stone async for stone in hunt.poneglyphs.all()]
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
            sent, missed = await announce_to_spawn_channels(self.bot, embed, scope=stone.announcement_scope)
            log.info(
                f"Poneglyph {stone.name} announced to {sent} channels, {missed} missed.", extra={"webhook": True}
            )

    @announce_stones.before_loop
    async def before_announce_stones(self):
        await self.bot.wait_until_ready()
