import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

BOOST_KINDS = [
    ("special", "Chance of a special"),
    ("rarity", "Rarer treasures"),
    ("spawn_party", "A burst of spawns"),
    ("berries", "Berries per catch"),
]
OFFER_KINDS = [("boost", "A boost for everyone"), ("reward", "Treasures or berries (a reward bundle)")]
MAGNITUDE_HELP = (
    "Read differently by each kind. Chance of a special: the weight of the special is raised by this many "
    "percent, so 25 on a 2% special makes it 2.5%. Rarer treasures: how hard the rarity weighting is flattened, "
    "0 changing nothing and 50 roughly halving the edge common treasures have. Berries per catch: this many "
    "percent on top of the usual amount. A burst of spawns ignores it and uses the count below."
)
EMOJI_HELP = "Shown next to the name. A unicode character, or a Discord emoji copied whole as <:name:id>."
DURATION_HELP = (
    "How long one purchase runs for. Buying it again while it is running adds this on top of what is left rather "
    "than starting a second one."
)
SPECIAL_HELP = (
    "Only for the chance of a special: the one whose chance goes up. Left empty, every special running at the "
    "time goes up together, which is rarely what an event wants."
)
CHANNEL_HELP = (
    "Only for a burst of spawns: the channel they go out in, on the main server. Left empty, the main server's "
    "own spawn channel is used."
)
REWARD_HELP = (
    "The bundle this offer sells. The same bundles the pass uses, so a card sold here is set up exactly like a "
    "card a tier gives."
)
STOCK_HELP = "How many can be sold in all, across every player. Left empty, as many as players can afford."
POT_HELP = (
    "Paid out of the crew's pot rather than the buyer's wallet. Staff spend the pot, since a crew has no captain "
    "to spend it for everyone."
)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("eventpass_app", "0015_pass_currency"),
        ("bd_models", "0025_special_counts_toward_collectors"),
        ("crew_app", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Boost",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "name",
                    models.CharField(help_text="Shown to players, e.g. 'Blizzard hour'.", max_length=64, unique=True),
                ),
                ("emoji", models.CharField(blank=True, default="", help_text=EMOJI_HELP, max_length=64)),
                ("kind", models.CharField(choices=BOOST_KINDS, default="rarity", max_length=16)),
                (
                    "description",
                    models.TextField(
                        blank=True, default="", help_text="A line telling players what it does. Shown in the shop."
                    ),
                ),
                ("magnitude", models.FloatField(default=25, help_text=MAGNITUDE_HELP)),
                ("duration_minutes", models.PositiveIntegerField(default=60, help_text=DURATION_HELP)),
                (
                    "spawns",
                    models.PositiveSmallIntegerField(
                        default=5, help_text="Only for a burst of spawns: how many go out, one after another."
                    ),
                ),
                ("channel_id", models.BigIntegerField(blank=True, help_text=CHANNEL_HELP, null=True)),
                (
                    "announce",
                    models.BooleanField(
                        default=True, help_text="Say in the main server's spawn channel that the boost has started."
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(default=True, help_text="Turn this off to stop it being bought or handed out."),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "special",
                    models.ForeignKey(
                        blank=True,
                        help_text=SPECIAL_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="bd_models.special",
                    ),
                ),
            ],
            options={"db_table": "eventshopboost", "ordering": ("name",), "managed": True},
        ),
        migrations.CreateModel(
            name="ShopOffer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Shown in the shop.", max_length=64)),
                ("emoji", models.CharField(blank=True, default="", help_text="Shown before the name.", max_length=64)),
                (
                    "description",
                    models.TextField(blank=True, default="", help_text="A line under the name, in the shop."),
                ),
                ("kind", models.CharField(choices=OFFER_KINDS, default="boost", max_length=8)),
                ("price", models.PositiveBigIntegerField(help_text="In the pass's own currency.")),
                (
                    "position",
                    models.PositiveSmallIntegerField(default=0, help_text="Offers are listed from the lowest."),
                ),
                ("enabled", models.BooleanField(default=True)),
                (
                    "starts_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Not on sale before this. Left empty, it is on sale as soon as the pass is.",
                        null=True,
                    ),
                ),
                (
                    "ends_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Off the shelf after this. Left empty, it stays until the pass closes.",
                        null=True,
                    ),
                ),
                ("stock", models.PositiveIntegerField(blank=True, help_text=STOCK_HELP, null=True)),
                (
                    "sold",
                    models.PositiveIntegerField(
                        default=0, editable=False, help_text="How many have gone, filled by the bot."
                    ),
                ),
                (
                    "per_player",
                    models.PositiveSmallIntegerField(
                        default=0, help_text="How many one player may buy. Zero means no limit of their own."
                    ),
                ),
                ("from_crew_pot", models.BooleanField(default=False, help_text=POT_HELP)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "boost",
                    models.ForeignKey(
                        blank=True,
                        help_text="The boost this offer sells.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="eventshop_app.boost",
                    ),
                ),
                (
                    "event_pass",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shop_offers",
                        to="eventpass_app.eventpass",
                    ),
                ),
                (
                    "reward",
                    models.ForeignKey(
                        blank=True,
                        help_text=REWARD_HELP,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shop_offers",
                        to="eventpass_app.reward",
                    ),
                ),
            ],
            options={"db_table": "eventshopoffer", "ordering": ("position", "pk"), "managed": True},
        ),
        migrations.CreateModel(
            name="ActiveBoost",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=BOOST_KINDS, max_length=16)),
                ("magnitude", models.FloatField(default=0)),
                (
                    "label",
                    models.CharField(
                        blank=True, default="", help_text="What it was called when bought.", max_length=96
                    ),
                ),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "ends_at",
                    models.DateTimeField(help_text="When it stops. Extended rather than doubled when bought again."),
                ),
                (
                    "spawns_left",
                    models.PositiveSmallIntegerField(
                        default=0, help_text="Only for a burst of spawns: how many are still to go out."
                    ),
                ),
                ("channel_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "announced_at",
                    models.DateTimeField(
                        blank=True, help_text="When players were told. Clear it to announce again.", null=True
                    ),
                ),
                (
                    "boost",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="runs",
                        to="eventshop_app.boost",
                    ),
                ),
                (
                    "bought_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="bd_models.player",
                    ),
                ),
                (
                    "special",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="bd_models.special",
                    ),
                ),
            ],
            options={"db_table": "eventshopactiveboost", "ordering": ("-started_at", "-pk"), "managed": True},
        ),
        migrations.CreateModel(
            name="ShopPurchase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("price", models.PositiveBigIntegerField(help_text="What it cost at the time.")),
                ("summary", models.CharField(blank=True, default="", help_text="What the buyer got.", max_length=256)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "crew",
                    models.ForeignKey(
                        blank=True,
                        help_text="Set when the pot paid rather than the player.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shop_purchases",
                        to="crew_app.crew",
                    ),
                ),
                (
                    "offer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="purchases",
                        to="eventshop_app.shopoffer",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shop_purchases",
                        to="bd_models.player",
                    ),
                ),
            ],
            options={"db_table": "eventshoppurchase", "ordering": ("-created_at", "-pk"), "managed": True},
        ),
        migrations.AddIndex(
            model_name="shopoffer",
            index=models.Index(fields=["event_pass", "enabled", "position"], name="eventshop_offer_listed_idx"),
        ),
        migrations.AddIndex(
            model_name="activeboost", index=models.Index(fields=["kind", "ends_at"], name="eventshop_active_live_idx")
        ),
        migrations.AddIndex(
            model_name="shoppurchase",
            index=models.Index(fields=["offer", "player"], name="eventshop_purchase_limit_idx"),
        ),
    ]
