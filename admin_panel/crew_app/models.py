"""
Crews: the side a player picks, and plays for.

A player belongs to one crew at a time, chosen from /player settings. Everything built on top
of crews — a hunt run as a race between them, a war scored over a season — reads membership
from here rather than keeping its own idea of who is on which side.
"""

from collector_app.models import Collector, CollectorTierLevel
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from bd_models.enums import AnnouncementScope
from bd_models.models import Ball, Player, Special, balls, specials


class Crew(models.Model):
    name = models.CharField(max_length=48, unique=True, help_text="Shown to players, e.g. 'Straw Hat Pirates'.")
    description = models.TextField(blank=True, default="", help_text="A line or two about what this crew is.")
    emoji = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Shown next to the name. A unicode character, or a Discord emoji copied whole, "
        "as <:name:id> — right-click it and Copy, or type a backslash before it and send it. "
        "An emoji this bot cannot reach is left out rather than shown broken.",
    )
    image = models.ImageField(
        max_length=200, null=True, blank=True, help_text="The crew's flag or art. A GIF works here too."
    )
    victory_image = models.ImageField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Posted in the spawn channels when this crew finishes a hunt. A GIF works, and this is "
        "where one earns its keep: it only ever plays on a win. Falls back to the hunt's own completion "
        "picture when left empty.",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Turn this off to stop players joining it. Members already in it stay, so a crew can be "
        "retired without losing its history.",
    )
    position = models.PositiveIntegerField(default=0, help_text="Crews are listed from lowest to highest.")
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    members: models.QuerySet["CrewMembership"]

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    class Meta:
        managed = True
        db_table = "crew"
        ordering = ("position", "name")

    def __str__(self) -> str:
        return self.name


class CrewMembership(models.Model):
    """
    One row per player who has picked a crew. A player can only be in one, which is what the
    one-to-one gives: joining another replaces this row rather than adding a second.
    """

    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name="crew_membership")
    player_id: int
    crew = models.ForeignKey(Crew, on_delete=models.CASCADE, related_name="members")
    crew_id: int
    joined_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "crewmembership"
        ordering = ("-joined_at",)

    def __str__(self) -> str:
        return f"{self.player_id} in {self.crew_id}"


class CrewWar(models.Model):
    """
    A season scored between crews.

    Points come in through the game event bus: the rules below say what each kind of deed is
    worth, and a deed by a player with no crew simply scores nothing. Only one war can be
    running at a time, which is what makes "the war" something players can talk about.
    """

    name = models.CharField(max_length=64, unique=True, help_text="e.g. 'The Great Crew War, season 1'.")
    description = models.TextField(blank=True, default="", help_text="What is at stake, shown above the table.")
    enabled = models.BooleanField(default=True, help_text="Turn this off to stop scoring without deleting it.")
    starts_at = models.DateTimeField(null=True, blank=True, help_text="Nothing scores before this.")
    ends_at = models.DateTimeField(null=True, blank=True, help_text="And nothing scores after it.")
    image = models.ImageField(
        max_length=200, null=True, blank=True, help_text="Banner for the standings. A GIF works."
    )
    announce_to = models.CharField(
        max_length=8,
        choices=AnnouncementScope.choices,
        default=AnnouncementScope.ALL,
        help_text="Where the result of this war is announced once you hand the rewards out: who won, the "
        "final table, and the winning crew's victory picture. Players are always told what they personally "
        "received by direct message, whatever this says.",
    )
    announced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the bot announced this war's result. Written the first time you hand the rewards "
        "out; clear it to have the result announced again.",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    rules: models.QuerySet["CrewWarRule"]
    rewards: models.QuerySet["CrewWarReward"]

    def is_live(self, at=None) -> bool:
        at = at or timezone.now()
        if not self.enabled:
            return False
        return (self.starts_at is None or self.starts_at <= at) and (self.ends_at is None or at <= self.ends_at)

    class Meta:
        managed = True
        db_table = "crewwar"
        ordering = ("-starts_at", "name")

    def __str__(self) -> str:
        return self.name


class CrewWarRule(models.Model):
    """What one kind of deed is worth in this war."""

    class Source(models.TextChoices):
        """
        Every deed a war can be told to count.

        They are grouped by what they ask of a player, because a war reads better when the
        points are spread across the groups than when they all sit on one of them: fighting
        rewards the people who show up to events, the treasure and trading deeds reward the
        ones who play on their own in between, and the last group rewards simply turning up.
        """

        # -- fighting
        BATTLE_PLAYED = "battle_played", "Took part in a battle"
        BATTLE_WIN = "battle_win", "Won a battle"
        BOSS_PLAYED = "boss_played", "Took part in a boss fight"
        BOSS_WIN = "boss_win", "Won a boss fight"

        # -- Grand Line Royale, the other bot. It reports what a player did and nothing else:
        # who it counts for is read from the crew membership here, never from the report.
        ROYALE_PLAYED = "royale_played", "Played a Royale match"
        ROYALE_WIN = "royale_win", "Won a Royale match"
        ROYALE_KILL = "royale_kill", "Killed someone in a Royale match"
        ROYALE_CHEST = "royale_chest", "Opened a chest in a Royale match"
        ROYALE_BOUNTY = "royale_bounty", "Claimed a bounty in a Royale match"

        # -- the events the staff run
        BOUNTY_CLAIMED = "bounty_claimed", "Caught a wanted treasure"
        PONEGLYPH_CLAIMED = "poneglyph_claimed", "Claimed a poneglyph"
        HUNT_COMPLETED = "hunt_completed", "Finished a poneglyph hunt"

        # -- treasures
        CATCH = "catch", "Caught a treasure"
        CATCH_SPECIAL = "catch_special", "Caught a special treasure"
        CRAFT = "craft", "Claimed a collector card"

        # -- between players
        TRADE = "trade", "Completed a trade"
        GIFT = "gift", "Gave a treasure away"
        FRIEND = "friend", "Made a friend"

        # -- the Hotel de Vente
        AUCTION_CREATE = "auction_create", "Listed a treasure at the Hotel"
        AUCTION_BID = "auction_bid", "Placed a bid"
        AUCTION_WON = "auction_won", "Won a listing"
        SELL = "sell", "Sold a treasure to Buggy"
        SHOP_BUY = "shop_buy", "Bought a treasure from Buggy's shop"

        # -- the shops
        PACK_BUY = "pack_buy", "Bought a pack"
        MERCHANT_BUY = "merchant_buy", "Bought from the merchant"

        # -- showing up
        DAILY_BERRIES = "daily_berries", "Claimed the daily berries"
        DAILY_PACK = "daily_pack", "Claimed the daily pack"
        WEEKLY_PACK = "weekly_pack", "Claimed the weekly pack"
        PLAYED = "played", "Played at all that day"

        # -- and the one nothing dispatches: what a line given by hand carries, so points an
        # admin awards for a tournament or a King of the Seas sit in the same ledger as the rest
        MANUAL = "manual", "Awarded by an admin"

    # the deeds a treasure passes through, where naming one is worth something: "caught Luffy"
    # reads as a deed, "bought Luffy from the merchant" does not
    BALL_SOURCES = (
        Source.CATCH,
        Source.CATCH_SPECIAL,
        Source.TRADE,
        Source.GIFT,
        Source.SELL,
        Source.SHOP_BUY,
        Source.AUCTION_CREATE,
        Source.AUCTION_WON,
    )
    # and the ones that go through a collector
    COLLECTOR_SOURCES = (Source.CRAFT,)

    war = models.ForeignKey(CrewWar, on_delete=models.CASCADE, related_name="rules")
    war_id: int
    source = models.CharField(max_length=32, choices=Source.choices)
    points = models.IntegerField(default=1, help_text="Added to the crew's score. A negative number takes points off.")
    daily_cap = models.PositiveIntegerField(
        default=0,
        help_text="Most points one player can earn from this deed in a day. 0 means no limit — handy on the "
        "deeds a player could repeat all evening.",
    )
    minimum_value = models.PositiveIntegerField(
        default=0,
        help_text="Only count the deed when the berries it moves reach this. It is what stops a crew farming "
        "a sale or a listing worth one berry, over and over. 0 counts every one, and deeds that move no "
        "berries ignore it.",
    )

    ball = models.ForeignKey(
        Ball,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        help_text="Only this treasure counts, so a war can pay 50 for catching Luffy and 1 for catching "
        "anything. Leave empty for any treasure.",
    )
    ball_id: int | None
    special = models.ForeignKey(
        Special,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        help_text="Only copies carrying this special count. Can be combined with the treasure above, for "
        "one exact card.",
    )
    special_id: int | None
    collector = models.ForeignKey(
        Collector,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        help_text="Claims only: the one collector that counts. Leave empty for any of them.",
    )
    collector_id: int | None
    tier_level = models.ForeignKey(
        CollectorTierLevel,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        help_text="Claims only: the tier that counts, like Craft or Elemental. This is how an awakened fruit "
        "pays more than a Tier 1, since nothing else tells them apart.",
    )
    tier_level_id: int | None

    @property
    def named(self) -> int:
        """
        How many things this rule names.

        It is the rule's specificity: of the rules a deed matches, the one naming the most wins,
        and only that one scores. A war can therefore say "a catch is worth 1" and "a catch of
        Luffy is worth 50" without a Luffy paying 51.
        """
        return sum(bool(x) for x in (self.ball_id, self.special_id, self.collector_id, self.tier_level_id))

    @property
    def is_targeted(self) -> bool:
        return bool(self.named)

    @property
    def target_label(self) -> str:
        """
        What this rule names, in words.

        Treasures and specials come from the caches first. Everything else is read out of the
        rows already loaded rather than through the foreign key, because this is called from the
        bot's async code and a lazy fetch there raises instead of querying: the rules are read
        with `select_related` on all four, and a name that is somehow missing is left out rather
        than taking the command down.
        """
        loaded = self._state.fields_cache
        parts = []
        if self.special_id and (special := specials.get(self.special_id) or loaded.get("special")):
            parts.append(special.name)
        if self.ball_id and (ball := balls.get(self.ball_id) or loaded.get("ball")):
            parts.append(ball.country)
        if self.collector_id and (collector := loaded.get("collector")):
            parts.append(collector.name)
        if self.tier_level_id and (tier := loaded.get("tier_level")):
            parts.append(tier.name)
        return " ".join(parts)

    @property
    def label(self) -> str:
        """The deed as a player reads it: "Caught a treasure", or "Caught a treasure — Luffy"."""
        target = self.target_label
        return f"{self.get_source_display()} — {target}" if target else self.get_source_display()

    def matches(self, context) -> bool:
        """
        Whether this deed is the one this rule is about.

        A rule naming nothing matches every deed of its source. A rule naming something matches
        only when the deed carries it, and a deed that carries nothing at all — an event
        dispatched without its details — never matches a rule that names one.
        """
        if not self.is_targeted:
            return True
        if context is None:
            return False
        if self.collector_id and context.collector_id != self.collector_id:
            return False
        if self.tier_level_id and context.tier_level_id != self.tier_level_id:
            return False
        if self.ball_id or self.special_id:
            # one copy has to carry both, otherwise a trade of a plain Luffy and a special Zoro
            # would match a rule asking for a special Luffy
            return any(
                (not self.ball_id or instance.ball_id == self.ball_id)
                and (not self.special_id or instance.special_id == self.special_id)
                for instance in context.instances
            )
        return True

    class Meta:
        managed = True
        db_table = "crewwarrule"
        ordering = ("source", "-id")
        constraints = (
            # a source can hold several rules now, one per thing named, but only one of each —
            # and NULLs count as equal here, or two rules naming nothing would both be allowed
            models.UniqueConstraint(
                fields=("war", "source", "ball", "special", "collector", "tier_level"),
                name="crewwarrule_one_per_target",
                nulls_distinct=False,
            ),
        )

    def clean(self):
        # no event carries this one, so a rule for it would sit there scoring nothing at all
        if self.source == self.Source.MANUAL:
            raise ValidationError(
                {"source": "Nothing dispatches this. Points by hand are given with /crew admin points."}
            )
        # "played" is scored off every slash command, so without a cap it would pay a player
        # for scrolling through their inventory all evening. The cap is what turns it into
        # "turned up today", which is the only thing it is good for.
        if self.source == self.Source.PLAYED and not self.daily_cap:
            raise ValidationError(
                {
                    "daily_cap": "Playing is scored off every command, so this one needs a daily cap. "
                    "Set it to the same number as the points to make it 'turned up today'."
                }
            )
        # a rule naming something its deed never carries would simply never score, which is the
        # kind of silence that takes an evening to debug
        deed = self.get_source_display()
        errors = {}
        if self.source not in self.BALL_SOURCES:
            for field in ("ball", "special"):
                if getattr(self, f"{field}_id"):
                    errors[field] = f"{deed} carries no treasure, so naming one here would stop it scoring."
        if self.source not in self.COLLECTOR_SOURCES:
            for field in ("collector", "tier_level"):
                if getattr(self, f"{field}_id"):
                    errors[field] = f"{deed} goes through no collector, so naming one here would stop it scoring."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.label}: {self.points}"


class CrewWarEntry(models.Model):
    """
    One deed scored, kept as a line rather than a running total.

    A ledger costs a little more to read than a counter, but it is the only way to answer "why
    does this crew have that many points" afterwards, and it makes the daily caps above a simple
    count over a window.
    """

    war = models.ForeignKey(CrewWar, on_delete=models.CASCADE, related_name="entries")
    war_id: int
    crew = models.ForeignKey(Crew, on_delete=models.CASCADE, related_name="war_entries")
    crew_id: int
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="war_entries")
    player_id: int
    source = models.CharField(max_length=32, choices=CrewWarRule.Source.choices)
    rule = models.ForeignKey(
        CrewWarRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
        help_text="The rule that paid for this deed. Kept so a daily cap counts that rule rather than the "
        "whole source: a rule naming one treasure deserves its own cap, not the generic one's.",
    )
    rule_id: int | None
    points = models.IntegerField()
    note = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Why these points were given, for the lines written by hand. Shown to the player as what "
        "they last earned, in place of the deed a rule would have named.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "crewwarentry"
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("war", "crew"), name="crewwar_war_crew_idx"),
            models.Index(fields=("war", "player"), name="crewwar_war_player_idx"),
            models.Index(fields=("war", "player", "source", "created_at"), name="crewwar_cap_idx"),
            models.Index(fields=("war", "player", "rule", "created_at"), name="crewwar_rule_cap_idx"),
        )

    def __str__(self) -> str:
        return f"{self.crew_id} +{self.points} ({self.source})"


class CrewWarReward(models.Model):
    """
    One rung of the reward ladder of a war, handed over when the war is done.

    A ladder is read from the top down. A player gets the highest rung they reached, and the
    rungs under it only while each one it passes through says it stacks — so a ladder of
    stacking rungs pays everything the player walked past, and one rung set not to stack is
    where the ladder stops and becomes "this instead of that".

    A crew rung works on the finishing place instead of the points, and goes to every member of
    that crew. That is the reward for winning the war rather than for playing it.
    """

    class Scope(models.TextChoices):
        PLAYER = "player", "Every player who brought this many points"
        CREW = "crew", "Every member of the crew finishing in this place"

    war = models.ForeignKey(CrewWar, on_delete=models.CASCADE, related_name="rewards")
    war_id: int
    scope = models.CharField(
        max_length=8,
        choices=Scope.choices,
        default=Scope.PLAYER,
        help_text="Whether this rung is earned by a player's own points or by their crew's place.",
    )
    threshold = models.PositiveIntegerField(
        default=1,
        help_text="On a player rung, the points needed — 1 is the rung for everyone who scored at all. On a "
        "crew rung, the finishing place: 1 is the winning crew, 2 the runner-up. 0 on a crew rung means every "
        "crew that scored.",
    )
    name = models.CharField(max_length=64, help_text="Shown to players, e.g. 'Rookie' or 'Yonko'.")
    money = models.PositiveBigIntegerField(default=0, help_text="Berries paid by this rung. 0 for none.")
    cumulative = models.BooleanField(
        default=True,
        help_text="Also hand out the rung below this one. Leave it on for a ladder that piles up, turn it off "
        "on the rung where the ladder should stop — the player then gets this rung and nothing under it. "
        "Ignored on crew rungs, which are earned on their own.",
    )
    message = models.CharField(
        max_length=256, blank=True, default="", help_text="A line said to the player when this rung is paid."
    )

    cards: models.QuerySet["CrewWarRewardCard"]
    payouts: models.QuerySet["CrewWarPayout"]

    @property
    def is_crew_reward(self) -> bool:
        return self.scope == self.Scope.CREW

    @property
    def label(self) -> str:
        if self.is_crew_reward:
            place = "every crew that scored" if not self.threshold else f"place {self.threshold}"
            return f"{self.name} ({place})"
        return f"{self.name} ({self.threshold:,} point{'' if self.threshold == 1 else 's'})"

    class Meta:
        managed = True
        db_table = "crewwarreward"
        ordering = ("scope", "threshold")
        unique_together = (("war", "scope", "threshold"),)

    def __str__(self) -> str:
        return self.label


class CrewWarRewardCard(models.Model):
    """One card of a rung. A rung can hand over as many as it likes, with or without a special."""

    reward = models.ForeignKey(CrewWarReward, on_delete=models.CASCADE, related_name="cards")
    reward_id: int
    ball = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="+")
    ball_id: int
    special = models.ForeignKey(
        Special,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The special put on the card. Leave empty for a plain one.",
    )
    special_id: int | None
    frame_key = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text='Frame given to the card, as its name or its key in the Frames section. Leave empty to give '
        'whatever frame runs on the day it is handed over, like a catch, and write "none" for a card that '
        "always stays plain.",
    )
    amount = models.PositiveIntegerField(default=1, help_text="How many copies of it.")
    tradeable = models.BooleanField(default=True, help_text="Whether the cards handed over can be traded.")

    @property
    def cached_ball(self) -> Ball | None:
        """
        The treasure, from the cache or from the row already loaded — never a fresh query.

        `label` is read from the bot's async code, where a lazy foreign key raises rather than
        querying, so this looks in the cache first and at the loaded row second.
        """
        return balls.get(self.ball_id) or self._state.fields_cache.get("ball")

    @property
    def cached_special(self) -> Special | None:
        if not self.special_id:
            return None
        return specials.get(self.special_id) or self._state.fields_cache.get("special")

    @property
    def label(self) -> str:
        special = self.cached_special
        ball = self.cached_ball
        name = ball.country if ball is not None else f"treasure {self.ball_id}"
        return f"{self.amount}x {special.name + ' ' if special else ''}{name}"

    class Meta:
        managed = True
        db_table = "crewwarrewardcard"
        ordering = ("pk",)

    def __str__(self) -> str:
        return self.label


class CrewWarPayout(models.Model):
    """
    One rung handed to one player, written before anything is given.

    The unique constraint is what makes running the payout twice harmless: the second run finds
    the row already there and hands nothing over, so a war can be paid out in pieces as the
    standings settle.
    """

    reward = models.ForeignKey(CrewWarReward, on_delete=models.CASCADE, related_name="payouts")
    reward_id: int
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="crew_war_payouts")
    player_id: int
    crew = models.ForeignKey(Crew, on_delete=models.SET_NULL, null=True, blank=True, related_name="war_payouts")
    crew_id: int | None
    points = models.IntegerField(default=0, help_text="What the player had brought when this was paid.")
    summary = models.CharField(max_length=256, blank=True, default="", help_text="What was actually handed over.")
    paid_at = models.DateTimeField(auto_now_add=True)
    announced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the player was told by direct message. Empty means the bot has not got to it yet, "
        "or could not reach them — the reward itself was handed over either way. Clear it to tell them again.",
    )

    class Meta:
        managed = True
        db_table = "crewwarpayout"
        ordering = ("-paid_at",)
        unique_together = (("reward", "player"),)
        indexes = (models.Index(fields=("announced_at",), name="crewwar_payout_told_idx"),)

    def __str__(self) -> str:
        return f"{self.reward_id} to {self.player_id}"
