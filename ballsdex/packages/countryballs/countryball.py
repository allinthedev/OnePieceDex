from __future__ import annotations

import logging
import math
import random
import string
from datetime import datetime
from typing import TYPE_CHECKING, Literal

import discord
from crew_app.models import CrewWarRule
from crew_app.scoring import score_quietly
from currency_app.models import BerryTransaction, CurrencySettings
from discord.ui import ActionRow, Button, Item, MediaGallery, TextDisplay, TextInput, button
from django.utils import timezone

from ballsdex.core.discord import Container, LayoutView, Modal
from ballsdex.core.game_events import Event, EventContext, bus
from ballsdex.core.metrics import caught_balls
from ballsdex.core.utils.formatting import format_command_mentions
from ballsdex.core.utils.utils import can_mention
from bd_models.models import (
    FRAME_EMOJI,
    Ball,
    BallInstance,
    Bounty,
    GuildConfig,
    Player,
    Special,
    Trade,
    TradeObject,
    balls,
    specials,
)
from settings.models import CUSTOM_EMOJI_RE, PromptMessage, Settings, settings
from settings.utils import format_currency

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.countryballs")


class CountryballNamePrompt(Modal, title=f"Catch this {settings.collectible_name}!"):
    name = TextInput(
        label=f"Name of this {settings.collectible_name}", style=discord.TextStyle.short, placeholder="Your guess"
    )

    def __init__(self, view: BallSpawnView):
        super().__init__()
        self.view = view

    async def on_error(self, interaction: discord.Interaction["BallsDexBot"], error: Exception) -> None:
        if isinstance(error, discord.NotFound) and error.code == 10062:
            return
        log.exception("An error occurred in countryball catching prompt", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(f"An error occurred with this {settings.collectible_name}.")
        else:
            await interaction.response.send_message(f"An error occurred with this {settings.collectible_name}.")

    async def on_submit(self, interaction: discord.Interaction["BallsDexBot"]):
        await interaction.response.defer(thinking=True)

        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        if self.view.caught:
            slow_message = settings.get_random_message(PromptMessage.PromptType.SLOW).format(
                user=interaction.user.mention,
                collectible=settings.collectible_name,
                ball=self.view.name,
                collectibles=settings.plural_collectible_name,
                emoji=interaction.client.get_emoji(self.view.model.emoji_id),
            )

            await interaction.followup.send(slow_message, ephemeral=True, allowed_mentions=await can_mention([player]))
            return

        if not self.view.is_name_valid(self.name.value):
            if len(self.name.value) > 500:
                wrong_name = self.name.value[:500] + "..."
            else:
                wrong_name = self.name.value

            wrong_message = settings.get_random_message(PromptMessage.PromptType.WRONG).format(
                user=interaction.user.mention,
                collectible=settings.collectible_name,
                ball=self.view.name,
                collectibles=settings.plural_collectible_name,
                wrong=wrong_name,
                emoji=interaction.client.get_emoji(self.view.model.emoji_id),
            )
            await interaction.followup.send(
                wrong_message, allowed_mentions=await can_mention([player]), ephemeral=False
            )
            return

        currency_settings = await CurrencySettings.aload()
        ball, has_caught_before = await self.view.catch_ball(interaction.user, player=player, guild=interaction.guild)
        text = self.view.get_catch_message(ball, has_caught_before, interaction.user.mention)
        if self.view.ballinstance is None:
            if random.random() < currency_settings.spawn_chance:
                amount = boosted_berries(currency_settings.spawn_amount, interaction.guild_id)
                await player.add_money(
                    amount,
                    reason=BerryTransaction.Reason.SPAWN_CATCH,
                    description=f"Caught {ball.description(short=True)}",
                    server_id=interaction.guild_id,
                )
                text += f"You get **{format_currency(amount, False, self.view.bot)}**"
                bus.dispatch_soon(
                    player.pk,
                    Event.CATCH_REWARD,
                    context=EventContext(instances=[ball], amount=amount, server_id=interaction.guild_id),
                    channel_id=interaction.channel_id,
                )

        await interaction.followup.send(text, allowed_mentions=discord.AllowedMentions(users=player.can_be_mentioned))
        await interaction.followup.edit_message(self.view.message.id, view=self.view)


def button_emoji(bot: "BallsDexBot", value: str) -> discord.Emoji | str | None:
    """
    The emoji configured for a button: a unicode emoji as it is, or a custom emoji the bot can use. A custom emoji the
    bot can't use would make Discord refuse the whole message, it is left out.
    """
    if not value:
        return None
    match = CUSTOM_EMOJI_RE.fullmatch(value)
    if match is None:
        return value
    emoji = bot.get_emoji(int(match.group(1) or match.group(2)))
    if emoji is None:
        log.warning(f"The emoji {value} of the catch button isn't available to the bot, it is left out.")
    return emoji


class CatchRow(ActionRow["BallSpawnView"]):
    """
    The action row holding the catch button. Components v2 does not allow buttons to be defined
    directly on the view, they must be wrapped in an action row.
    """

    def __init__(self, spawn_view: BallSpawnView):
        super().__init__()
        self.spawn_view = spawn_view

    @button(style=discord.ButtonStyle.primary, label="Catch me!")
    async def catch_button(self, interaction: discord.Interaction["BallsDexBot"], button: Button):
        if self.spawn_view.caught:
            slow_message = settings.get_formatted_message(
                category=PromptMessage.PromptType.SLOW,
                mention=interaction.user.mention,
                model=self.spawn_view.model,
                bot=interaction.client,
            )
            await interaction.response.send_message(slow_message, ephemeral=True)
        else:
            await interaction.response.send_modal(CountryballNamePrompt(self.spawn_view))


def boosted_weights(weights: list[float], guild_id: int | None) -> list[float]:
    """
    The spawn weights, flattened by a rarity boost bought in the event shop.

    Only ever flattened on the main server, and handed straight back everywhere else — `current` sees to that.
    The event shop is an app of its own, so a dex running without it keeps the plain draw.
    """
    try:
        from eventshop_app.boosts import current, flatten
    except ImportError:
        return weights
    return flatten(weights, current(guild_id).rarity_exponent)


def boosted_special_weights(weights: list[float], population: list[Special], guild_id: int | None) -> list[float]:
    """The weight of each special, raised by a boost on that special, or on every special at once."""
    try:
        from eventshop_app.boosts import current
    except ImportError:
        return weights
    boosts = current(guild_id)
    if not boosts.anything:
        return weights
    return [weight * boosts.special_weight(special.pk) for weight, special in zip(weights, population)]


def boosted_berries(amount: int, guild_id: int | None) -> int:
    """What a catch pays, raised by a berry boost. Never less than the plain amount."""
    try:
        from eventshop_app.boosts import current
    except ImportError:
        return amount
    return max(int(amount * current(guild_id).berry_factor), amount)

class BallSpawnView(LayoutView):
    """
    BallSpawnView is a Discord UI view that represents the spawning and interaction logic for a
    countryball in the BallsDex bot. It handles user interactions, spawning mechanics, and
    countryball catching logic.

    Attributes
    ----------
    bot: BallsDexBot
    model: Ball
        The ball being spawned.
    algo: str | None
        The algorithm used for spawning, used for metrics.
    message: discord.Message
        The Discord message associated with this view once created with `spawn`.
    caught: bool
        Whether the countryball has been caught yet.
    ballinstance: BallInstance | None
        If this is set, this ball instance will be spawned instead of creating a new ball instance.
        All properties are preserved, and if successfully caught, the owner is transferred (with
        a trade entry created). Use the `from_existing` constructor to use this.
    special: Special | None
        Force the spawned countryball to have a special event attached. If None, a random one will
        be picked.
    atk_bonus: int | None
        Force a specific attack bonus if set, otherwise random range defined in config.yml.
    hp_bonus: int | None
        Force a specific health bonus if set, otherwise random range defined in config.yml.
    claimed_bounty: Bounty | None
        The wanted poster this catch collected, once `catch_ball` has run. None when there was
        none on this treasure, or when someone else got to it first.
    """

    def __init__(self, bot: "BallsDexBot", model: Ball):
        super().__init__()
        self.bot = bot
        self.model = model
        self.algo: str | None = None
        self.message: discord.Message = discord.utils.MISSING
        self.caught = False
        self.ballinstance: BallInstance | None = None
        self.special: Special | None = None
        self.atk_bonus: int | None = None
        self.hp_bonus: int | None = None
        # set by catch_ball when the catch collected a wanted poster, read by the catch message
        self.claimed_bounty: Bounty | None = None
        self.og_id: int

        self.catch_row = CatchRow(self)
        self.style_catch_button("catch")

    @property
    def catch_button(self) -> Button["BallSpawnView"]:
        return self.catch_row.catch_button

    def style_catch_button(self, state: Literal["catch", "caught", "despawned"]):
        """
        Give the catch button the label, color and emoji configured for this state of the spawn.
        """
        button = self.catch_button
        button.label = getattr(settings, f"{state}_button_label") or settings.catch_button_label
        button.style = discord.ButtonStyle(getattr(settings, f"{state}_button_color"))
        button.emoji = button_emoji(self.bot, getattr(settings, f"{state}_button_emoji"))

    async def interaction_check(self, interaction: discord.Interaction["BallsDexBot"], /) -> bool:
        return await interaction.client.blacklist_check(interaction)

    async def on_timeout(self):
        self.catch_button.disabled = True
        # the view keeps running once caught, its button must keep that look
        if not self.caught:
            self.style_catch_button("despawned")
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        if self.ballinstance and not self.caught:
            await self.ballinstance.unlock()

    @classmethod
    async def from_existing(cls, bot: "BallsDexBot", ball_instance: BallInstance):
        """
        Get an instance from an existing `BallInstance`. Instead of creating a new ball instance,
        this will transfer ownership of the existing instance when caught.

        The ball instance must be unlocked from trades, and will be locked until caught or timed
        out.
        """
        if await ball_instance.is_locked():
            raise RuntimeError("This countryball is locked for a trade")

        # prevent countryball from being traded while spawned
        await ball_instance.lock_for_trade()

        view = cls(bot, ball_instance.countryball)
        view.ballinstance = ball_instance
        view.og_id = ball_instance.player.discord_id
        return view

    @classmethod
    async def get_random(cls, bot: "BallsDexBot", guild_id: int | None = None):
        """
        Get a new instance with a random countryball. Rarity values are taken into account.

        `guild_id` is what lets a rarity boost bought in the event shop flatten the weighting, which
        only ever happens on the main server. Left out, the draw is the plain one — an admin
        spawning a card by hand is not meant to ride somebody's paid hour.
        """
        countryballs = list(filter(lambda m: m.enabled, balls.values()))
        if not countryballs:
            raise RuntimeError("No ball to spawn")
        rarities = boosted_weights([x.rarity for x in countryballs], guild_id)
        cb = random.choices(population=countryballs, weights=rarities, k=1)[0]
        return cls(bot, cb)

    @property
    def name(self):
        return self.model.country

    @staticmethod
    def get_random_special(guild_id: int | None = None) -> Special | None:
        """
        The special a new treasure carries, None for a plain one.

        `guild_id` lets a boost raise the chance of one special — the Christmas one — on the main
        server. The share left for a plain treasure shrinks by exactly as much as the specials gain.
        """
        population = [
            x
            for x in specials.values()
            # handle null start/end dates with infinity times
            if (x.start_date or datetime.min.replace(tzinfo=timezone.get_current_timezone()))
            <= timezone.now()
            <= (x.end_date or datetime.max.replace(tzinfo=timezone.get_current_timezone()))
        ]

        if not population:
            return None

        boosted = boosted_special_weights([x.rarity for x in population], population, guild_id)
        common_weight: float = 1 - sum(boosted)

        if common_weight < 0:
            common_weight = 0

        weights = boosted + [common_weight]
        # None is added representing the common countryball
        special: Special | None = random.choices(population=population + [None], weights=weights, k=1)[0]

        return special

    async def get_tip(self, guild_id: int | None = None) -> str | None:
        """
        Roll for a tip to display below the spawn message.

        Parameters
        ----------
        guild_id: int | None
            The guild where the countryball spawns. If set, its configuration is checked, as server
            admins may opt out of tips.

        Returns
        -------
        str | None
            A formatted tip, or `None` if tips are disabled, no tip is configured, or the roll
            against `tip_chance` failed.
        """
        if not settings.tip_chance or random.randint(1, 100) > settings.tip_chance:
            return None
        if guild_id is not None:
            # a missing guild config means the default value, which is enabled
            enabled = (
                await GuildConfig.objects.filter(guild_id=guild_id).values_list("tips_enabled", flat=True).afirst()
            )
            if enabled is False:
                return None
        tip = settings.get_formatted_tip()
        return format_command_mentions(tip, self.bot) if tip else None

    async def build(self, spawn_message: str, file_name: str, guild_id: int | None = None) -> None:
        """
        Populate the components of this view. This must be called once, right before sending the
        spawn message, since the layout depends on the message and the attached image.

        Parameters
        ----------
        spawn_message: str
            The formatted spawn message, displayed above the countryball.
        file_name: str
            The name of the image uploaded alongside this view.
        guild_id: int | None
            The guild where the countryball spawns, used to determine if a tip may be displayed.
        """
        if spawn_message:
            self.add_item(TextDisplay(spawn_message))
        self.add_item(MediaGallery(discord.MediaGalleryItem(f"attachment://{file_name}")))

        tip_item: Item[LayoutView] | None = None
        if tip := await self.get_tip(guild_id):
            text = TextDisplay(f"-# \N{ELECTRIC LIGHT BULB} {tip}")
            tip_item = Container(text) if settings.tip_container else text

        if tip_item and settings.tip_position == Settings.TipPosition.ABOVE_BUTTON:
            self.add_item(tip_item)
        self.add_item(self.catch_row)
        if tip_item and settings.tip_position == Settings.TipPosition.BELOW_BUTTON:
            self.add_item(tip_item)

    async def spawn(self, channel: discord.TextChannel) -> bool:
        """
        Spawn a countryball in a channel.

        Parameters
        ----------
        channel: discord.TextChannel
            The channel where to spawn the countryball. Must have permission to send messages
            and upload files as a bot (not through interactions).

        Returns
        -------
        bool
            `True` if the operation succeeded, otherwise `False`. An error will be displayed
            in the logs if that's the case.
        """

        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))

        extension = self.model.wild_card.name.split(".")[-1]
        file_name = f"nt_{generate_random_name()}.{extension}"
        try:
            permissions = channel.permissions_for(channel.guild.me)
            if permissions.attach_files and permissions.send_messages:
                spawn_message = settings.get_random_message(PromptMessage.PromptType.SPAWN).format(
                    collectible=settings.collectible_name,
                    ball=self.name,
                    collectibles=settings.plural_collectible_name,
                    emoji=self.bot.get_emoji(self.model.emoji_id),
                )
                await self.build(spawn_message, file_name, channel.guild.id)

                self.message = await channel.send(
                    view=self, file=discord.File(self.model.wild_card.path, filename=file_name)
                )
                return True
            else:
                log.warning("Missing permission to spawn ball in channel %s.", channel)
        except discord.Forbidden:
            log.warning(f"Missing permission to spawn ball in channel {channel}.")
        except discord.HTTPException:
            log.error("Failed to spawn ball", exc_info=True)
        return False

    def is_name_valid(self, text: str) -> bool:
        """
        Check if the prompted name is valid.

        Parameters
        ----------
        text: str
            The text entered by the user. It will be lowered and stripped of enclosing blank
            characters.

        Returns
        -------
        bool
            Whether the name matches or not.
        """
        if self.model.catch_names:
            possible_names = (self.name.lower(), *self.model.catch_names.split(";"))
        else:
            possible_names = (self.name.lower(),)
        cname = text.lower().strip()
        # Remove fancy unicode characters like ’ to replace to '
        cname = cname.replace("\u2019", "'")
        cname = cname.replace("\u2018", "'")
        cname = cname.replace("\u201c", '"')
        cname = cname.replace("\u201d", '"')
        return cname in possible_names

    async def _pay_bounty(
        self, bounty: Bounty, ball: BallInstance, player: Player, user: discord.User | discord.Member
    ) -> Bounty | None:
        """
        Hand over a claimed wanted poster: tie it to the card that took it, and pay the reward.

        A failure here does not undo the catch — the card is already theirs — so the poster goes
        back up and the catch message simply says nothing about a bounty.
        """
        try:
            await Bounty.objects.filter(pk=bounty.pk).aupdate(claimed_instance=ball)
            if bounty.reward:
                await player.add_money(
                    bounty.reward,
                    reason=BerryTransaction.Reason.BOUNTY,
                    description=f"Bounty on {self.name}",
                    server_id=ball.server_id,
                )
        except Exception:
            log.exception("Could not pay the bounty on %s to %s, putting it back up", self.name, user.id)
            await bounty.arelease()
            return None
        await score_quietly(player.pk, CrewWarRule.Source.BOUNTY_CLAIMED)
        # only the first catch ever gets here, so this is the event for "be the one who took the poster"
        bus.dispatch_soon(
            player,
            Event.BOUNTY_CLAIM,
            context=EventContext(
                instances=[ball], amount=bounty.reward, price=bounty.reward, server_id=ball.server_id
            ),
        )
        log.info(
            "%s (%s) claimed the bounty on %s for %s",
            user,
            user.id,
            self.name,
            bounty.reward,
            extra={"webhook": True},
        )
        return bounty

    async def catch_ball(
        self, user: discord.User | discord.Member, *, player: Player | None, guild: discord.Guild | None
    ) -> tuple[BallInstance, bool]:
        """
        Mark this countryball as caught and assign a new `BallInstance` (or transfer ownership if
        attribute `ballinstance` was set).

        Parameters
        ----------
        user: discord.User | discord.Member
            The user that will obtain the new countryball.
        player: Player
            If already fetched, add the player model here to avoid an additional query.
        guild: discord.Guild | None
            If caught in a guild, specify here for additional logs. Will be extracted from `user`
            if it's a member object.

        Returns
        -------
        tuple[bool, BallInstance]
            A tuple whose first value indicates if this is the first time this player catches this
            countryball. Second value is the newly created countryball.

            If `ballinstance` was set, this value is returned instead.

        Raises
        ------
        RuntimeError
            The `caught` attribute is already set to `True`. You should always check before calling
            this function that the ball was not caught.
        """
        if self.caught:
            raise RuntimeError("This ball was already caught!")
        self.caught = True
        self.catch_button.disabled = True
        self.style_catch_button("caught")
        caught_time = timezone.now()
        player = player or (await Player.objects.aget_or_create(discord_id=user.id))[0]
        is_new = not await BallInstance.objects.filter(player=player, ball=self.model).aexists()

        if self.ballinstance:
            if self.ballinstance.player_id == player.pk:
                # the owner caught their own dropped countryball back, nothing changed hands
                self.ballinstance.locked = None  # type: ignore
                await self.ballinstance.asave(update_fields=("locked",))
                return self.ballinstance, is_new

            # if specified, do not create a countryball but switch owner
            # it's important to register this as a trade to avoid bypass
            trade = await Trade.objects.acreate(player1=self.ballinstance.player, player2=player)
            await TradeObject.objects.acreate(
                trade=trade, player=self.ballinstance.player, ballinstance=self.ballinstance
            )
            self.ballinstance.trade_player = self.ballinstance.player
            self.ballinstance.player = player
            self.ballinstance.locked = None  # type: ignore
            await self.ballinstance.asave(update_fields=("player", "trade_player", "locked"))
            return self.ballinstance, is_new

        # stat may vary by +/- 20% of base stat
        bonus_attack = (
            self.atk_bonus
            if self.atk_bonus is not None
            else random.randint(-settings.max_attack_bonus, settings.max_attack_bonus)
        )
        bonus_health = (
            self.hp_bonus
            if self.hp_bonus is not None
            else random.randint(-settings.max_health_bonus, settings.max_health_bonus)
        )

        # a wanted poster is claimed before the card exists, so the special it carries can be put
        # on at creation rather than added afterwards: the card is drawn with it from the start
        bounty = await Bounty.aclaim(self.model.pk, player)

        # check if we can spawn cards with a special background
        special: Special | None = self.special

        if not special:
            special = self.get_random_special(guild.id if guild else None)
        if bounty is not None and bounty.cached_special:
            special = bounty.cached_special

        ball = BallInstance(
            ball=self.model,
            player=player,
            special=special,
            attack_bonus=bonus_attack,
            health_bonus=bonus_health,
            server_id=guild.id if guild else None,
            spawned_time=self.message.created_at,
            catch_date=caught_time,
        )
        # transient attribute, read by the achievement post_save signal to notify in the
        # channel the catch actually happened in, instead of a guild's configured spawn channel
        ball._catch_channel_id = self.message.channel.id  # type: ignore
        try:
            await ball.asave()
        except Exception:
            # the card never came into being, so the poster goes back up rather than staying
            # claimed by a catch that did not happen
            if bounty is not None:
                await bounty.arelease()
            raise

        if bounty is not None:
            self.claimed_bounty = await self._pay_bounty(bounty, ball, player, user)

        # logging and stats
        log.log(
            logging.INFO if user.id in self.bot.catch_log else logging.DEBUG,
            f"{user} caught {settings.collectible_name} {self.model}, {special=}",
        )
        if isinstance(user, discord.Member) and user.guild.member_count:
            caught_balls.labels(
                country=self.name,
                special=special,
                # observe the size of the server, rounded to the nearest power of 10
                guild_size=10 ** math.ceil(math.log(max(user.guild.member_count - 1, 1), 10)),
                spawn_algo=self.algo,
            ).inc()

        return ball, is_new

    def get_catch_message(self, ball: BallInstance, new_ball: bool, mention: str) -> str:
        """
        Generate a user-facing message after a ball has been caught.

        Parameters
        ----------
        ball: BallInstance
            The newly created ball instance
        new_ball: bool
            Boolean indicating if this is a new countryball in completion
            (as returned by `catch_ball`)
        """
        text = ""
        if self.claimed_bounty is not None:
            bounty = self.claimed_bounty
            text += "🏴‍☠️ **Wanted poster claimed!** You were first, and the bounty is yours"
            if bounty.reward:
                text += f": **{format_currency(bounty.reward, False, self.bot)}**"
            text += ".\n"
        if ball.specialcard and ball.specialcard.catch_phrase:
            text += f"*{ball.specialcard.catch_phrase}*\n"
        if new_ball:
            text += f"This is a **new {settings.collectible_name}** that has been added to your completion!\n"
        if self.ballinstance:
            text += f"This {settings.collectible_name} was dropped by <@{self.og_id}>\n"

        caught_message = (
            settings.get_random_message(PromptMessage.PromptType.CATCH).format(
                user=mention,
                collectible=settings.collectible_name,
                ball=self.name,
                collectibles=settings.plural_collectible_name,
                emoji=self.bot.get_emoji(self.model.emoji_id),
            )
            + " "
        )

        frame = f" {FRAME_EMOJI}" if ball.framed else ""
        return caught_message + f"`(#{ball.pk:0X}, {ball.attack_bonus:+}%/{ball.health_bonus:+}%)`{frame}\n\n{text}"
