"""
Forty-one new quest types, and the settings they need.

Everything the bus already dispatched and nothing listened to (royale, boss fights, battles played,
favorites, the weekly pack), everything the panel's own packages now say on the bus (the advent
calendar, the Secret Santa, the sleigh, crews, hunts, wanted posters, achievements, the event shop)
and the quests that read a state rather than an action (completion, groups, playtime, rankings).

Only choices and new columns: nothing already stored changes meaning, and no existing quest is
touched.
"""

import django.db.models.deletion
from django.db import migrations, models

TYPES = [
    ("catch", "Catch treasures"),
    ("obtain", "Obtain treasures (catch, trade, pack, craft...)"),
    ("command", "Use a command"),
    ("trade", "Complete trades"),
    ("trade_treasures", "Exchange treasures in trades"),
    ("give_treasures", "Give treasures to players"),
    ("friend", "Add friends"),
    ("battle_win", "Win battles"),
    ("give_currency", "Give berries to players"),
    ("receive_currency", "Receive berries from players"),
    ("catch_currency", "Earn berries by catching treasures"),
    ("spend_currency", "Spend berries"),
    ("craft", "Craft (claim a collector card)"),
    ("pack_buy", "Buy packs"),
    ("merchant_buy", "Buy from the merchant"),
    ("shop_buy", "Buy from Buggy's shop"),
    ("sell", "Sell treasures to Buggy"),
    ("auction_create", "List treasures on the auction house"),
    ("auction_bid", "Place bids on the auction house"),
    ("auction_won", "Win auctions"),
    ("currency_streak", "Reach a daily berry streak"),
    ("pack_streak", "Reach a daily pack streak"),
    ("own_treasures", "Own treasures (how many you have, not what you do)"),
    ("own_favorites", "Own favorite treasures"),
    ("own_currency", "Hold berries"),
    ("complete_group", "Complete a group"),
    ("completion", "Reach a completion percentage"),
    ("playtime", "Play for a length of time"),
    ("leaderboard_rank", "Reach a place on the berry leaderboard"),
    ("favorite", "Set favorite treasures"),
    ("activity", "Play at all (any command)"),
    ("pack_weekly", "Claim the weekly pack"),
    ("auction_sold", "Sell treasures on the auction house"),
    ("trade_partners", "Trade with different players"),
    ("give_partners", "Give to different players"),
    ("battle_played", "Take part in battles"),
    ("boss_played", "Fight a boss"),
    ("boss_win", "Win a boss fight"),
    ("royale_played", "Play Grand Line Royale matches"),
    ("royale_win", "Win Grand Line Royale matches"),
    ("royale_kill", "Kill in Grand Line Royale"),
    ("royale_chest", "Open chests in Grand Line Royale"),
    ("royale_bounty", "Claim bounties in Grand Line Royale"),
    ("advent_open", "Open advent calendar doors"),
    ("advent_complete", "Finish the advent calendar"),
    ("santa_join", "Join the Secret Santa"),
    ("santa_wish", "Write a Secret Santa wishlist"),
    ("santa_gift", "Wrap a Secret Santa parcel"),
    ("santa_open", "Open a Secret Santa parcel"),
    ("sleigh_give", "Put treasures in the sleigh"),
    ("sleigh_full", "Fill the sleigh (with everyone else)"),
    ("crew_join", "Join a crew"),
    ("in_crew", "Be in a crew"),
    ("crew_points", "Score war points for a crew"),
    ("crew_rank", "Reach a place in the war ranking"),
    ("crew_war_win", "Win a crew war"),
    ("hunt_stone", "Claim poneglyphs"),
    ("hunt_complete", "Finish a hunt"),
    ("bounty_claim", "Take a wanted poster"),
    ("achievement_unlock", "Unlock achievements"),
    ("event_shop_buy", "Buy from an event pass's shop"),
    ("augment", "Augment treasures"),
    ("collectible_buy", "Buy collectibles"),
    ("vote", "Vote for the bot"),
]

MEASURES = [("count", "Number of times"), ("amount", "Total amount (berries, points, damage...)")]
TIME_UNITS = [("days", "Days"), ("months", "Months"), ("years", "Years")]


class Migration(migrations.Migration):
    dependencies = [
        ("eventpass_app", "0016_alter_passwalletentry_reason"),
        ("achievement_app", "0011_give_treasures_achievement"),
    ]

    operations = [
        migrations.AlterField(
            model_name="quest",
            name="type",
            field=models.CharField(
                choices=TYPES,
                help_text="What the player has to do. It decides which of the filters below are used.",
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="quest",
            name="measure",
            field=models.CharField(
                choices=MEASURES,
                default="count",
                help_text="Whether the goal counts actions or adds up berries.",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="achievement_category",
            field=models.ForeignKey(
                blank=True,
                help_text="Only count achievements of this category. Leave empty for any.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="achievement_app.achievementcategory",
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="time_unit",
            field=models.CharField(
                choices=TIME_UNITS,
                default="days",
                help_text=(
                    "The unit the goal is counted in, for a quest about how long the player has been playing."
                ),
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="on_time",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Only count an advent door opened on its own day, not one bought open afterwards with "
                    "/advent catchup."
                ),
                verbose_name="only on the day",
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="for_crew",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Only count it when the deed was done for a crew rather than for the player alone: a "
                    "poneglyph claimed in a hunt run as a race between crews."
                ),
                verbose_name="only for a crew",
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="in_crew_war",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Only count a Grand Line Royale deed done in a crew war raid. Left unchecked, only "
                    "ordinary matches count — the two are never mixed, so a quest always says which it "
                    "means."
                ),
                verbose_name="only in a crew war",
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="max_place",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text=(
                    "The place to finish at or above, 1 being the best: 3 is a podium, 10 a top ten. Used by "
                    "the ranking quests and by the Grand Line Royale ones."
                ),
                null=True,
                verbose_name="place to reach",
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="min_rounds",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Only count a Grand Line Royale match the player lasted this many rounds in.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="max_lost",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text=(
                    "Only count a battle where the player lost at most this many treasures. 0 asks for a "
                    "flawless win. A forfeit always counts as one loss."
                ),
                null=True,
                verbose_name="treasures lost at most",
            ),
        ),
        migrations.AddField(
            model_name="playerquest",
            name="seen",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "For the quests counting different people rather than actions: the Discord IDs already "
                    "counted, so trading with the same player twice only ever counts once."
                ),
            ),
        ),
    ]
