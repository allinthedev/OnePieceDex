from django.db import migrations, models

# listed once and used by both fields below, which hold the same set.
# The five crew war deeds join the set. They mirror the five ordinary Royale ones on purpose:
# the same deed done in a crew war raid is a different thing to a war, and has to be able to
# carry a different price and a different daily cap. Only the ones a war has a rule for score.
SOURCES = [
    ("battle_played", "Took part in a battle"),
    ("battle_win", "Won a battle"),
    ("boss_played", "Took part in a boss fight"),
    ("boss_win", "Won a boss fight"),
    ("royale_played", "Played a Royale match"),
    ("royale_win", "Won a Royale match"),
    ("royale_kill", "Killed someone in a Royale match"),
    ("royale_chest", "Opened a chest in a Royale match"),
    ("royale_bounty", "Claimed a bounty in a Royale match"),
    ("royale_war_played", "Played a crew war raid"),
    ("royale_war_win", "Won a crew war raid"),
    ("royale_war_kill", "Killed someone in a crew war raid"),
    ("royale_war_chest", "Opened a chest in a crew war raid"),
    ("royale_war_bounty", "Claimed a bounty in a crew war raid"),
    ("bounty_claimed", "Caught a wanted treasure"),
    ("poneglyph_claimed", "Claimed a poneglyph"),
    ("hunt_completed", "Finished a poneglyph hunt"),
    ("catch", "Caught a treasure"),
    ("catch_special", "Caught a special treasure"),
    ("craft", "Claimed a collector card"),
    ("trade", "Completed a trade"),
    ("gift", "Gave a treasure away"),
    ("friend", "Made a friend"),
    ("auction_create", "Listed a treasure at the Hotel"),
    ("auction_bid", "Placed a bid"),
    ("auction_won", "Won a listing"),
    ("sell", "Sold a treasure to Buggy"),
    ("shop_buy", "Bought a treasure from Buggy's shop"),
    ("pack_buy", "Bought a pack"),
    ("merchant_buy", "Bought from the merchant"),
    ("daily_berries", "Claimed the daily berries"),
    ("daily_pack", "Claimed the daily pack"),
    ("weekly_pack", "Claimed the weekly pack"),
    ("played", "Played at all that day"),
    ("manual", "Awarded by an admin"),
]


class Migration(migrations.Migration):
    dependencies = [("crew_app", "0009_royale_sources")]

    operations = [
        migrations.AlterField(
            model_name="crewwarentry",
            name="source",
            field=models.CharField(choices=SOURCES, max_length=32),
        ),
        migrations.AlterField(
            model_name="crewwarrule",
            name="source",
            field=models.CharField(choices=SOURCES, max_length=32),
        ),
    ]
