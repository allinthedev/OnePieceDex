"""
Definition of every quest type: which events make it progress, which settings it uses, which package it needs and
how its goal is written for players.

Adding a quest type means adding a `TypeDefinition` here and a branch in `engine._evaluate`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ballsdex.core.game_events import Event
from settings.models import settings

from .integrations import (
    AUCTION_HOUSE,
    AUGMENT,
    BATTLES,
    BOSS,
    COLLECTIBLES,
    CRAFTING,
    MERCHANT,
    PACKS,
    VOTE,
    Integration,
)
from .models import Measure, Quest, QuestType

TREASURE_FILTERS = (
    "ball",
    "special",
    "any_special",
    "group",
    "min_rarity",
    "max_rarity",
    "min_attack_bonus",
    "min_health_bonus",
    "hex_contains",
)
BERRY_MEASURES = (Measure.COUNT, Measure.AMOUNT)

# the royale deeds, each with the crew war raid it has a separate event for. Which of the two a quest
# counts is decided by `in_crew_war` and never mixed: a kill in a war is not a kill in a lobby
ROYALE_PAIRS = {
    QuestType.ROYALE_PLAYED: (Event.ROYALE_PLAYED, Event.ROYALE_WAR_PLAYED),
    QuestType.ROYALE_WIN: (Event.ROYALE_WIN, Event.ROYALE_WAR_WIN),
    QuestType.ROYALE_KILL: (Event.ROYALE_KILL, Event.ROYALE_WAR_KILL),
    QuestType.ROYALE_CHEST: (Event.ROYALE_CHEST, Event.ROYALE_WAR_CHEST),
    QuestType.ROYALE_BOUNTY: (Event.ROYALE_BOUNTY, Event.ROYALE_WAR_BOUNTY),
}
ROYALE_FILTERS = ("in_crew_war",)
# everything that can change what a player owns, for the goals counting a collection instead of an action
COLLECTION_EVENTS = frozenset({Event.CATCH, Event.OBTAIN, Event.SYNC})


@dataclass(frozen=True)
class TypeDefinition:
    type: QuestType
    events: frozenset[Event]
    fields: tuple[str, ...]
    goal_label: str
    help: str
    describe: Callable[[Quest], str]
    measures: tuple[Measure, ...] = (Measure.COUNT,)
    integration: Integration | None = None
    # whether the treasure filters apply to the treasures carried by the event
    filters_instances: bool = True
    # whether this type's events can say which server the player was in. Some cannot: a crew war is scored by
    # a background task, a vote arrives over a webhook, and what a player owns happened nowhere in particular.
    # Those are exempt from "only in the main server", which would otherwise turn them off without a word.
    knows_server: bool = True


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _berries(amount: int) -> str:
    return f"{amount:,} {settings.currency_plural}"


def _treasures(quest: Quest, count: int) -> str:
    """
    "5 Shiny Monkey D. Luffy treasures", "a treasure with a special", "one treasure of the Straw Hats group"...
    """
    words = []
    if quest.cached_special:
        words.append(quest.cached_special.name)
    if quest.cached_ball:
        words.append(quest.cached_ball.country)
    name = _plural(count, settings.collectible_name, settings.plural_collectible_name)
    text = f"{count if count > 1 else 'a'} {' '.join(words + [name])}"
    if quest.any_special and not quest.cached_special:
        text += " with a special"
    if quest.cached_group:
        text += f" from the {quest.cached_group.name} group"
    # a lower rarity value is a rarer treasure, and players call a treasure of rarity 60 a "T60"
    if quest.min_rarity is not None and quest.max_rarity is not None:
        text += f" between T{quest.min_rarity:g} and T{quest.max_rarity:g}"
    elif quest.max_rarity is not None:
        text += f" of T{quest.max_rarity:g} or rarer"
    elif quest.min_rarity is not None:
        text += f" of T{quest.min_rarity:g} or more common"
    if quest.min_attack_bonus is not None or quest.min_health_bonus is not None:
        stats = []
        if quest.min_attack_bonus is not None:
            stats.append(f"{quest.min_attack_bonus:+d}% attack")
        if quest.min_health_bonus is not None:
            stats.append(f"{quest.min_health_bonus:+d}% health")
        text += f" with at least {' and '.join(stats)}"
    if quest.hex_contains:
        text += f' whose ID contains "{quest.hex_contains.upper()}"'
    return text


def _has_treasure_filter(quest: Quest) -> bool:
    """Whether a quest says anything about which treasure it wants, or takes any."""
    return bool(
        quest.ball_id
        or quest.special_id
        or quest.any_special
        or quest.group_id
        or quest.min_rarity is not None
        or quest.max_rarity is not None
        or quest.min_attack_bonus is not None
        or quest.min_health_bonus is not None
        or quest.hex_contains
    )


def _unit(quest: Quest) -> str:
    count = quest.target
    unit = quest.time_unit or "days"
    return f"{count} {unit[:-1] if count == 1 else unit}"


def _places(quest: Quest) -> str:
    place = quest.max_place or 1
    return "first place" if place == 1 else f"top {place}"


def _in_war(quest: Quest) -> str:
    return " in a crew war raid" if quest.in_crew_war else ""


def _where(quest: Quest) -> str:
    return " in the main server" if quest.main_server_only else ""


def _with(quest: Quest) -> str:
    return f" with <@{quest.partner_discord_id}>" if quest.partner_discord_id else ""


def _times(count: int) -> str:
    return f" {count} times" if count > 1 else ""


def _describe_catch(quest: Quest) -> str:
    text = f"Catch {_treasures(quest, quest.target)}{_where(quest)}"
    if quest.max_catch_seconds is not None:
        text += f" in less than {quest.max_catch_seconds:g} seconds"
    return f"{text}."


def _describe_obtain(quest: Quest) -> str:
    return f"Obtain {_treasures(quest, quest.target)}{_where(quest)}."


def _describe_own(quest: Quest) -> str:
    kind = quest.tier_level.name if quest.tier_level_id and quest.tier_level else ""
    if kind:
        count = quest.target
        return f"Own {count} {kind} {_plural(count, 'card')}."
    return f"Own {_treasures(quest, quest.target)}."


def _describe_currency_streak(quest: Quest) -> str:
    return f"Claim your daily {settings.currency_plural} {quest.target} days in a row."


def _describe_pack_streak(quest: Quest) -> str:
    return f"Claim your daily pack {quest.target} days in a row."


def _describe_command(quest: Quest) -> str:
    return f"Use /{quest.command_name or '?'}{_times(quest.target)}{_where(quest)}."


def _describe_trade(quest: Quest) -> str:
    count = quest.target
    text = f"Complete {count if count > 1 else 'a'} {_plural(count, 'trade')}{_with(quest)}"
    conditions = []
    if quest.must_receive_treasure or quest.ball_id or quest.special_id or quest.any_special:
        conditions.append(_treasures(quest, 1))
    if quest.min_currency:
        conditions.append(f"at least {_berries(quest.min_currency)}")
    if conditions:
        text += f" where you receive {' and '.join(conditions)}"
    return f"{text}."


def _describe_trade_treasures(quest: Quest) -> str:
    treasures = _plural(quest.target, settings.collectible_name, settings.plural_collectible_name)
    return f"Exchange {quest.target} {treasures} in {'a single trade' if quest.in_one_trade else 'trades'}."


def _describe_give_treasures(quest: Quest) -> str:
    recipient = f"<@{quest.partner_discord_id}>" if quest.partner_discord_id else "other players"
    return f"Give {_treasures(quest, quest.target)} to {recipient}{_where(quest)}."


def _describe_friend(quest: Quest) -> str:
    if quest.partner_discord_id:
        return f"Become friends with <@{quest.partner_discord_id}>."
    count = quest.target
    return f"Add {count} new {_plural(count, 'friend')}."


def _losses(quest: Quest) -> str:
    if quest.max_lost is None:
        return ""
    if quest.max_lost == 0:
        return f" without losing a single {settings.collectible_name}"
    return f" losing at most {quest.max_lost} {_plural(quest.max_lost, settings.collectible_name)}"


def _describe_battle(quest: Quest) -> str:
    count = quest.target
    return f"Win {count if count > 1 else 'a'} {_plural(count, 'battle')}{_losses(quest)}."


def _describe_battle_played(quest: Quest) -> str:
    count = quest.target
    return f"Take part in {count} {_plural(count, 'battle')}{_losses(quest)}."


def _describe_give(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Give {_berries(quest.target)} to other players{_with(quest)}."
    minimum = f" of at least {_berries(quest.min_currency)}" if quest.min_currency else ""
    count = quest.target
    return f"Give berries{minimum} to other players{_with(quest)}{_times(count)}."


def _describe_receive(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Receive {_berries(quest.target)} from other players{_with(quest)}."
    minimum = f" of at least {_berries(quest.min_currency)}" if quest.min_currency else ""
    return f"Receive berries{minimum} from other players{_with(quest)}{_times(quest.target)}."


def _describe_catch_currency(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Earn {_berries(quest.target)} by catching {settings.plural_collectible_name}{_where(quest)}."
    count = quest.target
    return f"Get berries from a catch{_times(count)}{_where(quest)}."


def _describe_spend(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Spend {_berries(quest.target)}."
    return f"Spend berries{_times(quest.target)}."


def _describe_craft(quest: Quest) -> str:
    kind = quest.tier_level.name.lower() if quest.tier_level_id and quest.tier_level else ""
    what = f"{kind} " if kind else ""
    if quest.collector_id and quest.collector:
        return f"Craft the {what}card of {quest.collector.name}{_times(quest.target)}."
    count = quest.target
    return f"Craft {count if count > 1 else 'a'} {what}{_plural(count, 'card')}."


def _describe_pack(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Spend {_berries(quest.target)} on packs."
    name = quest.item.name if quest.item_id and quest.item else "pack"
    count = quest.target
    return f"Buy {count} {_plural(count, name)}."


def _describe_merchant(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Spend {_berries(quest.target)} at the merchant."
    if quest.merchant_item_id and quest.merchant_item:
        return f"Buy {quest.merchant_item.name} from the merchant{_times(quest.target)}."
    count = quest.target
    return f"Buy {count} {_plural(count, 'item')} from the merchant."


def _describe_shop(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Spend {_berries(quest.target)} in Buggy's shop."
    return f"Buy {_treasures(quest, quest.target)} from Buggy's shop."


def _describe_sell(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Earn {_berries(quest.target)} by selling to Buggy."
    return f"Sell {_treasures(quest, quest.target)} to Buggy."


def _describe_auction_create(quest: Quest) -> str:
    return f"List {_treasures(quest, quest.target)} on the auction house."


def _describe_auction_bid(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Bid {_berries(quest.target)} on the auction house."
    minimum = f" of at least {_berries(quest.min_currency)}" if quest.min_currency else ""
    count = quest.target
    return f"Place {count} {_plural(count, 'bid')}{minimum} on the auction house."


def _describe_auction_won(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Win {_berries(quest.target)} worth of auctions."
    count = quest.target
    return f"Win {count} {_plural(count, 'auction')}."


# -- the deeds the bus already carried, and the ones the panel's own packages now put on it -------------------------


def _describe_favorite(quest: Quest) -> str:
    return f"Set {_treasures(quest, quest.target)} as a favorite."


def _describe_own_favorites(quest: Quest) -> str:
    return f"Have {_treasures(quest, quest.target)} marked as favorites at the same time."


def _describe_own_currency(quest: Quest) -> str:
    return f"Hold {_berries(quest.target)} at once."


def _describe_complete_group(quest: Quest) -> str:
    if quest.cached_group:
        treasures = _plural(quest.goal, settings.collectible_name, settings.plural_collectible_name)
        return f"Own all {quest.goal} {treasures} of the {quest.cached_group.name} group."
    count = quest.target
    return f"Complete {count} {_plural(count, 'group')}."


def _describe_completion(quest: Quest) -> str:
    return f"Reach {quest.target}% completion of the dex."


def _describe_playtime(quest: Quest) -> str:
    return f"Have been playing for {_unit(quest)}, counted from your first catch."


def _describe_leaderboard_rank(quest: Quest) -> str:
    return f"Reach the {_places(quest)} of the {settings.currency_plural} leaderboard."


def _describe_activity(quest: Quest) -> str:
    return f"Use the bot{_times(quest.target)}{_where(quest)}."


def _describe_pack_weekly(quest: Quest) -> str:
    return f"Claim your weekly pack{_times(quest.target)}."


def _describe_auction_sold(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Earn {_berries(quest.target)} selling on the auction house."
    return f"Sell {_treasures(quest, quest.target)} on the auction house."


def _describe_trade_partners(quest: Quest) -> str:
    count = quest.target
    return f"Trade with {count} different {_plural(count, 'player')}."


def _describe_give_partners(quest: Quest) -> str:
    count = quest.target
    return f"Give {settings.plural_collectible_name} to {count} different {_plural(count, 'player')}."


def _describe_boss_played(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Deal {quest.target:,} damage to bosses."
    count = quest.target
    return f"Fight {count if count > 1 else 'a'} {_plural(count, 'boss', 'bosses')}."


def _describe_boss_win(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Deal {quest.target:,} damage in boss fights you go on to win."
    count = quest.target
    return f"Win {count if count > 1 else 'a'} {_plural(count, 'boss fight')}."


def _describe_royale_played(quest: Quest) -> str:
    count = quest.target
    matches = _plural(count, "Grand Line Royale match", "Grand Line Royale matches")
    text = f"Play {count} {matches}{_in_war(quest)}"
    conditions = []
    if quest.max_place:
        conditions.append(f"finishing in the {_places(quest)}")
    if quest.min_rounds:
        conditions.append(f"lasting at least {quest.min_rounds} rounds")
    if conditions:
        text += f", {' and '.join(conditions)}"
    return f"{text}."


def _describe_royale_win(quest: Quest) -> str:
    count = quest.target
    matches = _plural(count, "Grand Line Royale match", "Grand Line Royale matches")
    return f"Win {count} {matches}{_in_war(quest)}."


def _describe_royale_kill(quest: Quest) -> str:
    count = quest.target
    return f"Get {count} {_plural(count, 'kill')} in Grand Line Royale{_in_war(quest)}."


def _describe_royale_chest(quest: Quest) -> str:
    count = quest.target
    return f"Open {count} {_plural(count, 'chest')} in Grand Line Royale{_in_war(quest)}."


def _describe_royale_bounty(quest: Quest) -> str:
    count = quest.target
    return f"Claim {count} {_plural(count, 'bounty', 'bounties')} in Grand Line Royale{_in_war(quest)}."


def _describe_advent_open(quest: Quest) -> str:
    count = quest.target
    when = " on the day it opens" if quest.on_time else ""
    return f"Open {count} {_plural(count, 'door')} of the advent calendar{when}."


def _describe_advent_complete(quest: Quest) -> str:
    return "Open every door of the advent calendar."


def _describe_santa_join(quest: Quest) -> str:
    return "Sign up for the Secret Santa."


def _describe_santa_wish(quest: Quest) -> str:
    count = quest.target
    return f"Fill {count} {_plural(count, 'slot')} of your Secret Santa wishlist."


def _describe_santa_gift(quest: Quest) -> str:
    if _has_treasure_filter(quest):
        return f"Fill a Secret Santa parcel with {_treasures(quest, quest.target)}."
    count = quest.target
    return f"Fill {count} Secret Santa {_plural(count, 'parcel')}."


def _describe_santa_open(quest: Quest) -> str:
    return "Open the Secret Santa parcel somebody wrapped for you."


def _describe_sleigh_give(quest: Quest) -> str:
    return f"Put {_treasures(quest, quest.target)} in the sleigh."


def _describe_sleigh_full(quest: Quest) -> str:
    return "Be one of the players who filled the sleigh."


def _describe_crew_join(quest: Quest) -> str:
    return "Pick a crew in /player settings."


def _describe_in_crew(quest: Quest) -> str:
    return "Be flying a crew's colours."


def _describe_crew_points(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Bring your crew {quest.target:,} war points."
    return f"Score war points for your crew{_times(quest.target)}."


def _describe_crew_rank(quest: Quest) -> str:
    return f"Be in the {_places(quest)} of the running crew war's contributors."


def _describe_crew_war_win(quest: Quest) -> str:
    return "Be in the crew that wins the war."


def _describe_hunt_stone(quest: Quest) -> str:
    count = quest.target
    who = " for your crew" if quest.for_crew else ""
    return f"Claim {count if count > 1 else 'a'} {_plural(count, 'poneglyph')}{who}."


def _describe_hunt_complete(quest: Quest) -> str:
    count = quest.target
    who = " run between crews" if quest.for_crew else ""
    return f"Finish {count if count > 1 else 'a'} {_plural(count, 'hunt')}{who}."


def _describe_bounty_claim(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Collect {_berries(quest.target)} of bounties."
    count = quest.target
    treasures = _plural(count, settings.collectible_name, settings.plural_collectible_name)
    return f"Be the first to catch {count if count > 1 else 'a'} wanted {treasures}."


def _describe_achievement_unlock(quest: Quest) -> str:
    count = quest.target
    category = quest.achievement_category.name if quest.achievement_category_id else ""
    where = f" in the {category} category" if category else ""
    return f"Unlock {count} {_plural(count, 'achievement')}{where}."


def _describe_event_shop_buy(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Spend {quest.target:,} of the event's own currency in its shop."
    if quest.merchant_item_id and quest.merchant_item:
        return f"Buy {quest.merchant_item.name} from the event shop{_times(quest.target)}."
    count = quest.target
    return f"Buy {count} {_plural(count, 'thing')} from the event shop."


def _describe_augment(quest: Quest) -> str:
    return f"Augment {_treasures(quest, quest.target)}."


def _describe_collectible_buy(quest: Quest) -> str:
    if quest.measure == Measure.AMOUNT:
        return f"Spend {_berries(quest.target)} on collectibles."
    count = quest.target
    return f"Buy {count} {_plural(count, 'collectible')}."


def _describe_vote(quest: Quest) -> str:
    return f"Vote for the bot{_times(quest.target)}."


TYPES: dict[str, TypeDefinition] = {
    definition.type: definition
    for definition in (
        TypeDefinition(
            QuestType.CATCH,
            frozenset({Event.CATCH}),
            TREASURE_FILTERS + ("main_server_only", "max_catch_seconds"),
            "Number of catches",
            "Counts the treasures the player catches themselves when they spawn.",
            _describe_catch,
        ),
        TypeDefinition(
            QuestType.OBTAIN,
            frozenset({Event.CATCH, Event.OBTAIN}),
            TREASURE_FILTERS + ("main_server_only",),
            "Number of treasures obtained",
            "Counts the treasures the player gets in any way: catches, trades, packs, crafts, rewards...",
            _describe_obtain,
        ),
        TypeDefinition(
            QuestType.COMMAND,
            frozenset({Event.COMMAND}),
            ("command_name", "require_command_effect", "main_server_only"),
            "Number of uses",
            'Counts the uses of one slash command, like "treasures list" to open the inventory.',
            _describe_command,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.TRADE,
            frozenset({Event.TRADE}),
            (
                "partner_discord_id",
                "with_friend",
                "min_currency",
                "must_receive_treasure",
                "ball",
                "special",
                "any_special",
            ),
            "Number of trades",
            "Counts completed trades. The treasure filters apply to what the player receives.",
            _describe_trade,
        ),
        TypeDefinition(
            QuestType.TRADE_TREASURES,
            frozenset({Event.TRADE}),
            ("in_one_trade", "partner_discord_id", "with_friend"),
            "Number of treasures exchanged",
            "Counts the treasures changing hands in the player's trades, given and received. A trade where only "
            "one side gives something is a gift and doesn't count.",
            _describe_trade_treasures,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.GIVE_TREASURES,
            frozenset({Event.GIFT}),
            TREASURE_FILTERS + ("partner_discord_id", "with_friend", "main_server_only"),
            "Number of treasures given",
            "Counts the treasures the player gives away with the give command. Set a partner to ask for a present "
            "to one person in particular.",
            _describe_give_treasures,
        ),
        TypeDefinition(
            QuestType.FRIEND,
            frozenset({Event.FRIEND}),
            ("partner_discord_id", "with_friend"),
            "Number of new friends",
            "Counts the friendships made during the event, not the ones the player already had.",
            _describe_friend,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.BATTLE_WIN,
            frozenset({Event.BATTLE_WIN}),
            ("max_lost",),
            "Number of battles won",
            "Counts the battles the player wins. Set the treasures lost at most to 0 to ask for a flawless win; "
            "a forfeit always counts as one loss, so a fight that never reached its end is never flawless.",
            _describe_battle,
            integration=BATTLES,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.GIVE_CURRENCY,
            frozenset({Event.CURRENCY_SENT}),
            ("partner_discord_id", "with_friend", "min_currency"),
            "Number of gifts, or berries given",
            "Counts the berries the player gives away with the give command.",
            _describe_give,
            measures=BERRY_MEASURES,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.RECEIVE_CURRENCY,
            frozenset({Event.CURRENCY_RECEIVED}),
            ("partner_discord_id", "with_friend", "min_currency"),
            "Number of gifts, or berries received",
            "Counts the berries the player receives from someone, a player or an admin.",
            _describe_receive,
            measures=BERRY_MEASURES,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.CATCH_CURRENCY,
            frozenset({Event.CATCH_REWARD}),
            TREASURE_FILTERS + ("main_server_only",),
            "Number of catches with berries, or berries earned",
            "Counts the times a catch also gives berries, or how many berries those catches gave.",
            _describe_catch_currency,
            measures=BERRY_MEASURES,
        ),
        TypeDefinition(
            QuestType.OWN_TREASURES,
            frozenset({Event.CATCH, Event.OBTAIN}),
            TREASURE_FILTERS + ("tier_level",),
            "Number owned",
            "Counts what the player has in their collection right now, not what they just did: "
            '"own 10 treasures of T50 or rarer". Checked again every time they get one. A craft type asks for '
            "collector cards, which are treasures wearing that craft's own special.",
            _describe_own,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.CURRENCY_STREAK,
            frozenset({Event.CURRENCY_STREAK}),
            ("main_server_only",),
            "Days in a row",
            "Counts the streak of daily berry claims the player is on, not how many times they claimed. "
            "A streak that breaks starts the count again.",
            _describe_currency_streak,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.PACK_STREAK,
            frozenset({Event.PACK_STREAK}),
            ("main_server_only",),
            "Days in a row",
            "Counts the streak of daily pack claims the player is on. A streak that breaks starts again.",
            _describe_pack_streak,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.SPEND_CURRENCY,
            frozenset({Event.ECONOMY}),
            (),
            "Number of purchases, or berries spent",
            "Counts every berry the player spends, wherever they spend it.",
            _describe_spend,
            measures=BERRY_MEASURES,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.CRAFT,
            frozenset({Event.CRAFT}),
            ("collector", "tier_level"),
            "Number of crafts",
            'Counts the collector cards the player claims. Pick a craft type ("Craft", "Elemental") to only count '
            "those, and a collector to ask for one card in particular.",
            _describe_craft,
            integration=CRAFTING,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.PACK_BUY,
            frozenset({Event.PACK_BUY}),
            ("item",),
            "Number of packs, or berries spent",
            "Counts the packs the player buys.",
            _describe_pack,
            measures=BERRY_MEASURES,
            integration=PACKS,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.MERCHANT_BUY,
            frozenset({Event.MERCHANT_BUY}),
            ("merchant_item",),
            "Number of purchases, or berries spent",
            "Counts what the player buys from the merchant.",
            _describe_merchant,
            measures=BERRY_MEASURES,
            integration=MERCHANT,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.SHOP_BUY,
            frozenset({Event.SHOP_BUY}),
            TREASURE_FILTERS,
            "Number of purchases, or berries spent",
            "Counts the treasures the player buys from Buggy's shop. Use the rarity filters to ask for treasures "
            "of a given tier.",
            _describe_shop,
            measures=BERRY_MEASURES,
            integration=AUCTION_HOUSE,
        ),
        TypeDefinition(
            QuestType.SELL,
            frozenset({Event.SELL}),
            TREASURE_FILTERS,
            "Number of sales, or berries earned",
            "Counts the treasures the player sells to Buggy. Use the rarity filters to ask for treasures of a "
            "given tier.",
            _describe_sell,
            measures=BERRY_MEASURES,
            integration=AUCTION_HOUSE,
        ),
        TypeDefinition(
            QuestType.AUCTION_CREATE,
            frozenset({Event.AUCTION_CREATE}),
            TREASURE_FILTERS,
            "Number of listings",
            "Counts the treasures the player puts up for auction.",
            _describe_auction_create,
            integration=AUCTION_HOUSE,
        ),
        TypeDefinition(
            QuestType.AUCTION_BID,
            frozenset({Event.AUCTION_BID}),
            ("min_currency",),
            "Number of bids, or berries bid",
            "Counts the bids that went through. Raising a bid already placed doesn't count again.",
            _describe_auction_bid,
            measures=BERRY_MEASURES,
            integration=AUCTION_HOUSE,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.AUCTION_WON,
            frozenset({Event.AUCTION_WON}),
            TREASURE_FILTERS,
            "Number of auctions won, or berries paid",
            "Counts the listings the player wins, when the seller accepts their bid.",
            _describe_auction_won,
            measures=BERRY_MEASURES,
            integration=AUCTION_HOUSE,
        ),
        # -- what a player has, rather than what they just did
        TypeDefinition(
            QuestType.OWN_FAVORITES,
            frozenset({Event.FAVORITE, Event.CATCH, Event.OBTAIN, Event.SYNC}),
            TREASURE_FILTERS,
            "Number of favorites held",
            "Counts the treasures the player has marked as favorites right now, not the times they marked one. "
            "A goal to reach, so unfavoriting one afterwards does not undo the quest.",
            _describe_own_favorites,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.OWN_CURRENCY,
            frozenset({Event.ECONOMY, Event.SYNC}),
            (),
            "Berries held",
            "Counts what the player has in the bank right now. A goal to reach, so spending it afterwards does "
            "not undo the quest.",
            _describe_own_currency,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.COMPLETE_GROUP,
            COLLECTION_EVENTS,
            ("group",),
            "Number of groups completed",
            'Name a group and the goal becomes "own all of it", counted in treasures of that group. Leave it '
            "empty and the goal counts how many whole groups the player has finished.",
            _describe_complete_group,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.COMPLETION,
            COLLECTION_EVENTS,
            (),
            "Completion, in percent",
            "Counts how much of the dex the player owns, in percent, exactly as the completion achievements do. "
            "Above 100 asks for several copies of everything.",
            _describe_completion,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.PLAYTIME,
            COLLECTION_EVENTS,
            ("time_unit",),
            "Time played, in the unit chosen below",
            "Counted from the first treasure the player caught themselves, which is recorded by the achievements "
            "package: without it, nobody has a first catch and this never moves.",
            _describe_playtime,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.LEADERBOARD_RANK,
            frozenset({Event.SYNC}),
            ("max_place",),
            "Leave at 1",
            "Asks the player to reach a place on the berry leaderboard. The place is the one set below, and the "
            "goal stays at 1: either they are in it or they are not. Read only when the player opens the pass, "
            "because working out a place means counting everybody richer than them and berries move constantly "
            "— so a player who climbs the table sees it the next time they run /pass view.",
            _describe_leaderboard_rank,
            filters_instances=False,
            knows_server=False,
        ),
        # -- deeds the bus already carried and nothing listened to
        TypeDefinition(
            QuestType.FAVORITE,
            frozenset({Event.FAVORITE}),
            TREASURE_FILTERS,
            "Number of treasures favorited",
            "Counts the treasures the player marks as a favorite. Unmarking one is not counted, in either "
            "direction.",
            _describe_favorite,
        ),
        TypeDefinition(
            QuestType.ACTIVITY,
            frozenset({Event.ACTIVITY}),
            ("main_server_only",),
            "Number of times",
            "Counts that the player turned up at all, at most once an hour, and only for the commands no other "
            'quest is watching. Set it to 1 with a daily reset for a "come and play today" quest — but a '
            "command another quest asks about is dispatched as that command and never as activity, so a player "
            "who only runs those will not move this. A daily claim quest is the safer way to ask the same thing.",
            _describe_activity,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.PACK_WEEKLY,
            frozenset({Event.PACK_WEEKLY}),
            ("main_server_only",),
            "Number of weekly packs",
            "Counts the weekly pack claims. There is one a week, so a goal above 1 needs a pass that runs for "
            "that many weeks.",
            _describe_pack_weekly,
            integration=PACKS,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.AUCTION_SOLD,
            frozenset({Event.AUCTION_SOLD}),
            TREASURE_FILTERS,
            "Number of sales, or berries earned",
            "Counts the listings of the player that actually sold, when they accept an offer. Listing a treasure "
            "is free, so this is the one that asks for a sale rather than for an advert.",
            _describe_auction_sold,
            measures=BERRY_MEASURES,
            integration=AUCTION_HOUSE,
        ),
        TypeDefinition(
            QuestType.TRADE_PARTNERS,
            frozenset({Event.TRADE}),
            ("min_currency", "must_receive_treasure"),
            "Number of different players",
            "Counts the people the player trades with, each one only once however many trades they do together. "
            "The one quest type that cannot be farmed with a friend.",
            _describe_trade_partners,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.GIVE_PARTNERS,
            frozenset({Event.GIFT}),
            TREASURE_FILTERS,
            "Number of different players",
            "Counts the people the player gives treasures to, each one only once however much they are given.",
            _describe_give_partners,
        ),
        TypeDefinition(
            QuestType.BATTLE_PLAYED,
            frozenset({Event.BATTLE_PLAYED}),
            ("max_lost",),
            "Number of battles played",
            "Counts the battles the player takes part in, won or lost, so a small deck is not shut out of the "
            "pass. Set the treasures lost at most to ask for a clean fight; a battle given up counts as one "
            "loss for both players, so forfeiting is never a clean fight.",
            _describe_battle_played,
            integration=BATTLES,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.BOSS_PLAYED,
            frozenset({Event.BOSS_PLAYED}),
            (),
            "Number of boss fights, or damage dealt",
            "Counts the boss fights the player picked in at least once, whether the boss killed them or not. "
            'With "total amount" the goal is the damage they dealt over the fight instead.',
            _describe_boss_played,
            measures=BERRY_MEASURES,
            integration=BOSS,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.BOSS_WIN,
            frozenset({Event.BOSS_WIN}),
            (),
            "Number of boss fights won, or damage dealt",
            "Counts the boss fights the player was named the winner of. One player wins a boss, so this is a "
            "quest for a tier nobody is expected to finish, or for a hidden one.",
            _describe_boss_win,
            measures=BERRY_MEASURES,
            integration=BOSS,
            filters_instances=False,
            knows_server=False,
        ),
        # -- Grand Line Royale, reported by the other bot over the bridge
        TypeDefinition(
            QuestType.ROYALE_PLAYED,
            frozenset(ROYALE_PAIRS[QuestType.ROYALE_PLAYED]),
            ROYALE_FILTERS + ("max_place", "min_rounds"),
            "Number of matches",
            "Counts the Grand Line Royale matches the player finished, as the royale bot reports them. The place "
            "and the rounds are how a quest asks for a podium or for a long survival instead of just turning up.",
            _describe_royale_played,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.ROYALE_WIN,
            frozenset(ROYALE_PAIRS[QuestType.ROYALE_WIN]),
            ROYALE_FILTERS,
            "Number of wins",
            "Counts the Grand Line Royale matches the player won.",
            _describe_royale_win,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.ROYALE_KILL,
            frozenset(ROYALE_PAIRS[QuestType.ROYALE_KILL]),
            ROYALE_FILTERS,
            "Number of kills",
            "Counts the kills the player made in Grand Line Royale, one by one.",
            _describe_royale_kill,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.ROYALE_CHEST,
            frozenset(ROYALE_PAIRS[QuestType.ROYALE_CHEST]),
            ROYALE_FILTERS,
            "Number of chests",
            "Counts the chests the player opened in Grand Line Royale, one by one.",
            _describe_royale_chest,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.ROYALE_BOUNTY,
            frozenset(ROYALE_PAIRS[QuestType.ROYALE_BOUNTY]),
            ROYALE_FILTERS,
            "Number of bounties",
            "Counts the bounties the player claimed in Grand Line Royale, one by one.",
            _describe_royale_bounty,
            filters_instances=False,
        ),
        # -- the advent calendar
        TypeDefinition(
            QuestType.ADVENT_OPEN,
            frozenset({Event.ADVENT_OPEN}),
            ("on_time",),
            "Number of doors",
            "Counts the doors the player opens. A door bought open afterwards with /advent catchup counts too "
            'unless "only on the day" is ticked, which is what tells a player who kept up from one who paid.',
            _describe_advent_open,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.ADVENT_COMPLETE,
            frozenset({Event.ADVENT_COMPLETE}),
            (),
            "Leave at 1",
            "Completed when the player has opened every door of the calendar, however they got there.",
            _describe_advent_complete,
            filters_instances=False,
        ),
        # -- the Secret Santa
        TypeDefinition(
            QuestType.SANTA_JOIN,
            frozenset({Event.SANTA_JOIN}),
            (),
            "Leave at 1",
            "Completed when the player signs up for the Secret Santa.",
            _describe_santa_join,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.SANTA_WISH,
            frozenset({Event.SANTA_WISH}),
            (),
            "Number of slots filled",
            "Counts how much of the wishlist is written, not how many times the player edited it: changing the "
            "same slot three times is still one wish.",
            _describe_santa_wish,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.SANTA_GIFT,
            frozenset({Event.SANTA_GIFT}),
            TREASURE_FILTERS,
            "Number of parcels",
            "Counts the parcels the player fills. A parcel paid for holds no card yet, so a quest naming a "
            "treasure or a rarity only counts a parcel filled with a real card — which is how to ask for a "
            "present worth opening instead of the cheapest way out.",
            _describe_santa_gift,
        ),
        TypeDefinition(
            QuestType.SANTA_OPEN,
            frozenset({Event.SANTA_OPEN}),
            TREASURE_FILTERS,
            "Leave at 1",
            "Completed when the player opens the parcel wrapped for them. There is deliberately no quest for "
            "receiving one: a player must never learn when or how their parcel was filled, and a quest "
            "completing at that moment would tell them.",
            _describe_santa_open,
        ),
        # -- the sleigh
        TypeDefinition(
            QuestType.SLEIGH_GIVE,
            frozenset({Event.SLEIGH_GIVE}),
            TREASURE_FILTERS,
            "Number of treasures given",
            "Counts the treasures the player puts in the sleigh. The rarity filters are how a sleigh quest asks "
            "for something better than the cheapest card in the collection.",
            _describe_sleigh_give,
        ),
        TypeDefinition(
            QuestType.SLEIGH_FULL,
            frozenset({Event.SLEIGH_FULL}),
            (),
            "Leave at 1",
            "Completed for everybody who put something in, the day the sleigh fills up. The one collective goal "
            "in the bot: it is not about what the player did but about what the server managed together.",
            _describe_sleigh_full,
            filters_instances=False,
            knows_server=False,
        ),
        # -- crews
        TypeDefinition(
            QuestType.CREW_JOIN,
            frozenset({Event.CREW_JOIN}),
            (),
            "Leave at 1",
            "Completed when the player picks a crew in /player settings. Changing crew counts again; picking the "
            "one they already fly does not.",
            _describe_crew_join,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.IN_CREW,
            frozenset({Event.CREW_JOIN, Event.CREW_POINTS, Event.SYNC}),
            (),
            "Leave at 1",
            "Asks the player to be in a crew, checked rather than counted: somebody who leaves their crew loses "
            "it again until they claim it.",
            _describe_in_crew,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.CREW_POINTS,
            frozenset({Event.CREW_POINTS}),
            (),
            "Number of deeds, or points scored",
            "Counts the war points the player brings their crew. Nothing scores without a war running, a crew to "
            "fly for, and a rule in the panel for the deed — which is exactly what the crew war already says.",
            _describe_crew_points,
            measures=BERRY_MEASURES,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.CREW_RANK,
            frozenset({Event.CREW_POINTS, Event.SYNC}),
            ("max_place",),
            "Leave at 1",
            "Asks the player to be among the top contributors of the running war, at the place set below. "
            "Checked when they score and when they open the pass, and players tied on points share a place.",
            _describe_crew_rank,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.CREW_WAR_WIN,
            frozenset({Event.CREW_WAR_WIN}),
            (),
            "Leave at 1",
            "Completed for every member of the winning crew when a war is settled. A war ends once, so this "
            "belongs on a pass that outlives it, or in its final reward.",
            _describe_crew_war_win,
            filters_instances=False,
            knows_server=False,
        ),
        # -- poneglyph hunts
        TypeDefinition(
            QuestType.HUNT_STONE,
            frozenset({Event.HUNT_STONE}),
            ("for_crew",),
            "Number of poneglyphs",
            "Counts the stones the player hands a set in for. In a hunt run between crews only the first member "
            'to hand a set in claims it, so "only for a crew" asks for that one.',
            _describe_hunt_stone,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.HUNT_COMPLETE,
            frozenset({Event.HUNT_COMPLETE}),
            ("for_crew",),
            "Number of hunts",
            "Counts the hunts finished for the player: their own, and the crew hunts they were paid a share of. "
            "A crew hunt is finished by the crew, so every member who shares the reward gets it.",
            _describe_hunt_complete,
            filters_instances=False,
        ),
        # -- wanted posters
        TypeDefinition(
            QuestType.BOUNTY_CLAIM,
            frozenset({Event.BOUNTY_CLAIM}),
            TREASURE_FILTERS,
            "Number of posters, or berries collected",
            "Counts the wanted posters the player took. Only the first catch of a live bounty collects it, so "
            "this is a race: a good hidden quest, a cruel mandatory one.",
            _describe_bounty_claim,
            measures=BERRY_MEASURES,
        ),
        # -- the rest of the panel's own packages
        TypeDefinition(
            QuestType.ACHIEVEMENT_UNLOCK,
            frozenset({Event.ACHIEVEMENT_UNLOCK}),
            ("achievement_category",),
            "Number of achievements",
            "Counts the achievements the player unlocks while the pass runs, not the ones they already had.",
            _describe_achievement_unlock,
            filters_instances=False,
            knows_server=False,
        ),
        TypeDefinition(
            QuestType.EVENT_SHOP_BUY,
            frozenset({Event.EVENT_SHOP_BUY}),
            ("merchant_item",),
            "Number of purchases, or event currency spent",
            "Counts what the player buys with an event pass's own currency rather than with berries. The same "
            "purchase is also counted by the merchant quests, which count the ones paid in berries too.",
            _describe_event_shop_buy,
            measures=BERRY_MEASURES,
            integration=MERCHANT,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.AUGMENT,
            frozenset({Event.AUGMENT}),
            TREASURE_FILTERS,
            "Number of treasures augmented",
            "Counts the treasures the player augments, with the stats they come out with: a minimum bonus asks "
            "for an augment that actually worked, not for the money spent trying.",
            _describe_augment,
            integration=AUGMENT,
        ),
        TypeDefinition(
            QuestType.COLLECTIBLE_BUY,
            frozenset({Event.COLLECTIBLE_BUY}),
            (),
            "Number of collectibles, or berries spent",
            "Counts the collectibles the player claims.",
            _describe_collectible_buy,
            measures=BERRY_MEASURES,
            integration=COLLECTIBLES,
            filters_instances=False,
        ),
        TypeDefinition(
            QuestType.VOTE,
            frozenset({Event.VOTE}),
            (),
            "Number of votes",
            "Counts the votes the player casts for the bot on Top.gg. A vote is allowed every twelve hours, so "
            "this makes a cheap daily quest that pays the dex back.",
            _describe_vote,
            integration=VOTE,
            filters_instances=False,
            knows_server=False,
        ),
    )
}

PARAMETER_FIELDS = tuple(dict.fromkeys(name for definition in TYPES.values() for name in definition.fields))


def goal_text(quest: Quest) -> str:
    definition = TYPES.get(quest.type)
    return definition.describe(quest) if definition else ""


def player_description(quest: Quest) -> str:
    """
    What a player reads as the goal: the description written by hand, or the one generated from the settings,
    plus the one thing neither of them can say — that the quest is not theirs alone.
    """
    text = quest.description or goal_text(quest)
    if quest.shared_with_crew:
        text = f"{text} Counted for your whole crew, together."
    return text
