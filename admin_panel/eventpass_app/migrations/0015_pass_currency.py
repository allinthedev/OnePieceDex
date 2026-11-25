import django.db.models.deletion
from django.db import migrations, models

CURRENCY_NAME_HELP = (
    "The name of the currency this pass hands out, like Snowflakes. Left empty, the pass has no currency of its "
    "own and its shop cannot be used."
)
CURRENCY_EMOJI_HELP = (
    "Shown next to an amount. A unicode character like ❄️, or a Discord emoji copied whole as <:name:id>."
)
DAILY_HELP = (
    "Handed out on top of the berries every time a player claims /daily while the pass is live. Zero hands out "
    "nothing, which is what a pass without a currency wants."
)
KIND_HELP = (
    "Berries and the pass currency are always given whatever the bundle's mode; only treasures are picked or drawn."
)
REASONS = [
    ("pass", "Pass reward"),
    ("daily", "Daily claim"),
    ("shop", "Spent in the shop"),
    ("crew_gift", "Given to a crew"),
    ("crew_spend", "Spent out of the crew pot"),
    ("admin", "Set by an admin"),
    ("refund", "Refunded"),
]
REWARD_KINDS = [("berries", "Berries"), ("treasure", "Treasure"), ("tokens", "The pass's own currency")]


class Migration(migrations.Migration):
    dependencies = [
        ("eventpass_app", "0014_reward_frame_key_none"),
        ("bd_models", "0025_special_counts_toward_collectors"),
        ("crew_app", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventpass",
            name="currency_name",
            field=models.CharField(blank=True, default="", help_text=CURRENCY_NAME_HELP, max_length=32),
        ),
        migrations.AddField(
            model_name="eventpass",
            name="currency_emoji",
            field=models.CharField(blank=True, default="", help_text=CURRENCY_EMOJI_HELP, max_length=64),
        ),
        migrations.AddField(
            model_name="eventpass",
            name="daily_currency",
            field=models.PositiveIntegerField(default=0, help_text=DAILY_HELP),
        ),
        migrations.AlterField(
            model_name="rewardline",
            name="kind",
            field=models.CharField(choices=REWARD_KINDS, default="treasure", help_text=KIND_HELP, max_length=16),
        ),
        migrations.CreateModel(
            name="PassWallet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("balance", models.PositiveBigIntegerField(default=0, help_text="What is left to spend.")),
                (
                    "earned",
                    models.PositiveBigIntegerField(
                        default=0,
                        help_text="Everything ever credited, spending included. What a leaderboard of the event reads.",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "event_pass",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wallets",
                        to="eventpass_app.eventpass",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="pass_wallets", to="bd_models.player"
                    ),
                ),
            ],
            options={"db_table": "eventpasswallet", "managed": True},
        ),
        migrations.CreateModel(
            name="CrewPassWallet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("balance", models.PositiveBigIntegerField(default=0, help_text="What the crew has left to spend.")),
                (
                    "received",
                    models.PositiveBigIntegerField(default=0, help_text="Everything the crew has ever been given."),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "crew",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="pass_wallets", to="crew_app.crew"
                    ),
                ),
                (
                    "event_pass",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="crew_wallets",
                        to="eventpass_app.eventpass",
                    ),
                ),
            ],
            options={"db_table": "eventpasscrewwallet", "managed": True},
        ),
        migrations.CreateModel(
            name="PassWalletEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "amount",
                    models.BigIntegerField(help_text="Signed: positive credits the wallet, negative debits it."),
                ),
                (
                    "balance_after",
                    models.PositiveBigIntegerField(help_text="The balance once this movement was applied."),
                ),
                ("reason", models.CharField(choices=REASONS, default="admin", max_length=16)),
                ("description", models.CharField(blank=True, default="", max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "crew_wallet",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="eventpass_app.crewpasswallet",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="eventpass_app.passwallet",
                    ),
                ),
            ],
            options={"db_table": "eventpasswalletentry", "managed": True, "ordering": ("-created_at", "-pk")},
        ),
        migrations.AddConstraint(
            model_name="passwallet",
            constraint=models.UniqueConstraint(fields=("event_pass", "player"), name="eventpass_wallet_unique"),
        ),
        migrations.AddConstraint(
            model_name="crewpasswallet",
            constraint=models.UniqueConstraint(fields=("event_pass", "crew"), name="eventpass_crew_wallet_unique"),
        ),
        migrations.AddIndex(
            model_name="passwalletentry",
            index=models.Index(fields=["wallet", "-created_at"], name="eventpass_entry_wallet_idx"),
        ),
        migrations.AddIndex(
            model_name="passwalletentry",
            index=models.Index(fields=["crew_wallet", "-created_at"], name="eventpass_entry_crew_idx"),
        ),
    ]
