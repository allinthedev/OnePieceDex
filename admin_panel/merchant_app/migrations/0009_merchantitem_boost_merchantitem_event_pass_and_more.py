"""A merchant item can sell a boost, and can be priced in an event pass's own currency."""

import django.db.models.deletion
from django.db import migrations, models

BOOST_HELP = (
    "The boost this item starts, for an item that sells one. Boosts run on the main server and never need "
    "an event to be running."
)
PASS_HELP = (
    "Which wallet the price below is taken from. Only read when there is a price in a currency."
)
KIND_HELP = "What the player walks away with. A boost needs no treasure and makes no card."
PRICE_HELP = (
    "What it costs in the event pass's own currency, like Snowflakes. Fill this one OR the berry price, "
    "never both: to sell the same thing both ways, make the item twice."
)
KINDS = [("treasure", "A treasure"), ("boost", "A boost for the whole server")]


class Migration(migrations.Migration):
    dependencies = [
        ("bd_models", "0026_credits_colour"),
        ("eventpass_app", "0015_pass_currency"),
        ("eventshop_app", "0001_initial"),
        ("merchant_app", "0008_globalshop_weekly_announcement"),
    ]

    operations = [
        migrations.AddField(
            model_name="merchantitem",
            name="kind",
            field=models.CharField(
                choices=KINDS,
                default="treasure",
                help_text=KIND_HELP,
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="merchantitem",
            name="boost",
            field=models.ForeignKey(
                blank=True,
                null=True,
                help_text=BOOST_HELP,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="merchant_items",
                to="eventshop_app.boost",
            ),
        ),
        migrations.AddField(
            model_name="merchantitem",
            name="event_pass",
            field=models.ForeignKey(
                blank=True,
                null=True,
                help_text=PASS_HELP,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="merchant_items",
                to="eventpass_app.eventpass",
            ),
        ),
        migrations.AddField(
            model_name="merchantitem",
            name="price_currency",
            field=models.PositiveBigIntegerField(
                blank=True,
                null=True,
                help_text=PRICE_HELP,
                verbose_name="price in the pass currency",
            ),
        ),
        migrations.AlterField(
            model_name="merchantitem",
            name="ball",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="bd_models.ball",
            ),
        ),
    ]
