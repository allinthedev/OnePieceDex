"""
The sleigh: a pot everyone fills with their own cards, and that empties itself back into the server.

A card put in the sleigh leaves the giver's dex for good and comes out the other side wearing the event's
special. What it keeps is its frame and its bonuses — the card that goes in is the card that comes out, only
dressed for Christmas.

The rarer the gift, the more it scores for the giver's crew, because the whole point is to reward being
generous rather than being busy. A rule of a crew war cannot price that, since the points depend on the card,
so the sleigh works its own points out and writes them straight into the war's ledger.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from bd_models.enums import AnnouncementScope
from bd_models.models import Ball, BallInstance, Player, Special, balls, specials


class Sleigh(models.Model):
    """
    One sleigh. A dex can keep last year's next to this year's; only an enabled one takes gifts.
    """

    name = models.CharField(max_length=64, help_text="Shown to players, e.g. 'The sleigh'.")
    emoji = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Shown next to the name. A unicode character, or a Discord emoji copied whole as <:name:id>.",
    )
    description = models.TextField(blank=True, default="", help_text="A line or two about what it is for.")
    enabled = models.BooleanField(default=True, help_text="Turn this off and nothing more goes in.")
    special = models.ForeignKey(
        Special,
        on_delete=models.CASCADE,
        related_name="sleighs",
        help_text="What every card put in here becomes. The Christmas special: a card only ever gains it by "
        "being given away, which is what makes a sleigh card worth having.",
    )
    special_id: int

    opens_at = models.DateTimeField(help_text="Nothing can be given before this. Times are UTC.")
    closes_at = models.DateTimeField(help_text="And nothing after it. The sleigh empties itself afterwards.")
    per_day = models.PositiveSmallIntegerField(
        default=1,
        validators=(MinValueValidator(1),),
        help_text="How many cards one player may put in per day. One is what makes the choice matter.",
    )
    goal = models.PositiveIntegerField(
        default=0, help_text="How many cards fill it, for the bar players see. Zero hides the bar."
    )

    points_base = models.PositiveIntegerField(
        default=50, help_text="Points a gift of the pivot rarity below is worth to the giver's crew."
    )
    points_pivot = models.FloatField(
        default=0.1,
        validators=(MinValueValidator(0.0001),),
        help_text="The rarity worth exactly the points above. A LOWER rarity is a RARER treasure, so a card ten "
        "times rarer than this scores ten times as much — up to the ceiling below.",
    )
    points_cap = models.PositiveIntegerField(
        default=2000, help_text="Most points one gift can ever be worth, however rare the card."
    )

    announce_to = models.CharField(
        max_length=8,
        choices=AnnouncementScope.choices,
        default=AnnouncementScope.MAIN,
        help_text="Where the sleigh says it has been filled, and where its waves are announced.",
    )
    empty_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the leftovers start going back out as spawns. Left empty, nothing is ever released and "
        "staff hand the cards out themselves.",
    )
    wave_count = models.PositiveSmallIntegerField(
        default=4,
        validators=(MinValueValidator(1),),
        help_text="How many waves the leftovers are split into. Four waves six hours apart give every timezone "
        "a fair shot at them.",
        verbose_name="waves",
    )
    wave_hours = models.PositiveSmallIntegerField(
        default=6, validators=(MinValueValidator(1),), help_text="Hours between one wave and the next."
    )
    spawn_channel_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Where the waves spawn, on the main server. Left empty, the main server's own spawn channel.",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "sleigh"
        ordering = ("-opens_at", "pk")
        verbose_name_plural = "sleighs"

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    @property
    def cached_special(self) -> Special | None:
        return specials.get(self.special_id) or self.special

    def is_open(self, at=None) -> bool:
        """Whether a card can be given right now."""
        at = at or timezone.now()
        return self.enabled and self.opens_at <= at <= self.closes_at

    def points_for(self, rarity: float) -> int:
        """
        What a gift of this rarity scores. Never zero, never past the ceiling.

        Rarity is the spawn weight, so a rare treasure carries a small number: the points are the pivot divided
        by the card's own rarity, which makes them rise as the card gets rarer.
        """
        floor = max(float(rarity), 0.0001)
        worth = round(self.points_base * (self.points_pivot / floor))
        return max(1, min(int(worth), self.points_cap))

    def wave_due(self, position: int):
        """When wave `position` (counting from one) goes out."""
        if self.empty_at is None:
            return None
        return self.empty_at + timedelta(hours=self.wave_hours * (position - 1))

    def __str__(self) -> str:
        return self.name


class SleighCard(models.Model):
    """
    One card inside the sleigh.

    The giver's instance is consumed — marked deleted, the way the rest of the dex consumes a card — and what it
    was is kept here instead. The card is recreated when it is handed out or caught, which is why the frame and
    the bonuses are copied across rather than looked up again.
    """

    sleigh = models.ForeignKey(Sleigh, on_delete=models.CASCADE, related_name="cards")
    sleigh_id: int
    ball = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="sleigh_cards")
    ball_id: int
    given_by = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sleigh_gifts",
        help_text="Who gave it. Empty for a card staff put in themselves.",
    )
    given_by_id: int | None
    crew = models.ForeignKey(
        "crew_app.Crew",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sleigh_gifts",
        help_text="The crew the gift scored for, as it stood on the day.",
    )
    crew_id: int | None
    attack_bonus = models.IntegerField(default=0)
    health_bonus = models.IntegerField(default=0)
    frame = models.JSONField(
        blank=True, default=dict, help_text="The frame the given card wore, carried over to the card it becomes."
    )
    rarity = models.FloatField(help_text="The card's rarity on the day, kept so the points can be explained.")
    points = models.PositiveIntegerField(default=0, help_text="What the gift scored for the crew.")
    given_at = models.DateTimeField(auto_now_add=True, editable=False)

    released_at = models.DateTimeField(
        null=True, blank=True, help_text="When it went back out as a spawn, for anyone to catch."
    )
    claimed_by = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sleigh_claims",
        help_text="Who ended up with it, when staff handed it to someone.",
    )
    claimed_by_id: int | None
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_instance = models.ForeignKey(
        BallInstance, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        managed = True
        db_table = "sleighcard"
        ordering = ("-given_at", "-pk")
        indexes = [
            models.Index(fields=("sleigh", "released_at"), name="sleigh_card_inside_idx"),
            models.Index(fields=("sleigh", "given_by"), name="sleigh_card_giver_idx"),
        ]

    @property
    def cached_ball(self) -> Ball:
        return balls.get(self.ball_id) or self.ball

    @property
    def inside(self) -> bool:
        """Whether it is still in the sleigh, waiting to go somewhere."""
        return self.released_at is None and self.claimed_by_id is None

    @property
    def state(self) -> str:
        if self.claimed_by_id:
            return "given to a player"
        if self.released_at:
            return "released as a spawn"
        return "in the sleigh"

    def __str__(self) -> str:
        return f"{self.cached_ball.country} ({self.points} points)"


class SleighWave(models.Model):
    """
    One batch of leftovers going back out.

    The count of what has gone lives in the row, so a restart in the middle of a wave picks up where it left
    off rather than spawning the batch twice.
    """

    sleigh = models.ForeignKey(Sleigh, on_delete=models.CASCADE, related_name="waves")
    sleigh_id: int
    position = models.PositiveSmallIntegerField(help_text="Counting from one.")
    due_at = models.DateTimeField(help_text="When this wave starts going out.")
    cards = models.PositiveIntegerField(default=0, help_text="How many cards this wave was given to send.")
    sent = models.PositiveIntegerField(default=0, help_text="How many have gone out so far.")
    announced_at = models.DateTimeField(
        null=True, blank=True, help_text="When players were told. Clear it to announce again."
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "sleighwave"
        ordering = ("sleigh", "position")
        constraints = [models.UniqueConstraint(fields=("sleigh", "position"), name="sleigh_wave_unique")]

    @property
    def left(self) -> int:
        return max(self.cards - self.sent, 0)

    @property
    def done(self) -> bool:
        return self.sent >= self.cards

    def __str__(self) -> str:
        return f"Wave {self.position} ({self.sent}/{self.cards})"
