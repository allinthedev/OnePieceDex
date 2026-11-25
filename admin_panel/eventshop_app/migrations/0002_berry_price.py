from django.db import migrations, models

PRICE_HELP = "In the pass's own currency. Leave empty and it cannot be bought that way."
BERRIES_HELP = (
    "In berries. Leave empty and it cannot be bought that way. An offer priced both ways lets the player pick."
)


class Migration(migrations.Migration):
    dependencies = [("eventshop_app", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="shopoffer",
            name="price",
            field=models.PositiveBigIntegerField(
                blank=True, help_text=PRICE_HELP, null=True, verbose_name="price in currency"
            ),
        ),
        migrations.AddField(
            model_name="shopoffer",
            name="price_berries",
            field=models.PositiveBigIntegerField(
                blank=True, help_text=BERRIES_HELP, null=True, verbose_name="price in berries"
            ),
        ),
        migrations.AddField(
            model_name="shoppurchase",
            name="paid_with",
            field=models.CharField(
                choices=[("tokens", "The pass's currency"), ("berries", "Berries")],
                default="tokens",
                help_text="Which currency paid for it.",
                max_length=8,
            ),
        ),
    ]
