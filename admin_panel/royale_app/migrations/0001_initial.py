from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="RoyaleSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "enabled",
                    models.BooleanField(
                        default=False,
                        help_text="Accept end-of-match reports. Off means the bridge answers 503 and Royale "
                        "keeps its reports queued rather than losing them, so turning this off for an evening "
                        "costs nothing.",
                    ),
                ),
                (
                    "shared_secret",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=128,
                        help_text="The same secret Royale sends in its Authorization header. Leave empty to keep "
                        "the webhook server from starting at all. Generate a long random string; it never leaves "
                        "the host.",
                    ),
                ),
                (
                    "allowed_guild_ids",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="One server id per line. A report from any other server is refused with 403, "
                        "which Royale keeps and retries, so adding the server here is enough to let it through "
                        "afterwards. Leave empty to accept every server.",
                    ),
                ),
            ],
            options={
                "db_table": "royalesettings",
                "managed": True,
                "verbose_name_plural": "Royale settings",
            },
        ),
        migrations.CreateModel(
            name="RoyaleMatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "match_id",
                    models.CharField(
                        max_length=128,
                        unique=True,
                        help_text="Royale's own id for the match, the same string on every retry.",
                    ),
                ),
                ("guild_id", models.BigIntegerField(blank=True, null=True)),
                ("channel_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "mode",
                    models.CharField(blank=True, default="", max_length=32, help_text='"normal", or a boss key.'),
                ),
                ("island", models.CharField(blank=True, default="", max_length=64)),
                ("rounds", models.PositiveIntegerField(default=0)),
                (
                    "players_reported",
                    models.PositiveIntegerField(default=0, help_text="How many players the report carried."),
                ),
                (
                    "players_known",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="How many of them this bot already knew. The rest have never used it.",
                    ),
                ),
                (
                    "kills_reported",
                    models.PositiveIntegerField(default=0, help_text="Kills across every player in the report."),
                ),
                (
                    "points_awarded",
                    models.IntegerField(
                        default=0,
                        help_text="Crew war points this match actually handed out. Zero when no war is running, "
                        "when the war has no rule for a royale kill, or when nobody who played flies a flag.",
                    ),
                ),
                (
                    "report",
                    models.JSONField(
                        default=dict,
                        help_text="The report as it arrived, kept so a scoring argument can be settled.",
                    ),
                ),
                ("received_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "royalematch",
                "managed": True,
                "ordering": ("-received_at",),
                "verbose_name_plural": "Royale matches",
            },
        ),
        migrations.AddIndex(
            model_name="royalematch",
            index=models.Index(fields=["received_at"], name="royale_match_received_idx"),
        ),
    ]
