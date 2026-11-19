"""
The bridge from Grand Line Royale.

Royale is a separate bot, on the same host, playing battle royale matches in Discord. When a
match ends it hands this one a report: what each player did, and nothing else. It never says
which crew anyone belongs to and it never says what a deed is worth — crew membership is read
from `crew_app` and the scoring table is the crew war's own, so no report can move a player
between crews or pay them more than an admin said.

The settings below are the switch. With no shared secret the webhook server never starts at
all, exactly like the vote webhook, so the bridge is off until someone fills it in.
"""

from asgiref.sync import sync_to_async
from django.db import models


class RoyaleSettings(models.Model):
    """The one row of settings for the bridge. Loaded fresh per report, so a change takes."""

    enabled = models.BooleanField(
        default=False,
        help_text="Accept end-of-match reports. Off means the bridge answers 503 and Royale keeps "
        "its reports queued rather than losing them, so turning this off for an evening costs nothing.",
    )
    shared_secret = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="The same secret Royale sends in its Authorization header. Leave empty to keep the "
        "webhook server from starting at all. Generate a long random string; it never leaves the host.",
    )
    allowed_guild_ids = models.TextField(
        blank=True,
        default="",
        help_text="One server id per line. A report from any other server is refused with 403, which "
        "Royale keeps and retries, so adding the server here is enough to let it through afterwards. "
        "Leave empty to accept every server.",
    )

    @property
    def guild_ids(self) -> set[int]:
        found = set()
        for line in self.allowed_guild_ids.splitlines():
            line = line.strip()
            if line.isdigit():
                found.add(int(line))
        return found

    def allows(self, guild_id: int | None) -> bool:
        """Whether a report from this server is accepted. No list means every server."""
        allowed = self.guild_ids
        if not allowed:
            return True
        return guild_id in allowed

    @classmethod
    def load(cls) -> "RoyaleSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    async def aload(cls) -> "RoyaleSettings":
        return await sync_to_async(cls.load)()

    class Meta:
        managed = True
        db_table = "royalesettings"
        verbose_name_plural = "Royale settings"

    def __str__(self) -> str:
        return "Royale settings"


class RoyaleMatch(models.Model):
    """
    One match reported, written before a single point is handed out.

    The unique `match_id` is what makes a retry harmless: Royale keeps a report queued until it
    gets a 2xx, so the same match can arrive several times, and the second arrival finds this row
    already there and scores nothing. It is the same trick `CrewWarPayout` uses to let a war be
    paid out twice without paying twice.

    The row is also the only place that remembers a report arrived at all, which is what answers
    "why did that match give nobody anything" a week later.
    """

    match_id = models.CharField(
        max_length=128,
        unique=True,
        help_text="Royale's own id for the match, the same string on every retry.",
    )
    guild_id = models.BigIntegerField(null=True, blank=True)
    channel_id = models.BigIntegerField(null=True, blank=True)
    mode = models.CharField(max_length=32, blank=True, default="", help_text='"normal", or a boss key.')
    island = models.CharField(max_length=64, blank=True, default="")
    rounds = models.PositiveIntegerField(default=0)

    players_reported = models.PositiveIntegerField(default=0, help_text="How many players the report carried.")
    players_known = models.PositiveIntegerField(
        default=0, help_text="How many of them this bot already knew. The rest have never used it."
    )
    kills_reported = models.PositiveIntegerField(default=0, help_text="Kills across every player in the report.")
    points_awarded = models.IntegerField(
        default=0,
        help_text="Crew war points this match actually handed out. Zero when no war is running, when "
        "the war has no rule for a royale kill, or when nobody who played flies a flag.",
    )

    report = models.JSONField(
        default=dict, help_text="The report as it arrived, kept so a scoring argument can be settled."
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "royalematch"
        ordering = ("-received_at",)
        verbose_name_plural = "Royale matches"
        indexes = (models.Index(fields=("received_at",), name="royale_match_received_idx"),)

    def __str__(self) -> str:
        return self.match_id
