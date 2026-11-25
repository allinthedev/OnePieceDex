"""
The shop of an event pass: what its own currency buys.

An offer is either a bundle of treasures — a `Reward` of the pass itself, so nothing about handing out cards had
to be written a second time — or a boost, an effect that runs for everybody at once.

A boost is bought from any server and always lands on the **main** one: the point of buying an hour of rarer
treasures is the hour everybody plays through, not the server the buyer happened to be standing in. Boosts of
different kinds stack; buying one whose kind is already running extends the hour instead of stacking it, which is
what stops four people turning the same hour into four.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from eventpass_app.models import EventPass, Reward

from bd_models.models import Player, Special, specials


class BoostKind(models.TextChoices):
    """
    What a boost does. The magnitude below is read differently by each one, which is why they are listed apart.
    """

    SPECIAL = "special", "Chance of a special"
    RARITY = "rarity", "Rarer treasures"
    SPAWN_PARTY = "spawn_party", "A burst of spawns"
    BERRIES = "berries", "Berries per catch"


MAGNITUDE_HELP = (
    "Read differently by each kind. Chance of a special: the weight of the special is raised by this many "
    "percent, so 25 on a 2% special makes it 2.5%. Rarer treasures: how hard the rarity weighting is flattened, "
    "0 changing nothing and 50 roughly halving the edge common treasures have. Berries per catch: this many "
    "percent on top of the usual amount. A burst of spawns ignores it and uses the count below."
)


class Boost(models.Model):
    """
    One boost, as staff set it up. What the shop sells is an offer pointing at one of these, so the same boost
    can be sold at two prices, or handed out by a quest without being on sale at all.
    """

    name = models.CharField(max_length=64, unique=True, help_text="Shown to players, e.g. 'Blizzard hour'.")
    emoji = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Shown next to the name. A unicode character, or a Discord emoji copied whole as <:name:id>.",
    )
    kind = models.CharField(max_length=16, choices=BoostKind.choices, default=BoostKind.RARITY)
    description = models.TextField(
        blank=True, default="", help_text="A line telling players what it does. Shown in the shop."
    )
    magnitude = models.FloatField(default=25, help_text=MAGNITUDE_HELP)
    duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="How long one purchase runs for. Buying it again while it is running adds this on top of what "
        "is left rather than starting a second one.",
    )
    special = models.ForeignKey(
        Special,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Only for the chance of a special: the one whose chance goes up. Left empty, every special "
        "running at the time goes up together, which is rarely what an event wants.",
    )
    special_id: int | None
    spawns = models.PositiveSmallIntegerField(
        default=5, help_text="Only for a burst of spawns: how many go out, one after another."
    )
    channel_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Only for a burst of spawns: the channel they go out in, on the main server. Left empty, the "
        "main server's own spawn channel is used.",
    )
    announce = models.BooleanField(
        default=True, help_text="Say in the main server's spawn channel that the boost has started."
    )
    enabled = models.BooleanField(default=True, help_text="Turn this off to stop it being bought or handed out.")
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "eventshopboost"
        ordering = ("name",)

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    @property
    def duration(self) -> timedelta:
        return timedelta(minutes=self.duration_minutes)

    @property
    def cached_special(self) -> Special | None:
        return (specials.get(self.special_id) or self.special) if self.special_id else None

    def clean(self):
        if self.kind == BoostKind.SPAWN_PARTY and not self.spawns:
            raise ValidationError({"spawns": "A burst of spawns has to spawn something."})
        if self.kind != BoostKind.SPAWN_PARTY and self.duration_minutes < 1:
            raise ValidationError({"duration_minutes": "A boost that runs for no time at all does nothing."})
        if self.kind == BoostKind.RARITY and not 0 <= self.magnitude < 100:
            raise ValidationError({"magnitude": "Flattening is a percentage below 100."})

    def __str__(self) -> str:
        return self.name

class ActiveBoost(models.Model):
    """
    A boost running right now, on the main server.

    The kind and the magnitude are copied here rather than read back from the boost: an hour somebody paid for
    keeps running as it was sold, even if staff retune or delete the boost halfway through.
    """

    boost = models.ForeignKey(Boost, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs")
    boost_id: int | None
    kind = models.CharField(max_length=16, choices=BoostKind.choices)
    magnitude = models.FloatField(default=0)
    special = models.ForeignKey(Special, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    special_id: int | None
    label = models.CharField(max_length=96, blank=True, default="", help_text="What it was called when bought.")
    started_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(help_text="When it stops. Extended rather than doubled when bought again.")
    spawns_left = models.PositiveSmallIntegerField(
        default=0, help_text="Only for a burst of spawns: how many are still to go out."
    )
    channel_id = models.BigIntegerField(null=True, blank=True)
    bought_by = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    bought_by_id: int | None
    announced_at = models.DateTimeField(
        null=True, blank=True, help_text="When players were told. Clear it to announce again."
    )

    class Meta:
        managed = True
        db_table = "eventshopactiveboost"
        ordering = ("-started_at", "-pk")
        indexes = [models.Index(fields=("kind", "ends_at"), name="eventshop_active_live_idx")]

    def is_live(self, at=None) -> bool:
        at = at or timezone.now()
        return self.started_at <= at <= self.ends_at

    @property
    def cached_special(self) -> Special | None:
        return (specials.get(self.special_id) or self.special) if self.special_id else None

    def __str__(self) -> str:
        return f"{self.label or self.kind} until {self.ends_at:%Y-%m-%d %H:%M}"