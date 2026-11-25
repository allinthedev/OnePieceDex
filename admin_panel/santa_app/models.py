"""
Secret Santa: everyone writes down what they would like, everyone gives to one other player, nobody knows who
gave them theirs.

The draw is one single cycle — A gives to B, B to C, and the last one back to A — rather than random pairs. That
is what makes it a chain: everybody gives exactly once, everybody receives exactly once, and nobody is paired
back with the person giving to them.

**The giver is never named, and how a parcel was filled is never shown.** A parcel filled by a card, one paid for
in the event's currency and one the bot filled in because its giver never turned up all arrive looking exactly
the same. That is deliberate: there is no penalty for not giving, and naming the giver — or showing nothing where
a name would be — would be a penalty by the back door. `SantaGift.kind` is for staff and nobody else.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from eventpass_app.models import EventPass

from bd_models.enums import AnnouncementScope
from bd_models.models import Ball, BallInstance, Player, Special, balls, specials


class SecretSanta(models.Model):
    """One run of the exchange. Next year's is a new row."""

    name = models.CharField(max_length=64, help_text="Shown to players, e.g. 'Secret Santa 2026'.")
    emoji = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Shown next to the name. A unicode character, or a Discord emoji copied whole as <:name:id>.",
    )
    description = models.TextField(blank=True, default="", help_text="A line or two about how it works.")
    enabled = models.BooleanField(default=True, help_text="Turn this off and none of the commands do anything.")

    event_pass = models.ForeignKey(
        EventPass,
        on_delete=models.CASCADE,
        related_name="secret_santas",
        help_text="Where the currency comes from, for players who fill their parcel by paying rather than by "
        "giving one of their own cards.",
    )
    event_pass_id: int
    special = models.ForeignKey(
        Special,
        on_delete=models.CASCADE,
        related_name="secret_santas",
        help_text="What every card in a parcel comes out as. The Christmas special.",
    )
    special_id: int

    signup_opens_at = models.DateTimeField(help_text="Players can sign up from here. Times are UTC.")
    signup_closes_at = models.DateTimeField(help_text="And not after. The draw happens once this has passed.")
    wrap_until = models.DateTimeField(
        help_text="Last moment a player can fill the parcel they owe. Whatever is still empty afterwards is "
        "filled by the bot."
    )
    opens_at = models.DateTimeField(help_text="When parcels can be opened. Christmas morning.")
    closes_at = models.DateTimeField(help_text="Last moment a parcel can be opened. Nothing is lost before it.")

    wishlist_size = models.PositiveSmallIntegerField(
        default=3,
        validators=(MinValueValidator(1),),
        help_text="How many cards a player may ask for. Their Santa picks one of them.",
    )
    min_rarity = models.FloatField(
        default=0,
        help_text="The floor on what may be asked for. A LOWER rarity is a RARER treasure, so this is the "
        "rarest a card may be: set it to the rarity of your T10 and nothing rarer than a T10 can be wished for. "
        "Zero puts no limit on it at all.",
    )
    price = models.PositiveIntegerField(
        default=0,
        help_text="What it costs, in the pass's currency, to fill your parcel by paying instead of giving one "
        "of your own cards. Zero turns that way of filling it off.",
    )
    fill_the_rest = models.BooleanField(
        default=True,
        verbose_name="fill the empty parcels",
        help_text="Once the wrapping time has passed, the bot fills every parcel still empty with a card drawn "
        "from the receiver's own wishlist. Keep this on: it is what lets there be no penalty for not giving, "
        "since nobody can tell a filled parcel from a given one.",
    )
    announce_to = models.CharField(
        max_length=8,
        choices=AnnouncementScope.choices,
        default=AnnouncementScope.MAIN,
        help_text="Where the draw and the opening day are announced. Never anything about one player's parcel.",
    )
    drawn_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the chain was drawn, filled by the bot. Clear it and run the draw again to redraw — "
        "only safe before anybody has wrapped anything.",
    )
    filled_at = models.DateTimeField(
        null=True, blank=True, help_text="When the bot filled the empty parcels. Filled by the bot."
    )
    announced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the opening day was announced. Clear it to announce again. Nothing about any one "
        "player's parcel is ever announced.",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "secretsanta"
        ordering = ("-signup_opens_at", "pk")
        verbose_name = "Secret Santa"
        verbose_name_plural = "Secret Santas"

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    @property
    def cached_special(self) -> Special | None:
        return specials.get(self.special_id) or self.special

    def signups_open(self, at=None) -> bool:
        at = at or timezone.now()
        return self.enabled and self.signup_opens_at <= at <= self.signup_closes_at

    def wrapping_open(self, at=None) -> bool:
        """Whether a parcel can still be filled: once the chain is drawn, until the wrapping time is up."""
        at = at or timezone.now()
        return self.enabled and self.drawn_at is not None and at <= self.wrap_until

    def opening_open(self, at=None) -> bool:
        at = at or timezone.now()
        return self.enabled and self.opens_at <= at <= self.closes_at

    def may_be_wished(self, ball: Ball) -> bool:
        """Whether this treasure is common enough to be asked for."""
        return not self.min_rarity or float(ball.rarity) >= self.min_rarity

    def clean(self):
        order = (
            ("signup_opens_at", "signup_closes_at"),
            ("signup_closes_at", "wrap_until"),
            ("wrap_until", "opens_at"),
            ("opens_at", "closes_at"),
        )
        for first, second in order:
            if getattr(self, first) and getattr(self, second) and getattr(self, first) >= getattr(self, second):
                raise ValidationError({second: f"This comes after {first.replace('_', ' ')}."})

    def __str__(self) -> str:
        return self.name


class SantaEntry(models.Model):
    """
    One player taking part, and who they were drawn to give to.

    `gives_to` is the chain itself: following it from any entry walks every player once and comes back to where
    it started. It is unique, so no two players can be drawn to give to the same person.
    """

    santa = models.ForeignKey(SecretSanta, on_delete=models.CASCADE, related_name="entries")
    santa_id: int
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="santa_entries")
    player_id: int
    gives_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="given_by",
        help_text="The entry this one gives to, set by the draw.",
    )
    gives_to_id: int | None
    joined_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "santaentry"
        ordering = ("santa", "pk")
        constraints = [
            models.UniqueConstraint(fields=("santa", "player"), name="santa_entry_unique"),
            # the chain cannot fork: one giver per receiver
            models.UniqueConstraint(fields=("santa", "gives_to"), name="santa_entry_target_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.player_id} in {self.santa_id}"


class SantaWish(models.Model):
    """One card a player would like. Their Santa picks one of these, and nothing else can be given."""

    entry = models.ForeignKey(SantaEntry, on_delete=models.CASCADE, related_name="wishes")
    entry_id: int
    ball = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="santa_wishes")
    ball_id: int
    position = models.PositiveSmallIntegerField(default=1, help_text="Where it sits on the list, from one.")
    added_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "santawish"
        ordering = ("entry", "position", "pk")
        constraints = [
            models.UniqueConstraint(fields=("entry", "position"), name="santa_wish_slot_unique"),
            models.UniqueConstraint(fields=("entry", "ball"), name="santa_wish_ball_unique"),
        ]

    @property
    def cached_ball(self) -> Ball:
        return balls.get(self.ball_id) or self.ball

    def __str__(self) -> str:
        return self.cached_ball.country


class SantaGift(models.Model):
    """
    One parcel: what is in it, and nothing a player is ever shown about where it came from.

    The card itself is only created when the parcel is opened, so what sits here until Christmas morning is a
    description of a card rather than a card somebody could trade away early.
    """

    class Kind(models.TextChoices):
        CARD = "card", "A card the giver gave"
        PAID = "paid", "Paid for in the event's currency"
        FILLED = "filled", "Filled in by the bot"

    santa = models.ForeignKey(SecretSanta, on_delete=models.CASCADE, related_name="gifts")
    santa_id: int
    giver = models.ForeignKey(SantaEntry, on_delete=models.CASCADE, related_name="gift_given")
    giver_id: int
    receiver = models.ForeignKey(SantaEntry, on_delete=models.CASCADE, related_name="gift_received")
    receiver_id: int
    ball = models.ForeignKey(
        Ball, on_delete=models.CASCADE, related_name="santa_gifts", help_text="Which of the wishes it is."
    )
    ball_id: int
    kind = models.CharField(
        max_length=8,
        choices=Kind.choices,
        help_text="How the parcel came to be filled. For staff only — a player is never shown this, and that is "
        "the whole point of it.",
    )
    attack_bonus = models.IntegerField(default=0)
    health_bonus = models.IntegerField(default=0)
    roll_bonuses = models.BooleanField(
        default=False,
        help_text="Whether the card rolls its bonuses when the parcel is opened, as a catch does. Set for a "
        "parcel that was paid for or filled in, since no real card went into it.",
    )
    frame = models.JSONField(
        blank=True, default=dict, help_text="The frame the given card wore, carried into the card it becomes."
    )
    wrapped_at = models.DateTimeField(auto_now_add=True, editable=False)
    opened_at = models.DateTimeField(null=True, blank=True)
    instance = models.ForeignKey(
        BallInstance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The card it became, created when it was opened.",
    )

    class Meta:
        managed = True
        db_table = "santagift"
        ordering = ("-wrapped_at", "-pk")
        constraints = [
            models.UniqueConstraint(fields=("santa", "giver"), name="santa_gift_giver_unique"),
            models.UniqueConstraint(fields=("santa", "receiver"), name="santa_gift_receiver_unique"),
        ]
        indexes = [models.Index(fields=("santa", "opened_at"), name="santa_gift_unopened_idx")]

    @property
    def cached_ball(self) -> Ball:
        return balls.get(self.ball_id) or self.ball

    @property
    def opened(self) -> bool:
        return self.opened_at is not None

    def __str__(self) -> str:
        return f"{self.cached_ball.country} for {self.receiver_id}"
