from __future__ import annotations

from datetime import datetime, timedelta

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from bd_models.models import Ball, BallInstance, Player, Special, balls, frame_entry, specials


class CollectorSettings(models.Model):
    monitoring_enabled = models.BooleanField(
        default=True,
        help_text="Watch the collector cards of monitored tiers: when their owner stops meeting the requirements "
        "(traded, gave or sold a required treasure), a timer starts and the card is taken back once it runs out.",
    )
    grace_period_hours = models.PositiveIntegerField(
        default=48, help_text="How long a player has to get the missing treasures back before losing the card."
    )

    @classmethod
    def load(cls) -> CollectorSettings:
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    async def aload(cls) -> CollectorSettings:
        return await sync_to_async(cls.load)()

    @property
    def grace_period(self) -> timedelta:
        return timedelta(hours=self.grace_period_hours)

    def __str__(self) -> str:
        return "Collector settings"

    class Meta:
        managed = True
        db_table = "collectorsettings"
        verbose_name_plural = "collector settings"


class CollectorTierLevel(models.Model):
    """
    A tier shared by every collector, like "Tier 1", "Tier 2" or "Awakened".
    """

    name = models.CharField(max_length=32, unique=True, help_text='Name shown to players, like "Tier 2".')
    position = models.PositiveSmallIntegerField(default=1, help_text="Tiers are shown from the lowest position.")
    emoji = models.CharField(
        max_length=64, blank=True, default="", help_text="Optional emoji shown on the claim button."
    )
    special = models.ForeignKey(
        Special,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Special given to the cards of this tier, unless a collector sets another one.",
    )
    special_id: int | None
    claimable = models.BooleanField(
        default=True,
        help_text="Uncheck to prevent players from claiming this tier on every collector, for instance while its "
        "requirements are being set up.",
    )
    monitored = models.BooleanField(
        default=True,
        help_text="Cards of this tier claimed from now on are taken back if their owner stops meeting the "
        "requirements for too long. Cards claimed before this option was enabled are never watched.",
    )

    @property
    def cached_special(self) -> Special | None:
        return specials.get(self.special_id) or self.special if self.special_id else None

    def __str__(self) -> str:
        return self.name

    class Meta:
        managed = True
        db_table = "collectortierlevel"
        ordering = ("position", "id")


class Collector(models.Model):
    name = models.CharField(max_length=64, unique=True)
    ball = models.ForeignKey(Ball, on_delete=models.CASCADE, null=True, blank=True)
    ball_id: int | None
    start_date = models.DateTimeField(
        help_text="Start date of this collector. If blank, it starts immediately", null=True, blank=True
    )
    end_date = models.DateTimeField(
        help_text="End date of this collector. If blank, collector is permanent", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    tiers: models.QuerySet[CollectorTier]
    requirements: models.QuerySet[CollectorRequirement]

    @property
    def cached_ball(self) -> "Ball | None":
        return balls.get(self.ball_id) or self.ball if self.ball_id else None

    @property
    def active(self) -> bool:
        return (
            (self.start_date or datetime.min.replace(tzinfo=timezone.get_default_timezone()))
            <= timezone.now()
            <= (self.end_date or datetime.max.replace(tzinfo=timezone.get_default_timezone()))
        )

    def __str__(self):
        return self.name

    class Meta:
        managed = True
        db_table = "collector"
        indexes = [models.Index(fields=("ball",))]


class CollectorTier(models.Model):
    """
    One tier of a collector. The requirements of a tier are the collector requirements with the same tier level.
    """

    collector = models.ForeignKey(Collector, on_delete=models.CASCADE, related_name="tiers")
    collector_id: int
    level = models.ForeignKey(CollectorTierLevel, on_delete=models.PROTECT, related_name="collector_tiers")
    level_id: int
    special = models.ForeignKey(
        Special,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Leave empty to use the special of the tier.",
    )
    special_id: int | None
    no_special = models.BooleanField(
        default=False, help_text="The card has no special at all, the treasure itself is the collector card."
    )
    tradeable = models.BooleanField(default=True, help_text="Whether the claimed cards can be traded.")
    frame_key = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text='Frame given to the claimed card, as its name or its key in the Frames section ("09-20-2026", '
        'or "09-20-2026:3" for a frame of one special). Leave empty to give whatever frame runs on the day the '
        'card is claimed, like a catch, and write "none" for a card that always stays plain.',
    )
    enabled = models.BooleanField(default=True, help_text="Uncheck to disable this tier for this collector only.")
    price = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Optional amount of currency players must pay to claim this tier."
    )

    @property
    def card_special_id(self) -> int | None:
        """
        The special given to the claimed cards. The level must be loaded (`select_related`).
        """
        if self.no_special:
            return None
        return self.special_id or self.level.special_id

    def __str__(self) -> str:
        return f"{self.collector} ({self.level})"

    class Meta:
        managed = True
        db_table = "collectortier"
        unique_together = (("collector", "level"),)


class CollectorRequirement(models.Model):
    collector = models.ForeignKey(Collector, on_delete=models.CASCADE, related_name="requirements")
    collector_id: int
    level = models.ForeignKey(
        CollectorTierLevel,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="The tier this requirement belongs to.",
    )
    level_id: int
    ball = models.ForeignKey(Ball, on_delete=models.SET_NULL, null=True, blank=True)
    ball_id: int | None
    special = models.ForeignKey(Special, on_delete=models.SET_NULL, null=True, blank=True)
    special_id: int | None
    frame_key = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text='Only the copies carrying this frame count, by its name ("OPDex Birthday") or by its key. The '
        "frame must be one of the required treasure's and must have a name. Leave empty for any copy, framed or "
        'not, and pick the "Frame" special instead to accept any frame.',
    )
    amount = models.PositiveIntegerField(default=1)
    delete_balls = models.BooleanField(
        default=False,
        help_text="If a user meets all requirements, will the required balls be removed? Removed treasures are "
        "never watched afterwards.",
    )

    @property
    def cached_ball(self) -> "Ball | None":
        return balls.get(self.ball_id) or self.ball if self.ball_id else None

    @property
    def cached_special(self) -> "Special | None":
        return specials.get(self.special_id) or self.special if self.special_id else None

    @property
    def frame_name(self) -> str:
        """
        The name of the frame this requirement asks for, as the copies given with it carry it. Empty when it asks
        for no particular frame, and when the key points at nothing: an unknown frame must match no treasure
        rather than every one of them, so the caller checks `frame_key` before reading this.
        """
        if not self.frame_key:
            return ""
        ball = self.cached_ball
        entry = frame_entry(ball, self.frame_key) if ball else None
        return str((entry or {}).get("name") or "")

    def clean(self) -> None:
        super().clean()
        if not self.frame_key:
            return
        if not self.ball_id:
            raise ValidationError({"frame_key": "Name the treasure as well: a frame belongs to one treasure."})
        # read the treasure of the form rather than the cache, the frame may have been added a minute ago
        entry = frame_entry(self.ball, self.frame_key)
        if entry is None:
            raise ValidationError({"frame_key": f'{self.ball.country} has no frame called "{self.frame_key}".'})
        if not entry.get("name"):
            raise ValidationError(
                {
                    "frame_key": "That frame has no name, so the copies carrying it cannot be told apart. Give it "
                    "one in the Frames section first."
                }
            )

    def __str__(self):
        title = f"{self.collector.name} requirement: X{self.amount} "
        if self.ball:
            title += f"{self.ball.country} "
        if self.frame_key:
            title += f"[{self.frame_name or self.frame_key}] "
        if self.special:
            title += f"{self.special.name}"
        return title

    class Meta:
        managed = True
        db_table = "collectorrequirement"
        indexes = [
            models.Index(fields=("collector",)),
            models.Index(fields=("ball",)),
            models.Index(fields=("special",)),
            models.Index(fields=("amount",)),
        ]


class CollectorInstance(models.Model):
    """
    A claimed collector card. Cards claimed before the monitoring existed are not linked to their treasure.
    """

    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    player_id: int
    collector = models.ForeignKey(Collector, on_delete=models.CASCADE)
    collector_id: int
    level = models.ForeignKey(CollectorTierLevel, on_delete=models.PROTECT, related_name="instances")
    level_id: int
    ball_instance = models.ForeignKey(
        BallInstance, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", help_text="The card."
    )
    ball_instance_id: int | None
    claimed_at = models.DateTimeField(null=True, blank=True)
    monitored = models.BooleanField(
        default=False, help_text="Whether the card is taken back if its owner stops meeting the requirements."
    )
    at_risk_since = models.DateTimeField(
        null=True, blank=True, help_text="When the owner stopped meeting the requirements."
    )
    grace_ends_at = models.DateTimeField(null=True, blank=True, help_text="When the card will be taken back.")
    revoked_at = models.DateTimeField(
        null=True, blank=True, help_text="When the card was taken back. The collector can then be claimed again."
    )

    @property
    def at_risk(self) -> bool:
        return self.revoked_at is None and self.at_risk_since is not None

    def __str__(self) -> str:
        return f"{self.collector} ({self.level}) claimed by {self.player}"

    class Meta:
        managed = True
        db_table = "collectorinstance"
        constraints = [
            models.UniqueConstraint(
                fields=("player", "collector", "level"),
                condition=Q(revoked_at__isnull=True),
                name="collectorinstance_active_unique",
            )
        ]
        indexes = [
            models.Index(fields=("player",)),
            models.Index(fields=("collector",)),
            models.Index(fields=("monitored", "revoked_at")),
        ]
