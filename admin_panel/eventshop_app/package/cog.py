"""
The /shop commands: spend a pass's own currency, see what it buys, and give some of it to your crew.

The shop stays open as long as the pass lets anything be claimed — set a pass's `claim_until` past its `ends_at`
and players keep a window after the event to spend what they earned during it, which is what an advent event
wants: the quests stop, the spending does not.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from asgiref.sync import sync_to_async
from crew_app.models import CrewMembership
from currency_app.ledger import adjust_money
from currency_app.models import BerryTransaction
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import format_dt
from django.db import transaction
from django.utils import timezone
from eventpass_app import wallet
from eventpass_app.models import EventPass, PassWalletEntry
from eventpass_app.rewards import give_bundle
from eventpass_app.transformers import EventPassTransform

from ballsdex.core.utils.broadcast import main_spawn_channel
from ballsdex.core.utils.transformers import TTLModelTransformer
from ballsdex.core.utils.utils import is_staff
from bd_models.models import Player
from settings.models import settings

from ..boosts import buy_or_extend, describe, snapshot
from ..boosts import refresh as refresh_boosts
from ..models import ActiveBoost, BoostKind, ShopOffer, ShopPurchase

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("eventshop")

# how often the snapshot of the running boosts is rebuilt, and how often one spawn of a burst goes out
TICK_SECONDS = 30


def shop_open(event_pass: EventPass, at=None) -> bool:
    """
    Whether this pass's shop takes money right now.

    Open from the moment the pass starts until the last date it lets anything be claimed, so the window after
    an event — where the quests are over but the currency is still worth something — comes for free.
    """
    at = at or timezone.now()
    if event_pass.status != EventPass.Status.ACTIVE or not event_pass.currency_name:
        return False
    if event_pass.starts_at and at < event_pass.starts_at:
        return False
    closes = event_pass.claim_until or event_pass.ends_at
    return not closes or at <= closes


async def open_shops() -> list[EventPass]:
    """Every pass whose shop is open, in the order the passes are listed."""
    now = timezone.now()
    found = [
        event_pass
        async for event_pass in EventPass.objects.filter(status=EventPass.Status.ACTIVE)
        .exclude(currency_name="")
        .order_by("position", "pk")
    ]
    return [event_pass for event_pass in found if shop_open(event_pass, now)]


async def only_shop(event_pass: EventPass | None) -> tuple[EventPass | None, str]:
    """
    The pass to work on: the one named, else the only one with an open shop. Returns (pass, what to say).
    """
    if event_pass is not None:
        if not shop_open(event_pass):
            return None, f"The shop of **{event_pass.name}** is closed."
        return event_pass, ""
    shops = await open_shops()
    if not shops:
        return None, "No event shop is open right now."
    if len(shops) > 1:
        names = ", ".join(f"**{shop.name}**" for shop in shops)
        return None, f"Several shops are open: name the one you mean with `event_pass`. ({names})"
    return shops[0], ""


class ShopOfferTransformer(TTLModelTransformer[ShopOffer]):
    """The offers a player can pick from: what is on sale right now, with its price in the label."""

    name = "offer"
    model = ShopOffer
    ttl = 30

    def get_queryset(self) -> "QuerySet[ShopOffer]":
        return ShopOffer.objects.filter(enabled=True).select_related("event_pass", "boost", "reward")

    async def get_options(
        self, interaction: discord.Interaction["BallsDexBot"], value: str
    ) -> list[app_commands.Choice[str]]:
        await self.maybe_refresh()
        now = timezone.now()
        choices: list[app_commands.Choice[str]] = []
        for offer in self.items.values():
            if not offer.is_on_sale(now) or not shop_open(offer.event_pass, now):
                continue
            label = f"{offer.name} — {offer.price:,} {offer.event_pass.currency_name}"
            if offer.left is not None:
                label += f" ({offer.left} left)"
            if value.lower() not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=str(offer.pk)))
            if len(choices) == 25:
                break
        return choices


ShopOfferTransform = app_commands.Transform[ShopOffer, ShopOfferTransformer]


def price_text(event_pass: EventPass, offer: ShopOffer) -> str:
    """Every way this offer can be paid for, in one line."""
    parts = []
    if offer.price:
        parts.append(wallet.format_tokens(event_pass, offer.price))
    if offer.price_berries:
        parts.append(f"{offer.price_berries:,} berries")
    return " · ".join(parts) or "no price"


class PayWith(discord.ui.View):
    """
    Which currency to pay an offer with, when it takes both.

    Only the player who asked can press, and a button they cannot afford is shown disabled rather than
    hidden — knowing an offer takes berries, and how many, is worth more than a tidy row of buttons.
    """

    def __init__(self, user_id: int, event_pass: EventPass, offer: ShopOffer, tokens: int, berries: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.chosen: str | None = None
        self.add_item(
            self._button("tokens", wallet.format_tokens(event_pass, offer.price), tokens >= (offer.price or 0))
        )
        self.add_item(
            self._button("berries", f"{offer.price_berries:,} berries", berries >= (offer.price_berries or 0))
        )

    def _button(self, kind: str, label: str, affordable: bool) -> discord.ui.Button:
        button: discord.ui.Button = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.blurple if affordable else discord.ButtonStyle.grey,
            disabled=not affordable,
        )

        async def pressed(interaction: discord.Interaction):
            self.chosen = kind
            await interaction.response.defer()
            self.stop()

        button.callback = pressed
        return button

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This one is not yours to answer.", ephemeral=True)
            return False
        return True


class Refused(Exception):
    """A purchase that cannot go through, with the line to show the buyer."""


def _buy(
    offer_id: int,
    player_id: int,
    crew_id: int | None,
    server_id: int | None,
    channel_id: int | None,
    paid_with: str = "tokens",
) -> str:
    """
    Take the money and hand the goods over, both or neither. Returns the line shown to the buyer.

    `paid_with` says which of the two prices to charge. An offer priced a single way is charged that way
    whatever is asked for, so a stale button cannot take the wrong currency.

    The offer row is locked for the duration, so a stock of one cannot be sold twice and two people clicking at
    the same instant cannot both get the last copy. `Refused` is raised with the reason when it cannot happen,
    before anything is taken.
    """
    with transaction.atomic():
        offer = (
            # `of` matters: boost and reward are nullable, so select_related joins them with an OUTER JOIN,
            # and Postgres refuses FOR UPDATE on the nullable side of one. Only the offer row needs locking
            # anyway — the boost and the bundle are read, never written, by this.
            ShopOffer.objects.select_for_update(of=("self",))
            .select_related("event_pass", "boost", "reward")
            .filter(pk=offer_id)
            .first()
        )
        if offer is None:
            raise Refused("That offer is gone.")
        event_pass = offer.event_pass
        if not shop_open(event_pass):
            raise Refused(f"The shop of **{event_pass.name}** is closed.")
        if not offer.is_on_sale():
            raise Refused(f"**{offer.name}** is not on sale right now.")
        if offer.per_player and ShopPurchase.objects.filter(offer=offer, player_id=player_id).count() >= (
            offer.per_player
        ):
            raise Refused(f"You have already bought **{offer.name}** as many times as you may.")

        ways = offer.ways_to_pay
        if not ways:
            raise Refused(f"**{offer.name}** has no price, so it cannot be bought.")
        # an offer that only takes one currency takes it whatever the caller asked for
        paid_with = paid_with if paid_with in ways else ways[0]
        cost = offer.cost(paid_with)
        label = f"{event_pass.name}: {offer.name}"[: PassWalletEntry.DESCRIPTION_MAX_LENGTH]

        if paid_with == "berries":
            if offer.from_crew_pot:
                raise Refused("An offer paid out of the crew's pot cannot be paid in berries.")
            try:
                adjust_money(
                    player_id,
                    -cost,
                    reason=BerryTransaction.Reason.EVENT_SHOP,
                    description=label[: BerryTransaction.DESCRIPTION_MAX_LENGTH],
                    server_id=server_id,
                )
            except ValueError as error:
                raise Refused(f"**{offer.name}** costs {cost:,} berries, and you do not have them.") from error
        elif offer.from_crew_pot:
            if crew_id is None:
                raise Refused("That offer is paid out of a crew's pot, and no crew was given.")
            try:
                wallet.adjust_crew(
                    crew_id, event_pass.pk, -cost, reason=PassWalletEntry.Reason.CREW_SPEND, description=label
                )
            except wallet.NotEnough as error:
                raise Refused(
                    f"The pot holds {wallet.format_tokens(event_pass, error.held)}, and this costs "
                    f"{wallet.format_tokens(event_pass, cost)}."
                ) from error
        else:
            try:
                wallet.adjust(player_id, event_pass.pk, -cost, reason=PassWalletEntry.Reason.SHOP, description=label)
            except wallet.NotEnough as error:
                raise Refused(
                    f"You hold {wallet.format_tokens(event_pass, error.held)}, and this costs "
                    f"{wallet.format_tokens(event_pass, cost)}."
                ) from error

        offer.sold += 1
        offer.save(update_fields=("sold",))

        if offer.kind == ShopOffer.Kind.BOOST and offer.boost is not None:
            running = buy_or_extend(offer.boost, player_id, label=offer.boost.name)
            summary = f"{offer.boost.label} until {running.ends_at:%H:%M} UTC"
        elif offer.kind == ShopOffer.Kind.REWARD and offer.reward is not None:
            result = give_bundle(player_id, event_pass, offer.reward, server_id=server_id, channel_id=channel_id)
            summary = ", ".join(result.lines) or "nothing"
        else:
            # an offer whose contents were deleted under it: the money goes back rather than vanishing
            raise Refused(f"**{offer.name}** is not set up properly. Nothing was taken.")

        ShopPurchase.objects.create(
            offer=offer,
            player_id=player_id,
            crew_id=crew_id if offer.from_crew_pot else None,
            price=cost,
            paid_with=paid_with,
            summary=summary[:256],
        )
    return summary


class EventShopCog(commands.GroupCog, name="Event shop", group_name="shop"):
    """Spend what an event pass hands out."""

    admin = app_commands.Group(name="admin", description="Staff commands for the event shop.")

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def cog_load(self):
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    # ── the loop ────────────────────────────────────────────────────────────────────────────────

    @tasks.loop(seconds=TICK_SECONDS)
    async def tick(self):
        """
        Keep the snapshot of the running boosts current, announce the new ones, and let a burst spawn.

        Everything in here is guarded on its own: a burst that cannot find its channel must not stop the
        snapshot from being rebuilt, or every server would keep playing with an hour that is long over.
        """
        try:
            await refresh_boosts()
        except Exception:
            log.exception("could not refresh the boosts")
        try:
            await self.announce_boosts()
        except Exception:
            log.exception("could not announce a boost")
        try:
            await self.run_bursts()
        except Exception:
            log.exception("could not run a burst of spawns")

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    async def announce_boosts(self):
        """
        Say in the main server that a boost has started. The date is written only once the message is out, so a
        boost nobody could be told about is still announced on the next pass rather than silently skipped.
        """
        now = timezone.now()
        due = ActiveBoost.objects.filter(
            announced_at__isnull=True, ends_at__gt=now, started_at__lte=now
        ).select_related("boost")
        async for running in due:
            if running.boost is not None and not running.boost.announce:
                await ActiveBoost.objects.filter(pk=running.pk).aupdate(announced_at=now)
                continue
            channel = await main_spawn_channel(self.bot, running.channel_id)
            if channel is None:
                continue
            embed = discord.Embed(
                title=f"{running.label or 'A boost'} is live",
                colour=settings.embed_colour,
                description=describe(running.kind, running.magnitude, running.spawns_left),
            )
            if running.kind != BoostKind.SPAWN_PARTY:
                embed.add_field(name="Until", value=format_dt(running.ends_at, style="R"))
            if running.cached_special:
                embed.add_field(name="The special", value=running.cached_special.name)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                log.warning("could not announce boost %s in %s", running.pk, channel.id)
                continue
            await ActiveBoost.objects.filter(pk=running.pk).aupdate(announced_at=now)

    async def run_bursts(self):
        """
        Let one spawn of each running burst go out, so five spawns land over a few minutes rather than all at
        once. The count lives in the row, so a restart halfway through loses nothing.
        """
        now = timezone.now()
        spawner = self.bot.get_cog("CountryBallsSpawner")
        if spawner is None:
            return
        due = ActiveBoost.objects.filter(kind=BoostKind.SPAWN_PARTY, spawns_left__gt=0, ends_at__gt=now)
        async for burst in due:
            channel = await main_spawn_channel(self.bot, burst.channel_id)
            if channel is None:
                continue
            # claim the spawn before sending it: two overlapping ticks cannot both spend the same one
            if not await ActiveBoost.objects.filter(pk=burst.pk, spawns_left__gt=0).aupdate(
                spawns_left=burst.spawns_left - 1
            ):
                continue
            ball = await spawner.countryball_cls.get_random(self.bot, guild_id=channel.guild.id)
            await ball.spawn(channel)

    # ── the commands ────────────────────────────────────────────────────────────────────────────

    @app_commands.command()
    @app_commands.describe(event_pass="The event, when more than one shop is open.")
    async def balance(
        self, interaction: discord.Interaction["BallsDexBot"], event_pass: EventPassTransform | None = None
    ):
        """
        What you hold of an event's currency.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        event_pass, problem = await only_shop(event_pass)
        if event_pass is None:
            await interaction.followup.send(problem)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        held = await wallet.abalance(player.pk, event_pass.pk)
        embed = discord.Embed(
            title=f"{event_pass.emoji} {event_pass.name}".strip(),
            colour=settings.embed_colour,
            description=f"You hold **{wallet.format_tokens(event_pass, held)}**.",
        )
        membership = await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
        if membership is not None:
            pot = await wallet.acrew_balance(membership.crew_id, event_pass.pk)
            embed.add_field(
                name=membership.crew.label,
                value=f"The crew's pot holds {wallet.format_tokens(event_pass, pot)}.",
                inline=False,
            )
        closes = event_pass.claim_until or event_pass.ends_at
        if closes:
            embed.set_footer(text="Spend it before the shop closes.")
            embed.add_field(name="Shop closes", value=format_dt(closes, style="R"))
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    @app_commands.describe(event_pass="The event, when more than one shop is open.")
    async def view(self, interaction: discord.Interaction["BallsDexBot"], event_pass: EventPassTransform | None = None):
        """
        What an event's currency buys right now.
        """
        await interaction.response.defer(thinking=True)
        event_pass, problem = await only_shop(event_pass)
        if event_pass is None:
            await interaction.followup.send(problem, ephemeral=True)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        held = await wallet.abalance(player.pk, event_pass.pk)
        now = timezone.now()
        lines: list[str] = []
        async for offer in (
            ShopOffer.objects.filter(event_pass=event_pass, enabled=True)
            .select_related("boost")
            .order_by("position", "pk")
        ):
            if not offer.is_on_sale(now):
                continue
            head = f"**{offer.label}** — {price_text(event_pass, offer)}"
            if offer.left is not None:
                head += f" · {offer.left} left"
            if offer.from_crew_pot:
                head += " · from the crew's pot"
            lines.append(head)
            detail = offer.description.strip()
            if not detail and offer.boost is not None:
                detail = describe(offer.boost.kind, offer.boost.magnitude, offer.boost.spawns)
                if offer.boost.kind != BoostKind.SPAWN_PARTY:
                    detail += f", for {offer.boost.duration_minutes} minutes"
            if detail:
                lines.append(f"-# {detail}")
        body = "\n".join(lines) or "Nothing is on sale right now."
        embed = discord.Embed(
            title=f"{event_pass.emoji} {event_pass.name} shop".strip(),
            colour=settings.embed_colour,
            # an embed holds 4096 characters: a shop long enough to reach that is cut, not refused
            description=body[:4000] + ("\n-# …and more." if len(body) > 4000 else ""),
        )
        embed.set_footer(text=f"You hold {wallet.format_tokens(event_pass, held)} · buy with /shop buy")
        running = snapshot()
        if running.anything:
            embed.add_field(
                name="Running now",
                value="\n".join(
                    f"{BoostKind(kind).label} until {format_dt(until, style='R')}"  # type: ignore[arg-type]
                    for kind, until in running.until.items()
                )
                or "—",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    @app_commands.describe(offer="What you are buying.")
    async def buy(self, interaction: discord.Interaction["BallsDexBot"], offer: ShopOfferTransform):
        """
        Buy something with an event's currency.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        crew_id = await CrewMembership.objects.filter(player=player).values_list("crew_id", flat=True).afirst()
        if offer.from_crew_pot and not await is_staff(interaction):
            await interaction.followup.send(
                "That offer is paid out of the crew's pot, and only staff can spend a pot: a crew has no "
                "captain to spend it for everyone. Ask them."
            )
            return
        ways = offer.ways_to_pay
        if not ways:
            await interaction.followup.send(f"**{offer.name}** has no price, so it cannot be bought.")
            return
        paid_with = ways[0]
        if len(ways) > 1:
            # both prices are set, so the choice is the player's
            held = await wallet.abalance(player.pk, offer.event_pass_id)
            view = PayWith(interaction.user.id, offer.event_pass, offer, held, player.money)
            embed = discord.Embed(
                title=offer.label,
                colour=settings.embed_colour,
                description=(offer.description.strip() or "") + "\n\nHow do you want to pay?",
            )
            embed.set_footer(text=f"You hold {wallet.format_tokens(offer.event_pass, held)} · {player.money:,} berries")
            message = await interaction.followup.send(embed=embed, view=view, wait=True)
            await view.wait()
            if view.chosen is None:
                await message.edit(content="Nothing bought.", embed=None, view=None)
                return
            paid_with = view.chosen
            await message.edit(view=None)
        try:
            summary = await sync_to_async(_buy)(
                offer.pk, player.pk, crew_id, interaction.guild_id, interaction.channel_id, paid_with
            )
        except Refused as error:
            await interaction.followup.send(str(error))
            return
        await interaction.followup.send(f"Bought **{offer.name}**. You got: {summary}")

    @app_commands.command()
    @app_commands.describe(amount="How much to give.", event_pass="The event, when more than one shop is open.")
    async def give(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        amount: app_commands.Range[int, 1, 1_000_000_000],
        event_pass: EventPassTransform | None = None,
    ):
        """
        Give some of your event currency to your own crew's pot.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        event_pass, problem = await only_shop(event_pass)
        if event_pass is None:
            await interaction.followup.send(problem)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        membership = await CrewMembership.objects.filter(player=player).select_related("crew").afirst()
        if membership is None:
            await interaction.followup.send("You are in no crew, so there is no pot to give to.")
            return
        try:
            pot = await wallet.agive_to_crew(
                player.pk,
                membership.crew_id,
                event_pass.pk,
                amount,
                label=f"{interaction.user} to {membership.crew.name}",
            )
        except wallet.NotEnough as error:
            await interaction.followup.send(f"You only hold {wallet.format_tokens(event_pass, error.held)}.")
            return
        await interaction.followup.send(
            f"Given {wallet.format_tokens(event_pass, amount)} to **{membership.crew.label}**. "
            f"Its pot now holds {wallet.format_tokens(event_pass, pot)}. A gift is one way: it cannot be taken "
            f"back."
        )

    @admin.command(name="tokens")
    @app_commands.describe(
        user="Who to credit.",
        amount="How much. A negative number takes it back.",
        event_pass="The event, when more than one pass has a currency.",
    )
    async def admin_tokens(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        user: discord.User,
        amount: app_commands.Range[int, -1_000_000_000, 1_000_000_000],
        event_pass: EventPassTransform | None = None,
    ):
        """
        Give a player an event's currency, or take it back.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not await is_staff(interaction):
            await interaction.followup.send("That one is for staff.")
            return
        if not amount:
            await interaction.followup.send("That would move nothing.")
            return
        event_pass, problem = await only_shop(event_pass)
        if event_pass is None:
            await interaction.followup.send(problem)
            return

        player, _ = await Player.objects.aget_or_create(discord_id=user.id)
        try:
            left = await wallet.aadjust(
                player.pk,
                event_pass.pk,
                amount,
                reason=PassWalletEntry.Reason.ADMIN,
                description=f"By {interaction.user}"[: PassWalletEntry.DESCRIPTION_MAX_LENGTH],
            )
        except wallet.NotEnough as error:
            await interaction.followup.send(
                f"{user.mention} only holds {wallet.format_tokens(event_pass, error.held)}."
            )
            return

        moved = wallet.format_tokens(event_pass, abs(amount))
        verb = "Gave" if amount > 0 else "Took back"
        await interaction.followup.send(
            f"{verb} {moved} {'to' if amount > 0 else 'from'} {user.mention}. "
            f"They now hold {wallet.format_tokens(event_pass, left)}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        log.info(
            "%s %s %s %s %s on %s, leaving %s.",
            interaction.user,
            verb.lower(),
            moved,
            "to" if amount > 0 else "from",
            user,
            event_pass.name,
            left,
            extra={"webhook": True},
        )

    @app_commands.command()
    async def boosts(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        The boosts running on the main server right now.
        """
        await interaction.response.defer(thinking=True)
        now = timezone.now()
        running = [
            boost
            async for boost in ActiveBoost.objects.filter(ends_at__gt=now, started_at__lte=now).order_by("ends_at")
        ]
        if not running:
            await interaction.followup.send("Nothing is boosted right now.")
            return
        lines = []
        for boost in running:
            what = describe(boost.kind, boost.magnitude, boost.spawns_left)
            if boost.kind == BoostKind.SPAWN_PARTY:
                lines.append(f"**{boost.label}** — {boost.spawns_left} spawns still to come")
                continue
            lines.append(f"**{boost.label}** — {what}, until {format_dt(boost.ends_at, style='R')}")
        embed = discord.Embed(title="Running now", colour=settings.embed_colour, description="\n".join(lines))
        embed.set_footer(text="Boosts only ever apply to the main server.")
        await interaction.followup.send(embed=embed)
