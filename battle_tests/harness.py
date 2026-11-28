"""
Scaffolding shared by the battle tests that drive the real cog without Discord.

What is real here: Django and its async ORM on the scratch database, the caches the bot fills at startup, the
`Battle` cog, its views, its turn clocks, discord.py's own view machinery (dispatch of a click, interaction
checks), the engine and the loadout rules. What is fake: the gateway and the HTTP side of Discord, replaced by
objects that record what the cog sends them and that refuse what Discord would refuse (answering an
interaction twice, a follow-up before any answer, editing a deleted message, a click on a disabled button).

Every test file takes a block of 1000 Discord ids of its own, far above any real snowflake, and wipes it
before and after, so the files can be replayed in any order.
"""

import asyncio
import itertools
import logging
import random as real_random
import sys
import traceback
import warnings
from collections import defaultdict
from types import SimpleNamespace

warnings.filterwarnings("ignore", category=RuntimeWarning)

import django  # noqa: E402

django.setup()

import discord  # noqa: E402
from asgiref.sync import sync_to_async  # noqa: E402
from battle_app import battle_ext, models  # noqa: E402
from battle_app.battle_ext import cog, engine, loadout, sessions  # noqa: E402
from currency_app.models import BerryTransaction  # noqa: E402
from discord.ext import commands  # noqa: E402
from discord.utils import MISSING  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.models import Q  # noqa: E402
from django.utils import timezone  # noqa: E402

from ballsdex.core.game_events import bus  # noqa: E402
from ballsdex.core.utils.transformers import BallInstanceTransformer  # noqa: E402
from bd_models import models as bd  # noqa: E402
from bd_models.models import Ball, BallGroup, BallInstance, Player, Special  # noqa: E402

# the names the test files use
bm = models
battle_cog = cog
__all__ = (
    "BALL",
    "BUFF_MARK",
    "GROUP",
    "ITEM_PREFIX",
    "SPECIAL",
    "BallInstance",
    "Fight",
    "Player",
    "Report",
    "World",
    "awipe_marked_rows",
    "battle_cog",
    "battle_ext",
    "bd",
    "bm",
    "commands",
    "engine",
    "loadout",
    "run",
    "sessions",
    "sync_to_async",
    "timezone",
)

logging.getLogger("discord.ui.view").setLevel(logging.CRITICAL)
logging.getLogger("ballsdex").setLevel(logging.CRITICAL)

# Real snowflakes of November 2026 are around 1.5e18; nothing real can sit at 9e18 before the 2080s.
ID_ROOT = 9_000_000_000_000_000_000
GUILD_ID = ID_ROOT + 999_999

# every Buff row written by the tests carries this fraction in its capacity_value, so a leftover of an
# interrupted run can be told from a row somebody entered for real
BUFF_MARK = 0.0625
ITEM_PREFIX = "ZZTEST "
# the advisory lock every test file takes on the scratch database for as long as it runs
SUITE_LOCK = 20261128


# -- what the bot does at startup -------------------------------------------------------------------------


def load_caches():
    """The part of `BallsDexBot.load_cache` the battle code depends on, done the same way."""
    bd.balls.clear()
    for ball in Ball.objects.all():
        bd.balls[ball.pk] = ball
    bd.regimes.clear()
    for regime in bd.Regime.objects.all():
        bd.regimes[regime.pk] = regime
    bd.economies.clear()
    for economy in bd.Economy.objects.all():
        bd.economies[economy.pk] = economy
    bd.specials.clear()
    for special in Special.objects.all():
        bd.specials[special.pk] = special
    group_ball_ids = defaultdict(set)
    for group_id, ball_id in BallGroup.objects.values_list("id", "countryballs__id"):
        if ball_id is not None:
            group_ball_ids[group_id].add(ball_id)
    bd.groups.clear()
    for group in BallGroup.objects.all():
        group._ball_ids = frozenset(group_ball_ids[group.pk])
        bd.groups[group.pk] = group


load_caches()
BALL = {ball.country: ball.pk for ball in bd.balls.values()}
GROUP = {group.name: pk for pk, group in bd.groups.items()}
SPECIAL = {special.name: pk for pk, special in bd.specials.items()}


# -- results ----------------------------------------------------------------------------------------------


class Report:
    """PASS / FAIL lines and one machine-readable summary line at the end, read by run_all.sh."""

    def __init__(self, name: str):
        self.name = name
        self.results: list[tuple[bool, str, str | None]] = []
        print(f"##### {name}")

    def section(self, title: str):
        print(f"=== {title} ===")

    def check(self, label: str, got, want=True, bug: str | None = None):
        """`bug` names the bug this test was written for: it tags the line should the bug come back."""
        ok = got == want
        tag = f"  [{bug}]" if bug and not ok else ""
        detail = "" if ok else f"  (wanted {want!r})"
        print(f"  {'PASS' if ok else 'FAIL'}  {label}: {got!r}{detail}{tag}")
        self.results.append((ok, label, bug))
        return ok

    def ok(self, label: str, condition, detail="", bug: str | None = None):
        ok = bool(condition)
        tag = f"  [{bug}]" if bug and not ok else ""
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f": {detail}" if detail != "" else "") + tag)
        self.results.append((ok, label, bug))
        return ok

    def note(self, text: str):
        print(f"  ....  {text}")

    async def scenario(self, title: str, function, *args):
        """Run one scenario; an exception escaping it is a failed test, not the end of the file."""
        self.section(title)
        try:
            await function(*args)
        except Exception as error:
            tail = "".join(traceback.format_exception(error)[-4:]).strip().replace("\n", "\n        ")
            print(f"  FAIL  {title}: the scenario raised {type(error).__name__}: {error}\n        {tail}")
            self.results.append((False, f"{title} (exception)", None))

    def finish(self):
        total = len(self.results)
        passed = sum(1 for ok, _, _ in self.results if ok)
        bugs = sorted({bug for ok, _, bug in self.results if not ok and bug})
        unexplained = sum(1 for ok, _, bug in self.results if not ok and not bug)
        print(
            f"SUMMARY {self.name} total={total} passed={passed} failed={total - passed} "
            f"unexplained={unexplained} bugs={','.join(bugs) or '-'}"
        )
        sys.stdout.flush()


# -- randomness under control -----------------------------------------------------------------------------


class ScriptedRandom:
    """
    Stands in for the `random` module inside engine.py, so a turn has one outcome.

    `random()` hands out the queued rolls first, then `roll`: at 0.99 nothing is dodged and a Crit Gamble
    misses. `uniform(a, b)` returns the point `spread` of the way from a to b: 1.0 is the top of the range.
    """

    def __init__(self, roll: float = 0.99, spread: float = 1.0):
        self.roll = roll
        self.spread = spread
        self.rolls: list[float] = []

    def queue(self, *rolls: float):
        self.rolls.extend(rolls)

    def random(self) -> float:
        return self.rolls.pop(0) if self.rolls else self.roll

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.spread


def script_random(roll: float = 0.99, spread: float = 1.0) -> ScriptedRandom:
    scripted = ScriptedRandom(roll, spread)
    engine.random = scripted
    return scripted


def real_randomness(seed=None):
    engine.random = real_random
    if seed is not None:
        real_random.seed(seed)


# -- fake Discord -----------------------------------------------------------------------------------------


class HarnessProtocolError(Exception):
    """The cog did something Discord would have refused, in a way discord.py has no exception for."""


class _Response:
    def __init__(self, status: int, reason: str):
        self.status = status
        self.reason = reason


def not_found() -> discord.NotFound:
    return discord.NotFound(_Response(404, "Not Found"), {"code": 10008, "message": "Unknown Message"})


def forbidden() -> discord.Forbidden:
    return discord.Forbidden(_Response(403, "Forbidden"), {"code": 50001, "message": "Missing Access"})


def unauthorized() -> discord.HTTPException:
    error = {"code": 50027, "message": "Invalid Webhook Token"}
    return discord.HTTPException(_Response(401, "Unauthorized"), error)


class FakeUser:
    def __init__(self, id: int, name: str, bot: bool = False):
        self.id = id
        self.name = name
        self.display_name = name
        self.bot = bot
        self.mention = f"<@{id}>"
        self.display_avatar = SimpleNamespace(url="https://cdn.discordapp.com/embed/avatars/0.png")

    def __repr__(self):
        return f"<FakeUser {self.name}>"


class FakeStore:
    """The part of discord.py's ViewStore a view talks to: who is listening, and since when."""

    def __init__(self, world: "World"):
        self.world = world
        self.live: set = set()

    def add(self, view, message: "FakeMessage"):
        if view in self.live or view.is_finished():
            return
        self.world.instrument(view)
        view._harness_message = message
        view._start_listening_from_store(self)
        self.live.add(view)

    def remove_view(self, view):
        self.live.discard(view)


class FakeMessage:
    _ids = itertools.count(ID_ROOT + 500_000_000)

    def __init__(self, world: "World", channel: "FakeChannel", content=None, embed=None, view=None, ephemeral=False):
        self.world = world
        self.id = next(FakeMessage._ids)
        self.channel = channel
        self.content = content
        self.embeds = [embed] if embed is not None else []
        self.view = view
        self.ephemeral = ephemeral
        self.deleted = False
        self.edits: list[dict] = []
        if not ephemeral:
            channel.messages[self.id] = self
        if view is not None:
            world.store.add(view, self)

    @property
    def embed(self):
        return self.embeds[0] if self.embeds else None

    async def edit(self, *, content=MISSING, embed=MISSING, view=MISSING, **kwargs):
        await self.world.lag()
        if self.deleted:
            raise not_found()
        self.edits.append({"content": content, "embed": embed, "view": view})
        if content is not MISSING:
            self.content = content
        if embed is not MISSING:
            self.embeds = [embed] if embed is not None else []
        if view is not MISSING:
            self.view = view
            if view is not None:
                self.world.store.add(view, self)
        return self

    def text(self) -> str:
        """Everything a player reads in this message, flattened."""
        parts = [self.content or ""]
        for embed in self.embeds:
            parts += [embed.title or "", embed.description or ""]
            parts += [f"{field.name}\n{field.value}" for field in embed.fields]
        if isinstance(self.view, discord.ui.LayoutView):
            parts += [item.content for item in self.view.walk_children() if isinstance(item, discord.ui.TextDisplay)]
        return "\n".join(part for part in parts if part)


class FakeWebhookMessage(FakeMessage, discord.WebhookMessage):
    """
    A message posted as the follow-up of an interaction. discord.py edits such a message with the token of
    that interaction, which Discord forgets after fifteen minutes: `World.expire_tokens` is those minutes.
    """

    generation = 0

    async def edit(self, **kwargs):
        if self.generation < self.world.token_generation:
            raise unauthorized()
        return await FakeMessage.edit(self, **kwargs)


class ChannelRoute:
    """
    A message reached through its channel, as `channel.get_partial_message` hands it: the same message,
    edited with the bot's own rights, whatever became of the interaction that posted it.
    """

    def __init__(self, message: FakeMessage):
        object.__setattr__(self, "_message", message)

    def __getattr__(self, name):
        return getattr(self._message, name)

    def __setattr__(self, name, value):
        setattr(self._message, name, value)

    async def edit(self, **kwargs):
        await FakeMessage.edit(self._message, **kwargs)
        return self


class FakeChannel:
    def __init__(self, world: "World", id: int):
        self.world = world
        self.id = id
        self.messages: dict[int, FakeMessage] = {}
        # True makes every new message fail, as in a channel the bot has lost its rights in
        self.broken = False

    async def fetch_message(self, message_id: int) -> FakeMessage:
        message = self.messages.get(message_id)
        if message is None or message.deleted:
            raise not_found()
        return message

    def get_partial_message(self, message_id: int) -> ChannelRoute:
        return ChannelRoute(self.messages[message_id])

    async def send(self, content=None, *, embed=None, view=None, **kwargs) -> FakeMessage:
        await self.world.lag()
        if self.broken:
            raise forbidden()
        return FakeMessage(self.world, self, content, embed, view)


class FakeResponse:
    def __init__(self, interaction: "FakeInteraction"):
        self.interaction = interaction
        self.kind: str | None = None

    def is_done(self) -> bool:
        return self.kind is not None

    def _answer(self, kind: str):
        if self.kind is not None:
            raise discord.InteractionResponded(self.interaction)
        self.kind = kind

    async def send_message(self, content=None, *, embed=MISSING, view=MISSING, ephemeral=False, **kwargs):
        self._answer("message")
        interaction = self.interaction
        await interaction.world.lag()
        message = FakeMessage(
            interaction.world,
            interaction.channel,
            content,
            None if embed is MISSING else embed,
            None if view is MISSING else view,
            ephemeral,
        )
        interaction.original = message
        interaction.sent.append(message)

    async def defer(self, *, ephemeral=False, thinking=False):
        self._answer("defer_thinking" if thinking or ephemeral else "defer")
        await self.interaction.world.lag()

    async def edit_message(self, *, content=MISSING, embed=MISSING, view=MISSING, **kwargs):
        self._answer("edit")
        if self.interaction.message is None:
            raise HarnessProtocolError("edit_message on an interaction that has no message")
        await self.interaction.message.edit(content=content, embed=embed, view=view)

    async def send_modal(self, modal):
        self._answer("modal")
        self.interaction.modal = modal


class FakeFollowup:
    def __init__(self, interaction: "FakeInteraction"):
        self.interaction = interaction

    async def send(self, content=None, *, embed=MISSING, view=MISSING, ephemeral=False, wait=False, **kwargs):
        interaction = self.interaction
        if not interaction.response.is_done():
            raise HarnessProtocolError("follow-up sent before the interaction was answered")
        if interaction.expired:
            raise unauthorized()
        await interaction.world.lag()
        message = FakeWebhookMessage(
            interaction.world,
            interaction.channel,
            content,
            None if embed is MISSING else embed,
            None if view is MISSING else view,
            ephemeral,
        )
        message.generation = interaction.generation
        interaction.sent.append(message)
        return message


class FakeInteraction:
    def __init__(self, world: "World", user: FakeUser, message: FakeMessage | None = None, data: dict | None = None):
        self.world = world
        self.client = world.bot
        self.user = user
        self.channel = world.channel
        self.channel_id = world.channel.id
        self.guild_id = GUILD_ID
        self.guild = None
        self.message = message
        self.data = data or {}
        self.extras: dict = {}
        self.namespace = SimpleNamespace()
        self.command = None
        self.type = discord.InteractionType.component if message else discord.InteractionType.application_command
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)
        self.original: FakeMessage | None = None
        self.sent: list[FakeMessage] = []
        self.error: Exception | None = None
        # True when the click reached nothing: its view no longer listens, or its button is greyed out
        self.dead = False
        self.modal = None
        self.generation = world.token_generation

    @property
    def expired(self) -> bool:
        """Whether the fifteen minutes Discord keeps an interaction's token for have gone by."""
        return self.generation < self.world.token_generation

    def is_expired(self) -> bool:
        return self.expired

    async def original_response(self) -> FakeMessage:
        if self.original is None:
            raise not_found()
        return self.original

    async def edit_original_response(self, *, content=MISSING, embed=MISSING, view=MISSING, **kwargs):
        if not self.response.is_done():
            raise HarnessProtocolError("edit_original_response before the interaction was answered")
        if self.expired:
            raise unauthorized()
        # a component interaction deferred as an update edits the message the component sits on
        target = self.message if self.message is not None and self.response.kind in ("defer", "edit") else None
        target = target or self.original
        if target is None:
            raise not_found()
        return await target.edit(content=content, embed=embed, view=view)

    # -- what a test reads back --

    @property
    def answered(self) -> bool:
        """False is what Discord shows as "This interaction failed"."""
        return self.response.is_done()

    def texts(self) -> list[str]:
        return [message.text() for message in self.sent]

    def said(self, needle: str) -> bool:
        return any(needle in text for text in self.texts())

    @property
    def first(self) -> str:
        """The first thing this interaction was told, by answer or by follow-up."""
        return self.sent[0].text() if self.sent else ""


class FakeBot:
    def __init__(self, world: "World"):
        self.world = world
        self.users: dict[int, FakeUser] = {}
        self.cogs: dict[str, object] = {}
        self.unknown_users: set[int] = set()
        # False is the bot at startup, before it has connected; True is a reload of the package
        self.ready = True

    def is_ready(self) -> bool:
        return self.ready

    async def add_cog(self, new_cog):
        self.cogs[new_cog.__cog_name__] = new_cog

    def get_emoji(self, id):
        return None

    def get_user(self, id: int):
        return None if id in self.unknown_users else self.users.get(id)

    async def fetch_user(self, id: int):
        user = self.get_user(id)
        if user is None:
            raise not_found()
        return user

    def get_channel(self, id: int):
        return self.world.channel if id == self.world.channel.id else None

    def get_cog(self, name: str):
        return self.cogs.get(name)

    async def blacklist_check(self, interaction) -> bool:
        return True


# -- the world a test file plays in ------------------------------------------------------------------------


class Fight:
    """A battle that has been proposed through the real command, and what the tests need to follow it."""

    def __init__(self, world: "World", a: int, b: int, proposal: FakeMessage, session_id: int):
        self.world = world
        self.a = a
        self.b = b
        self.proposal = proposal
        self.session_id = session_id
        self._board: FakeMessage | None = None

    @property
    def board(self) -> FakeMessage | None:
        """The message the battle is played on, wherever the cog has moved it to."""
        live = self.world.cog._turns.get(self.session_id)
        if live is not None:
            self._board = live.message
        return self._board

    async def session(self) -> models.BattleSession:
        return await models.BattleSession.objects.select_related("player1", "player2").aget(pk=self.session_id)

    async def state(self) -> dict:
        return (await self.session()).state

    async def status(self) -> str:
        return (await self.session()).status

    async def ready(self, n: int) -> FakeInteraction:
        interaction = await self.world.click(n, self.proposal.view, "ready", message=self.proposal)
        for message in interaction.sent:
            if isinstance(message.view, cog.BattleTurnView):
                self._board = message
        return interaction

    async def act(self, n: int, button: str, force_view=None) -> FakeInteraction:
        """Click a button of the turn view currently on the board (or of a given, possibly stale, view)."""
        board = self.board
        view = force_view or (board.view if board is not None else None)
        return await self.world.click(n, view, button, message=board, force=force_view is not None)

    async def play_out(self, button: str = "attack", limit: int = 80) -> int:
        """Both players press the same button in turn until the battle is over. Returns the turns played."""
        turns = 0
        while turns < limit:
            session = await self.session()
            if session.status != "active":
                break
            await self.act(self.a if session.state["active"] == "p1" else self.b, button)
            turns += 1
        return turns

    def card(self, state: dict, side: str, index: int = 0) -> dict:
        return state[f"{side}_balls"][index]

    def turn_views(self) -> list:
        """Every set of turn buttons of this battle still listening: there should never be more than one."""
        return [
            view
            for view in self.world.store.live
            if isinstance(view, cog.BattleTurnView) and view.session_id == self.session_id
        ]

    def boards(self) -> list[FakeMessage]:
        """Every message of the channel carrying turn buttons of this battle."""
        return [
            message
            for message in self.world.channel.messages.values()
            if isinstance(message.view, cog.BattleTurnView)
            and message.view.session_id == self.session_id
            and not message.deleted
        ]


class World:
    def __init__(self, block: int):
        """`block` picks the 1000 Discord ids this test file owns."""
        self.base = ID_ROOT + block * 1000
        self.store = FakeStore(self)
        self.bot = FakeBot(self)
        self.channel = FakeChannel(self, self.base + 900)
        self.cog = cog.Battle(self.bot)
        self.bot.cogs["Battle"] = self.cog
        self.events: list[tuple] = []
        self.errors: list[Exception] = []
        self.overrides: dict = {}
        # seconds every call to Discord takes. 0 by default; the tests about clicks landing together set it
        # to what a real round trip costs, since that is the window those clicks land in
        self.latency = 0.0
        self.token_generation = 0
        bus.subscribe("battle_tests", self._on_event)

    def expire_tokens(self):
        """Fifteen minutes go by: every interaction made so far can no longer be followed up or edited."""
        self.token_generation += 1

    async def lag(self):
        if self.latency:
            await asyncio.sleep(self.latency)

    async def later(self, delay: float, coroutine):
        """Run a coroutine after a delay: the second of two clicks that land close together."""
        await asyncio.sleep(delay)
        return await coroutine

    # -- players and what they own --

    def user(self, n: int, bot: bool = False) -> FakeUser:
        user_id = self.base + n
        if user_id not in self.bot.users:
            self.bot.users[user_id] = FakeUser(user_id, f"Tester{n}", bot=bot)
        return self.bot.users[user_id]

    async def player(self, n: int, money: int | None = None) -> Player:
        player, _ = await Player.objects.aget_or_create(discord_id=self.user(n).id)
        if money is not None:
            await Player.objects.filter(pk=player.pk).aupdate(money=money)
            player.money = money
        return player

    async def money(self, n: int) -> int:
        return (await Player.objects.aget(discord_id=self.user(n).id)).money

    async def ledger(self, *players: int) -> list[tuple[int, str]]:
        """Every berry movement the ledger holds for these players, oldest first, as (amount, reason)."""
        ids = [self.user(n).id for n in players]
        rows = BerryTransaction.objects.filter(player__discord_id__in=ids).order_by("pk")
        return [(row.amount, row.reason) async for row in rows]

    async def give(self, n: int, ball: str | int, attack_bonus: int = 0, health_bonus: int = 0, special=None) -> int:
        """Create a card for player `n`; returns its id."""
        player = await self.player(n)
        ball_id = BALL[ball] if isinstance(ball, str) else ball
        instance = await BallInstance.objects.acreate(
            ball_id=ball_id,
            player=player,
            attack_bonus=attack_bonus,
            health_bonus=health_bonus,
            special_id=SPECIAL[special] if isinstance(special, str) else special,
        )
        return instance.pk

    async def hand_over(self, instance_id: int, n: int):
        """Move a card to player `n`, as a trade or a gift would."""
        await BallInstance.objects.filter(pk=instance_id).aupdate(player=await self.player(n))

    async def arg(self, n: int, instance_id: int) -> BallInstance:
        """
        What Discord hands the command for a treasure argument: the row as `BallInstanceTransformer` reads
        it, refused when it is not the caller's.
        """
        instance = await BallInstanceTransformer().get_from_pk(instance_id)
        if instance.player.discord_id != self.user(n).id:
            raise commands.BadArgument("That treasure doesn't belong to you.")
        return instance

    # -- settings and the life of the cog --

    def override_settings(self, **overrides):
        """The settings as they are in the database, with a few values changed for this cog only."""
        self.overrides = overrides
        self._patch_settings()

    def restore_settings(self):
        self.overrides = {}
        self._patch_settings()

    def _patch_settings(self):
        overrides = self.overrides

        async def patched(refresh: bool = True):
            battle_settings = await models.BattleSettings.aload()
            for name, value in overrides.items():
                if not hasattr(battle_settings, name):
                    raise AttributeError(name)
                setattr(battle_settings, name, value)
            return battle_settings

        self.cog.get_settings = patched

    async def reload(self, ready: bool = True):
        """
        Load the package again through its own `setup()`: a reload when the bot is connected, a start of
        the process when it is not. The boards already posted keep their buttons either way; whether
        anything still answers behind them is what the tests look at.
        """
        await self.cog.cog_unload()
        self.bot.ready = ready
        await battle_ext.setup(self.bot)
        self.cog = self.bot.cogs["Battle"]
        self.bot.ready = True
        self._patch_settings()

    # -- Discord side --

    def instrument(self, view):
        """Keep a trace of what would otherwise only reach a log: a callback that raised."""
        if getattr(view, "_harness_instrumented", False):
            return
        view._harness_instrumented = True
        world = self
        original_error = view.on_error

        async def on_error(interaction, error, item):
            world.errors.append(error)
            interaction.error = error
            await original_error(interaction, error, item)

        view.on_error = on_error

    async def cmd(self, n: int, name: str, **arguments) -> FakeInteraction:
        """Run a slash command of the cog as player `n`."""
        interaction = FakeInteraction(self, self.user(n))
        command = getattr(cog.Battle, name)
        await command.callback(self.cog, interaction, **arguments)
        return interaction

    async def cmd_card(self, n: int, name: str, **instance_ids) -> FakeInteraction:
        """A command whose arguments are all treasures, given by id."""
        arguments = {key: await self.arg(n, value) for key, value in instance_ids.items()}
        return await self.cmd(n, name, **arguments)

    async def click(self, n: int, view, button, message=None, force: bool = False) -> FakeInteraction:
        if view is None:
            interaction = FakeInteraction(self, self.user(n), message=message)
            interaction.dead = True
            return interaction
        item = getattr(view, button) if isinstance(button, str) else button
        return await self.dispatch(n, view, item, message=message, force=force)

    async def choose(self, n: int, view, value, message=None, force: bool = False) -> FakeInteraction:
        """Pick a value in the (only) select of a view."""
        select = next(item for item in view.children if isinstance(item, discord.ui.Select))
        data = {"values": [str(value)], "custom_id": select.custom_id, "component_type": 3}
        return await self.dispatch(n, view, select, message=message, data=data, force=force)

    async def dispatch(self, n: int, view, item, message=None, data=None, force: bool = False) -> FakeInteraction:
        """
        Deliver a component interaction the way discord.py does: `View._scheduled_task` runs the checks,
        calls the callback and routes an exception to `on_error`. A view that has stopped listening and a
        greyed-out button get nothing, unless `force` says the click was already on its way.
        """
        self.instrument(view)
        message = message or getattr(view, "_harness_message", None)
        interaction = FakeInteraction(self, self.user(n), message=message, data=data)
        if (view.is_finished() or getattr(item, "disabled", False)) and not force:
            interaction.dead = True
            return interaction
        await view._scheduled_task(item, interaction)
        return interaction

    # -- battles --

    async def propose(self, a: int, b: int, wager: int = 0, max_size=None) -> tuple[FakeInteraction, Fight | None]:
        await self.player(a)
        await self.player(b)
        interaction = await self.cmd(a, "start", opponent=self.user(b), max_size=max_size, wager=wager)
        proposal = next((m for m in interaction.sent if isinstance(m.view, cog.BattleProposalView)), None)
        if proposal is None:
            return interaction, None
        return interaction, Fight(self, a, b, proposal, proposal.view.session_id)

    async def fight(self, a: int, b: int, deck_a: list, deck_b: list, wager: int = 0, max_size=None) -> Fight:
        """
        Propose, fill both decks through the real commands and press Ready twice.

        A deck entry is a treasure name, or (name, [item names]) for a character and what it is handed;
        any of those names can be replaced by {"ball": name, "attack_bonus": n, "special": name, ...}.
        """
        refusal, fight = await self.propose(a, b, wager=wager, max_size=max_size)
        assert fight is not None, f"the proposal was refused: {refusal.texts()}"
        for n, deck in ((a, deck_a), (b, deck_b)):
            for entry in deck:
                character, items = entry if isinstance(entry, tuple) else (entry, [])
                character_id = await self._own(n, character)
                added = await self.cmd_card(n, "add", countryball=character_id)
                assert added.said("Added"), added.texts()
                for item in items:
                    item_id = await self._own(n, item)
                    equipped = await self.cmd_card(n, "equip", item=item_id, character=character_id)
                    assert equipped.said("now holds"), equipped.texts()
        first = await fight.ready(a)
        second = await fight.ready(b)
        assert fight.board is not None, f"the battle did not start: {first.texts()} {second.texts()}"
        return fight

    async def _own(self, n: int, what) -> int:
        if isinstance(what, int):
            return what
        if isinstance(what, dict):
            return await self.give(n, **what)
        return await self.give(n, what)

    async def close_everything(self):
        """End whatever the players of this block still have open, so the next scenario starts clean."""
        mine = Q(player1__discord_id__gte=self.base, player1__discord_id__lt=self.base + 1000)
        open_ones = models.BattleSession.objects.filter(mine, status__in=sessions.OPEN)
        async for pk in open_ones.values_list("pk", flat=True):
            await sessions.acancel(pk)
            self.cog._forget(pk)

    # -- events --

    async def _on_event(self, player_id, event, context, channel_id):
        self.events.append((player_id, str(event), context, channel_id))

    def events_of(self, name: str) -> list[tuple]:
        """(player, lost_count, channel) of every event of that name, in the order they were sent."""
        mine = [entry for entry in self.events if entry[1] == name]
        return [(player, context.lost_count, channel) for player, _, context, channel in mine]


# -- cleaning up ------------------------------------------------------------------------------------------


def wipe(block: int):
    """Everything the test players of a block own goes with them: cards, sessions, records, berries ledger."""
    base = ID_ROOT + block * 1000
    Player.objects.filter(discord_id__gte=base, discord_id__lt=base + 1000).delete()


def wipe_marked_rows():
    """Buff rows and shop items the tests created, recognised by their mark."""
    for buff in models.Buff.objects.all():
        if abs((buff.capacity_value % 1) - BUFF_MARK) < 1e-9:
            buff.delete()
    models.BattleItem.objects.filter(name__startswith=ITEM_PREFIX).delete()


def foreign_rows() -> dict:
    """What sits in the tables the tests read as a whole and that the tests did not put there."""
    real = Q(player1__discord_id__lt=ID_ROOT) | Q(player2__discord_id__lt=ID_ROOT)
    return {
        "records": models.BattleRecord.objects.filter(real).count(),
        "sessions": models.BattleSession.objects.filter(real).count(),
        "shop_items": models.BattleItem.objects.exclude(name__startswith=ITEM_PREFIX).count(),
    }


def take_turn():
    """
    One test file at a time on the scratch database, whoever started it.

    The files do not all keep to their own players: the leaderboard reads every record there is, and the
    restart test closes every battle left open, as a restart does. Two sessions replaying the suite at the
    same moment used to fail each other's tests that way. The lock belongs to this process's connection to
    the database, and goes when the process does.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [SUITE_LOCK])
        if cursor.fetchone()[0]:
            return
        print("  ....  another test file is running on this database: waiting for it to finish")
        sys.stdout.flush()
        cursor.execute("SELECT pg_advisory_lock(%s)", [SUITE_LOCK])


def run(block: int, main):
    """Wait for the database, wipe the block, run the async `main(world)`, wipe again whatever happened."""
    take_turn()
    wipe(block)
    wipe_marked_rows()

    async def runner():
        world = World(block)
        try:
            await main(world)
        finally:
            real_randomness()
            await world.cog.cog_unload()
            for view in list(world.store.live):
                view.stop()

    try:
        asyncio.run(runner())
    finally:
        wipe(block)
        wipe_marked_rows()


awipe_marked_rows = sync_to_async(wipe_marked_rows)
aforeign_rows = sync_to_async(foreign_rows)
