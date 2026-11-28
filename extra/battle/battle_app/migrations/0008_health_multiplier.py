"""
A fighter's health is multiplied in a battle, so that a battle is more than an exchange of single blows.

Attack and health are about the same number on every treasure of the dex (on average 97 against 101 for
characters, 165 against 159 for weapons, 167 against 162 for devil fruits). A hit deals 60 to 100% of the
attack, so it took most of the health of an opponent of the same standing: a character lasted one or two
hits, and equipment changed nothing to that since it adds to both stats alike.

`health_multiplier` is applied to a character's health, and to the health of what it holds, when they
enter a deck. At 3, the default, an equal opponent lasts three to five hits and a blow that ends a fight
at once all but disappears; at 2 it lasts two to four and battles are shorter. The setting is in the
panel: nothing has to be deployed to try another figure.

A Capacity that deals a fixed amount of damage is not multiplied: its help text now says to size it
against multiplied health.
"""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("battle_app", "0007_relations")]

    operations = [
        migrations.AddField(
            model_name="battlesettings",
            name="health_multiplier",
            field=models.FloatField(
                default=3.0,
                help_text=(
                    "What every fighter's health is multiplied by in a battle, what it holds included. Attack "
                    "and health are about the same number on every treasure, so at 1 a hit takes most of an "
                    "equal opponent's health and a character lasts one or two hits. At 2 it lasts two to "
                    "four, at 3 three to five, and battles get longer by as much. Between 0.5 and 10. Only "
                    "characters added to a deck after a change are affected."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="buff",
            name="capacity_value",
            field=models.FloatField(
                default=0,
                help_text=(
                    "The number the effect needs: a percentage healed, an amount of damage, or a multiplier. "
                    "Ignored by the plain special attack. An amount of damage is dealt as written: size it "
                    "against health as the health multiplier of the battle settings leaves it, not as the "
                    "cards show it."
                ),
            ),
        ),
        migrations.AddConstraint(
            model_name="battlesettings",
            constraint=models.CheckConstraint(
                condition=Q(health_multiplier__gte=0.5) & Q(health_multiplier__lte=10),
                name="battlesettings_health_multiplier_bounds",
            ),
        ),
    ]
