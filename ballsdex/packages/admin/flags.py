import discord
from discord.ext.commands import FlagConverter, Range, flag

from ballsdex.core.utils.transformers import (
    BallGroupTransform,
    BallTransform,
    EconomyTransform,
    FrameTransform,
    RegimeTransform,
    SpecialTransform,
)
from settings.models import settings


def collectible_aliases() -> list[str]:
    """
    The dex's own word for a collectible, accepted alongside "countryball".

    A slash command shows this flag translated — "treasure:" on a dex whose collectibles are treasures — because
    the bot renames "countryball" everywhere it is shown. The text form has no translator, so without this alias
    "treasure:Monkey D. Luffy" is silently dropped and a random one spawns instead.
    """
    name = settings.collectible_name
    return [name] if name and name != "countryball" else []


class StatusFlags(FlagConverter):
    status: discord.Status | None = flag(description="The status you want to set")
    name: str | None = flag(description="Title of the activity, if not custom")
    state: str | None = flag(description="Custom status or subtitle of the activity")
    activity_type: discord.ActivityType | None = flag(
        description="The type of activity", default=discord.ActivityType.custom
    )


class RarityFlags(FlagConverter):
    chunked: bool = flag(default=True, description="Group together countryballs with the same rarity.")
    include_disabled: bool = flag(
        default=False, description="Include the countryballs that are disabled or with a rarity of 0."
    )


class SpawnFlags(FlagConverter):
    countryball: BallTransform | None = flag(
        description="The countryball you want to spawn. Random according to rarities if not specified.",
        aliases=collectible_aliases(),
    )
    group: BallGroupTransform | None = flag(description="Only spawn from this group.")
    channel: discord.TextChannel | None = flag(
        description="The channel you want to spawn the countryball in. Current channel if not specified.", default=None
    )
    n: Range[int, 1, 100] = flag(
        description="The number of countryballs to spawn. If no countryball was specified, it's random every time.",
        default=1,
    )
    special: SpecialTransform | None = flag(
        description="Force the countryball to have a special attribute when caught."
    )
    frame_name: FrameTransform | None = flag(
        description="Spawn it with this frame, picked from the list. With special=Frame and none picked, "
        "the frame of the day.",
        aliases=["frame"],
    )
    atk_bonus: int | None = flag(description="Force the countryball to have a specific attack bonus when caught.")
    hp_bonus: int | None = flag(description="Force the countryball to have a specific health bonus when caught.")


class GiveBallFlags(FlagConverter):
    countryball: BallTransform = flag(positional=True, description="The countryball you want to give")
    special: SpecialTransform | None = flag(description="A special event to set to this card")
    frame_name: FrameTransform | None = flag(
        description="Give it wearing this frame, picked from the list.",
        aliases=["frame"],
    )
    health_bonus: int | None = flag(description="Force a specific health bonus percentage")
    attack_bonus: int | None = flag(description="Force a specific attack bonus percentage")


class BulkGiveFlags(FlagConverter):
    # descriptions are kept terse on purpose: /admin is close to the 8000 character payload
    # Discord allows for one command, and going over stops the whole tree from syncing
    user: discord.User | None = flag(description="Who to give to.")
    role: discord.Role | None = flag(description="Give to everyone with this role.")
    n: Range[int, 1, 100] = flag(default=1, description="How many each player gets.")
    countryball: BallTransform | None = flag(
        description="Give this one. Random by rarity if left out.", aliases=collectible_aliases()
    )
    group: BallGroupTransform | None = flag(description="Only draw from this group.")
    min_rarity: float | None = flag(description="Lowest rarity to draw from.")
    max_rarity: float | None = flag(description="Highest rarity to draw from.")
    special: SpecialTransform | None = flag(description="Put this special on every card.")
    roll_specials: bool = flag(default=False, description="Roll a special per card, like a spawn.")
    health_bonus: int | None = flag(description="Force a health bonus percentage")
    attack_bonus: int | None = flag(description="Force an attack bonus percentage")


class BallsCountFlags(FlagConverter):
    user: discord.User | None = flag(description="The player whose countryballs you are counting")
    countryball: BallTransform | None = flag(
        description="Restrict counting to a specific countryball", aliases=collectible_aliases()
    )
    special: SpecialTransform | None = flag(description="Restrict counting to a special event")
    deleted: bool = flag(default=False, description="Count the deleted countryballs too")


class TradeHistoryFlags(FlagConverter):
    sort_oldest: bool = flag(description='"yes" to have oldest trades first', default=False)
    days: int | None = flag(description="Retrieve entries from the last n days")
    if settings.currency_enabled:
        currency: bool = flag(default=False, description=f"Only show trades that included {settings.currency_plural}")


class UserTradeHistoryFlags(TradeHistoryFlags):
    countryball: BallTransform | None = flag(
        description="The countryball you want to filter the history by", aliases=collectible_aliases()
    )
    user2: discord.User | None = flag(description="The second user you want to check the history of")
    special: SpecialTransform | None = flag(description="The special you want to filter the history by")


class CreateFlags(FlagConverter):
    name: Range[str, None, 48] = flag(description="The name of the countryball", aliases=["country"])
    health: int = flag(description="The health of the countryball")
    attack: int = flag(description="The attack of the countryball")
    rarity: float = flag(description="The rarity of the countryball, if enabled")
    emoji_id: Range[str, 17, 21] = flag(description="Emoji ID of this countryball.")
    credits: Range[str, None, 64] = flag(description="Authors of wild card and collection card")
    capacity_name: Range[str, None, 64] = flag(description="Name of the countryball's capacity")
    capacity_description: Range[str, None, 256] = flag(description="Description of the countryball's capacity")
    enabled: bool = flag(description="Type 'no' if you don't want this countryball to spawn.", default=True)
    tradeable: bool = flag(
        description="Type 'no' if you don't want this countryball to be traded with others.", default=True
    )
    regime: RegimeTransform = flag(description="Political regime of this countryball")
    economy: EconomyTransform | None = flag(description="Economical regime of this countryball", default=None)
