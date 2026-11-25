import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

EMOJI_HELP = "Shown next to the name. A unicode character, or a Discord emoji copied whole as <:name:id>."
PASS_HELP = (
    "Where the currency comes from, for players who fill their parcel by paying rather than by giving one of "
    "their own cards."
)
SPECIAL_HELP = "What every card in a parcel comes out as. The Christmas special."
WRAP_HELP = (
    "Last moment a player can fill the parcel they owe. Whatever is still empty afterwards is filled by the bot."
)
SIZE_HELP = "How many cards a player may ask for. Their Santa picks one of them."
RARITY_HELP = (
    "The floor on what may be asked for. A LOWER rarity is a RARER treasure, so this is the rarest a card may "
    "be: set it to the rarity of your T10 and nothing rarer than a T10 can be wished for. Zero puts no limit "
    "on it at all."
)
PRICE_HELP = (
    "What it costs, in the pass's currency, to fill your parcel by paying instead of giving one of your own "
    "cards. Zero turns that way of filling it off."
)
FILL_HELP = (
    "Once the wrapping time has passed, the bot fills every parcel still empty with a card drawn from the "
    "receiver's own wishlist. Keep this on: it is what lets there be no penalty for not giving, since nobody "
    "can tell a filled parcel from a given one."
)
ANNOUNCE_HELP = "Where the draw and the opening day are announced. Never anything about one player's parcel."
DRAWN_HELP = (
    "When the chain was drawn, filled by the bot. Clear it and run the draw again to redraw — only safe before "
    "anybody has wrapped anything."
)
ANNOUNCED_HELP = (
    "When the opening day was announced. Clear it to announce again. Nothing about any one player's parcel is "
    "ever announced."
)
GIVES_TO_HELP = "The entry this one gives to, set by the draw."
KIND_HELP = (
    "How the parcel came to be filled. For staff only — a player is never shown this, and that is the whole "
    "point of it."
)
ROLL_HELP = (
    "Whether the card rolls its bonuses when the parcel is opened, as a catch does. Set for a parcel that was "
    "paid for or filled in, since no real card went into it."
)
FRAME_HELP = "The frame the given card wore, carried into the card it becomes."
INSTANCE_HELP = "The card it became, created when it was opened."
SCOPES = [("all", "Every spawn channel"), ("main", "The main server only"), ("none", "Nowhere, announce nothing")]
KINDS = [
    ("card", "A card the giver gave"),
    ("paid", "Paid for in the event's currency"),
    ("filled", "Filled in by the bot"),
]


class Migration(migrations.Migration):
    initial = True

    dependencies = [("eventpass_app", "0015_pass_currency"), ("bd_models", "0025_special_counts_toward_collectors")]

    operations = [
        migrations.CreateModel(
            name="SecretSanta",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Shown to players, e.g. 'Secret Santa 2026'.", max_length=64)),
                ("emoji", models.CharField(blank=True, default="", help_text=EMOJI_HELP, max_length=64)),
                (
                    "description",
                    models.TextField(blank=True, default="", help_text="A line or two about how it works."),
                ),
                (
                    "enabled",
                    models.BooleanField(default=True, help_text="Turn this off and none of the commands do anything."),
                ),
                ("signup_opens_at", models.DateTimeField(help_text="Players can sign up from here. Times are UTC.")),
                (
                    "signup_closes_at",
                    models.DateTimeField(help_text="And not after. The draw happens once this has passed."),
                ),
                ("wrap_until", models.DateTimeField(help_text=WRAP_HELP)),
                ("opens_at", models.DateTimeField(help_text="When parcels can be opened. Christmas morning.")),
                (
                    "closes_at",
                    models.DateTimeField(help_text="Last moment a parcel can be opened. Nothing is lost before it."),
                ),
                (
                    "wishlist_size",
                    models.PositiveSmallIntegerField(
                        default=3, help_text=SIZE_HELP, validators=[django.core.validators.MinValueValidator(1)]
                    ),
                ),
                ("min_rarity", models.FloatField(default=0, help_text=RARITY_HELP)),
                ("price", models.PositiveIntegerField(default=0, help_text=PRICE_HELP)),
                (
                    "fill_the_rest",
                    models.BooleanField(default=True, help_text=FILL_HELP, verbose_name="fill the empty parcels"),
                ),
                (
                    "announce_to",
                    models.CharField(choices=SCOPES, default="main", help_text=ANNOUNCE_HELP, max_length=8),
                ),
                ("drawn_at", models.DateTimeField(blank=True, help_text=DRAWN_HELP, null=True)),
                (
                    "filled_at",
                    models.DateTimeField(
                        blank=True, help_text="When the bot filled the empty parcels. Filled by the bot.", null=True
                    ),
                ),
                ("announced_at", models.DateTimeField(blank=True, help_text=ANNOUNCED_HELP, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "event_pass",
                    models.ForeignKey(
                        help_text=PASS_HELP,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="secret_santas",
                        to="eventpass_app.eventpass",
                    ),
                ),
                (
                    "special",
                    models.ForeignKey(
                        help_text=SPECIAL_HELP,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="secret_santas",
                        to="bd_models.special",
                    ),
                ),
            ],
            options={
                "db_table": "secretsanta",
                "ordering": ("-signup_opens_at", "pk"),
                "verbose_name": "Secret Santa",
                "verbose_name_plural": "Secret Santas",
                "managed": True,
            },
        ),
        migrations.CreateModel(
            name="SantaEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                (
                    "gives_to",
                    models.ForeignKey(
                        blank=True,
                        help_text=GIVES_TO_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="given_by",
                        to="santa_app.santaentry",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="santa_entries", to="bd_models.player"
                    ),
                ),
                (
                    "santa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="santa_app.secretsanta"
                    ),
                ),
            ],
            options={"db_table": "santaentry", "ordering": ("santa", "pk"), "managed": True},
        ),
        migrations.CreateModel(
            name="SantaWish",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "position",
                    models.PositiveSmallIntegerField(default=1, help_text="Where it sits on the list, from one."),
                ),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                (
                    "ball",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="santa_wishes", to="bd_models.ball"
                    ),
                ),
                (
                    "entry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="wishes", to="santa_app.santaentry"
                    ),
                ),
            ],
            options={"db_table": "santawish", "ordering": ("entry", "position", "pk"), "managed": True},
        ),
        migrations.CreateModel(
            name="SantaGift",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=KINDS, help_text=KIND_HELP, max_length=8)),
                ("attack_bonus", models.IntegerField(default=0)),
                ("health_bonus", models.IntegerField(default=0)),
                ("roll_bonuses", models.BooleanField(default=False, help_text=ROLL_HELP)),
                ("frame", models.JSONField(blank=True, default=dict, help_text=FRAME_HELP)),
                ("wrapped_at", models.DateTimeField(auto_now_add=True)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                (
                    "ball",
                    models.ForeignKey(
                        help_text="Which of the wishes it is.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="santa_gifts",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "giver",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gift_given",
                        to="santa_app.santaentry",
                    ),
                ),
                (
                    "instance",
                    models.ForeignKey(
                        blank=True,
                        help_text=INSTANCE_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="bd_models.ballinstance",
                    ),
                ),
                (
                    "receiver",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gift_received",
                        to="santa_app.santaentry",
                    ),
                ),
                (
                    "santa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="gifts", to="santa_app.secretsanta"
                    ),
                ),
            ],
            options={"db_table": "santagift", "ordering": ("-wrapped_at", "-pk"), "managed": True},
        ),
        migrations.AddConstraint(
            model_name="santaentry",
            constraint=models.UniqueConstraint(fields=("santa", "player"), name="santa_entry_unique"),
        ),
        migrations.AddConstraint(
            model_name="santaentry",
            constraint=models.UniqueConstraint(fields=("santa", "gives_to"), name="santa_entry_target_unique"),
        ),
        migrations.AddConstraint(
            model_name="santawish",
            constraint=models.UniqueConstraint(fields=("entry", "position"), name="santa_wish_slot_unique"),
        ),
        migrations.AddConstraint(
            model_name="santawish",
            constraint=models.UniqueConstraint(fields=("entry", "ball"), name="santa_wish_ball_unique"),
        ),
        migrations.AddConstraint(
            model_name="santagift",
            constraint=models.UniqueConstraint(fields=("santa", "giver"), name="santa_gift_giver_unique"),
        ),
        migrations.AddConstraint(
            model_name="santagift",
            constraint=models.UniqueConstraint(fields=("santa", "receiver"), name="santa_gift_receiver_unique"),
        ),
        migrations.AddIndex(
            model_name="santagift", index=models.Index(fields=["santa", "opened_at"], name="santa_gift_unopened_idx")
        ),
    ]
