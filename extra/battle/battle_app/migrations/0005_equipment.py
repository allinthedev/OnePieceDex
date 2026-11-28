"""
Equipment: only characters fight, and a weapon and a devil fruit are attached to them.

- `EquipAffinity` says what share of an item's stats a character gets: the item that is canonically
  theirs, a kind of item they master, or the default of a kind for anybody. The most precise line wins.
- `EquipResistance` says what a defender's equipment does to the damage coming in, depending on what the
  attacker wears.
- The settings gain the three groups a treasure's part in a battle is read from (left empty, the groups
  named "Characters", "Weapons" and "Devil fruits"), the default share, the bonus of a full set, and the
  two bounds on what equipment can do to a single hit.

New tables and new columns only. Nothing is filled in here: the lines themselves are loaded afterwards
with `load_battle_equipment`.
"""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


def group(help_text: str) -> models.ForeignKey:
    return models.ForeignKey(
        blank=True,
        help_text=help_text,
        null=True,
        on_delete=django.db.models.deletion.SET_NULL,
        related_name="+",
        to="bd_models.ballgroup",
    )


class Migration(migrations.Migration):
    dependencies = [("battle_app", "0004_buff_capacity"), ("bd_models", "0019_guildconfig_tips_enabled")]

    operations = [
        migrations.AddField(
            model_name="battlesettings",
            name="character_group",
            field=group('The group of the treasures allowed to fight. Left empty, the group named "Characters".'),
        ),
        migrations.AddField(
            model_name="battlesettings",
            name="weapon_group",
            field=group('The group of the treasures equipped as a weapon. Left empty, the group named "Weapons".'),
        ),
        migrations.AddField(
            model_name="battlesettings",
            name="fruit_group",
            field=group(
                'The group of the treasures equipped as a devil fruit. Left empty, the group named "Devil fruits".'
            ),
        ),
        migrations.AddField(
            model_name="battlesettings",
            name="default_equip_percent",
            field=models.PositiveIntegerField(
                default=50,
                help_text=(
                    "Share of an item's stats, in percent, a character gets when no affinity rule says anything "
                    "about the pair: neither for this character, nor for this item, nor for its kind."
                ),
            ),
        ),
        migrations.AddField(
            model_name="battlesettings",
            name="full_set_bonus_percent",
            field=models.PositiveIntegerField(
                default=10,
                help_text=(
                    "Extra percent of attack and health for a character holding both a weapon and a devil "
                    "fruit, applied on its total. 0 turns the bonus off."
                ),
            ),
        ),
        migrations.AddField(
            model_name="battlesettings",
            name="resistance_floor",
            field=models.FloatField(
                default=0.25,
                help_text=(
                    "The least damage equipment can leave of one hit, as a multiplier. An attacker wears two "
                    "items and the resistances to each multiply, so two reasonable rules could otherwise add up "
                    "to an immunity."
                ),
            ),
        ),
        migrations.AddField(
            model_name="battlesettings",
            name="resistance_ceiling",
            field=models.FloatField(
                default=2.0,
                help_text=(
                    "The most equipment can multiply one hit by, when weaknesses to the attacker's weapon and "
                    "fruit line up."
                ),
            ),
        ),
        migrations.AddConstraint(
            model_name="battlesettings",
            constraint=models.CheckConstraint(
                condition=Q(resistance_floor__gt=0) & Q(resistance_floor__lte=models.F("resistance_ceiling")),
                name="battlesettings_resistance_floor_lte_ceiling",
            ),
        ),
        migrations.CreateModel(
            name="EquipAffinity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "percent",
                    models.PositiveIntegerField(
                        default=100,
                        help_text=(
                            "Share of the item's own attack and health added to the character, in percent. 200 "
                            "for an item that is canonically theirs, 110 to 150 for a kind they master, 50 for "
                            "one they have no business holding, less for one they cannot use at all."
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
                    "character",
                    models.ForeignKey(
                        blank=True,
                        help_text="The character holding the item. Leave empty for a rule about everybody.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="equip_affinities",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        help_text="One exact weapon or devil fruit. Set this or a group, never both.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "item_group",
                    models.ForeignKey(
                        blank=True,
                        help_text=(
                            "A kind of item: every weapon or fruit of this group. Set this or an exact item, "
                            "never both."
                        ),
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="bd_models.ballgroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "equip affinity",
                "verbose_name_plural": "equip affinities",
                "db_table": "battleequipaffinity",
                "managed": True,
            },
        ),
        migrations.CreateModel(
            name="EquipResistance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "multiplier",
                    models.FloatField(
                        default=1.0,
                        help_text=(
                            "Applied to the damage the defender takes. 0.5 halves it (a resistance), 1.5 adds "
                            "half again (a weakness). Between 0.05 and 5."
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
                    "character",
                    models.ForeignKey(
                        blank=True,
                        help_text="The defender. Leave empty for a rule about anybody wearing the item below.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="equip_resistances",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "equipped_item",
                    models.ForeignKey(
                        blank=True,
                        help_text=(
                            "What the defender has to be wearing for the rule to apply. Leave empty for a rule "
                            "that holds whatever they wear."
                        ),
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "against_item",
                    models.ForeignKey(
                        blank=True,
                        help_text="The exact item the attacker wears. Set this or a group, never both.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "against_group",
                    models.ForeignKey(
                        blank=True,
                        help_text="The kind of item the attacker wears. Set this or an exact item, never both.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="bd_models.ballgroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "equip resistance",
                "verbose_name_plural": "equip resistances",
                "db_table": "battleequipresistance",
                "managed": True,
            },
        ),
        migrations.AddConstraint(
            model_name="equipaffinity",
            constraint=models.CheckConstraint(
                condition=Q(item__isnull=False, item_group__isnull=True)
                | Q(item__isnull=True, item_group__isnull=False),
                name="battleequipaffinity_item_xor_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipaffinity",
            constraint=models.UniqueConstraint(
                condition=Q(character__isnull=False, item__isnull=False),
                fields=("character", "item"),
                name="battleequipaffinity_character_item",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipaffinity",
            constraint=models.UniqueConstraint(
                condition=Q(character__isnull=False, item_group__isnull=False),
                fields=("character", "item_group"),
                name="battleequipaffinity_character_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipaffinity",
            constraint=models.UniqueConstraint(
                condition=Q(character__isnull=True, item__isnull=False),
                fields=("item",),
                name="battleequipaffinity_anybody_item",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipaffinity",
            constraint=models.UniqueConstraint(
                condition=Q(character__isnull=True, item_group__isnull=False),
                fields=("item_group",),
                name="battleequipaffinity_anybody_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipresistance",
            constraint=models.CheckConstraint(
                condition=Q(against_item__isnull=False, against_group__isnull=True)
                | Q(against_item__isnull=True, against_group__isnull=False),
                name="battleequipresistance_item_xor_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipresistance",
            constraint=models.CheckConstraint(
                condition=Q(multiplier__gte=0.05) & Q(multiplier__lte=5), name="battleequipresistance_multiplier_bounds"
            ),
        ),
    ]
