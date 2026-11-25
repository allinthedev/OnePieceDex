"""
An advent calendar: one door a day, and what is behind each of them.

Everything a door gives is a `Reward` of the event pass — the same bundles a tier or the shop uses — so berries,
treasures, a frame, a special or the pass's own currency all work behind a door without this app knowing how any
of them are handed out. A door with no bundle gives nothing, which is a fine way to set a calendar up before the
rewards are decided.

A door opens on its own day and never before. A day that has gone by can still be bought open, in berries, which
is the one way a player catches up — and the reason the price is worth setting: it is where an event takes
currency back out of the economy.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from eventpass_app.models import EventPass, Reward

from bd_models.enums import AnnouncementScope
from bd_models.models import Player

# a calendar can run past Christmas, but not past a month
MAX_DOORS = 31


def door_date(starts_on: date, day: int) -> date:
    """The day door `day` opens. Door 1 opens on the first day, so the first door is not a day late."""
    return starts_on + timedelta(days=day - 1)


class AdventCalendar(models.Model):
    """
    One calendar. A dex can hold several — last year's, this year's — and only the enabled one is played.
    """

    event_pass = models.ForeignKey(
        EventPass,
        on_delete=models.CASCADE,
        related_name="advent_calendars",
        help_text="The event this calendar belongs to. Its currency is what a door can hand out, and its name "
        "is what players see.",
    )
    event_pass_id: int
    name = models.CharField(max_length=64, help_text="Shown at the top of the calendar.")
    emoji = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Shown next to the name. A unicode character, or a Discord emoji copied whole as <:name:id>.",
    )
    description = models.TextField(blank=True, default="", help_text="A line or two under the name.")
    enabled = models.BooleanField(
        default=True, help_text="Turn this off and nobody can open a door. Last year's calendar lives here."
    )
    starts_on = models.DateField(
        help_text="The day door 1 opens, UTC. Door 2 opens the day after, and so on. A day ends at midnight UTC."
    )
    door_count = models.PositiveSmallIntegerField(
        default=24,
        validators=(MinValueValidator(1), MaxValueValidator(MAX_DOORS)),
        verbose_name="doors",
        help_text="How many doors it has. Set 25 to include Christmas day itself.",
    )
    catch_up_price = models.PositiveIntegerField(
        default=0,
        help_text="Berries it costs to open a door whose day has gone by. Zero means no catching up at all: a "
        "day missed is missed.",
    )
    catch_up_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last moment a missed door can be bought open. Left empty, the day after the last door. This "
        "is the window where the event is over but players can still finish the calendar.",
    )
    surprise_chance = models.FloatField(
        default=0,
        validators=(MinValueValidator(0), MaxValueValidator(1)),
        help_text="Chance, between 0 and 1, that a surprise fires on top of the door being opened. It never "
        "replaces what the door gives.",
    )
    announce_to = models.CharField(
        max_length=8,
        choices=AnnouncementScope.choices,
        default=AnnouncementScope.NONE,
        help_text="Where a surprise worth shouting about is announced. The doors themselves are never announced.",
    )
    background = models.ImageField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Optional picture behind the grid of doors. Fitted to the grid, so anything roughly landscape works.",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "adventcalendar"
        ordering = ("-starts_on", "pk")

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    @property
    def ends_on(self) -> date:
        return door_date(self.starts_on, self.door_count)

    @property
    def closes_at(self):
        """The last moment a missed door can be bought, set or worked out from the last door."""
        if self.catch_up_until:
            return self.catch_up_until
        end = door_date(self.starts_on, self.door_count) + timedelta(days=1)
        return datetime(end.year, end.month, end.day, tzinfo=dt_timezone.utc)

    def day_today(self, at=None) -> int | None:
        """
        Which door today is, or None when today is outside the calendar.
        """
        at = at or timezone.now()
        today = at.astimezone(dt_timezone.utc).date()
        day = (today - self.starts_on).days + 1
        return day if 1 <= day <= self.door_count else None

    def __str__(self) -> str:
        return self.name


class AdventDoor(models.Model):
    """
    One door. What is behind it is a reward bundle, so a door is set up the same way a tier is.

    Christmas day is only a door like any other: give door 25 a bundle holding one pool line, with the Christmas
    special and a rarity range, and it hands out a random card from that range — a rare pack, with no code of
    its own.
    """

    calendar = models.ForeignKey(AdventCalendar, on_delete=models.CASCADE, related_name="doors")
    calendar_id: int
    day = models.PositiveSmallIntegerField(
        validators=(MinValueValidator(1), MaxValueValidator(MAX_DOORS)),
        help_text="Which day of the calendar this is. Door 1 opens on the day the calendar starts.",
    )
    reward = models.ForeignKey(
        Reward,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advent_doors",
        help_text="What is behind it. Left empty, the door opens on nothing, which is only useful while the "
        "calendar is being set up.",
    )
    reward_id: int | None
    message = models.CharField(
        max_length=256, blank=True, default="", help_text="Shown when it is opened, under what was given."
    )

    class Meta:
        managed = True
        db_table = "adventdoor"
        ordering = ("calendar", "day")
        constraints = [models.UniqueConstraint(fields=("calendar", "day"), name="advent_door_unique")]

    def opens_on(self, starts_on: date | None = None) -> date:
        return door_date(starts_on or self.calendar.starts_on, self.day)

    def __str__(self) -> str:
        return f"Day {self.day}"


class AdventStreak(models.Model):
    """
    A reward for having opened a number of doors — the 7th, the 14th, every one of them.

    Counted on doors opened rather than days in a row, because a door bought open is a door opened: a player who
    pays to catch up has caught up, and holding a broken run against them afterwards would make the price
    pointless.
    """

    calendar = models.ForeignKey(AdventCalendar, on_delete=models.CASCADE, related_name="streaks")
    calendar_id: int
    doors = models.PositiveSmallIntegerField(
        validators=(MinValueValidator(1), MaxValueValidator(MAX_DOORS)),
        help_text="Given once this many doors have been opened.",
    )
    reward = models.ForeignKey(Reward, on_delete=models.CASCADE, related_name="advent_streaks")
    reward_id: int
    message = models.CharField(max_length=256, blank=True, default="", help_text="Shown when it is reached.")

    class Meta:
        managed = True
        db_table = "adventstreak"
        ordering = ("calendar", "doors")
        constraints = [models.UniqueConstraint(fields=("calendar", "doors"), name="advent_streak_unique")]

    def __str__(self) -> str:
        return f"{self.doors} doors"


class AdventSurprise(models.Model):
    """
    Something that can happen on top of a door, drawn by weight when the calendar's chance fires.

    A surprise never replaces what the door gives. It can hand out its own bundle, and it can set a boost running
    for the whole server, which is what turns one player's door into everybody's hour.
    """

    calendar = models.ForeignKey(AdventCalendar, on_delete=models.CASCADE, related_name="surprises")
    calendar_id: int
    name = models.CharField(max_length=64, help_text="Shown to the player, e.g. 'A gust of snow'.")
    emoji = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="", help_text="Shown when it fires.")
    weight = models.FloatField(
        default=1,
        validators=(MinValueValidator(0),),
        help_text="How likely this one is among the surprises. A surprise weighted 3 is drawn three times as "
        "often as one weighted 1.",
    )
    reward = models.ForeignKey(
        Reward,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advent_surprises",
        help_text="An extra bundle for the player who opened the door.",
    )
    reward_id: int | None
    boost = models.ForeignKey(
        "eventshop_app.Boost",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advent_surprises",
        help_text="A boost set running for everyone on the main server — a burst of spawns, an hour of rarer "
        "treasures. Exactly as if it had been bought in the shop, extension included.",
    )
    boost_id: int | None
    once_per_player = models.BooleanField(
        default=False, help_text="Tick this and a player can only ever get this surprise once."
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "adventsurprise"
        ordering = ("calendar", "-weight", "name")

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    def clean(self):
        if self.reward_id is None and self.boost_id is None:
            raise ValidationError("A surprise that gives nothing and boosts nothing does nothing.")

    def __str__(self) -> str:
        return self.name


class AdventOpening(models.Model):
    """
    One door a player has opened. The row is what stops a door being opened twice, so it is written before
    anything is handed out.
    """

    calendar = models.ForeignKey(AdventCalendar, on_delete=models.CASCADE, related_name="openings")
    calendar_id: int
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="advent_openings")
    player_id: int
    day = models.PositiveSmallIntegerField()
    paid = models.PositiveIntegerField(
        default=0, help_text="Berries it cost, for a door bought open after its day. Zero when opened on time."
    )
    surprise = models.ForeignKey(AdventSurprise, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    summary = models.CharField(max_length=256, blank=True, default="", help_text="What came out of it.")
    opened_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "adventopening"
        ordering = ("-opened_at", "-pk")
        constraints = [models.UniqueConstraint(fields=("calendar", "player", "day"), name="advent_opening_unique")]
        indexes = [models.Index(fields=("calendar", "player"), name="advent_opening_player_idx")]

    def __str__(self) -> str:
        return f"Day {self.day} by {self.player_id}"


class AdventStreakGrant(models.Model):
    """One streak reward already given, so reaching it again cannot hand it out twice."""

    streak = models.ForeignKey(AdventStreak, on_delete=models.CASCADE, related_name="grants")
    streak_id: int
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="advent_streak_grants")
    player_id: int
    summary = models.CharField(max_length=256, blank=True, default="")
    given_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "adventstreakgrant"
        constraints = [models.UniqueConstraint(fields=("streak", "player"), name="advent_streak_grant_unique")]

    def __str__(self) -> str:
        return f"{self.streak_id} for {self.player_id}"
