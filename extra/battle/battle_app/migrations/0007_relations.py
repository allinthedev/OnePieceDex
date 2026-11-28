"""
Who the two fighters are, whatever they wear.

- A `Matchup` (this attacker against this defender) gains a note, and its multiplier is kept between
  0.1 and 5: a line that zeroes a hit or multiplies it by fifty is a typo, not a rivalry.
- `GroupMatchup` is new: a bond between the members of one group, applied when both fighters belong to
  it. "The Whitebeard Pirates are brothers: they hold back against each other."

Both are loaded from `relations.csv` by `load_battle_equipment`.
"""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("battle_app", "0006_tier_bands"), ("bd_models", "0019_guildconfig_tips_enabled")]

    operations = [
        migrations.AddField(
            model_name="matchup",
            name="note",
            field=models.CharField(
                blank=True, default="", help_text="Why, for whoever reads this next.", max_length=200
            ),
        ),
        migrations.AlterField(
            model_name="matchup",
            name="damage_multiplier",
            field=models.FloatField(
                default=1.25,
                help_text=(
                    "Damage multiplier applied when attacker hits defender. 1.0 = no effect, above 1 hits "
                    "harder, below 1 holds back. Between 0.1 and 5."
                ),
            ),
        ),
        migrations.AddConstraint(
            model_name="matchup",
            constraint=models.CheckConstraint(
                condition=Q(damage_multiplier__gte=0.1) & Q(damage_multiplier__lte=5),
                name="battlematchup_multiplier_bounds",
            ),
        ),
        migrations.CreateModel(
            name="GroupMatchup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "damage_multiplier",
                    models.FloatField(
                        default=0.75,
                        help_text=(
                            "Applied to the damage between two members of the group. Below 1 they hold back, "
                            "above 1 they go at each other harder. Between 0.1 and 5."
                        ),
                    ),
                ),
                (
                    "note",
                    models.CharField(
                        blank=True, default="", help_text="Why, for whoever reads this next.", max_length=200
                    ),
                ),
                (
                    "group",
                    models.OneToOneField(
                        help_text="The group both fighters have to belong to.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="battle_bond",
                        to="bd_models.ballgroup",
                    ),
                ),
            ],
            options={"verbose_name": "group bond", "db_table": "battlegroupmatchup", "managed": True},
        ),
        migrations.AddConstraint(
            model_name="groupmatchup",
            constraint=models.CheckConstraint(
                condition=Q(damage_multiplier__gte=0.1) & Q(damage_multiplier__lte=5),
                name="battlegroupmatchup_multiplier_bounds",
            ),
        ),
    ]
