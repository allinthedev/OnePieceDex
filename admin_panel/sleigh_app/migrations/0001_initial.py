import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

SPECIAL_HELP = (
    "What every card put in here becomes. The Christmas special: a card only ever gains it by being given "
    "away, which is what makes a sleigh card worth having."
)
EMOJI_HELP = "Shown next to the name. A unicode character, or a Discord emoji copied whole as <:name:id>."
PER_DAY_HELP = "How many cards one player may put in per day. One is what makes the choice matter."
GOAL_HELP = "How many cards fill it, for the bar players see. Zero hides the bar."
BASE_HELP = "Points a gift of the pivot rarity below is worth to the giver's crew."
PIVOT_HELP = (
    "The rarity worth exactly the points above. A LOWER rarity is a RARER treasure, so a card ten times rarer "
    "than this scores ten times as much — up to the ceiling below."
)
CAP_HELP = "Most points one gift can ever be worth, however rare the card."
ANNOUNCE_HELP = "Where the sleigh says it has been filled, and where its waves are announced."
EMPTY_HELP = (
    "When the leftovers start going back out as spawns. Left empty, nothing is ever released and staff hand the "
    "cards out themselves."
)
WAVES_HELP = (
    "How many waves the leftovers are split into. Four waves six hours apart give every timezone a fair shot at them."
)
CHANNEL_HELP = "Where the waves spawn, on the main server. Left empty, the main server's own spawn channel."
GIVEN_BY_HELP = "Who gave it. Empty for a card staff put in themselves."
CREW_HELP = "The crew the gift scored for, as it stood on the day."
FRAME_HELP = "The frame the given card wore, carried over to the card it becomes."
RARITY_HELP = "The card's rarity on the day, kept so the points can be explained."
CLAIMED_HELP = "Who ended up with it, when staff handed it to someone."
SCOPES = [("all", "Every spawn channel"), ("main", "The main server only"), ("none", "Nowhere, announce nothing")]


class Migration(migrations.Migration):
    initial = True

    dependencies = [("bd_models", "0025_special_counts_toward_collectors"), ("crew_app", "0012_sleigh_gift")]

    operations = [
        migrations.CreateModel(
            name="Sleigh",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Shown to players, e.g. 'The sleigh'.", max_length=64)),
                ("emoji", models.CharField(blank=True, default="", help_text=EMOJI_HELP, max_length=64)),
                (
                    "description",
                    models.TextField(blank=True, default="", help_text="A line or two about what it is for."),
                ),
                ("enabled", models.BooleanField(default=True, help_text="Turn this off and nothing more goes in.")),
                ("opens_at", models.DateTimeField(help_text="Nothing can be given before this. Times are UTC.")),
                (
                    "closes_at",
                    models.DateTimeField(help_text="And nothing after it. The sleigh empties itself afterwards."),
                ),
                (
                    "per_day",
                    models.PositiveSmallIntegerField(
                        default=1, help_text=PER_DAY_HELP, validators=[django.core.validators.MinValueValidator(1)]
                    ),
                ),
                ("goal", models.PositiveIntegerField(default=0, help_text=GOAL_HELP)),
                ("points_base", models.PositiveIntegerField(default=50, help_text=BASE_HELP)),
                (
                    "points_pivot",
                    models.FloatField(
                        default=0.1, help_text=PIVOT_HELP, validators=[django.core.validators.MinValueValidator(0.0001)]
                    ),
                ),
                ("points_cap", models.PositiveIntegerField(default=2000, help_text=CAP_HELP)),
                (
                    "announce_to",
                    models.CharField(choices=SCOPES, default="main", help_text=ANNOUNCE_HELP, max_length=8),
                ),
                ("empty_at", models.DateTimeField(blank=True, help_text=EMPTY_HELP, null=True)),
                (
                    "wave_count",
                    models.PositiveSmallIntegerField(
                        default=4,
                        help_text=WAVES_HELP,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="waves",
                    ),
                ),
                (
                    "wave_hours",
                    models.PositiveSmallIntegerField(
                        default=6,
                        help_text="Hours between one wave and the next.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                ("spawn_channel_id", models.BigIntegerField(blank=True, help_text=CHANNEL_HELP, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "special",
                    models.ForeignKey(
                        help_text=SPECIAL_HELP,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sleighs",
                        to="bd_models.special",
                    ),
                ),
            ],
            options={
                "db_table": "sleigh",
                "ordering": ("-opens_at", "pk"),
                "verbose_name_plural": "sleighs",
                "managed": True,
            },
        ),
        migrations.CreateModel(
            name="SleighCard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("attack_bonus", models.IntegerField(default=0)),
                ("health_bonus", models.IntegerField(default=0)),
                ("frame", models.JSONField(blank=True, default=dict, help_text=FRAME_HELP)),
                ("rarity", models.FloatField(help_text=RARITY_HELP)),
                ("points", models.PositiveIntegerField(default=0, help_text="What the gift scored for the crew.")),
                ("given_at", models.DateTimeField(auto_now_add=True)),
                (
                    "released_at",
                    models.DateTimeField(
                        blank=True, help_text="When it went back out as a spawn, for anyone to catch.", null=True
                    ),
                ),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "ball",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="sleigh_cards", to="bd_models.ball"
                    ),
                ),
                (
                    "claimed_by",
                    models.ForeignKey(
                        blank=True,
                        help_text=CLAIMED_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sleigh_claims",
                        to="bd_models.player",
                    ),
                ),
                (
                    "claimed_instance",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="bd_models.ballinstance",
                    ),
                ),
                (
                    "crew",
                    models.ForeignKey(
                        blank=True,
                        help_text=CREW_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sleigh_gifts",
                        to="crew_app.crew",
                    ),
                ),
                (
                    "given_by",
                    models.ForeignKey(
                        blank=True,
                        help_text=GIVEN_BY_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sleigh_gifts",
                        to="bd_models.player",
                    ),
                ),
                (
                    "sleigh",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="cards", to="sleigh_app.sleigh"
                    ),
                ),
            ],
            options={"db_table": "sleighcard", "ordering": ("-given_at", "-pk"), "managed": True},
        ),
        migrations.CreateModel(
            name="SleighWave",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveSmallIntegerField(help_text="Counting from one.")),
                ("due_at", models.DateTimeField(help_text="When this wave starts going out.")),
                (
                    "cards",
                    models.PositiveIntegerField(default=0, help_text="How many cards this wave was given to send."),
                ),
                ("sent", models.PositiveIntegerField(default=0, help_text="How many have gone out so far.")),
                (
                    "announced_at",
                    models.DateTimeField(
                        blank=True, help_text="When players were told. Clear it to announce again.", null=True
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "sleigh",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="waves", to="sleigh_app.sleigh"
                    ),
                ),
            ],
            options={"db_table": "sleighwave", "ordering": ("sleigh", "position"), "managed": True},
        ),
        migrations.AddIndex(
            model_name="sleighcard", index=models.Index(fields=["sleigh", "released_at"], name="sleigh_card_inside_idx")
        ),
        migrations.AddIndex(
            model_name="sleighcard", index=models.Index(fields=["sleigh", "given_by"], name="sleigh_card_giver_idx")
        ),
        migrations.AddConstraint(
            model_name="sleighwave",
            constraint=models.UniqueConstraint(fields=("sleigh", "position"), name="sleigh_wave_unique"),
        ),
    ]
