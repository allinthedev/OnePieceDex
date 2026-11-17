"""
Crews: the side a player picks, and plays for.

A player belongs to one crew at a time, chosen from /player settings. Everything built on top
of crews — a hunt run as a race between them, a war scored over a season — reads membership
from here rather than keeping its own idea of who is on which side.
"""

from django.db import models
from django.utils import timezone

from bd_models.models import Player


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
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    rules: models.QuerySet["CrewWarRule"]

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
        BATTLE_PLAYED = "battle_played", "Took part in a battle"
        BATTLE_WIN = "battle_win", "Won a battle"
        BOSS_PLAYED = "boss_played", "Took part in a boss fight"
        BOSS_WIN = "boss_win", "Won a boss fight"
        BOUNTY_CLAIMED = "bounty_claimed", "Caught a wanted treasure"
        PONEGLYPH_CLAIMED = "poneglyph_claimed", "Claimed a poneglyph"
        HUNT_COMPLETED = "hunt_completed", "Finished a poneglyph hunt"

    war = models.ForeignKey(CrewWar, on_delete=models.CASCADE, related_name="rules")
    war_id: int
    source = models.CharField(max_length=32, choices=Source.choices)
    points = models.IntegerField(default=1, help_text="Added to the crew's score. A negative number takes points off.")
    daily_cap = models.PositiveIntegerField(
        default=0,
        help_text="Most points one player can earn from this deed in a day. 0 means no limit — handy on the "
        "deeds a player could repeat all evening.",
    )

    class Meta:
        managed = True
        db_table = "crewwarrule"
        ordering = ("source",)
        unique_together = (("war", "source"),)

    def __str__(self) -> str:
        return f"{self.get_source_display()}: {self.points}"


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
    points = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "crewwarentry"
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("war", "crew"), name="crewwar_war_crew_idx"),
            models.Index(fields=("war", "player"), name="crewwar_war_player_idx"),
            models.Index(fields=("war", "player", "source", "created_at"), name="crewwar_cap_idx"),
        )

    def __str__(self) -> str:
        return f"{self.crew_id} +{self.points} ({self.source})"
