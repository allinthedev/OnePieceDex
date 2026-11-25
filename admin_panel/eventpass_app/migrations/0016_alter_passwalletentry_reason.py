"""The ledger can say that currency moved between two players, not only to a crew."""

from django.db import migrations, models

REASONS = [
    ("pass", "Pass reward"),
    ("daily", "Daily claim"),
    ("shop", "Spent in the shop"),
    ("crew_gift", "Given to a crew"),
    ("crew_spend", "Spent out of the crew pot"),
    ("gift_sent", "Given to a player"),
    ("gift_received", "Received from a player"),
    ("admin", "Set by an admin"),
    ("refund", "Refunded"),
]


class Migration(migrations.Migration):
    dependencies = [("eventpass_app", "0015_pass_currency")]

    operations = [
        migrations.AlterField(
            model_name="passwalletentry",
            name="reason",
            field=models.CharField(choices=REASONS, default="admin", max_length=16),
        ),
    ]
