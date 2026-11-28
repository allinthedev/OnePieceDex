"""
Makes the quests of an event pass progress, completes them and tells players what they can claim.

Quests only progress inside the bot process, once `engine.configure` was called, and only while their pass is
running: nothing done before the pass starts or after it ends is ever counted. The engine listens to
`ballsdex.core.game_events.bus`, like the achievement engine, so a package dispatching an action doesn't know or
care that event passes exist.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from achievement_app.models import DAYS_PER_UNIT, PlayerAchievementStats
from django.db.models import F, Q
from django.db.models.expressions import RawSQL
from django.utils import timezone

from ballsdex.core.game_events import Event, EventContext, normalize_command
from bd_models.models import BallInstance, Friendship, Player, balls, groups, special_filter
from settings.models import settings

from .access import has_early_access, progress_gate
from .models import (
    CrewQuest,
    EventPass,
    Measure,
    PassTier,
    PlayerPass,
    PlayerQuest,
    Quest,
    QuestType,
    Reset,
    Reward,
    Source,
)
from .rewards import grant, reward_preview
from .state import REWARD_LINES, _finished, _pass_progress, finished_tier_ids, period_of, unlocked_tier_ids
from .types import TYPES, _has_treasure_filter

if TYPE_CHECKING:
    from datetime import datetime

    from ballsdex.core.bot import BallsDexBot

    from .notifications import PassNotifier

__all__ = ("engine",)

log = logging.getLogger("eventpass")


@dataclass
class Increment:
    amount: int


@dataclass
class Absolute:
    value: int


@dataclass
class Distinct:
    """
    One more person counted, for the quests asking for different players rather than more actions.

    The engine keeps the people already counted on the row, so trading with the same friend ten times is
    still one. The key is a Discord ID.
    """

    key: int


# the quests that read what a player has instead of counting what they just did. They are not evaluated from the
# event at all: the event only says "look again", and the answer always comes from the database, which is far
# easier to trust than a tally kept in step with catches, trades, gifts and sales.
STATE_TYPES = frozenset(
    {
        QuestType.OWN_TREASURES,
        QuestType.OWN_FAVORITES,
        QuestType.OWN_CURRENCY,
        QuestType.COMPLETE_GROUP,
        QuestType.COMPLETION,
        QuestType.PLAYTIME,
        QuestType.IN_CREW,
        QuestType.CREW_RANK,
        QuestType.LEADERBOARD_RANK,
    }
)

# a deed done in a crew war raid. Royale reports those under events of their own, and a quest says which of the
# two families it means, so a kill in a war never feeds a quest about ordinary matches or the other way round.
WAR_EVENTS = frozenset(
    {
        Event.ROYALE_WAR_PLAYED,
        Event.ROYALE_WAR_WIN,
        Event.ROYALE_WAR_KILL,
        Event.ROYALE_WAR_CHEST,
        Event.ROYALE_WAR_BOUNTY,
    }
)


@dataclass
class Completion:
    """
    A quest a player just finished, and what they got if it was given right away.
    """

    quest: Quest
    period: str
    auto_claimed: bool = False
    summary: str = ""


@dataclass
class TierDone:
    """
    A tier a player just finished. Worth its own message: the tier is the milestone, not whichever quest happened
    to close it.
    """

    tier: PassTier
    reward: str = ""


class EventPassEngine:
    CACHE_TTL = 60

    def __init__(self):
        self.bot: BallsDexBot | None = None
        self.notifier: PassNotifier | None = None
        self._quests: list[Quest] = []
        self._loaded_at = 0.0
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def configure(self, bot: BallsDexBot | None, notifier: PassNotifier | None):
        self.bot = bot
        self.notifier = notifier
        self._loaded_at = 0.0

    # -- entry points ------------------------------------------------------------------------------------------------

    async def handle_event(self, player_id: int, event: Event, context: EventContext, channel_id: int | None):
        """
        Subscriber of the game event bus.
        """
        if self.bot is None:
            return
        now = timezone.now()
        candidates = [
            quest
            for quest in await self.active_quests()
            if quest.type in TYPES and self._listens(quest, event) and self._in_window(quest, now)
        ]
        if not candidates:
            return
        try:
            async with self._locks[player_id]:
                completions = await self._process(player_id, candidates, context, event, channel_id, now)
        except Exception:
            log.exception("Failed to progress the quests of player %s for %s", player_id, event)
            return
        if not completions:
            return
        tiers = await self._tiers_just_finished(player_id, completions)
        if self.notifier:
            await self.notifier.add(player_id, completions, channel_id, tiers)

    @staticmethod
    async def _tiers_just_finished(player_id: int, completions: list[Completion]) -> list[TierDone]:
        """
        The tiers these completions closed: finished now, and not finished without them.

        Asking both questions is what tells a milestone from a tier that was already done, and it stays right when
        several quests land at once. Nothing extra is written down for it.
        """
        done: list[TierDone] = []
        just_completed = {completion.quest.pk for completion in completions}
        for event_pass in {completion.quest.event_pass for completion in completions}:
            completed_ids, required = await _pass_progress(player_id, event_pass)
            newly = _finished(required, completed_ids) - _finished(required, completed_ids - just_completed)
            if not newly:
                continue
            tiers = PassTier.objects.filter(pk__in=newly).select_related("event_pass").prefetch_related(REWARD_LINES)
            async for tier in tiers:
                done.append(TierDone(tier=tier, reward=reward_preview(tier.reward) if tier.reward_id else ""))
        return done

    async def sync_player(self, player_id: int) -> None:
        """
        Refresh every quest of this player that reads a state: what they own, hold, have completed, how long
        they have played, where they rank.

        Quests counting actions cannot be refreshed — a catch is only ever counted when it happens — so this
        is cheap enough to run whenever a player opens their pass, which is where a ranking or a berry total
        is most likely to have moved without them doing anything the bus saw.
        """
        await self.handle_event(player_id, Event.SYNC, EventContext(), None)

    async def listens_to_command(self, name: str) -> bool:
        return any(
            quest.type == QuestType.COMMAND and normalize_command(quest.command_name) == name
            for quest in await self.active_quests()
        )

    async def active_quests(self) -> list[Quest]:
        """
        Every quest of every active pass, cached for a minute so the bot doesn't query them on each action.
        """
        if time.monotonic() - self._loaded_at > self.CACHE_TTL:
            self._quests = [
                quest
                async for quest in Quest.objects.filter(enabled=True, event_pass__status=EventPass.Status.ACTIVE)
                .select_related("event_pass", "tier", "reward", "ball", "special", "group", "item", "merchant_item")
                .select_related("collector", "tier_level")
                .prefetch_related(REWARD_LINES, "after")
            ]
            self._loaded_at = time.monotonic()
        return self._quests

    def invalidate(self):
        self._loaded_at = 0.0

    # -- processing --------------------------------------------------------------------------------------------------

    @staticmethod
    def _listens(quest: Quest, event: Event) -> bool:
        """
        Whether this quest has anything to say about this event.

        Its type decides, with one addition: a quest whose counter belongs to a crew, or whose target was drawn
        for the player, has to be caught up when they open their pass. Neither moved because of anything they
        did, so neither would ever be noticed without a refresh.
        """
        if event in TYPES[quest.type].events:
            return True
        return event == Event.SYNC and (quest.shared_with_crew or quest.draw_treasure)

    @staticmethod
    def _in_window(quest: Quest, now: datetime) -> bool:
        starts_at, ends_at = quest.window()
        early = quest.event_pass.early_starts_at
        if quest.starts_at is None and early is not None:
            # a quest that follows the pass's dates opens with its early start too; who may actually play
            # before the public start is decided per player, once the quest is a candidate
            starts_at = min(starts_at, early)
        return quest.event_pass.window_open(now) and starts_at <= now <= ends_at

    async def _process(
        self,
        player_id: int,
        candidates: list[Quest],
        context: EventContext,
        event: Event,
        channel_id: int | None,
        now: datetime,
    ) -> list[Completion]:
        # a locked tier holds its quests: they only start moving once the player unlocks it
        by_pass: dict[int, list[Quest]] = defaultdict(list)
        for quest in candidates:
            by_pass[quest.event_pass_id].append(quest)
        allowed: list[Quest] = []
        for quests in by_pass.values():
            event_pass = quests[0].event_pass
            # a pass reserved to a role or to newcomers only moves for the players taking part in it
            once_allowed, repeat_allowed = await progress_gate(player_id, event_pass)
            if not once_allowed and not repeat_allowed:
                continue
            # before the pass opens for everybody, only the players let in early play
            if event_pass.open_early(now) and not await has_early_access(player_id, event_pass):
                continue
            if any(quest.tier_id for quest in quests):
                unlocked = await unlocked_tier_ids(player_id, event_pass, now)
            else:
                unlocked = set()
            allowed.extend(
                quest
                for quest in quests
                if (quest.tier_id is None or quest.tier_id in unlocked)
                and (repeat_allowed if quest.reset != Reset.NONE else once_allowed)
            )
        if not allowed:
            return []
        allowed = await self._chains_open(player_id, allowed)
        if not allowed:
            return []

        periods = {quest.pk: period_of(quest, now) for quest in allowed}
        rows = {
            (row.quest_id, row.period): row
            async for row in PlayerQuest.objects.filter(
                player_id=player_id, quest_id__in=[quest.pk for quest in allowed]
            )
        }

        completions: list[Completion] = []
        for quest in allowed:
            period = periods[quest.pk]
            row = rows.get((quest.pk, period))
            if row is not None and row.completed_at:
                continue
            if quest.draw_treasure:
                # the target has to exist before anything can be matched against it, so the row is written now
                # rather than when the first deed lands
                row = await self._drawn(player_id, quest, row, period)
                rows[(quest.pk, period)] = row
                if row.drawn_ball_id is None:
                    continue
            if not self._matches(quest, context, event):
                continue
            if quest.draw_treasure and event != Event.SYNC:
                if not any(instance.ball_id == row.drawn_ball_id for instance in context.instances):
                    continue
            if quest.with_friend and not await self._with_a_friend(player_id, context):
                continue
            if quest.type in STATE_TYPES:
                # these ask what the player has, not what they just did, so they are read rather than evaluated
                result = await self._state(player_id, quest, row)
            elif event == Event.SYNC:
                # a refresh is not a deed: it only re-reads what is already written down, which for a quest
                # counting actions is nothing at all
                result = None
            else:
                result = self._evaluate(quest, context, event)
            if quest.shared_with_crew:
                result = await self._shared(quest, player_id, period, result, now)
            if result is None:
                continue
            completion = await self._apply(quest, player_id, row, period, result, now, context, channel_id)
            if completion is not None:
                completions.append(completion)
        return completions

    @staticmethod
    async def _chains_open(player_id: int, quests: list[Quest]) -> list[Quest]:
        """
        Drop the quests still waiting on other quests of the same pass.

        One query per pass holding a chained quest, and none at all for a pass with no chains — which is every
        pass built so far, so this costs nothing until somebody uses it.
        """
        chained = [quest for quest in quests if quest.waits_for]
        if not chained:
            return quests
        done: dict[int, set[int]] = {}
        for pass_id in {quest.event_pass_id for quest in chained}:
            done[pass_id] = {
                quest_id
                async for quest_id in PlayerQuest.objects.filter(
                    player_id=player_id, quest__event_pass_id=pass_id, completed_at__isnull=False
                ).values_list("quest_id", flat=True)
            }
        return [quest for quest in quests if quest.chain_open(done.get(quest.event_pass_id, set()))]

    @staticmethod
    def _draw(quest: Quest) -> int | None:
        """
        One treasure out of the pool the quest's filters describe, drawn flat.

        Flat and not weighted by rarity on purpose: a weighted draw would hand almost everybody one of the
        commonest treasures in the pool, which is not a target, it is a formality. Read from the treasure cache,
        so drawing costs no query.
        """
        group = groups.get(quest.group_id) if quest.group_id else None
        if quest.group_id and group is None:
            return None
        pool = [
            ball.pk
            for ball in balls.values()
            if ball.enabled
            and (group is None or ball.pk in group._ball_ids)
            and (quest.min_rarity is None or ball.rarity >= quest.min_rarity)
            and (quest.max_rarity is None or ball.rarity <= quest.max_rarity)
        ]
        return random.choice(pool) if pool else None

    async def _drawn(self, player_id: int, quest: Quest, row: PlayerQuest | None, period: str) -> PlayerQuest:
        """
        This player's own target for a quest that draws one, drawing it the first time it is needed.

        The write only lands while the row still has no target, and the value is read back from the database
        rather than trusted: two deeds landing together must not leave the player with two different targets,
        and whichever draw won is the one they keep.
        """
        if row is None:
            row, _ = await PlayerQuest.objects.aget_or_create(player_id=player_id, quest_id=quest.pk, period=period)
        if row.drawn_ball_id is not None:
            return row
        drawn = self._draw(quest)
        if drawn is None:
            log.warning("Quest %s draws a target but nothing matches its filters", quest.pk)
            return row
        await PlayerQuest.objects.filter(pk=row.pk, drawn_ball__isnull=True).aupdate(drawn_ball_id=drawn)
        row.drawn_ball_id = (
            await PlayerQuest.objects.filter(pk=row.pk).values_list("drawn_ball_id", flat=True).afirst()
        )
        return row

    async def _shared(
        self, quest: Quest, player_id: int, period: str, result: Increment | Absolute | Distinct | None, now: datetime
    ) -> Absolute | None:
        """
        Add a deed to the crew's counter and hand back where the crew now stands.

        The crew's row is the truth and the player's own row mirrors it, which is what lets everything else —
        claiming, periods, tier completion — work exactly as it does for a quest nobody shares. The counter is
        moved with an `F()` expression, so two members scoring at the same moment both count.

        A player with no crew moves nothing and finishes nothing: there is no counter for them to be part of.
        """
        crew_id = await self._crew_id(player_id)
        if crew_id is None:
            return None
        shared, _ = await CrewQuest.objects.aget_or_create(quest_id=quest.pk, crew_id=crew_id, period=period)
        total = shared.progress
        if isinstance(result, Increment) and result.amount:
            await CrewQuest.objects.filter(pk=shared.pk).aupdate(progress=F("progress") + result.amount)
            total = (
                await CrewQuest.objects.filter(pk=shared.pk).values_list("progress", flat=True).afirst()
            ) or 0
        if total >= quest.goal and shared.completed_at is None:
            await CrewQuest.objects.filter(pk=shared.pk, completed_at__isnull=True).aupdate(completed_at=now)
        return Absolute(total) if total else None

    @staticmethod
    async def _with_a_friend(player_id: int, context: EventContext) -> bool:
        """
        Whether the other player in this action is on the player's friend list.

        An action with nobody on the other side never counts for such a quest: there is no friend to have done it
        with.
        """
        partner = context.partner_discord_id
        if not partner:
            return False
        return await Friendship.objects.filter(
            Q(player1_id=player_id, player2__discord_id=partner) | Q(player2_id=player_id, player1__discord_id=partner)
        ).aexists()

    async def _state(self, player_id: int, quest: Quest, row: PlayerQuest | None = None) -> Absolute | None:
        """
        Where the player stands on a quest that reads a state: what they own, hold, have completed or rank at.

        Always an `Absolute`, so the best they ever reached is what counts — a quest about holding berries is
        not undone by spending them afterwards, and one about a ranking is not lost to somebody overtaking
        them an hour later. `None` only when the answer cannot be worked out at all.
        """
        match quest.type:
            case QuestType.OWN_TREASURES:
                return Absolute(await self._owned_queryset(player_id, quest, row).acount())

            case QuestType.OWN_FAVORITES:
                owned = self._owned_queryset(player_id, quest).filter(favorite=True)
                return Absolute(await owned.acount())

            case QuestType.OWN_CURRENCY:
                money = await Player.objects.filter(pk=player_id).values_list("money", flat=True).afirst()
                return Absolute(money or 0)

            case QuestType.COMPLETE_GROUP:
                return Absolute(await self._group_progress(player_id, quest))

            case QuestType.COMPLETION:
                # the achievements already decide what completion means, including what above 100% means;
                # imported here rather than at the top so one engine never has to load the other to start
                from achievement_app.engine import completion_percentage

                return Absolute(await completion_percentage(player_id, quest.goal))

            case QuestType.PLAYTIME:
                first_catch = (
                    await PlayerAchievementStats.objects.filter(player_id=player_id)
                    .values_list("first_catch_at", flat=True)
                    .afirst()
                )
                if first_catch is None:
                    return None
                days = (timezone.now() - first_catch).days
                return Absolute(days // DAYS_PER_UNIT.get(quest.time_unit, 1))

            case QuestType.IN_CREW:
                return Absolute(1 if await self._crew_id(player_id) else 0)

            case QuestType.CREW_RANK:
                return Absolute(await self._war_place(player_id, quest.max_place or 1))

            case QuestType.LEADERBOARD_RANK:
                return Absolute(await self._money_place(player_id, quest.max_place or 1))
        return None

    @staticmethod
    def _owned_queryset(player_id: int, quest: Quest, row: PlayerQuest | None = None):
        """
        The treasures a player owns that match the quest's treasure filters.

        Read from the database rather than followed through events: a collection changes through catches,
        trades, gifts and sales, and a total is far easier to trust than a tally kept in step with all of them.
        """
        queryset = BallInstance.objects.filter(player_id=player_id, deleted=False)
        if quest.draw_treasure and row is not None and row.drawn_ball_id:
            # the pool the target was drawn from stops mattering the moment the target exists
            queryset = queryset.filter(ball_id=row.drawn_ball_id)
        elif quest.ball_id:
            queryset = queryset.filter(ball_id=quest.ball_id)
        if quest.tier_level_id:
            # a collector card is a treasure wearing that craft's own special, so asking for the craft is
            # asking for the special it leaves behind. A craft with no special of its own leaves nothing to
            # recognise its cards by, so the quest matches nothing rather than matching the whole collection,
            # which is what no filter at all would quietly mean
            special_id = quest.tier_level.special_id if quest.tier_level else None
            if special_id is None:
                log.warning(
                    "Quest %s asks for the %s craft, which has no special of its own: nothing can be counted",
                    quest.pk,
                    quest.tier_level.name if quest.tier_level else quest.tier_level_id,
                )
                return queryset.none()
            queryset = queryset.filter(special_id=special_id)
        if quest.special_id and quest.cached_special:
            # the bot's own filter, so the "Frame" special picks out the framed treasures here exactly as it
            # does everywhere else rather than looking for a special no treasure ever wears
            queryset = queryset.filter(special_filter(quest.cached_special))
        elif quest.any_special:
            queryset = queryset.filter(special_id__isnull=False)
        if quest.group_id:
            queryset = queryset.filter(ball__groups=quest.group_id)
        if quest.min_rarity is not None:
            queryset = queryset.filter(ball__rarity__gte=quest.min_rarity)
        if quest.max_rarity is not None:
            queryset = queryset.filter(ball__rarity__lte=quest.max_rarity)
        if quest.min_attack_bonus is not None:
            queryset = queryset.filter(attack_bonus__gte=quest.min_attack_bonus)
        if quest.min_health_bonus is not None:
            queryset = queryset.filter(health_bonus__gte=quest.min_health_bonus)
        if quest.hex_contains:
            queryset = queryset.annotate(hex_id=RawSQL("to_hex(ballinstance.id)", ())).filter(
                hex_id__icontains=quest.hex_contains
            )
        return queryset

    @staticmethod
    async def _group_progress(player_id: int, quest: Quest) -> int:
        """
        How far the player is on the groups: distinct treasures of one named group, or whole groups finished.

        One query either way — the player's distinct treasure ids — and the rest is done against the group
        cache, so asking for "how many groups are done" costs no more than asking about one.
        """
        owned = {
            ball_id
            async for ball_id in BallInstance.objects.filter(player_id=player_id, deleted=False)
            .values_list("ball_id", flat=True)
            .distinct()
        }
        if quest.group_id:
            group = groups.get(quest.group_id)
            return len(owned & group._ball_ids) if group else 0
        return sum(1 for group in groups.values() if group._ball_ids and group._ball_ids <= owned)

    @staticmethod
    async def _crew_id(player_id: int) -> int | None:
        """Which crew the player flies for, None when they fly none or crews are not set up."""
        from crew_app.models import CrewMembership

        return await CrewMembership.objects.filter(player_id=player_id).values_list("crew_id", flat=True).afirst()

    @staticmethod
    async def _war_place(player_id: int, wanted: int) -> int:
        """
        1 when the player is at or above `wanted` in the running war's table of contributors, 0 otherwise.

        Players tied on points share a place, so two players on 300 are both second and nobody is pushed out
        of a top ten by a draw they did not lose.
        """
        from crew_app.scoring import live_war, place_of, player_points

        live = await live_war()
        if live is None:
            return 0
        war, _ = live
        points = await player_points(war, player_id)
        if not points:
            return 0
        return 1 if await place_of(war, points) <= wanted else 0

    @staticmethod
    async def _money_place(player_id: int, wanted: int) -> int:
        """1 when the player is in the top `wanted` of the berry leaderboard, 0 otherwise."""
        money = await Player.objects.filter(pk=player_id).values_list("money", flat=True).afirst()
        if not money:
            return 0
        above = await Player.objects.filter(money__gt=money).acount()
        return 1 if above + 1 <= wanted else 0

    def _matches(self, quest: Quest, context: EventContext, event: Event) -> bool:
        """
        The filters that apply to every type: where it happened, who with, and how much it moved.
        """
        event_pass = quest.event_pass
        definition = TYPES.get(quest.type)
        # a type whose events cannot name a server is exempt: a crew war scored by a background task or a
        # collection the player simply has never happened in a guild, and holding them to the main server
        # would turn them off without a word rather than restrict them
        knows_server = definition.knows_server if definition else True
        if knows_server and (quest.main_server_only or event_pass.main_server_only):
            if event_pass.main_server_id is None or context.server_id != event_pass.main_server_id:
                return False
        if quest.partner_discord_id and context.partner_discord_id != quest.partner_discord_id:
            return False
        if quest.min_currency:
            moved = abs(context.amount) or abs(context.price) or context.received_currency
            if moved < quest.min_currency:
                return False
        if definition and definition.filters_instances and context.instances:
            if not any(quest.matches_instance(instance) for instance in context.instances):
                return False
        return True

    def _evaluate(
        self, quest: Quest, context: EventContext, event: Event
    ) -> Increment | Absolute | Distinct | None:
        """
        How much this action moves the quest, `None` when it doesn't count at all.
        """
        match quest.type:
            case QuestType.CATCH | QuestType.OBTAIN | QuestType.AUCTION_CREATE | QuestType.GIVE_TREASURES:
                count = sum(1 for x in context.instances if quest.matches_instance(x) and self._fast_enough(quest, x))
                return Increment(count) if count else None

            case QuestType.SHOP_BUY | QuestType.SELL | QuestType.AUCTION_WON:
                if quest.measure == Measure.AMOUNT:
                    amount = abs(context.price or context.amount)
                    return Increment(amount) if amount else None
                count = sum(1 for x in context.instances if quest.matches_instance(x))
                return Increment(count or 1)

            case QuestType.CATCH_CURRENCY:
                if quest.measure == Measure.AMOUNT:
                    return Increment(abs(context.amount)) if context.amount else None
                return Increment(1)

            case QuestType.COMMAND:
                if normalize_command(context.command_name) != normalize_command(quest.command_name):
                    return None
                # only a command that said it did nothing is turned away; one that never reports still counts,
                # so this flag can be set without making a quest impossible to finish
                if quest.require_command_effect and context.command_worked is False:
                    return None
                return Increment(1)

            case QuestType.TRADE:
                needs_treasure = quest.must_receive_treasure or quest.ball_id or quest.special_id or quest.any_special
                if needs_treasure and not any(quest.matches_instance(x) for x in context.instances):
                    return None
                return Increment(1)

            case QuestType.TRADE_TREASURES:
                received = len(context.instances)
                # a trade where one side gives nothing is a gift, not an exchange
                if not (received or context.received_currency) or not (context.given_count or context.given_currency):
                    return None
                exchanged = received + context.given_count
                if not exchanged:
                    return None
                return Absolute(exchanged) if quest.in_one_trade else Increment(exchanged)

            case QuestType.FRIEND:
                return Increment(1)

            case QuestType.GIVE_CURRENCY:
                amount = abs(context.amount)
                if not amount:
                    return None
                return Increment(amount if quest.measure == Measure.AMOUNT else 1)

            case QuestType.RECEIVE_CURRENCY:
                amount = context.received_currency or abs(context.amount)
                if not amount:
                    return None
                return Increment(amount if quest.measure == Measure.AMOUNT else 1)

            case QuestType.SPEND_CURRENCY:
                # the ledger event is signed, only what leaves the player counts
                if context.amount >= 0:
                    return None
                spent = abs(context.amount)
                return Increment(spent if quest.measure == Measure.AMOUNT else 1)

            case QuestType.CRAFT:
                if quest.collector_id and context.collector_id != quest.collector_id:
                    return None
                if quest.tier_level_id and context.tier_level_id != quest.tier_level_id:
                    return None
                return Increment(1)

            case QuestType.PACK_BUY:
                if quest.item_id and context.item_id != quest.item_id:
                    return None
                return self._purchase(quest, context)

            case QuestType.MERCHANT_BUY:
                if quest.merchant_item_id and context.merchant_item_id != quest.merchant_item_id:
                    return None
                return self._purchase(quest, context)

            case QuestType.CURRENCY_STREAK | QuestType.PACK_STREAK:
                # a streak is where the player stands, not something that adds up: five days in a row is 5,
                # not five separate claims. The goal is to reach it, so a streak that breaks afterwards does
                # not undo the quest — an absolute result keeps the best the player ever reached
                return Absolute(context.streak) if context.streak else None

            case QuestType.AUCTION_BID:
                if quest.measure == Measure.AMOUNT:
                    return Increment(context.price) if context.price else None
                return Increment(1)

            # -- treasures the event carries, counted one by one
            case QuestType.FAVORITE | QuestType.SLEIGH_GIVE | QuestType.AUGMENT | QuestType.SANTA_OPEN:
                count = sum(1 for x in context.instances if quest.matches_instance(x))
                return Increment(count) if count else None

            case QuestType.AUCTION_SOLD | QuestType.BOUNTY_CLAIM:
                if quest.measure == Measure.AMOUNT:
                    amount = abs(context.price or context.amount)
                    return Increment(amount) if amount else None
                count = sum(1 for x in context.instances if quest.matches_instance(x))
                return Increment(count or 1)

            case QuestType.SANTA_GIFT:
                # a parcel paid for holds no card yet, only the promise of one, so it carries no treasure to
                # inspect. A quest naming a treasure or a rarity therefore only counts a parcel filled with a
                # real card, which is the whole point of being able to ask for one
                if _has_treasure_filter(quest) and not any(quest.matches_instance(x) for x in context.instances):
                    return None
                return Increment(1)

            # -- deeds with nothing to look at but the fact they happened
            case (
                QuestType.PACK_WEEKLY
                | QuestType.ACTIVITY
                | QuestType.VOTE
                | QuestType.SANTA_JOIN
                | QuestType.SLEIGH_FULL
                | QuestType.CREW_JOIN
                | QuestType.CREW_WAR_WIN
                | QuestType.ADVENT_COMPLETE
            ):
                return Increment(1)

            case QuestType.BATTLE_WIN | QuestType.BATTLE_PLAYED:
                if quest.max_lost is not None and context.lost_count > quest.max_lost:
                    return None
                return Increment(1)

            case QuestType.BOSS_PLAYED | QuestType.BOSS_WIN:
                if quest.measure == Measure.AMOUNT:
                    return Increment(context.damage) if context.damage else None
                return Increment(1)

            # -- grand line royale, where a crew war raid and an ordinary match are never mixed
            case QuestType.ROYALE_PLAYED:
                if not self._right_royale(quest, event):
                    return None
                if quest.max_place and not 0 < context.place <= quest.max_place:
                    return None
                if quest.min_rounds and context.rounds < quest.min_rounds:
                    return None
                return Increment(1)

            case (
                QuestType.ROYALE_WIN
                | QuestType.ROYALE_KILL
                | QuestType.ROYALE_CHEST
                | QuestType.ROYALE_BOUNTY
            ):
                return Increment(1) if self._right_royale(quest, event) else None

            case QuestType.ADVENT_OPEN:
                # a door whose day has gone by is bought open with berries, and that is what tells a player
                # who kept up with the calendar from one who paid to catch up
                if quest.on_time and context.amount:
                    return None
                return Increment(1)

            case QuestType.SANTA_WISH:
                # how much of the list is written, not how many times it was edited: changing the same slot
                # three times is still one wish
                return Absolute(context.total) if context.total else None

            case QuestType.CREW_POINTS:
                if not context.points:
                    return None
                return Increment(context.points if quest.measure == Measure.AMOUNT else 1)

            case QuestType.HUNT_STONE | QuestType.HUNT_COMPLETE:
                if quest.for_crew and not context.for_crew:
                    return None
                return Increment(1)

            case QuestType.ACHIEVEMENT_UNLOCK:
                if quest.achievement_category_id and context.category_id != quest.achievement_category_id:
                    return None
                return Increment(1)

            case QuestType.EVENT_SHOP_BUY:
                if quest.merchant_item_id and context.merchant_item_id != quest.merchant_item_id:
                    return None
                if quest.measure == Measure.AMOUNT:
                    # paid out of the pass's own purse, which is never berries
                    return Increment(context.tokens) if context.tokens else None
                return Increment(1)

            case QuestType.COLLECTIBLE_BUY:
                return self._purchase(quest, context)

            # -- different people, rather than more of the same action
            case QuestType.TRADE_PARTNERS:
                if quest.must_receive_treasure and not context.instances:
                    return None
                return Distinct(context.partner_discord_id) if context.partner_discord_id else None

            case QuestType.GIVE_PARTNERS:
                if not any(quest.matches_instance(x) for x in context.instances):
                    return None
                return Distinct(context.partner_discord_id) if context.partner_discord_id else None
        return None

    @staticmethod
    def _right_royale(quest: Quest, event: Event) -> bool:
        """
        Whether this royale deed is the kind the quest asked for.

        A kill in a crew war raid and a kill in an ordinary lobby arrive under events of their own, and a
        quest says which it means. Mixing them would let a quest about ordinary matches be finished in a war
        nobody outside a crew can enter.
        """
        return (event in WAR_EVENTS) == bool(quest.in_crew_war)

    @staticmethod
    def _purchase(quest: Quest, context: EventContext) -> Increment | None:
        if quest.measure == Measure.AMOUNT:
            spent = abs(context.price or context.amount)
            return Increment(spent) if spent else None
        return Increment(1)

    @staticmethod
    def _fast_enough(quest: Quest, instance) -> bool:
        if quest.max_catch_seconds is None:
            return True
        if not instance.catch_date or not instance.spawned_time:
            return False
        return (instance.catch_date - instance.spawned_time).total_seconds() <= quest.max_catch_seconds

    async def _apply(
        self,
        quest: Quest,
        player_id: int,
        row: PlayerQuest | None,
        period: str,
        result: Increment | Absolute | Distinct,
        now: datetime,
        context: EventContext,
        channel_id: int | None,
    ) -> Completion | None:
        target = quest.goal
        if row is None:
            row, _ = await PlayerQuest.objects.aget_or_create(player_id=player_id, quest_id=quest.pk, period=period)
            if row.completed_at:
                return None

        # the people a quest about different players has already counted. Written back with the progress, so
        # the list and the number it comes from can never drift apart. The per-player lock around the whole of
        # `_process` is what makes reading it, adding to it and writing it safe.
        seen: list[int] | None = None
        if isinstance(result, Distinct):
            seen = [int(key) for key in row.seen] if isinstance(row.seen, list) else []
            if result.key in seen:
                return None
            seen.append(result.key)
            progress = min(len(seen), target)
        elif isinstance(result, Increment):
            progress = min(row.progress + result.amount, target)
        else:
            progress = min(max(result.value, row.progress), target)

        if progress < target:
            if progress != row.progress or seen is not None:
                changes: dict[str, object] = {"progress": progress}
                if seen is not None:
                    changes["seen"] = seen
                await PlayerQuest.objects.filter(pk=row.pk, completed_at__isnull=True).aupdate(**changes)
            return None

        # only the update that actually completes the quest counts, whichever action got there first
        done: dict[str, object] = {"progress": target, "completed_at": now}
        if seen is not None:
            done["seen"] = seen
        updated = await PlayerQuest.objects.filter(pk=row.pk, completed_at__isnull=True).aupdate(**done)
        if not updated:
            return None
        await PlayerPass.objects.aget_or_create(player_id=player_id, event_pass_id=quest.event_pass_id)
        log.debug("Player %s completed quest %s (%s)", player_id, quest.pk, period or "once")

        completion = Completion(quest=quest, period=period)
        # the quest may hand its reward over on its own, or the bot may be set to never ask for a click
        gives_now = not quest.claim_required or settings.pass_auto_claim
        if gives_now and quest.reward_id:
            given = await grant(
                player_id,
                quest.event_pass,
                quest.reward,
                source=Source.QUEST,
                source_id=quest.pk,
                period=period,
                server_id=context.server_id,
                channel_id=channel_id,
                label=quest.name,
            )
            if given is not None:
                await PlayerQuest.objects.filter(pk=row.pk).aupdate(claimed_at=now)
                completion.auto_claimed = True
                completion.summary = given.summary
        return completion

    # -- claiming ----------------------------------------------------------------------------------------------------

    async def claim(
        self, player_id: int, quest: Quest, *, channel_id: int | None = None, server_id: int | None = None
    ) -> tuple[str, str]:
        """
        Claim the reward of a completed quest.

        Returns
        -------
        tuple[str, str]
            A status (`claimed`, `already`, `not_completed`, `closed`, `nothing`) and what the player got.
        """
        now = timezone.now()
        if not quest.event_pass.claimable(now):
            return ("closed", "")
        period = period_of(quest, now)
        row = await PlayerQuest.objects.filter(player_id=player_id, quest_id=quest.pk, period=period).afirst()
        if row is None or row.completed_at is None:
            return ("not_completed", "")
        if row.claimed_at is not None:
            return ("already", "")
        if quest.reward_id is None:
            await PlayerQuest.objects.filter(pk=row.pk, claimed_at__isnull=True).aupdate(claimed_at=now)
            return ("nothing", "")

        given = await grant(
            player_id,
            quest.event_pass,
            quest.reward,
            source=Source.QUEST,
            source_id=quest.pk,
            period=period,
            server_id=server_id,
            channel_id=channel_id,
            label=quest.name,
        )
        if given is None:
            await PlayerQuest.objects.filter(pk=row.pk, claimed_at__isnull=True).aupdate(claimed_at=now)
            return ("already", "")
        await PlayerQuest.objects.filter(pk=row.pk).aupdate(claimed_at=now)
        return ("claimed", given.summary)

    async def claim_tier(
        self, player_id: int, tier, *, channel_id: int | None = None, server_id: int | None = None
    ) -> tuple[str, str]:
        """
        Claim the reward of a finished tier, if it has one.
        """
        event_pass = tier.event_pass
        if not event_pass.claimable():
            return ("closed", "")
        if tier.reward_id is None:
            return ("nothing", "")
        if tier.pk not in await finished_tier_ids(player_id, event_pass):
            return ("unfinished", "")
        given = await grant(
            player_id,
            event_pass,
            tier.reward,
            source=Source.TIER,
            source_id=tier.pk,
            server_id=server_id,
            channel_id=channel_id,
            label=tier.name,
        )
        return ("already", "") if given is None else ("claimed", given.summary)

    async def claim_final(
        self, player_id: int, event_pass: EventPass, *, channel_id: int | None = None, server_id: int | None = None
    ) -> tuple[str, str]:
        """
        Claim the reward given for finishing the whole pass.
        """
        if not event_pass.claimable():
            return ("closed", "")
        if event_pass.final_reward_id is None:
            return ("nothing", "")
        tiers = {tier async for tier in event_pass.tiers.values_list("pk", flat=True)}
        if tiers and not tiers <= await finished_tier_ids(player_id, event_pass):
            return ("unfinished", "")
        # loaded here: the pass comes from queries that don't join its reward, and reading `event_pass.final_reward`
        # would be a synchronous query, which async code is not allowed to make
        final_reward = await Reward.objects.filter(pk=event_pass.final_reward_id).afirst()
        if final_reward is None:
            return ("nothing", "")
        given = await grant(
            player_id,
            event_pass,
            final_reward,
            source=Source.FINAL,
            source_id=event_pass.pk,
            server_id=server_id,
            channel_id=channel_id,
            label=event_pass.name,
        )
        if given is None:
            return ("already", "")
        await PlayerPass.objects.aupdate_or_create(
            player_id=player_id, event_pass_id=event_pass.pk, defaults={"final_claimed_at": timezone.now()}
        )
        return ("claimed", given.summary)


engine = EventPassEngine()
