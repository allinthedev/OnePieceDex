"""
This file contains [discord.py transformers][discord.app_commands.Transformer] used to provide autocompletion,
parsing and validation for various Ballsdex models.
"""

import logging
import time
from collections import Counter
from datetime import date, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterable

import discord
from currency_app.models import ItemBall
from discord import app_commands
from discord.ext import commands
from django.db.models import Model, Q
from django.db.models.expressions import RawSQL
from django.utils import timezone

from bd_models.models import (
    Ball,
    BallGroup,
    BallInstance,
    Economy,
    Regime,
    Special,
    is_frame_special,
    special_filter,
    specials,
)
from settings.models import settings

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.core.utils.transformers")

__all__ = (
    "BallTransform",
    "BallInstanceTransform",
    "SpecialTransform",
    "RegimeTransform",
    "EconomyTransform",
    "BallGroupTransform",
    "FrameTransform",
)


class TradeCommandType(Enum):
    """
    If a command is using `BallInstanceTransformer` for trading purposes, it should define this
    enum to filter out values.
    """

    PICK = 0
    REMOVE = 1


class ModelTransformer[T: "Model"](app_commands.Transformer, commands.Converter):
    """
    Base abstract class for autocompletion from on Django models

    This also works with hybrid commands.

    Attributes
    ----------
    name: str
        Name to qualify the object being listed
    column: str
        Column of the model to use for matching text-based conversions. Defaults to "name".
    model: T
        The Django model associated to the class derivation
    base: int
        The base in which database IDs are converted. Defaults to decimal (10).


    Parameters
    ----------
    **filters: Any
        Filters to apply on the model before providing options.
    """

    name: str
    column: str = "name"
    model: type[T]
    base: int = 10

    def __init__(self, **filters: Any):
        self.filters = filters

    def key(self, model: T) -> str:
        """
        Return a string used for searching while sending autocompletion suggestions.
        """
        return getattr(model, self.column)

    def get_queryset(self) -> "QuerySet[T]":
        return self.model.objects.filter(**self.filters)

    async def validate(self, ctx: commands.Context["BallsDexBot"], item: T):
        """
        A function to validate the fetched item before calling back the command.

        Raises
        ------
        commands.BadArgument
            Raised if the item does not pass validation with the message to be displayed
        """
        pass

    async def get_from_pk(self, value: int) -> T:
        """
        Return a Django model instance from a primary key.

        Raises
        ------
        KeyError | django.db.models.Model.DoesNotExist
            Entry does not exist
        """
        return await self.get_queryset().aget(pk=value)

    async def get_from_text(self, value: str) -> T:
        """
        Return a Django model instance from the raw value entered.

        Raises
        ------
        KeyError | django.db.models.Model.DoesNotExist
            Entry does not exist
        """
        return await self.get_queryset().aget(**{f"{self.column}__iexact": value})

    async def get_options(
        self, interaction: discord.Interaction["BallsDexBot"], value: str
    ) -> list[app_commands.Choice[int]]:
        """
        Generate the list of options for autocompletion
        """
        raise NotImplementedError()

    async def autocomplete(
        self, interaction: discord.Interaction["BallsDexBot"], value: str
    ) -> list[app_commands.Choice[int]]:
        t1 = time.time()
        choices: list[app_commands.Choice[int]] = []
        for option in await self.get_options(interaction, value):
            choices.append(option)
        t2 = time.time()
        log.debug(f"{self.name.title()} autocompletion took {round((t2 - t1) * 1000)}ms, {len(choices)} results")
        return choices

    async def transform(self, interaction: discord.Interaction["BallsDexBot"], value: str) -> T:
        if not value:
            raise commands.BadArgument("You need to use the autocomplete function for the economy selection.")
        try:
            instance = await self.get_from_pk(int(value, self.base))
            await self.validate(await commands.Context.from_interaction(interaction), instance)
        except (self.model.DoesNotExist, KeyError, ValueError):
            raise commands.BadArgument(
                f"The {self.name} could not be found. Make sure to use the autocomplete function on this command."
            )
        else:
            return instance

    async def convert(self, ctx: commands.Context["BallsDexBot"], argument: str) -> T:
        try:
            instance = await self.get_from_text(argument)
            await self.validate(ctx, instance)
        except self.model.DoesNotExist as e:
            raise commands.BadArgument(f"The {self.name} could not be found.") from e
        else:
            return instance


class BallInstanceTransformer(ModelTransformer[BallInstance]):
    name = settings.collectible_name
    model = BallInstance
    base = 16

    def get_queryset(self) -> "QuerySet[BallInstance]":
        return super().get_queryset().prefetch_related("player")

    async def get_from_pk(self, value: int) -> BallInstance:
        return await self.get_queryset().prefetch_related("player", "trade_player", "ball").aget(pk=value)

    async def get_from_text(self, value: str) -> BallInstance:
        return await self.get_queryset().aget(pk=int(value, 16))

    async def validate(self, ctx: commands.Context["BallsDexBot"], item: BallInstance):
        # checking if the ball does belong to user, and a custom ID wasn't forced
        if item.player.discord_id != ctx.author.id:
            raise commands.BadArgument(f"That {settings.collectible_name} doesn't belong to you.")

    async def get_options(
        self, interaction: discord.Interaction["BallsDexBot"], value: str
    ) -> list[app_commands.Choice[int]]:
        balls_queryset = self.get_queryset().filter(player__discord_id=interaction.user.id)

        if (special := getattr(interaction.namespace, "special", None)) and special.isdigit():
            picked = specials.get(int(special))
            balls_queryset = balls_queryset.filter(
                special_filter(picked) if picked is not None else Q(special_id=int(special))
            )

        if interaction.command and (trade_type := interaction.command.extras.get("trade", None)):
            if trade_type == TradeCommandType.PICK:
                balls_queryset = (
                    balls_queryset.filter(
                        Q(Q(locked__isnull=True) | Q(locked__lt=timezone.now() - timedelta(minutes=30)))
                    )
                    .exclude(tradeable=False)
                    .exclude(ball__tradeable=False)
                    .exclude(special__tradeable=False)
                )
            else:
                balls_queryset = balls_queryset.filter(
                    locked__isnull=False, locked__gt=timezone.now() - timedelta(minutes=30)
                )

        if value.startswith("="):
            ball_name = value[1:]
            balls_queryset = balls_queryset.filter(ball__country__iexact=ball_name)
        else:
            balls_queryset = (
                balls_queryset.select_related("ball")
                .annotate(
                    searchable=RawSQL(
                        "to_hex(ballinstance.id) || ' ' || ball.country || ' ' || "
                        "COALESCE(ball.catch_names, '') || ' ' || "
                        "COALESCE(ball.translations, '')",
                        (),
                    )
                )
                .filter(searchable__icontains=value.replace(".", ""))
            )
        balls_queryset = balls_queryset[:25]

        choices: list[app_commands.Choice] = [
            app_commands.Choice(name=x.description(bot=interaction.client), value=f"{x.pk:X}")
            async for x in balls_queryset
        ]
        return choices


class TTLModelTransformer[T: "Model"](ModelTransformer[T]):
    """
    Base class for simple Django model autocompletion with TTL cache.

    This is used in most cases except for BallInstance which requires special handling depending
    on the interaction passed.

    Attributes
    ----------
    ttl: float
        Delay in seconds for `items` to live until refreshed with `load_items`, defaults to 300
    """

    ttl: float = 300

    def __init__(self, **filters: Any):
        super().__init__(**filters)
        self.items: dict[int, T] = {}
        self.search_map: dict[T, str] = {}
        self.last_refresh: float = 0
        log.debug(f"Inited transformer for {self.name}")

    async def load_items(self) -> Iterable[T]:
        """
        Query values to fill `items` with.
        """
        return [x async for x in self.get_queryset()]

    async def maybe_refresh(self):
        t = time.time()
        if t - self.last_refresh > self.ttl:
            self.items = {x.pk: x for x in await self.load_items()}
            self.last_refresh = t
            self.search_map = {x: self.key(x).lower() for x in self.items.values()}

    async def get_options(
        self, interaction: discord.Interaction["BallsDexBot"], value: str
    ) -> list[app_commands.Choice[str]]:
        await self.maybe_refresh()

        i = 0
        choices: list[app_commands.Choice] = []
        for item in self.items.values():
            if value.lower() in self.search_map[item]:
                choices.append(app_commands.Choice(name=self.key(item), value=str(item.pk)))
                i += 1
                if i == 25:
                    break
        return choices


class BallTransformer(TTLModelTransformer[Ball]):
    name = settings.collectible_name
    column = "country"
    model = Ball


class BallObtainableTransformer(BallTransformer):
    """
    Every countryball players can get: the enabled ones, and the ones only found in packs.
    """

    def get_queryset(self) -> "QuerySet[Ball]":
        return Ball.objects.filter(Q(enabled=True) | Q(pk__in=ItemBall.objects.values("ball_id")))


class SpecialTransformer(TTLModelTransformer[Special]):
    name = "special event"
    model = Special


class RegimeTransformer(TTLModelTransformer[Regime]):
    name = "regime"
    model = Regime


class EconomyTransformer(TTLModelTransformer[Economy]):
    name = "economy"
    model = Economy


class BallGroupTransformer(TTLModelTransformer[BallGroup]):
    name = "group"
    model = BallGroup


# a frame is recognised by what it holds rather than by its key, so the dated and the named ones both count
HAS_FRAME_SQL = "EXISTS (SELECT 1 FROM jsonb_each(capacity_logic) e WHERE e.value ? 'card' OR e.value ? 'spawn')"
# what `frames.utils.NO_SPECIAL` stands for: in place of a special ID, the treasures without one. Kept here
# rather than imported, so reading a frame's label works whether or not the frames package is installed —
# it is part of the key format ("MM-DD-YYYY:0") rather than a setting of that package.
NO_SPECIAL_ID = 0


def namespace_value(interaction: discord.Interaction, *names: str) -> str | None:
    """
    The raw value of another option of the command being typed, under the first of `names` that carries one.

    A flag is shown under the dex's own word for a collectible — "treasure:" rather than "countryball:" — and the
    namespace carries the name Discord sent, so every name the option can arrive under has to be tried.
    """
    for name in names:
        if not name:
            continue
        value = getattr(interaction.namespace, name, None)
        if value:
            return str(value)
    return None


class FrameTransformer(app_commands.Transformer, commands.Converter):
    """
    A dropdown of frames, so a frame is picked rather than typed out in full.

    Frames are no model of their own: they live in `Ball.capacity_logic`. This reads that column instead of the
    ball cache, so a frame added in the admin panel can be spawned without reloading the cache first.

    With a treasure already named in the command, its own frames are listed — the ones of every treasure, and the
    ones of the special picked alongside. With no treasure named yet, every frame name there is, so the dropdown
    still says what exists.
    """

    name = "frame"
    # the list of every name is only rebuilt this often: it is read on each keystroke
    ttl: float = 60

    def __init__(self):
        self.names: list[tuple[str, int]] = []
        self.last_refresh: float = 0

    async def transform(self, interaction: discord.Interaction["BallsDexBot"], value: str) -> str:
        return value.strip()

    async def convert(self, ctx: commands.Context["BallsDexBot"], argument: str) -> str:
        return argument.strip()

    async def autocomplete(  # type: ignore[override]
        self, interaction: discord.Interaction["BallsDexBot"], value: str
    ) -> list[app_commands.Choice[str]]:
        try:
            from frames.utils import NO_SPECIAL, is_frame_entry, is_named_key, parse_frame_key
        except ImportError:
            return []

        ball_id = namespace_value(interaction, "countryball", settings.collectible_name.lower())
        if ball_id is None or not ball_id.isdigit():
            return await self.every_name(value)
        capacity = await Ball.objects.filter(pk=int(ball_id)).values_list("capacity_logic", flat=True).afirst()
        if not isinstance(capacity, dict):
            return []

        special_id = self.special_id(interaction)
        wanted = {None, NO_SPECIAL if special_id is None else special_id}
        today = date.today()
        # compared on the day and the scope rather than on an exact key: several frames can share a day,
        # and each of them carries its own name in the key
        day_text = today.strftime("%m-%d-%Y")
        running = {(day_text, None), (day_text, NO_SPECIAL if special_id is None else special_id)}

        rows: list[tuple[tuple[int, int, int], str, str]] = []
        for key, entry in capacity.items():
            if not is_frame_entry(entry):
                continue
            parsed = parse_frame_key(key)
            if parsed is None and not is_named_key(key):
                continue
            if parsed is not None and parsed[1] not in wanted:
                continue
            runs_today = parsed is not None and parsed in running
            label = self.label(key, entry, parsed, runs_today)
            if value.lower() not in label.lower():
                continue
            day = parsed[0] if parsed else ""
            # today first, then the named frames, then the dated ones with the most recent first
            order = (
                0 if runs_today else 1,
                0 if parsed is None else 1,
                -int(day[6:] + day[:2] + day[3:5]) if day else 0,
            )
            rows.append((order, label, key))

        rows.sort(key=lambda row: (row[0], row[1]))
        return [app_commands.Choice(name=label[:100], value=key) for _, label, key in rows[:25]]

    @staticmethod
    def label(key: str, entry: dict, parsed: tuple[str, int | None] | None, running_today: bool) -> str:
        """What one frame reads as in the dropdown: its name, then when it applies and to what."""
        parts = [str(entry.get("name") or key)]
        if parsed is None:
            parts.append("any day")
        else:
            parts.append(parsed[0])
            if parsed[1] == NO_SPECIAL_ID:
                parts.append("no special")
            elif parsed[1] is not None:
                special = specials.get(parsed[1])
                parts.append(special.name if special else f"special #{parsed[1]}")
        if running_today:
            parts.append("today")
        return " · ".join(parts)

    @staticmethod
    def special_id(interaction: discord.Interaction["BallsDexBot"]) -> int | None:
        """The special the frames are narrowed down to, None when the command names none that narrows them."""
        raw = namespace_value(interaction, "special")
        if raw is None or not raw.isdigit():
            return None
        special = specials.get(int(raw))
        # the "Frame" special only means "spawn it framed", it says nothing about which frame
        if special is None or is_frame_special(special):
            return None
        return int(raw)

    async def every_name(self, value: str) -> list[app_commands.Choice[str]]:
        """Every frame name of every treasure, for a command where no treasure has been named yet."""
        await self.maybe_refresh()
        choices: list[app_commands.Choice[str]] = []
        for name, count in self.names:
            if value.lower() not in name.lower():
                continue
            treasures = settings.collectible_name if count == 1 else settings.plural_collectible_name
            choices.append(app_commands.Choice(name=f"{name} · on {count} {treasures}"[:100], value=name))
            if len(choices) == 25:
                break
        return choices

    async def maybe_refresh(self):
        now = time.time()
        if now - self.last_refresh <= self.ttl and self.names:
            return
        try:
            from frames.utils import is_frame_entry, is_named_key, parse_frame_key
        except ImportError:
            return
        counter: Counter[str] = Counter()
        framed = Ball.objects.annotate(has_frames=RawSQL(HAS_FRAME_SQL, ())).filter(has_frames=True)
        async for capacity in framed.values_list("capacity_logic", flat=True):
            if not isinstance(capacity, dict):
                continue
            seen: set[str] = set()
            for key, entry in capacity.items():
                if not is_frame_entry(entry) or (parse_frame_key(key) is None and not is_named_key(key)):
                    continue
                # a frame set up over two months has the same name every day: one treasure, counted once
                seen.add(str(entry.get("name") or key))
            counter.update(seen)
        self.names = sorted(counter.items(), key=lambda row: (-row[1], row[0].lower()))
        self.last_refresh = now


BallTransform = app_commands.Transform[Ball, BallTransformer]
BallInstanceTransform = app_commands.Transform[BallInstance, BallInstanceTransformer]
SpecialTransform = app_commands.Transform[Special, SpecialTransformer]
RegimeTransform = app_commands.Transform[Regime, RegimeTransformer]
EconomyTransform = app_commands.Transform[Economy, EconomyTransformer]
BallGroupTransform = app_commands.Transform[BallGroup, BallGroupTransformer]
SpecialEnabledTransform = app_commands.Transform[Special, SpecialTransformer(hidden=False)]
BallEnabledTransform = app_commands.Transform[Ball, BallTransformer(enabled=True)]
BallObtainableTransform = app_commands.Transform[Ball, BallObtainableTransformer]
FrameTransform = app_commands.Transform[str, FrameTransformer]
