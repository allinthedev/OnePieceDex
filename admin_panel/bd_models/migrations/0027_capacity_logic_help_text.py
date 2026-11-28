"""
Say what `Ball.capacity_logic` actually holds.

It was labelled "Effect of this capacity", which is what the field was built for and not what it
contains: the frames package stores each treasure's alternate artwork in it, one entry per frame.
A battle capacity is set on the treasure's Buff instead, in the battle package.

Help text only, no data or schema change.
"""

from django.db import migrations, models

HELP = (
    "Holds this treasure's frames, not a capacity effect: the frames package keeps its alternate "
    "artwork here, one entry per frame. Edit it in the Frames section rather than by hand. A battle "
    "capacity is set on the treasure's Buff, in the battle package."
)


class Migration(migrations.Migration):
    dependencies = [("bd_models", "0026_credits_colour")]

    operations = [
        migrations.AlterField(
            model_name="ball",
            name="capacity_logic",
            field=models.JSONField(blank=True, default=dict, help_text=HELP),
        )
    ]
