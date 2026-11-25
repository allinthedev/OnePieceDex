from django.db import migrations, models
from django.db.models import Q

REPEATABLE_HELP = (
    "Let players claim this tier again, as many times as they can meet its requirements. Meant for a tier "
    "whose requirements are consumed, like the elementals: each claim costs the cards again. Left off, a "
    "tier is claimed once and never again."
)
COPY_HELP = (
    "Which claim this is, for a tier that can be claimed again. Always 1 on a tier claimed once, which is "
    "what keeps a double click from claiming twice."
)


class Migration(migrations.Migration):
    dependencies = [("collector_app", "0013_collectorrequirement_frame_key")]

    operations = [
        migrations.AddField(
            model_name="collectortierlevel",
            name="repeatable",
            field=models.BooleanField(default=False, help_text=REPEATABLE_HELP),
        ),
        migrations.AddField(
            model_name="collectorinstance",
            name="copy",
            field=models.PositiveIntegerField(default=1, help_text=COPY_HELP),
        ),
        migrations.RemoveConstraint(model_name="collectorinstance", name="collectorinstance_active_unique"),
        migrations.AddConstraint(
            model_name="collectorinstance",
            constraint=models.UniqueConstraint(
                condition=Q(revoked_at__isnull=True),
                fields=("player", "collector", "level", "copy"),
                name="collectorinstance_active_unique",
            ),
        ),
    ]
