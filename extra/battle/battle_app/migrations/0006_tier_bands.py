"""
Rarity tiers become bands, and a gap in rarity stops costing more than 10% of the damage.

A tier used to be `round(rarity)`. Rarity runs from 1 to over 200, so a T20 and a T22 were "two tiers
apart", nearly every fight fell on one of the two extreme multipliers, and those were 0.3 and 1.0: a rare
card dealt more than three times the damage it took before its own, better stats were even counted.

- `tier_bounds` cuts rarity into bands. Cards of the same band fight as equals.
- The five multipliers now run from 0.9 to 1.0, evenly spaced. A rarer card is already far ahead on its
  own attack and health; the tier only adds a touch to that.
- The bonus critical chance against a much more common enemy goes to 0, so that the gap is worth exactly
  what the multipliers say.

A settings row that already exists is only retuned where it still holds the old default: a figure
somebody chose on purpose is left alone.
"""

from django.db import migrations, models

import battle_app.models

OLD_DEFAULTS = {
    "tier_same_multiplier": 0.7,
    "tier_enemy_1_higher_multiplier": 0.5,
    "tier_enemy_2plus_higher_multiplier": 0.3,
    "tier_enemy_1_lower_multiplier": 0.9,
    "tier_enemy_2plus_lower_bonus_crit_chance": 0.10,
}
NEW_DEFAULTS = {
    "tier_same_multiplier": 0.95,
    "tier_enemy_1_higher_multiplier": 0.925,
    "tier_enemy_2plus_higher_multiplier": 0.9,
    "tier_enemy_1_lower_multiplier": 0.975,
    "tier_enemy_2plus_lower_bonus_crit_chance": 0.0,
}


def retune(apps, schema_editor):
    settings = apps.get_model("battle_app", "BattleSettings")
    for row in settings.objects.all():
        changed = []
        for name, old in OLD_DEFAULTS.items():
            if abs(getattr(row, name) - old) < 1e-9:
                setattr(row, name, NEW_DEFAULTS[name])
                changed.append(name)
        if changed:
            row.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [("battle_app", "0005_equipment")]

    operations = [
        migrations.AddField(
            model_name="battlesettings",
            name="tier_bounds",
            field=models.JSONField(
                default=battle_app.models.default_tier_bounds,
                help_text=(
                    "Where each rarity tier ends, rarest first, as a list of rarities: [15, 35, 85, 140, 180] "
                    "makes six tiers, T1 to T15, T16 to T35, and so on, the last one holding everything past "
                    "180. Cards of the same tier fight as equals however their rarities differ inside it."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="battlesettings",
            name="tier_same_multiplier",
            field=models.FloatField(default=0.95, help_text="Damage multiplier vs. an equal-tier enemy."),
        ),
        migrations.AlterField(
            model_name="battlesettings",
            name="tier_enemy_1_higher_multiplier",
            field=models.FloatField(default=0.925, help_text="Damage multiplier vs. an enemy 1 tier higher (rarer)."),
        ),
        migrations.AlterField(
            model_name="battlesettings",
            name="tier_enemy_2plus_higher_multiplier",
            field=models.FloatField(default=0.9, help_text="Damage multiplier vs. an enemy 2+ tiers higher (rarer)."),
        ),
        migrations.AlterField(
            model_name="battlesettings",
            name="tier_enemy_1_lower_multiplier",
            field=models.FloatField(
                default=0.975, help_text="Damage multiplier vs. an enemy 1 tier lower (more common)."
            ),
        ),
        migrations.AlterField(
            model_name="battlesettings",
            name="tier_enemy_2plus_lower_bonus_crit_chance",
            field=models.FloatField(
                default=0.0,
                help_text=(
                    "Extra critical-strike chance (0-1) added to ANY damaging action vs. an enemy 2+ tiers lower. "
                    "Left at 0 so that a gap in rarity is worth exactly what the multipliers above say and "
                    "nothing more."
                ),
            ),
        ),
        migrations.RunPython(retune, migrations.RunPython.noop),
    ]
