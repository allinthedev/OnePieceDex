import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, AsyncIterator, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Container, Section, Separator, TextDisplay, Thumbnail
from django.db.models import Q
from django.utils import timezone

from ballsdex.core.discord import LayoutView, View
from ballsdex.core.game_events import Event, EventContext, bus
from ballsdex.core.utils.menus import ChunkedListSource, ItemFormatter, Menu
from ballsdex.core.utils.transformers import BallInstanceTransform
from bd_models.models import BallInstance, Player
from settings.models import settings

from ..models import (
    BattleItem,
    BattleRecord,
    BattleSession,
    BattleSessionStatus,
    BattleSettings,
    Buff,
    EquipAffinity,
    EquipResistance,
    GroupMatchup,
    Matchup,
    PlayerBattleItem,
    group_ids_of,
    group_sizes,
    role_of,
)
from . import sessions
from .engine import BattleAction, BattleBall, hp_bar, resolve_action
from .loadout import (
    ROLE_CHARACTER,
    SLOTS,
    AffinityRule,
    ResistanceRule,
    affinity_percent,
    apply_equipment,
    contribution,
    equipment_line,
    has_full_set,
    relation_multiplier,
    resistance_multiplier,
)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.battle")

MAX_LOG_LINES = 5
# the most characters a deck can be asked to hold with /battle start, unless the default set in the panel
# is higher still. A battle is played one character at a time: past this it never ends
MAX_DECK_SIZE = 10
# what a click is told when its battle is finished or was called off
BATTLE_OVER = "This battle is over."
ITEM_ACTION_FOR_EFFECT = {
    "extra_heal": BattleAction.HEAL,
    "attack_boost": BattleAction.ATTACK,
    "guaranteed_crit": BattleAction.CRIT,
}
# Same flat ATK/HP bonus per special as /boss fights (extra/... boss/cog.py's SPECIAL_BUFFS),
# keyed by the special's emoji rather than a hardcoded name so it still matches if a special is
# renamed. Field name on BattleSettings holding that bonus amount.
SPECIAL_BONUS_SETTING = {
    "⚡": "haki_special_bonus",
    "✨": "shiny_special_bonus",
    "🔮": "mythical_special_bonus",
}


def special_bonus(countryball: BallInstance, battle_settings: BattleSettings) -> int:
    special = countryball.specialcard
    if not special or not special.emoji:
        return 0
    field_name = SPECIAL_BONUS_SETTING.get(special.emoji)
    return getattr(battle_settings, field_name) if field_name else 0


async def serialize_ball(
    countryball: BallInstance, owner_id: int, bot: "BallsDexBot", battle_settings: BattleSettings
) -> BattleBall:
    buff = await Buff.aget_buff(countryball)
    ball = countryball.countryball
    emoji = bot.get_emoji(ball.emoji_id)
    bonus = special_bonus(countryball, battle_settings)
    # multiplied here, once, with everything the card brings: attack and health are about the same number
    # on every treasure, and without this a hit takes most of an equal opponent's health
    health = round((countryball.health + (buff.health if buff else 0) + bonus) * battle_settings.health_multiplier)
    attack = countryball.attack + (buff.attack if buff else 0) + bonus
    return BattleBall(
        instance_id=countryball.pk,
        ball_id=ball.pk,
        name=ball.country,
        owner_id=owner_id,
        health=health,
        max_health=health,
        attack=attack,
        # kept apart from the two above, which also carry whatever the fighter is given to wear
        base_attack=attack,
        base_health=health,
        rarity=ball.rarity,
        emoji=str(emoji) if emoji else "",
        capacity_name=ball.capacity_name or "",
        # the effect comes from the buff, never from ball.capacity_logic: that column holds the treasure's
        # frames, and reading it here is what used to make every Capacity a plain 1.5x attack
        capacity_effect=(buff.capacity_effect if buff else ""),
        capacity_value=(buff.capacity_value if buff else 0.0),
    )


def serialize_item(
    countryball: BallInstance, slot: str, percent: int, bot: "BallsDexBot", health_multiplier: float = 1.0
) -> dict:
    """
    A weapon or a devil fruit as it sits on a fighter: its own stats, already worked out for this very card,
    and the share of them its bearer gets. Plain values only, so it goes into the battle state as it is.
    """
    ball = countryball.countryball
    emoji = bot.get_emoji(ball.emoji_id)
    return {
        "slot": slot,
        "instance_id": countryball.pk,
        "ball_id": ball.pk,
        "name": ball.country,
        "emoji": str(emoji) if emoji else "",
        "attack": countryball.attack,
        # an item's health is multiplied like its bearer's own, or equipment would weigh on attack alone
        "health": round(countryball.health * health_multiplier),
        "percent": percent,
        # kept with the item so a resistance about "any blunt weapon" needs no lookup in the middle of a turn
        "group_ids": group_ids_of(ball.pk),
    }


async def equip_percent(character_ball_id: int, item_ball_id: int, battle_settings: BattleSettings) -> int:
    """
    The share of this item's stats this character gets, from the affinity table: their own line for it,
    their line for its kind, the line of its kind for anybody, or the default in the settings.
    """
    item_groups = group_ids_of(item_ball_id)
    rows = EquipAffinity.objects.filter(Q(character_id=character_ball_id) | Q(character__isnull=True)).filter(
        Q(item_id=item_ball_id) | Q(item_group_id__in=item_groups)
    )
    rules = [
        AffinityRule(
            percent=row.percent,
            character_id=row.character_id,
            item_id=row.item_id,
            group_id=row.item_group_id,
            pk=row.pk,
        )
        async for row in rows
    ]
    return affinity_percent(
        rules, character_ball_id, item_ball_id, item_groups, group_sizes(), battle_settings.default_equip_percent
    )


async def get_equipment_multiplier(
    attacker: BattleBall, defender: BattleBall, battle_settings: BattleSettings
) -> float:
    """
    What the defender's equipment does to this hit, given what the attacker wears. 1.0 when the attacker
    wears nothing: these rules are about equipment, `Matchup` is the one about who the fighters are.
    """
    if not attacker.equipment:
        return 1.0
    rows = EquipResistance.objects.filter(Q(character_id=defender.ball_id) | Q(character__isnull=True))
    rules = [
        ResistanceRule(
            multiplier=row.multiplier,
            character_id=row.character_id,
            equipped_item_id=row.equipped_item_id,
            against_item_id=row.against_item_id,
            against_group_id=row.against_group_id,
            pk=row.pk,
        )
        async for row in rows
    ]
    if not rules:
        return 1.0
    return resistance_multiplier(
        rules,
        defender.ball_id,
        [entry["ball_id"] for entry in defender.equipment],
        [(entry["ball_id"], entry.get("group_ids", [])) for entry in attacker.equipment],
        group_sizes(),
        floor=battle_settings.resistance_floor,
        ceiling=battle_settings.resistance_ceiling,
    )


def side_balls(state: dict, side: str) -> list[dict]:
    return state[f"{side}_balls"]


def current_ball(state: dict, side: str) -> Optional[dict]:
    return next((b for b in side_balls(state, side) if not b["dead"]), None)


def other_side(side: str) -> str:
    return "p2" if side == "p1" else "p1"


def total_power(balls: list[dict]) -> int:
    return sum(b["attack"] + b["max_health"] for b in balls)


async def get_matchup_multiplier(attacker_ball_id: int, defender_ball_id: int) -> float:
    """
    What who the two fighters are does to a hit: the line about this exact pair, or failing that the bond
    of a group they both belong to.
    """
    if attacker_ball_id == defender_ball_id:
        # a mirror match, the same character on both sides: a bond between crewmates says nothing about
        # somebody fighting their own double, and no pair can name it either
        return 1.0
    row = await Matchup.objects.filter(attacker_id=attacker_ball_id, defender_id=defender_ball_id).afirst()
    if row is not None:
        return row.damage_multiplier
    attacker_groups = group_ids_of(attacker_ball_id)
    defender_groups = group_ids_of(defender_ball_id)
    shared = set(attacker_groups) & set(defender_groups)
    if not shared:
        return 1.0
    bonds = [
        (bond.group_id, bond.damage_multiplier) async for bond in GroupMatchup.objects.filter(group_id__in=shared)
    ]
    return relation_multiplier(None, bonds, attacker_groups, defender_groups, group_sizes())


def retired(countryball: BallInstance) -> str | None:
    """
    Why this card cannot take part in a battle, when its treasure has been retired from the dex.

    A retired treasure still sits in the collections of the players who got it while it was around, and
    still belongs to its groups, so being a character or a weapon is not enough to be let in: nothing about
    a retired treasure is balanced or even listed any more.
    """
    ball = countryball.countryball
    if ball.enabled:
        return None
    return f"**{ball.country}** has been retired from the dex and sits battles out."


def deck_lines(balls: list[dict]) -> str:
    if not balls:
        return "Empty"
    lines = []
    for b in balls:
        if b["dead"]:
            lines.append(f"~~{b['emoji']} {b['name']}~~ 💀")
        else:
            bar = hp_bar(b["health"], b["max_health"])
            lines.append(f"{b['emoji']} {b['name']} `{bar}` {b['health']}/{b['max_health']}")
            worn = equipment_line(b.get("equipment") or [])
            if worn:
                lines.append(f"-# ┗ {worn}")
    text = "\n".join(lines)
    # an embed field holds 1024 characters, and a big deck in full gear can get close
    return text if len(text) <= 1024 else text[:1020].rsplit("\n", 1)[0] + "\n…"


async def player_name(bot: "BallsDexBot", discord_id: int) -> str:
    user = bot.get_user(discord_id)
    if user is None:
        try:
            user = await bot.fetch_user(discord_id)
        except discord.HTTPException:
            return f"Player {discord_id}"
    return user.display_name


class BattleShopSelect(discord.ui.Select):
    def __init__(self, items: list[BattleItem]):
        options = [
            discord.SelectOption(
                label=f"{item.name} — {item.price} {settings.currency_plural}",
                description=(item.description or "")[:100],
                value=str(item.pk),
            )
            for item in items
        ]
        super().__init__(placeholder="Buy an item...", options=options)

    async def callback(self, interaction: discord.Interaction["BallsDexBot"]):
        item_id = int(self.values[0])
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            item, quantity, balance = await sessions.abuy(player.pk, item_id)
        except sessions.ItemGone:
            await interaction.response.send_message("That item is no longer available.", ephemeral=True)
            return
        except ValueError:
            # the ledger's way of saying the purse is too light
            item = await BattleItem.objects.filter(pk=item_id).afirst()
            name = f"**{item.name}**" if item else "that"
            await interaction.response.send_message(
                f"You don't have enough {settings.currency_display_plural(interaction.client)} for {name}.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"Bought **{item.name}**! You now have **{quantity}**.\n"
                f"Balance: {balance} {settings.currency_display_plural(interaction.client)}"
            )
        )


class BattleShopView(View):
    def __init__(self, items: list[BattleItem]):
        super().__init__(timeout=120)
        if items:
            self.add_item(BattleShopSelect(items))


class BattleProposalView(View):
    def __init__(self, session_id: int, player1_id: int, player2_id: int):
        super().__init__(timeout=None)
        self.session_id = session_id
        self.player1_id = player1_id
        self.player2_id = player2_id

    async def interaction_check(self, interaction: discord.Interaction["BallsDexBot"]) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id not in (self.player1_id, self.player2_id):
            await interaction.response.send_message("You aren't a part of this battle.", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.success, emoji="✔", label="Ready")
    async def ready(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.on_ready_click(interaction, self)

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="✖", label="Cancel")
    async def cancel(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.on_cancel_click(interaction, self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🛒", label="Shop")
    async def shop(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.open_shop(interaction)


class BattleTurnView(View):
    """
    The buttons of one turn of one battle.

    It remembers the turn it was made for. A click that arrives once that turn has been played, from these
    buttons or from an item menu opened under them, is turned away by the cog, whoever it comes from.

    It has no timeout of its own. discord.py pushes a view's timeout back on every click it accepts, so a
    player could hold their turn open for as long as they kept pressing Item: the cog keeps the clock.
    """

    def __init__(self, session_id: int, turn: int, active_user_id: int, other_user_id: int, capacity_label: str):
        super().__init__(timeout=None)
        self.session_id = session_id
        self.turn = turn
        self.active_user_id = active_user_id
        self.other_user_id = other_user_id
        self.capacity.label = capacity_label[:80] or "Capacity"

    async def interaction_check(self, interaction: discord.Interaction["BallsDexBot"]) -> bool:
        if not await super().interaction_check(interaction):
            return False
        # both players get through: whose turn it is is the cog's to say, on the state as it is once the
        # click is being dealt with, and the one kept waiting has to be able to forfeit
        if interaction.user.id not in (self.active_user_id, self.other_user_id):
            await interaction.response.send_message("You aren't a part of this battle.", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="⚔", label="Attack")
    async def attack(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.on_turn_action(interaction, self, BattleAction.ATTACK)

    @discord.ui.button(style=discord.ButtonStyle.success, emoji="❤", label="Heal")
    async def heal(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.on_turn_action(interaction, self, BattleAction.HEAL)

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="🎲", label="Crit Gamble")
    async def crit(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.on_turn_action(interaction, self, BattleAction.CRIT)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Capacity")
    async def capacity(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.on_turn_action(interaction, self, BattleAction.CAPACITY)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🎒", label="Item")
    async def item(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.on_item_click(interaction, self)

    @discord.ui.button(style=discord.ButtonStyle.danger, label="Forfeit", row=1)
    async def forfeit(self, interaction: discord.Interaction["BallsDexBot"], button: discord.ui.Button):
        cog: "Battle" = interaction.client.get_cog("Battle")  # type: ignore
        await cog.on_forfeit_click(interaction, self)


@dataclass
class LiveTurn:
    """The turn being played in one battle: its buttons, and the message they sit on."""

    view: BattleTurnView
    message: discord.Message | discord.PartialMessage


class Battle(commands.GroupCog):
    """
    Brawl with your treasures!
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self._settings: BattleSettings | None = None
        # One lock per battle. Whatever reads a battle's state and writes it back holds it, so two clicks
        # landing together are dealt with one after the other, the second on what the first left behind.
        self._locks: dict[int, asyncio.Lock] = {}
        # A player is checked for being free and then given a battle: two /battle start at the same moment
        # must not both get past the check.
        self._starting = asyncio.Lock()
        self._proposals: dict[int, BattleProposalView] = {}
        self._turns: dict[int, LiveTurn] = {}
        self._timers: dict[int, asyncio.Task] = {}

    async def cog_unload(self):
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()

    async def get_settings(self, refresh: bool = True) -> BattleSettings:
        if not self._settings:
            self._settings = await BattleSettings.aload()
        if refresh:
            await self._settings.arefresh_from_db()
        return self._settings

    # -- What is kept in memory about a battle ------------------------------------------------

    def _lock(self, session_id: int) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    @staticmethod
    async def _fetch(session_id: int) -> BattleSession | None:
        return await BattleSession.objects.select_related("player1", "player2").filter(pk=session_id).afirst()

    @staticmethod
    async def _save(session: BattleSession):
        # updated_at is named because Django only refreshes it when it is: it is what tells a battle being
        # played from one that was abandoned
        await session.asave(update_fields=("state", "updated_at"))

    def _forget(self, session_id: int):
        """Let go of a battle that is over: its buttons stop listening and its clock stops."""
        timer = self._timers.pop(session_id, None)
        # the clock is what ends a battle when it plays the last blow itself: it must not cancel itself
        # halfway through doing so
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        live = self._turns.pop(session_id, None)
        if live is not None:
            live.view.stop()
        proposal = self._proposals.pop(session_id, None)
        if proposal is not None:
            proposal.stop()
        self._locks.pop(session_id, None)

    async def resume_timers(self):
        """
        Give every battle being played its clock back, after a reload of the package.

        The boards posted before the reload still answer, but the clocks belonged to the cog that was
        unloaded: without this, a turn nobody plays would wait for ever.
        """
        battle_settings = await self.get_settings()
        async for session in BattleSession.objects.filter(status=BattleSessionStatus.ACTIVE):
            self._arm_timer(session.pk, session.state.get("turn", 0), battle_settings.turn_timeout_seconds)

    # -- Proposal phase -----------------------------------------------------------------

    @app_commands.command()
    async def start(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        opponent: discord.Member,
        max_size: Optional[int] = None,
        wager: app_commands.Range[int, 0] = 0,
    ):
        """
        Start a new battle with a chosen user.

        Parameters
        ----------
        opponent: discord.Member
            The player you want to battle.
        max_size: int
            Optional. How many characters each deck can hold.
        wager: int
            Optional. Berries both players stake — winner takes all. Leave it out to play for nothing.
        """
        if opponent.bot or opponent.id == interaction.user.id:
            await interaction.response.send_message("You must pick another player.", ephemeral=True)
            return

        battle_settings = await self.get_settings()
        deck_size = max_size or battle_settings.max_deck_size
        if deck_size < 1:
            await interaction.response.send_message(
                f"You must allow at least 1 {settings.collectible_name} in the deck!", ephemeral=True
            )
            return
        largest = max(MAX_DECK_SIZE, battle_settings.max_deck_size)
        if deck_size > largest:
            await interaction.response.send_message(
                f"A deck holds {largest} characters at most.", ephemeral=True
            )
            return

        player1, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        player2, _ = await Player.objects.aget_or_create(discord_id=opponent.id)
        if wager and not player1.can_afford(wager):
            await interaction.response.send_message(
                f"You don't have enough {settings.currency_display_plural(self.bot)} to stake **{wager}**.",
                ephemeral=True,
            )
            return

        session = None
        async with self._starting:
            refusal, closing = await self._in_the_way(player1, player2, opponent.mention)
            closed = []
            for old, text in closing:
                if await sessions.acancel(old.pk, only=(BattleSessionStatus.PROPOSED,)) is not None:
                    closed.append((old, text))
                elif refusal is None:
                    # it stopped being a plan between the check and now: started, or closed from elsewhere.
                    # Whether its players are free is no longer known, so nothing is opened on a guess
                    refusal = "A battle you were part of changed just now. Try again."
            if refusal is None:
                session = await BattleSession.objects.acreate(
                    channel_id=interaction.channel_id,
                    player1=player1,
                    player2=player2,
                    wager_amount=wager,
                    status=BattleSessionStatus.PROPOSED,
                    state={
                        "deck_size": deck_size,
                        "p1_balls": [],
                        "p2_balls": [],
                        "p1_ready": False,
                        "p2_ready": False,
                    },
                )
        if session is None:
            await interaction.response.send_message(refusal, ephemeral=True)
        else:
            embed = self.proposal_embed(session, interaction.user.display_name, opponent.display_name)
            view = BattleProposalView(session.pk, interaction.user.id, opponent.id)
            self._proposals[session.pk] = view
            wager_text = f" for **{wager}** {settings.currency_display_plural(self.bot)}" if wager else ""
            await interaction.response.send_message(
                f"Hey {opponent.mention}, {interaction.user.mention} is proposing a battle{wager_text}!",
                embed=embed,
                view=view,
            )
            sent = await interaction.original_response()
            async with self._lock(session.pk):
                # read again: a deck command can have got in while the message was on its way
                session = await self._fetch(session.pk)
                if session is not None:
                    session.state["message_id"] = sent.id
                    await self._save(session)
        for old, text in closed:
            await self._strike_plan(old, text)

    async def _in_the_way(
        self, author: Player, opponent: Player, opponent_mention: str
    ) -> tuple[str | None, list[tuple[BattleSession, str]]]:
        """
        Why these two cannot open a battle right now, and the plans to close along the way.

        Two kinds of plan close by themselves. One nobody touched for half an hour: its players have left
        it. And one the author was only invited to and never took up: adding a character or pressing Ready
        is what accepts a battle, so somebody who has done neither is free to start one of their own, and
        doing so turns the invitation down. Without that, proposing a battle to somebody would lock them
        out of battles for as long as the proposal was left standing.
        """
        stale_before = timezone.now() - sessions.STALE_AFTER
        closing: list[tuple[BattleSession, str]] = []
        standing: list[BattleSession] = []
        open_sessions = BattleSession.objects.filter(
            Q(player1__in=(author, opponent)) | Q(player2__in=(author, opponent)), status__in=sessions.OPEN
        )
        async for session in open_sessions:
            proposed = session.status == BattleSessionStatus.PROPOSED
            state = session.state
            if proposed and session.updated_at < stale_before:
                closing.append((session, "This battle plan sat untouched for too long and was closed."))
            elif (
                proposed
                and session.player2_id == author.pk
                and not state.get("p2_balls")
                and not state.get("p2_ready")
            ):
                closing.append((session, "The invitation was turned down: this battle plan is closed."))
            else:
                standing.append(session)

        if any(author.pk in (session.player1_id, session.player2_id) for session in standing):
            refusal = "You're already in another battle right now."
        elif standing:
            refusal = f"{opponent_mention} is already in another battle right now."
        else:
            return None, closing
        # refused: nothing is turned down on the author's behalf, only what was abandoned goes
        return refusal, [(session, text) for session, text in closing if session.updated_at < stale_before]

    async def _strike_plan(self, session: BattleSession, text: str):
        """Show a plan that has been closed as closed, where it was posted."""
        self._forget(session.pk)
        message_id = session.state.get("message_id")
        channel = self.bot.get_channel(session.channel_id)
        if not message_id or channel is None:
            return
        embed = discord.Embed(title="Battle Plan", description=text, color=settings.embed_colour)
        try:
            message = await channel.fetch_message(message_id)  # type: ignore
            await message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass

    def proposal_embed(self, session: BattleSession, author_name: str, opponent_name: str) -> discord.Embed:
        state = session.state
        author_ready = "✅ " if state["p1_ready"] else ""
        opponent_ready = "✅ " if state["p2_ready"] else ""
        embed = discord.Embed(
            title="Battle Plan",
            description=(
                f"Add characters with `/battle add` (and `/battle remove`), up to **{state['deck_size']}** per "
                f"deck, then arm them with `/battle equip`: one weapon and one devil fruit each. "
                f"Click ✔ once ready — 🛒 opens the shop anytime."
            ),
            color=settings.embed_colour,
        )
        if session.wager_amount:
            embed.description += f"\n**Wager:** {session.wager_amount} {settings.currency_display_plural(self.bot)}"
        embed.add_field(name=f"{author_ready}{author_name}'s deck", value=deck_lines(state["p1_balls"]), inline=True)
        embed.add_field(
            name=f"{opponent_ready}{opponent_name}'s deck", value=deck_lines(state["p2_balls"]), inline=True
        )
        return embed

    async def get_active_session(self, interaction: discord.Interaction["BallsDexBot"]) -> BattleSession | None:
        """The battle `interaction.user` is currently a part of, if any — not scoped to a channel,
        since multiple battles can now run at once as long as they don't share a player."""
        return await BattleSession.objects.select_related("player1", "player2").filter(
            Q(player1__discord_id=interaction.user.id) | Q(player2__discord_id=interaction.user.id),
            status__in=sessions.OPEN,
        ).afirst()

    @asynccontextmanager
    async def _building(
        self, interaction: discord.Interaction["BallsDexBot"]
    ) -> AsyncIterator[tuple[BattleSession, str] | None]:
        """
        The battle this player is still putting a deck together for and their side of it, held for the
        time of one change.

        A deck lives in the battle's state, which is read, changed and written back whole. Both players
        fill theirs at the same time, so each change is made under the battle's lock and on a state read
        once the lock is held: otherwise the second of two changes writes back a state that never saw the
        first, and a card is lost with both players told it was added.

        Answers the interaction itself and yields None when there is nothing to change.
        """
        found = await self.get_active_session(interaction)
        if not found or found.status != BattleSessionStatus.PROPOSED:
            await interaction.response.send_message("You don't have a battle being set up right now!", ephemeral=True)
            yield None
            return
        async with self._lock(found.pk):
            session = await self._fetch(found.pk)
            if not session or session.status != BattleSessionStatus.PROPOSED:
                await interaction.response.send_message(
                    "You don't have a battle being set up right now!", ephemeral=True
                )
                yield None
                return
            side = self._side_for(session, interaction.user.id)
            if side is None:
                await interaction.response.send_message("You aren't a part of this battle!", ephemeral=True)
                yield None
                return
            if session.state[f"{side}_ready"]:
                await interaction.response.send_message(
                    "You cannot change your deck, you're already ready.", ephemeral=True
                )
                yield None
                return
            yield session, side

    @app_commands.command()
    async def add(self, interaction: discord.Interaction["BallsDexBot"], countryball: BallInstanceTransform):
        """
        Add a character to your battle deck.
        """
        async with self._building(interaction) as found:
            if found is None:
                return
            session, side = found
            state = session.state

            if reason := retired(countryball):
                await interaction.response.send_message(reason, ephemeral=True)
                return
            battle_settings = await self.get_settings()
            role = role_of(countryball.ball_id, battle_settings)
            if role != ROLE_CHARACTER:
                if role in SLOTS:
                    reason = (
                        f"A {'devil fruit' if role == 'fruit' else role} does not fight on its own. Add a "
                        "character with `/battle add`, then hand it over with `/battle equip`."
                    )
                else:
                    reason = "Only characters can fight: ships, crews and the like sit battles out for now."
                await interaction.response.send_message(reason, ephemeral=True)
                return

            balls = side_balls(state, side)
            if len(balls) >= state["deck_size"]:
                await interaction.response.send_message(
                    f"You cannot add more than {state['deck_size']} {settings.plural_collectible_name}!",
                    ephemeral=True,
                )
                return
            if any(b["instance_id"] == countryball.pk for b in balls):
                await interaction.response.send_message(
                    f"You cannot add the same {settings.collectible_name} twice!", ephemeral=True
                )
                return

            ball = await serialize_ball(countryball, interaction.user.id, self.bot, battle_settings)
            balls.append(ball.to_dict())
            await self._save(session)

            await interaction.response.send_message(
                f"Added `{countryball.description(short=True)}`!", ephemeral=True
            )
            await self._refresh_proposal_message(interaction, session)

    @app_commands.command()
    async def remove(self, interaction: discord.Interaction["BallsDexBot"], countryball: BallInstanceTransform):
        """
        Remove a character from your battle deck.
        """
        async with self._building(interaction) as found:
            if found is None:
                return
            session, side = found
            state = session.state

            balls = side_balls(state, side)
            before = len(balls)
            state[f"{side}_balls"] = [b for b in balls if b["instance_id"] != countryball.pk]
            if len(state[f"{side}_balls"]) == before:
                await interaction.response.send_message(
                    f"That {settings.collectible_name} is not in your deck!", ephemeral=True
                )
                return

            await self._save(session)
            await interaction.response.send_message(
                f"Removed `{countryball.description(short=True)}`!", ephemeral=True
            )
            await self._refresh_proposal_message(interaction, session)

    @app_commands.command()
    async def equip(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        item: BallInstanceTransform,
        character: BallInstanceTransform,
    ):
        """
        Give a weapon or a devil fruit to a character of your battle deck.

        Parameters
        ----------
        item: BallInstance
            The weapon or devil fruit to hand over.
        character: BallInstance
            The character of your deck who gets it.
        """
        async with self._building(interaction) as found:
            if found is None:
                return
            session, side = found
            state = session.state
            battle_settings = await self.get_settings()

            if reason := retired(item):
                await interaction.response.send_message(reason, ephemeral=True)
                return
            slot = role_of(item.ball_id, battle_settings)
            if slot not in SLOTS:
                await interaction.response.send_message(
                    "Only a weapon or a devil fruit can be equipped.", ephemeral=True
                )
                return
            balls = side_balls(state, side)
            bearer = next((b for b in balls if b["instance_id"] == character.pk), None)
            if bearer is None:
                await interaction.response.send_message(
                    "That character is not in your deck: add them with `/battle add` first.", ephemeral=True
                )
                return
            for other in balls:
                if any(entry["instance_id"] == item.pk for entry in other.get("equipment") or []):
                    where = "this character" if other is bearer else f"**{other['name']}**"
                    await interaction.response.send_message(
                        f"That one is already on {where}. Take it off with `/battle unequip` to move it.",
                        ephemeral=True,
                    )
                    return

            percent = await equip_percent(bearer["ball_id"], item.ball_id, battle_settings)
            entry = serialize_item(item, slot, percent, self.bot, battle_settings.health_multiplier)
            fighter = BattleBall.from_dict(bearer)
            replaced = next((old for old in fighter.equipment if old.get("slot") == slot), None)
            # one weapon and one fruit each: a second one of a kind takes the place of the first
            fighter.equipment = [old for old in fighter.equipment if old.get("slot") != slot] + [entry]
            apply_equipment(fighter, battle_settings.full_set_bonus_percent)
            state[f"{side}_balls"] = [
                fighter.to_dict() if b["instance_id"] == fighter.instance_id else b for b in balls
            ]
            await self._save(session)

            gained = (
                f"+{contribution(entry['attack'], percent)} ATK, +{contribution(entry['health'], percent)} HP "
                f"({percent}% of its stats)"
            )
            text = f"**{fighter.name}** now holds **{entry['name']}**: {gained}."
            if replaced is not None:
                text += f"\n-# {replaced['name']} was put back."
            if battle_settings.full_set_bonus_percent and has_full_set(fighter.equipment):
                text += f"\n-# Weapon and fruit together: +{battle_settings.full_set_bonus_percent}% on top."
            await interaction.response.send_message(text, ephemeral=True)
            await self._refresh_proposal_message(interaction, session)

    @app_commands.command()
    async def unequip(self, interaction: discord.Interaction["BallsDexBot"], item: BallInstanceTransform):
        """
        Take a weapon or a devil fruit back from the character holding it.

        Parameters
        ----------
        item: BallInstance
            The weapon or devil fruit to take back.
        """
        async with self._building(interaction) as found:
            if found is None:
                return
            session, side = found
            state = session.state
            balls = side_balls(state, side)
            bearer = next(
                (b for b in balls if any(entry["instance_id"] == item.pk for entry in b.get("equipment") or [])),
                None,
            )
            if bearer is None:
                await interaction.response.send_message("Nobody in your deck is holding that.", ephemeral=True)
                return

            battle_settings = await self.get_settings()
            fighter = BattleBall.from_dict(bearer)
            fighter.equipment = [entry for entry in fighter.equipment if entry["instance_id"] != item.pk]
            apply_equipment(fighter, battle_settings.full_set_bonus_percent)
            state[f"{side}_balls"] = [
                fighter.to_dict() if b["instance_id"] == fighter.instance_id else b for b in balls
            ]
            await self._save(session)
            await interaction.response.send_message(
                f"Took `{item.description(short=True)}` back from **{fighter.name}**.", ephemeral=True
            )
            await self._refresh_proposal_message(interaction, session)

    @app_commands.command()
    async def leave(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Leave your current battle: cancel it before it starts, forfeit it once it has.
        """
        session = await self.get_active_session(interaction)
        if session is None:
            await interaction.response.send_message("You aren't in a battle right now.", ephemeral=True)
            return
        # the way out that needs no button: the message of a battle can be deleted, or out of reach in a
        # channel its player cannot see
        await interaction.response.defer(ephemeral=True)
        if session.status == BattleSessionStatus.PROPOSED:
            refused = await self._cancel_plan(session.pk)
            done = "The battle has been cancelled."
        else:
            refused = await self._forfeit(session.pk, interaction.user.id)
            done = "You forfeited the battle."
        await interaction.followup.send(refused or done, ephemeral=True)

    @staticmethod
    def _side_for(session: BattleSession, discord_id: int) -> str | None:
        if discord_id == session.player1.discord_id:
            return "p1"
        if discord_id == session.player2.discord_id:
            return "p2"
        return None

    async def _refresh_proposal_message(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        session: BattleSession,
        message: discord.Message | None = None,
    ):
        message_id = session.state.get("message_id")
        if message is None and not message_id:
            return
        channel = self.bot.get_channel(session.channel_id) or interaction.channel
        if message is None and channel is None:
            return
        author_name = await player_name(self.bot, session.player1.discord_id)
        opponent_name = await player_name(self.bot, session.player2.discord_id)
        embed = self.proposal_embed(session, author_name, opponent_name)
        try:
            if message is None:
                message = await channel.fetch_message(message_id)  # type: ignore
            await message.edit(embed=embed)
        except discord.HTTPException:
            pass

    # -- Shop -----------------------------------------------------------------------------

    async def open_shop(self, interaction: discord.Interaction["BallsDexBot"]):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        items = [x async for x in BattleItem.objects.filter(enabled=True).order_by("price")]
        owned = {
            x.item_id: x.quantity
            async for x in PlayerBattleItem.objects.filter(player=player, quantity__gt=0)
        }

        if not items:
            await interaction.response.send_message("The battle shop is empty right now.", ephemeral=True)
            return

        lines = []
        for item in items:
            have = owned.get(item.pk, 0)
            lines.append(f"**{item.name}** — {item.price} {settings.currency_display_plural(self.bot)} (own: {have})")
        content = (
            f"**Battle Shop**\nBalance: {player.money} {settings.currency_display_plural(self.bot)}\n\n"
            + "\n".join(lines)
        )
        await interaction.response.send_message(content, view=BattleShopView(items), ephemeral=True)

    # -- Proposal button handlers -----------------------------------------------------------

    async def _drop_lost_cards(self, session: BattleSession, side: str, battle_settings: BattleSettings) -> list[str]:
        """
        Take out of a deck what its player no longer owns, and return the names of what went.

        A deck is a copy taken when each card was added. Between then and Ready a card can be traded,
        given away or sold, and it would otherwise still fight for the player who no longer has it.
        """
        state = session.state
        balls = side_balls(state, side)
        player = session.player1 if side == "p1" else session.player2
        wanted = {ball["instance_id"] for ball in balls}
        wanted |= {entry["instance_id"] for ball in balls for entry in ball.get("equipment") or []}
        owned = {
            pk
            async for pk in BallInstance.objects.filter(pk__in=wanted, player=player).values_list("pk", flat=True)
        }
        if owned >= wanted:
            return []

        gone: list[str] = []
        kept: list[dict] = []
        for ball in balls:
            if ball["instance_id"] not in owned:
                gone.append(ball["name"])
                continue
            worn = ball.get("equipment") or []
            lost = [entry for entry in worn if entry["instance_id"] not in owned]
            if lost:
                gone.extend(entry["name"] for entry in lost)
                fighter = BattleBall.from_dict(ball)
                fighter.equipment = [entry for entry in worn if entry["instance_id"] in owned]
                apply_equipment(fighter, battle_settings.full_set_bonus_percent)
                ball = fighter.to_dict()
            kept.append(ball)
        state[f"{side}_balls"] = kept
        return gone

    async def on_ready_click(self, interaction: discord.Interaction["BallsDexBot"], view: BattleProposalView):
        async with self._lock(view.session_id):
            session = await self._fetch(view.session_id)
            if not session or session.status != BattleSessionStatus.PROPOSED:
                await interaction.response.send_message("This battle is no longer available.", ephemeral=True)
                return

            state = session.state
            side = self._side_for(session, interaction.user.id)
            if side is None:
                await interaction.response.send_message("You aren't a part of this battle.", ephemeral=True)
                return
            if state[f"{side}_ready"]:
                await interaction.response.send_message(
                    "You're already ready: waiting for the other player.", ephemeral=True
                )
                return
            if not side_balls(state, side):
                # refused on the spot. Taken, it left this player ready with nothing to fight with and no
                # way to add anything, a ready deck being closed to changes
                await interaction.response.send_message(
                    "Add at least one character with `/battle add` before pressing Ready.", ephemeral=True
                )
                return

            battle_settings = await self.get_settings()
            gone = await self._drop_lost_cards(session, side, battle_settings)
            if gone:
                await self._save(session)
                await interaction.response.send_message(
                    f"No longer yours, so taken out of your deck: {', '.join(gone)}. "
                    "Press Ready again once your deck is set.",
                    ephemeral=True,
                )
                await self._refresh_proposal_message(interaction, session, interaction.message)
                return

            other = other_side(side)
            state[f"{side}_ready"] = True
            if not state[f"{other}_ready"]:
                await self._save(session)
                await interaction.response.send_message("Waiting for the other player to press Ready.", ephemeral=True)
                await self._refresh_proposal_message(interaction, session, interaction.message)
                return

            # the other deck was checked when its player pressed Ready, which can be a while ago
            gone = await self._drop_lost_cards(session, other, battle_settings)
            if gone:
                state[f"{other}_ready"] = False
                await self._save(session)
                await interaction.response.send_message(
                    f"The other player no longer owns {', '.join(gone)}: it was taken out of their deck, and "
                    "they have to press Ready again.",
                    ephemeral=True,
                )
                await self._refresh_proposal_message(interaction, session, interaction.message)
                return

            await interaction.response.defer()
            state.update(turn=0, active="p1", log=[])
            # the wager leaves both wallets and the plan becomes a battle in one transaction: a second
            # click landing here finds a battle already started, and charges nobody
            outcome = await sessions.astart(session.pk, state)
            if outcome == sessions.BROKE:
                for key in ("turn", "active", "log"):
                    del state[key]
                state["p1_ready"] = state["p2_ready"] = False
                await self._save(session)
                await self._refresh_proposal_message(interaction, session, interaction.message)
                await interaction.followup.send(
                    "One of you can no longer afford the wager. Battle not started.", ephemeral=True
                )
                return
            if outcome != sessions.STARTED:
                await interaction.followup.send("This battle is no longer available.", ephemeral=True)
                return

            session.status = BattleSessionStatus.ACTIVE
            self._proposals.pop(session.pk, None)
            view.stop()
            try:
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="Battle Plan",
                        description="Battle started! Scroll down for the fight.",
                        color=settings.embed_colour,
                    ),
                    view=None,
                )
            except discord.HTTPException:
                pass
            await self._show_turn(session, battle_settings, None, interaction)

    async def _cancel_plan(
        self, session_id: int, interaction: discord.Interaction["BallsDexBot"] | None = None
    ) -> str | None:
        """
        Close a battle that has not started. `interaction` is the click on its Cancel button, when that is
        where this comes from. Returns None once closed, or why it was not.
        """
        async with self._lock(session_id):
            session = await self._fetch(session_id)
            if session is None or await sessions.acancel(session_id, only=(BattleSessionStatus.PROPOSED,)) is None:
                return "This battle is no longer available."
            self._forget(session_id)
            embed = discord.Embed(
                title="Battle Plan", description="The battle has been cancelled.", color=settings.embed_colour
            )
            if interaction is None:
                await self._strike_plan(session, embed.description)
                return None
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.HTTPException:
                pass
            return None

    async def on_cancel_click(self, interaction: discord.Interaction["BallsDexBot"], view: BattleProposalView):
        refused = await self._cancel_plan(view.session_id, interaction)
        if refused is not None:
            await interaction.response.send_message(refused, ephemeral=True)
            return
        view.stop()

    # -- Active battle --------------------------------------------------------------------

    def build_turn_view(self, session: BattleSession, battle_settings: BattleSettings) -> BattleTurnView:
        state = session.state
        active = state["active"]
        active_id = session.player1.discord_id if active == "p1" else session.player2.discord_id
        other_id = session.player2.discord_id if active == "p1" else session.player1.discord_id
        ball = current_ball(state, active)
        label = (ball["capacity_name"] if ball else "") or "Capacity"
        view = BattleTurnView(session.pk, state.get("turn", 0), active_id, other_id, label)
        if ball:
            # greyed out once used up, rather than left there to be wasted. A click that still gets
            # through (it was on its way) falls back on a plain attack, as the engine says it does
            view.heal.disabled = ball.get("heal_uses", 0) >= battle_settings.heal_uses_per_battle
            view.capacity.disabled = ball.get("capacity_uses", 0) >= battle_settings.capacity_uses_per_battle
        return view

    def battle_embed(self, session: BattleSession, p1_name: str, p2_name: str) -> discord.Embed:
        state = session.state
        active_name = p1_name if state["active"] == "p1" else p2_name
        log_text = "\n".join(state.get("log", []))
        embed = discord.Embed(
            title="Battle in progress",
            description=f"**{active_name}**'s turn — Turn {state.get('turn', 0)}\n\n{log_text}",
            color=settings.embed_colour,
        )
        embed.add_field(name=f"{p1_name}'s deck", value=deck_lines(state["p1_balls"]), inline=True)
        embed.add_field(name=f"{p2_name}'s deck", value=deck_lines(state["p2_balls"]), inline=True)
        return embed

    async def _board(self, session: BattleSession) -> discord.Message | None:
        """
        The message a battle is being played on: the one kept in memory, or failing that (after a reload
        of the package) the one its state remembers.
        """
        live = self._turns.get(session.pk)
        if live is not None:
            return live.message
        board_id = session.state.get("board_id")
        channel = self.bot.get_channel(session.channel_id)
        if not board_id or channel is None:
            return None
        try:
            return await channel.fetch_message(board_id)  # type: ignore
        except discord.HTTPException:
            return None

    async def _send_new(
        self, session: BattleSession, interaction: discord.Interaction["BallsDexBot"] | None, **content
    ) -> discord.Message | None:
        """Post a new message for a battle whose own message is gone. None when there is nowhere to post."""
        if interaction is not None:
            try:
                return await interaction.followup.send(wait=True, **content)
            except discord.HTTPException:
                pass
        channel = self.bot.get_channel(session.channel_id)
        if channel is None:
            return None
        try:
            return await channel.send(**content)  # type: ignore
        except discord.HTTPException:
            log.warning("Battle #%s has nowhere left to be shown", session.pk, exc_info=True)
            return None

    async def _show_turn(
        self,
        session: BattleSession,
        battle_settings: BattleSettings,
        board: discord.Message | None,
        interaction: discord.Interaction["BallsDexBot"] | None,
    ) -> bool:
        """
        Put the turn to play in front of the players: the board, its buttons and its clock.

        The board is edited in place. When it is gone (a moderator, a purge) the battle moves to a new
        message rather than staying where nobody can reach it; and when even that cannot be posted, the
        battle is called off and the wager given back. False in that last case.
        """
        p1_name = await player_name(self.bot, session.player1.discord_id)
        p2_name = await player_name(self.bot, session.player2.discord_id)
        embed = self.battle_embed(session, p1_name, p2_name)
        view = self.build_turn_view(session, battle_settings)
        previous = self._turns.pop(session.pk, None)
        if previous is not None:
            previous.view.stop()

        message = None
        if board is not None:
            try:
                message = await board.edit(embed=embed, view=view)
            except discord.HTTPException:
                message = None
        if message is None:
            message = await self._send_new(session, interaction, embed=embed, view=view)
        if message is None:
            view.stop()
            await sessions.acancel(session.pk)
            self._forget(session.pk)
            return False

        channel = self.bot.get_channel(session.channel_id)
        if isinstance(message, discord.WebhookMessage) and channel is not None:
            # a board posted as the follow-up of a click is edited with that click's token, which dies
            # after fifteen minutes. A battle left to its clock lasts longer than that: from here on
            # the board is reached as a plain message of its channel
            message = channel.get_partial_message(message.id)  # type: ignore
        self._turns[session.pk] = LiveTurn(view, message)
        if session.state.get("board_id") != message.id:
            session.state["board_id"] = message.id
            await self._save(session)
        self._arm_timer(session.pk, session.state.get("turn", 0), battle_settings.turn_timeout_seconds)
        return True

    def _arm_timer(self, session_id: int, turn: int, seconds: int):
        """
        Start the clock of a turn: when it runs out, the turn is played as a plain attack.

        One clock per battle, started over at every turn and by nothing else. A clock still running for a
        turn that has been played does no harm, the turn number it carries no longer being the one to play.
        """
        previous = self._timers.pop(session_id, None)
        if previous is not None and previous is not asyncio.current_task():
            previous.cancel()
        self._timers[session_id] = asyncio.create_task(self._run_out(session_id, turn, max(1, seconds)))

    async def _run_out(self, session_id: int, turn: int, seconds: int):
        await asyncio.sleep(seconds)
        try:
            await self._play(session_id, turn, None, BattleAction.ATTACK)
        except Exception:
            log.exception("The turn clock of battle #%s failed", session_id)

    async def _retire_board(self, interaction: discord.Interaction["BallsDexBot"], view: BattleTurnView):
        """Take the buttons off the board of a battle that is over, so nobody presses them again."""
        view.stop()
        try:
            await interaction.edit_original_response(view=None)
        except discord.HTTPException:
            pass

    async def on_turn_action(
        self, interaction: discord.Interaction["BallsDexBot"], view: BattleTurnView, action: BattleAction
    ):
        # acknowledged before anything else: the click may have to wait its turn behind another one
        await interaction.response.defer()
        refused = await self._play(
            view.session_id,
            view.turn,
            interaction.user.id,
            action,
            board=interaction.message,
            interaction=interaction,
        )
        if refused is None:
            # these buttons have done their job. The cog stops the ones it posted itself; the ones
            # posted before a reload of the package are only known through the click they just got
            view.stop()
            return
        await interaction.followup.send(refused, ephemeral=True)
        if refused == BATTLE_OVER:
            await self._retire_board(interaction, view)

    async def on_item_click(self, interaction: discord.Interaction["BallsDexBot"], view: BattleTurnView):
        if interaction.user.id != view.active_user_id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        owned = [
            x
            async for x in PlayerBattleItem.objects.filter(player=player, quantity__gt=0).select_related("item")
        ]
        if not owned:
            await interaction.response.send_message("You don't have any battle items.", ephemeral=True)
            return

        usable = [x for x in owned if x.item.effect_type in ITEM_ACTION_FOR_EFFECT]
        if not usable:
            await interaction.response.send_message("None of your items can be used right now.", ephemeral=True)
            return

        names = {x.item_id: x.item.name for x in usable}
        options = [discord.SelectOption(label=f"{x.item.name} (x{x.quantity})", value=str(x.item_id)) for x in usable]
        select = discord.ui.Select(placeholder="Use an item...", options=options)

        async def use_item(select_interaction: discord.Interaction["BallsDexBot"]):
            item_id = int(select.values[0])
            await select_interaction.response.defer()
            # the menu stays open for a minute, and the turn it was opened in can be long gone by the time
            # something is picked: it is played as that turn or not at all, and the item is only used up
            # once it is certain to be played
            refused = await self._play(
                view.session_id,
                view.turn,
                select_interaction.user.id,
                None,
                item_id=item_id,
                board=interaction.message,
                interaction=interaction,
            )
            if refused is None:
                view.stop()
            try:
                await select_interaction.edit_original_response(
                    content=refused or f"Used **{names.get(item_id, 'the item')}**.", view=None
                )
            except discord.HTTPException:
                pass

        select.callback = use_item
        item_view = View(timeout=60)
        item_view.add_item(select)
        await interaction.response.send_message(view=item_view, ephemeral=True)

    async def on_forfeit_click(self, interaction: discord.Interaction["BallsDexBot"], view: BattleTurnView):
        await interaction.response.defer()
        refused = await self._forfeit(
            view.session_id, interaction.user.id, board=interaction.message, interaction=interaction
        )
        if refused is None:
            # these buttons have done their job. The cog stops the ones it posted itself; the ones
            # posted before a reload of the package are only known through the click they just got
            view.stop()
            return
        await interaction.followup.send(refused, ephemeral=True)
        if refused == BATTLE_OVER:
            await self._retire_board(interaction, view)

    async def _forfeit(
        self,
        session_id: int,
        user_id: int,
        *,
        board: discord.Message | None = None,
        interaction: discord.Interaction["BallsDexBot"] | None = None,
    ) -> str | None:
        """
        Give a battle up, whoever's turn it is: the other player wins. Returns None once done, or why not.

        Not tied to the turn on purpose. A player kept waiting by an opponent who has walked away, or who
        is playing the clock, has to have a way out that does not depend on that opponent.
        """
        async with self._lock(session_id):
            session = await self._fetch(session_id)
            if session is None or session.status != BattleSessionStatus.ACTIVE:
                return BATTLE_OVER
            side = self._side_for(session, user_id)
            if side is None:
                return "You aren't a part of this battle."
            await self._finish(session, other_side(side), forfeited=True, board=board, interaction=interaction)
            return None

    async def _play(
        self,
        session_id: int,
        turn: int,
        actor_id: int | None,
        action: BattleAction | None,
        *,
        item_id: int | None = None,
        board: discord.Message | None = None,
        interaction: discord.Interaction["BallsDexBot"] | None = None,
    ) -> str | None:
        """
        Play one turn of a battle, once.

        `turn` is the turn the caller believes it is playing and `actor_id` who is asking, None for the
        clock. With `item_id`, the action is the one that item goes with. Returns None when the turn was
        played, and otherwise what to tell whoever asked, nothing having changed.

        Everything that can ask for a turn comes through here: a button, an item menu, the clock, each of
        them possibly late, twice, or from the wrong player. So the battle is read once its lock is held,
        and the turn is only played if it is still running, still at that turn, and asked for by the
        player whose turn it is.
        """
        async with self._lock(session_id):
            session = await self._fetch(session_id)
            if session is None or session.status != BattleSessionStatus.ACTIVE:
                return BATTLE_OVER
            state = session.state
            if state.get("turn", 0) != turn:
                return "That turn has already been played."
            active = state["active"]
            defending = other_side(active)
            player = session.player1 if active == "p1" else session.player2
            if actor_id is not None and actor_id != player.discord_id:
                return "It's not your turn."
            attacker_ball = current_ball(state, active)
            defender_ball = current_ball(state, defending)
            if attacker_ball is None or defender_ball is None:
                return BATTLE_OVER

            attacker = BattleBall.from_dict(attacker_ball)
            defender = BattleBall.from_dict(defender_ball)
            battle_settings = await self.get_settings()

            item_effect = None
            if item_id is not None:
                item = await BattleItem.objects.filter(pk=item_id).afirst()
                action = ITEM_ACTION_FOR_EFFECT.get(item.effect_type) if item else None
                if item is None or action is None:
                    return "That item cannot be used in a battle."
                if action is BattleAction.HEAL and attacker.heal_uses >= battle_settings.heal_uses_per_battle:
                    return f"**{attacker.name}** has no heals left this battle: **{item.name}** would be wasted."
                if not await sessions.aspend_item(player.pk, item.pk):
                    return f"You have no **{item.name}** left."
                item_effect = (item.effect_type, item.effect_value)
            if action is None:
                return "That turn could not be played."

            matchup = await get_matchup_multiplier(attacker.ball_id, defender.ball_id)
            # who the fighters are, then what they wear: the two multiply into the one figure the engine takes
            worn = await get_equipment_multiplier(attacker, defender, battle_settings)
            result = resolve_action(
                action, attacker, defender, battle_settings, matchup * worn, item_effect, lore=matchup > 1.0
            )
            if result.damage and worn != 1.0:
                hint = "🛡️ Resisted" if worn < 1.0 else "💢 Weak point"
                result = result._replace(
                    text=f"{result.text}\n-# {hint}: what they wear changed this hit (x{worn:g})."
                )

            # write mutated dataclasses back into the raw dict lists
            state[f"{active}_balls"] = [
                attacker.to_dict() if b["instance_id"] == attacker.instance_id else b
                for b in side_balls(state, active)
            ]
            state[f"{defending}_balls"] = [
                defender.to_dict() if b["instance_id"] == defender.instance_id else b
                for b in side_balls(state, defending)
            ]
            state["turn"] = turn + 1
            log_lines = state.setdefault("log", [])
            log_lines.append(f"Turn {state['turn']}: {result.text}")
            state["log"] = log_lines[-MAX_LOG_LINES:]

            winner_side = None
            if all(b["dead"] for b in side_balls(state, defending)):
                winner_side = active
            elif all(b["dead"] for b in side_balls(state, active)):
                winner_side = defending

            board = board or await self._board(session)
            if winner_side:
                await self._finish(session, winner_side, forfeited=False, board=board, interaction=interaction)
                return None

            state["active"] = defending
            if not await sessions.aadvance(session.pk, turn, state):
                return "That turn has already been played."
            await self._show_turn(session, battle_settings, board, interaction)
            return None

    async def _finish(
        self,
        session: BattleSession,
        winner_side: str,
        *,
        forfeited: bool,
        board: discord.Message | None = None,
        interaction: discord.Interaction["BallsDexBot"] | None = None,
    ) -> bool:
        """
        End a battle and pay its winner. False when it had already been ended, nothing then being paid.
        Called with the battle's lock held.
        """
        state = session.state
        loser_side = other_side(winner_side)
        winner_player = session.player1 if winner_side == "p1" else session.player2
        loser_player = session.player2 if winner_side == "p1" else session.player1

        earnings = await self._compute_earnings(
            winner_player, loser_player, side_balls(state, winner_side), side_balls(state, loser_side)
        )
        # the status, the pot, the reward and the record in one transaction, and only if the battle was
        # still running: the second of two final blows finds it finished and stops here
        if not await sessions.aclose(session.pk, state, winner_player.pk, earnings):
            return False
        session.status = BattleSessionStatus.FINISHED
        board = board or await self._board(session)
        self._forget(session.pk)

        p1_name = await player_name(self.bot, session.player1.discord_id)
        p2_name = await player_name(self.bot, session.player2.discord_id)
        winner_name = p1_name if winner_side == "p1" else p2_name

        embed = discord.Embed(title="Battle: Complete!", color=settings.embed_colour)
        forfeit_suffix = " (forfeit)" if forfeited else ""
        summary = f"**Winner: {winner_name}**{forfeit_suffix}\nTurns: {state.get('turn', 0)}"
        if session.wager_amount:
            summary += f"\nWager won: {session.wager_amount * 2} {settings.currency_display_plural(self.bot)}"
        if earnings:
            summary += f"\nBattle reward: {earnings} {settings.currency_display_plural(self.bot)}"
        embed.description = summary
        embed.add_field(name=f"{p1_name}'s final deck", value=deck_lines(state["p1_balls"]), inline=True)
        embed.add_field(name=f"{p2_name}'s final deck", value=deck_lines(state["p2_balls"]), inline=True)

        shown = False
        if board is not None:
            try:
                await board.edit(embed=embed, view=None)
                shown = True
            except discord.HTTPException:
                pass
        if not shown:
            # the board is gone: the result is still owed to the two players
            await self._send_new(session, interaction, embed=embed)

        channel_id = session.channel_id
        # how much of their own deck each side lost, so a quest can ask for a win without a casualty.
        # A forfeit is not a flawless win: the fight never reached its end, so it is counted as one loss.
        # That holds for both players and for both events: a quest asking for battles played without a
        # loss would otherwise be filled by starting battles and giving them up at once.
        lost = {
            side: sum(1 for ball in side_balls(state, side) if ball["dead"]) or (1 if forfeited else 0)
            for side in (winner_side, loser_side)
        }
        await bus.dispatch(
            winner_player,
            Event.BATTLE_WIN,
            context=EventContext(lost_count=lost[winner_side]),
            channel_id=channel_id,
        )
        # both sides get a participation event: a war scored on taking part should not only ever
        # reward the player who won
        for participant, side in ((winner_player, winner_side), (loser_player, loser_side)):
            await bus.dispatch(
                participant,
                Event.BATTLE_PLAYED,
                context=EventContext(lost_count=lost[side]),
                channel_id=channel_id,
            )
        return True

    async def _compute_earnings(
        self, winner: Player, loser: Player, winner_balls: list[dict], loser_balls: list[dict]
    ) -> int:
        battle_settings = await self.get_settings()
        since = timezone.now() - timedelta(hours=24)
        wins_today = await BattleRecord.objects.filter(winner=winner, created_at__gte=since).acount()
        same_opponent_wins = await BattleRecord.objects.filter(
            winner=winner, created_at__gte=since
        ).filter(Q(player1=loser) | Q(player2=loser)).acount()

        if same_opponent_wins >= battle_settings.max_rewarded_wins_per_opponent_per_day:
            return 0

        if wins_today < battle_settings.guaranteed_daily_wins:
            return battle_settings.guaranteed_win_reward

        winner_power = max(1, total_power(winner_balls))
        loser_power = total_power(loser_balls)
        scale = min(
            battle_settings.performance_scale_max,
            max(battle_settings.performance_scale_min, loser_power / winner_power),
        )
        return round(battle_settings.performance_base_reward * scale)

    # -- Leaderboard ------------------------------------------------------------------------

    @app_commands.command()
    async def leaderboard(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Show the top 10 players by battle wins, with their win-loss record.
        """
        await interaction.response.defer(thinking=True)

        wins_by_player: dict[int, int] = {}
        losses_by_player: dict[int, int] = {}
        async for record in BattleRecord.objects.all().only("player1_id", "player2_id", "winner_id"):
            # a battle whose winner has since left the dex has nobody to credit, and so nobody to charge
            # with the loss either: the record of the player still around is left as it was
            if not record.winner_id:
                continue
            loser_id = record.player2_id if record.winner_id == record.player1_id else record.player1_id
            wins_by_player[record.winner_id] = wins_by_player.get(record.winner_id, 0) + 1
            losses_by_player[loser_id] = losses_by_player.get(loser_id, 0) + 1

        if not wins_by_player:
            await interaction.followup.send("No battles have been recorded yet.", ephemeral=True)
            return

        # most wins first, and between two players on the same number of wins, the one who lost less
        top = sorted(wins_by_player.items(), key=lambda x: (-x[1], losses_by_player.get(x[0], 0)))[:10]
        players = {p.pk: p async for p in Player.objects.filter(id__in=[pk for pk, _ in top])}

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        entries = []
        for rank, (player_id, wins) in enumerate(top, start=1):
            player = players.get(player_id)
            if not player:
                continue
            losses = losses_by_player.get(player_id, 0)
            win_rate = round(wins / (wins + losses) * 100, 1)
            try:
                user = await self.bot.fetch_user(player.discord_id)
            except (discord.NotFound, discord.HTTPException):
                continue
            entries.append(
                Section(
                    TextDisplay(
                        f"### {medals.get(rank, rank)}\n"
                        f"> {user.display_name}\n> **{wins}W - {losses}L** • Win rate: {win_rate}%"
                    ),
                    accessory=Thumbnail(media=user.display_avatar.url),
                )
            )

        view = LayoutView()
        view.restrict_author(interaction.user.id)
        container = Container(TextDisplay(f"# {settings.bot_name} Battle Leaderboard"), Separator())
        # 1 is the separator: the formatter clears whatever comes after that position before writing a
        # page, so a higher number leaves the first entry of the previous page on every page
        view.add_item(container)
        menu = Menu(interaction.client, view, ChunkedListSource(entries, 3), ItemFormatter(container, 1))
        await menu.init()
        await interaction.followup.send(view=view, allowed_mentions=discord.AllowedMentions(users=False))
