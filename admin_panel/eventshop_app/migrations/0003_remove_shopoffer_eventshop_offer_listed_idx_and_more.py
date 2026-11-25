"""
The event shop no longer sells anything: the boosts moved to the merchant, which sells them in berries or
in a pass's currency and keeps selling them when no event is running.

What is left of this app is the boost engine itself — Boost and ActiveBoost — which the merchant drives.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("eventshop_app", "0002_berry_price")]

    operations = [
        migrations.RemoveIndex(model_name="shopoffer", name="eventshop_offer_listed_idx"),
        migrations.RemoveIndex(model_name="shoppurchase", name="eventshop_purchase_limit_idx"),
        migrations.RemoveField(model_name="shoppurchase", name="crew"),
        migrations.RemoveField(model_name="shoppurchase", name="offer"),
        migrations.RemoveField(model_name="shoppurchase", name="player"),
        migrations.DeleteModel(name="ShopOffer"),
        migrations.DeleteModel(name="ShopPurchase"),
    ]
