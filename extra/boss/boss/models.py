"""
Boss fights set up ahead of time.

The fight itself lives in memory inside the cog — that is how this package has always worked,
and nothing here changes it. What is stored is the plan: which treasure, how much HP, where and
when, and how the automatic rounds should be run once people have had time to join.

Note that the models declared inside `cog.py` are not these. They are never queried, and since
they live in a module Django does not import at startup, they have no tables either. This file
is the app's real model module.
"""

from django.core.validators import MinValueValidator
from django.db import models

from bd_models.models import Ball


class BossSchedule(models.Model):
    class Pattern(models.TextChoices):
        ALTERNATE = "alternate", "Attack, defend, attack, defend..."
        RANDOM = "random", "Random order"

    name = models.CharField(
        max_length=64, help_text="For your own reference in this list, e.g. 'Kaido, Friday night'."
    )
    ball = models.ForeignKey(
        Ball, on_delete=models.CASCADE, related_name="boss_schedules", help_text="The treasure fought as the boss."
    )
    ball_id: int
    hp = models.PositiveBigIntegerField(
        validators=(MinValueValidator(1),), help_text="The boss's health pool."
    )
    channel_id = models.BigIntegerField(help_text="Discord channel ID the fight runs in.")
    starts_at = models.DateTimeField(help_text="When the bot opens the fight for players to join. UTC.")
    join_minutes = models.PositiveIntegerField(
        default=10,
        validators=(MinValueValidator(1),),
        help_text="How long players have to join before the first round begins.",
    )
    enabled = models.BooleanField(
        default=True, help_text="Turn this off to cancel a planned fight without deleting it."
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Filled in by the bot when the fight opened. Clear it to have the plan run again.",
    )

    auto = models.BooleanField(
        default=True,
        help_text="Run the rounds automatically once the joining window closes. Off means the fight opens and "
        "waits for an admin to drive it by hand.",
    )
    min_damage = models.PositiveIntegerField(
        default=500, help_text="Damage of the boss's first attack, when running automatically."
    )
    max_damage = models.PositiveIntegerField(
        default=4000, help_text="And of its last. The rounds in between climb evenly between the two."
    )
    swings = models.PositiveIntegerField(
        default=8,
        validators=(MinValueValidator(1),),
        help_text="How many attacking rounds. Each is paired with a defending round.",
    )
    pattern = models.CharField(
        max_length=16,
        choices=Pattern.choices,
        default=Pattern.ALTERNATE,
        help_text="Whether the boss takes turns attacking and defending, or mixes them up. Random never lets "
        "it attack more than twice in a row.",
    )
    seconds_per_round = models.PositiveIntegerField(
        default=180,
        validators=(MinValueValidator(180),),
        help_text="How long players get to pick each round. Three minutes at least, and whoever has not "
        "picked is pinged a minute before it closes.",
    )

    start_image = models.ImageField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Shown when the fight opens. Falls back to the treasure's own card.",
    )
    attack_image = models.ImageField(
        max_length=200, null=True, blank=True, help_text="Shown when the boss attacks. A GIF works."
    )
    defend_image = models.ImageField(
        max_length=200, null=True, blank=True, help_text="Shown when the boss defends. A GIF works."
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    def is_due(self, at) -> bool:
        """Whether the bot should open this fight now."""
        return self.enabled and self.started_at is None and self.starts_at <= at

    class Meta:
        managed = True
        db_table = "bossschedule"
        ordering = ("-starts_at",)
        verbose_name = "planned boss"
        verbose_name_plural = "planned bosses"
        constraints = (
            models.CheckConstraint(
                condition=models.Q(max_damage__gte=models.F("min_damage")), name="boss_damage_range",
            ),
        )

    def __str__(self) -> str:
        return self.name
