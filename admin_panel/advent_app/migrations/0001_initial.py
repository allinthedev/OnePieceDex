import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

PASS_HELP = (
    "The event this calendar belongs to. Its currency is what a door can hand out, and its name is what players see."
)
EMOJI_HELP = "Shown next to the name. A unicode character, or a Discord emoji copied whole as <:name:id>."
ENABLED_HELP = "Turn this off and nobody can open a door. Last year's calendar lives here."
STARTS_HELP = "The day door 1 opens, UTC. Door 2 opens the day after, and so on. A day ends at midnight UTC."
DOORS_HELP = "How many doors it has. Set 25 to include Christmas day itself."
CATCH_UP_HELP = (
    "Berries it costs to open a door whose day has gone by. Zero means no catching up at all: a day missed is missed."
)
UNTIL_HELP = (
    "Last moment a missed door can be bought open. Left empty, the day after the last door. This is the window "
    "where the event is over but players can still finish the calendar."
)
SURPRISE_HELP = (
    "Chance, between 0 and 1, that a surprise fires on top of the door being opened. It never replaces what the "
    "door gives."
)
ANNOUNCE_HELP = "Where a surprise worth shouting about is announced. The doors themselves are never announced."
BACKGROUND_HELP = "Optional picture behind the grid of doors. Fitted to the grid, so anything roughly landscape works."
DAY_HELP = "Which day of the calendar this is. Door 1 opens on the day the calendar starts."
DOOR_REWARD_HELP = (
    "What is behind it. Left empty, the door opens on nothing, which is only useful while the calendar is being set up."
)
STREAK_HELP = "Given once this many doors have been opened."
WEIGHT_HELP = (
    "How likely this one is among the surprises. A surprise weighted 3 is drawn three times as often as one weighted 1."
)
SURPRISE_REWARD_HELP = "An extra bundle for the player who opened the door."
SURPRISE_BOOST_HELP = (
    "A boost set running for everyone on the main server — a burst of spawns, an hour of rarer treasures. "
    "Exactly as if it had been bought in the shop, extension included."
)
PAID_HELP = "Berries it cost, for a door bought open after its day. Zero when opened on time."
SCOPES = [("all", "Every spawn channel"), ("main", "The main server only"), ("none", "Nowhere, announce nothing")]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("eventpass_app", "0015_pass_currency"),
        ("eventshop_app", "0001_initial"),
        ("bd_models", "0025_special_counts_toward_collectors"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdventCalendar",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Shown at the top of the calendar.", max_length=64)),
                ("emoji", models.CharField(blank=True, default="", help_text=EMOJI_HELP, max_length=64)),
                ("description", models.TextField(blank=True, default="", help_text="A line or two under the name.")),
                ("enabled", models.BooleanField(default=True, help_text=ENABLED_HELP)),
                ("starts_on", models.DateField(help_text=STARTS_HELP)),
                (
                    "door_count",
                    models.PositiveSmallIntegerField(
                        default=24,
                        help_text=DOORS_HELP,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(31),
                        ],
                        verbose_name="doors",
                    ),
                ),
                ("catch_up_price", models.PositiveIntegerField(default=0, help_text=CATCH_UP_HELP)),
                ("catch_up_until", models.DateTimeField(blank=True, help_text=UNTIL_HELP, null=True)),
                (
                    "surprise_chance",
                    models.FloatField(
                        default=0,
                        help_text=SURPRISE_HELP,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(1),
                        ],
                    ),
                ),
                (
                    "announce_to",
                    models.CharField(choices=SCOPES, default="none", help_text=ANNOUNCE_HELP, max_length=8),
                ),
                (
                    "background",
                    models.ImageField(blank=True, help_text=BACKGROUND_HELP, max_length=200, null=True, upload_to=""),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "event_pass",
                    models.ForeignKey(
                        help_text=PASS_HELP,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="advent_calendars",
                        to="eventpass_app.eventpass",
                    ),
                ),
            ],
            options={"db_table": "adventcalendar", "ordering": ("-starts_on", "pk"), "managed": True},
        ),
        migrations.CreateModel(
            name="AdventSurprise",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Shown to the player, e.g. 'A gust of snow'.", max_length=64)),
                ("emoji", models.CharField(blank=True, default="", max_length=64)),
                ("description", models.TextField(blank=True, default="", help_text="Shown when it fires.")),
                (
                    "weight",
                    models.FloatField(
                        default=1, help_text=WEIGHT_HELP, validators=[django.core.validators.MinValueValidator(0)]
                    ),
                ),
                (
                    "once_per_player",
                    models.BooleanField(
                        default=False, help_text="Tick this and a player can only ever get this surprise once."
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                (
                    "boost",
                    models.ForeignKey(
                        blank=True,
                        help_text=SURPRISE_BOOST_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="advent_surprises",
                        to="eventshop_app.boost",
                    ),
                ),
                (
                    "calendar",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="surprises",
                        to="advent_app.adventcalendar",
                    ),
                ),
                (
                    "reward",
                    models.ForeignKey(
                        blank=True,
                        help_text=SURPRISE_REWARD_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="advent_surprises",
                        to="eventpass_app.reward",
                    ),
                ),
            ],
            options={"db_table": "adventsurprise", "ordering": ("calendar", "-weight", "name"), "managed": True},
        ),
        migrations.CreateModel(
            name="AdventDoor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "day",
                    models.PositiveSmallIntegerField(
                        help_text=DAY_HELP,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(31),
                        ],
                    ),
                ),
                (
                    "message",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Shown when it is opened, under what was given.",
                        max_length=256,
                    ),
                ),
                (
                    "calendar",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="doors",
                        to="advent_app.adventcalendar",
                    ),
                ),
                (
                    "reward",
                    models.ForeignKey(
                        blank=True,
                        help_text=DOOR_REWARD_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="advent_doors",
                        to="eventpass_app.reward",
                    ),
                ),
            ],
            options={"db_table": "adventdoor", "ordering": ("calendar", "day"), "managed": True},
        ),
        migrations.CreateModel(
            name="AdventStreak",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "doors",
                    models.PositiveSmallIntegerField(
                        help_text=STREAK_HELP,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(31),
                        ],
                    ),
                ),
                (
                    "message",
                    models.CharField(blank=True, default="", help_text="Shown when it is reached.", max_length=256),
                ),
                (
                    "calendar",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="streaks",
                        to="advent_app.adventcalendar",
                    ),
                ),
                (
                    "reward",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="advent_streaks",
                        to="eventpass_app.reward",
                    ),
                ),
            ],
            options={"db_table": "adventstreak", "ordering": ("calendar", "doors"), "managed": True},
        ),
        migrations.CreateModel(
            name="AdventOpening",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day", models.PositiveSmallIntegerField()),
                ("paid", models.PositiveIntegerField(default=0, help_text=PAID_HELP)),
                ("summary", models.CharField(blank=True, default="", help_text="What came out of it.", max_length=256)),
                ("opened_at", models.DateTimeField(auto_now_add=True)),
                (
                    "calendar",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="openings",
                        to="advent_app.adventcalendar",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="advent_openings",
                        to="bd_models.player",
                    ),
                ),
                (
                    "surprise",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="advent_app.adventsurprise",
                    ),
                ),
            ],
            options={"db_table": "adventopening", "ordering": ("-opened_at", "-pk"), "managed": True},
        ),
        migrations.CreateModel(
            name="AdventStreakGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("summary", models.CharField(blank=True, default="", max_length=256)),
                ("given_at", models.DateTimeField(auto_now_add=True)),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="advent_streak_grants",
                        to="bd_models.player",
                    ),
                ),
                (
                    "streak",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="grants", to="advent_app.adventstreak"
                    ),
                ),
            ],
            options={"db_table": "adventstreakgrant", "managed": True},
        ),
        migrations.AddConstraint(
            model_name="adventdoor",
            constraint=models.UniqueConstraint(fields=("calendar", "day"), name="advent_door_unique"),
        ),
        migrations.AddConstraint(
            model_name="adventstreak",
            constraint=models.UniqueConstraint(fields=("calendar", "doors"), name="advent_streak_unique"),
        ),
        migrations.AddConstraint(
            model_name="adventopening",
            constraint=models.UniqueConstraint(fields=("calendar", "player", "day"), name="advent_opening_unique"),
        ),
        migrations.AddIndex(
            model_name="adventopening",
            index=models.Index(fields=["calendar", "player"], name="advent_opening_player_idx"),
        ),
        migrations.AddConstraint(
            model_name="adventstreakgrant",
            constraint=models.UniqueConstraint(fields=("streak", "player"), name="advent_streak_grant_unique"),
        ),
    ]
