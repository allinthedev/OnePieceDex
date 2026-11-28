"""
Give a treasure's Capacity somewhere of its own to live.

The engine used to read `Ball.capacity_logic`, which reads like the obvious place and is not: that
column belongs to the frames package, which keeps each treasure's alternate artwork in it. Nothing
crashed, because each side ignores the shape of the other, but it meant no treasure could ever be
given a real Capacity, and every Capacity action fell back to the default multiplier.

The effect now sits on `Buff`, which the battle package owns and already loads for every card in a
deck. The name of the capacity still comes from `Ball.capacity_name`, which nothing else claims.
"""

from django.db import migrations, models

EFFECTS = [
    ("", "Plain special attack (uses the default multiplier in the settings)"),
    ("heal_percent", "Heals the user by a % of its own max health"),
    ("flat_damage", "Deals a fixed amount of damage, whatever the attack stat"),
    ("damage_multiplier", "Attacks with its damage multiplied"),
]


DEFAULT_MULTIPLIER_HELP = (
    "Damage multiplier used by the Capacity action when the treasure's Buff sets no capacity effect, "
    "which is the case for every treasure until one is given one."
)


class Migration(migrations.Migration):
    dependencies = [("battle_app", "0003_battlesettings_haki_special_bonus_and_more")]

    operations = [
        migrations.AddField(
            model_name="buff",
            name="capacity_effect",
            field=models.CharField(
                blank=True,
                choices=EFFECTS,
                default="",
                help_text=(
                    "What the Capacity action does for this treasure. Left on the plain special attack, it "
                    "hits for the default multiplier set in the battle settings."
                ),
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="buff",
            name="capacity_value",
            field=models.FloatField(
                default=0,
                help_text=(
                    "The number the effect needs: a percentage healed, an amount of damage, or a multiplier. "
                    "Ignored by the plain special attack."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="battlesettings",
            name="default_capacity_multiplier",
            field=models.FloatField(default=1.5, help_text=DEFAULT_MULTIPLIER_HELP),
        ),
    ]
