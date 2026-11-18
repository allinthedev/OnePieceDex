"""
Poneglyph hunts: gather a set of treasures, hand them in, and hold the stone.

A hunt is a handful of poneglyphs. Each poneglyph is its own puzzle — a set of treasures,
announced when it opens — and a player holding that set can claim the stone. Collecting every
stone finishes the hunt.

A poneglyph is a counted thing, not a card: claiming one writes a row rather than minting a
treasure, so a hunt needs one picture of a stone rather than one illustration per poneglyph.

A hunt runs either per player or per crew. In crew mode the first member to hand in the set
claims the stone for everybody wearing that flag, which turns the hunt into a race between
crews rather than between individuals.
"""

from datetime import datetime

from crew_app.models import Crew
from django.db import models
from django.utils import timezone

from bd_models.enums import AnnouncementScope
from bd_models.models import Ball, BallInstance, Player, Special, balls, specials


class Hunt(models.Model):
    class Mode(models.TextChoices):
        INDIVIDUAL = "individual", "Every player for themselves"
        CREW = "crew", "A race between crews"

    name = models.CharField(max_length=64, unique=True, help_text="Shown to players, e.g. 'The Road Poneglyphs'.")
    description = models.TextField(
        blank=True,
        default="",
        help_text="The pitch, shown above the poneglyphs. Say what the hunt is and why anyone should care.",
    )
    mode = models.CharField(
        max_length=16,
        choices=Mode.choices,
        default=Mode.INDIVIDUAL,
        help_text="In crew mode the first member to hand a set in claims that poneglyph for the whole crew, "
        "and nobody else in it has to gather the same treasures again.",
    )
    enabled = models.BooleanField(
        default=True, help_text="Turn this off to hide the hunt from players without deleting it."
    )
    starts_at = models.DateTimeField(
        null=True, blank=True, help_text="Hidden before this. Leave empty for a hunt that is always on."
    )
    ends_at = models.DateTimeField(
        null=True, blank=True, help_text="And hidden after it. Leave empty for a hunt that never closes."
    )

    image = models.ImageField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Banner at the top of the hunt. An animated GIF works here and plays in Discord.",
    )
    completed_image = models.ImageField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Shown instead of the banner once every poneglyph is held. A GIF works here too, which is "
        "where an animation earns its keep: it only ever plays for someone who just finished.",
    )
    poneglyph_image = models.ImageField(
        max_length=200,
        null=True,
        blank=True,
        help_text="One picture of a stone, reused for every poneglyph in this hunt. This is what lets a hunt "
        "have nine poneglyphs without nine illustrations.",
    )
    announce_to = models.CharField(
        max_length=8,
        choices=AnnouncementScope.choices,
        default=AnnouncementScope.ALL,
        help_text="Where this hunt announces itself: a poneglyph surfacing, and a crew finishing the hunt. "
        "A hunt run for your own server only needs the main server; set it to nowhere and the poneglyphs "
        "appear with no warning at all.",
    )
    poneglyph_emoji = models.CharField(
        max_length=64,
        blank=True,
        default="🗿",
        help_text="Shown inline when counting stones held, e.g. '🗿 x4'.",
    )

    reward_money = models.PositiveBigIntegerField(default=0, help_text="Paid once, when the hunt is finished.")
    reward_ball = models.ForeignKey(
        Ball,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hunt_rewards",
        help_text="An optional treasure handed over on top of the money.",
    )
    reward_ball_id: int | None
    reward_special = models.ForeignKey(
        Special,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The special put on that treasure. Ignored without a reward treasure.",
    )
    reward_special_id: int | None
    completion_message = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Said on finishing the hunt. Left empty, it simply congratulates.",
    )
    announce_completion = models.BooleanField(
        default=True,
        help_text="Announce it when someone finishes this hunt, wherever the setting above sends it. On a "
        "crew hunt that is one announcement per crew; on an individual one it is one per player, so turn it "
        "off if that would be too much noise.",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    poneglyphs: models.QuerySet["Poneglyph"]

    @property
    def is_crew_hunt(self) -> bool:
        return self.mode == self.Mode.CREW

    @property
    def cached_reward_ball(self) -> Ball | None:
        return (balls.get(self.reward_ball_id) or self.reward_ball) if self.reward_ball_id else None

    @property
    def cached_reward_special(self) -> Special | None:
        return (specials.get(self.reward_special_id) or self.reward_special) if self.reward_special_id else None

    def is_live(self, at: datetime | None = None) -> bool:
        """Whether players can see and play this hunt right now."""
        at = at or timezone.now()
        if not self.enabled:
            return False
        return (self.starts_at is None or self.starts_at <= at) and (self.ends_at is None or at <= self.ends_at)

    class Meta:
        managed = True
        db_table = "hunt"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Poneglyph(models.Model):
    """
    One stone: a set of treasures to hand in, and the claim that follows.

    The set is listed in `requirements`. An admin can write it out, or let the bot draw it with
    the "Draw the treasures" action and then edit what it came up with before opening.
    """

    hunt = models.ForeignKey(Hunt, on_delete=models.CASCADE, related_name="poneglyphs")
    hunt_id: int
    name = models.CharField(max_length=64, help_text="e.g. 'Road Poneglyph of Zou'.")
    hint = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="A line of flavour shown above the treasures to gather.",
    )
    position = models.PositiveIntegerField(default=0, help_text="Poneglyphs are listed from lowest to highest.")
    opens_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="This stone stays hidden until then, which is how a hunt releases one a week. Leave empty "
        "to open it with the hunt itself.",
    )
    announced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the bot announced this stone's treasures. Clear it to have it announced again.",
    )
    announce_to = models.CharField(
        max_length=8,
        blank=True,
        default="",
        choices=[("", "Follow the hunt")] + AnnouncementScope.choices,
        help_text="Where this stone announces itself, when you want it to differ from the rest of the hunt. "
        "One stone set to nowhere surfaces in silence while the others are announced, which is how a hunt "
        "hides its last poneglyph.",
    )

    draw_count = models.PositiveIntegerField(
        default=3, help_text="How many treasures the 'Draw the treasures' action puts in the set."
    )
    draw_min_rarity = models.FloatField(
        null=True, blank=True, help_text="The action only draws treasures of at least this rarity."
    )
    draw_max_rarity = models.FloatField(
        null=True, blank=True, help_text="And at most this one. Remember a LOWER rarity is a RARER treasure."
    )

    requirements: models.QuerySet["PoneglyphRequirement"]

    def is_open(self, at: datetime | None = None) -> bool:
        """Whether this stone is visible yet, assuming its hunt is live."""
        return self.opens_at is None or self.opens_at <= (at or timezone.now())

    @property
    def announcement_scope(self) -> str:
        """Where this stone is announced: its own choice, or the hunt's when it has made none."""
        return self.announce_to or self.hunt.announce_to

    class Meta:
        managed = True
        db_table = "poneglyph"
        ordering = ("position", "pk")
        unique_together = (("hunt", "name"),)

    def __str__(self) -> str:
        return self.name


class PoneglyphRequirement(models.Model):
    """One line of a stone's set: how many of which treasure, and whether handing it in costs it."""

    poneglyph = models.ForeignKey(Poneglyph, on_delete=models.CASCADE, related_name="requirements")
    poneglyph_id: int
    ball = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="poneglyph_requirements")
    ball_id: int
    special = models.ForeignKey(
        Special,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Only copies carrying this special count. Leave empty for any copy.",
    )
    special_id: int | None
    amount = models.PositiveIntegerField(default=1, help_text="How many copies are needed.")
    consume = models.BooleanField(
        default=False,
        help_text="Destroy the copies handed in. Off by default: the treasures only have to be owned at the "
        "moment of claiming, and the player keeps them.",
    )

    @property
    def cached_ball(self) -> Ball:
        return balls.get(self.ball_id) or self.ball

    @property
    def cached_special(self) -> Special | None:
        return (specials.get(self.special_id) or self.special) if self.special_id else None

    def matching(self, player: Player) -> models.QuerySet[BallInstance]:
        """The copies this player owns that count towards this line."""
        owned = BallInstance.objects.filter(player=player, ball_id=self.ball_id)
        return owned.filter(special_id=self.special_id) if self.special_id else owned

    class Meta:
        managed = True
        db_table = "poneglyphrequirement"
        ordering = ("pk",)

    def __str__(self) -> str:
        return f"{self.amount}x {self.ball_id}"


class PoneglyphClaim(models.Model):
    """
    One stone held, by a player or by a crew. Never the same stone twice for the same holder.

    Which of the two columns is filled depends on the hunt's mode, and the two unique
    constraints are what stop a second claim in either mode.
    """

    poneglyph = models.ForeignKey(Poneglyph, on_delete=models.CASCADE, related_name="claims")
    poneglyph_id: int
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="poneglyph_claims",
        help_text="Who handed the set in. Always filled, even in crew mode, so credit is kept.",
    )
    player_id: int | None
    crew = models.ForeignKey(
        Crew,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="poneglyph_claims",
        help_text="The crew the stone belongs to, in a crew hunt. Empty in an individual one.",
    )
    crew_id: int | None
    claimed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "poneglyphclaim"
        ordering = ("-claimed_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("poneglyph", "player"), condition=models.Q(crew__isnull=True), name="poneglyph_one_per_player"
            ),
            models.UniqueConstraint(
                fields=("poneglyph", "crew"), condition=models.Q(crew__isnull=False), name="poneglyph_one_per_crew"
            ),
        )

    def __str__(self) -> str:
        return f"{self.poneglyph_id} held by {self.crew_id or self.player_id}"


class HuntCompletion(models.Model):
    """The reward of a whole hunt, handed over once to a player or to a crew."""

    hunt = models.ForeignKey(Hunt, on_delete=models.CASCADE, related_name="completions")
    hunt_id: int
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, null=True, blank=True, related_name="hunt_completions"
    )
    player_id: int | None
    crew = models.ForeignKey(Crew, on_delete=models.CASCADE, null=True, blank=True, related_name="hunt_completions")
    crew_id: int | None
    completed_at = models.DateTimeField(auto_now_add=True)
    reward_instance = models.ForeignKey(
        BallInstance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The treasure handed over, when the hunt gives one.",
    )

    class Meta:
        managed = True
        db_table = "huntcompletion"
        ordering = ("-completed_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("hunt", "player"), condition=models.Q(crew__isnull=True), name="hunt_done_once_per_player"
            ),
            models.UniqueConstraint(
                fields=("hunt", "crew"), condition=models.Q(crew__isnull=False), name="hunt_done_once_per_crew"
            ),
        )

    def __str__(self) -> str:
        return f"{self.hunt_id} finished by {self.crew_id or self.player_id}"
