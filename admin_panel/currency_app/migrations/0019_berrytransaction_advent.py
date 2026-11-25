from django.db import migrations, models

# frozen: the choices of BerryTransaction.Reason as they stood when the advent calendar was added
CHOICES = [
    ("unknown", "Unknown"),
    ("daily", "Daily claim"),
    ("bounty", "Wanted bounty"),
    ("give_sent", "Gave berries away"),
    ("give_received", "Received berries"),
    ("spawn_catch", "Caught a berry spawn"),
    ("achievement", "Achievement reward"),
    ("event_pass", "Event pass reward"),
    ("crew_war", "Crew war reward"),
    ("trade", "Trade"),
    ("admin_adjust", "Admin adjustment"),
    ("auction_sell", "Sold to Buggy"),
    ("auction_shop_buy", "Bought from Buggy's shop"),
    ("auction_bid_hold", "Bid placed (berries held)"),
    ("auction_bid_refund", "Bid returned"),
    ("auction_sale_payout", "Listing sold (payout)"),
    ("featured_bid_hold", "Featured bid placed (berries held)"),
    ("featured_bid_refund", "Featured bid returned"),
    ("featured_payout", "Featured auction sold (payout)"),
    ("pack_buy", "Bought a pack"),
    ("merchant_buy", "Bought from the merchant"),
    ("merchant_token", "Converted merchant tokens"),
    ("collectible_buy", "Bought a collectible"),
    ("collector_claim", "Claimed a collector card"),
    ("augment_buy", "Bought an augment"),
    ("battle_item_buy", "Bought a battle item"),
    ("battle_wager_hold", "Battle wager (berries held)"),
    ("battle_wager_refund", "Battle wager returned"),
    ("battle_payout", "Battle winnings"),
    ("advent_catch_up", "Advent door bought open"),
]


class Migration(migrations.Migration):
    dependencies = [("currency_app", "0018_berrytransaction_crew_war")]

    operations = [
        migrations.AlterField(
            model_name="berrytransaction",
            name="reason",
            field=models.CharField(choices=CHOICES, default="unknown", max_length=32),
        )
    ]
