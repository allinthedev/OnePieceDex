from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crew_app", "0010_royale_war_sources")]

    operations = [
        migrations.AddField(
            model_name="crewwar",
            name="auto_finish",
            field=models.BooleanField(
                default=False,
                help_text="Hand the rewards out and announce the winner on their own, within a couple of "
                "minutes of the end date passing. Off, both wait for someone to run 'Hand out the rewards' "
                "by hand. The war needs an end date: one with no end never finishes on its own. Turning "
                "Enabled off does not stop this, so a war can be closed to scoring and still pay itself out.",
            ),
        ),
        migrations.AddField(
            model_name="crewwar",
            name="finished_at",
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text="When this war paid itself out at the end of its clock. Written by the bot, once. "
                "Clear it to have the ladder handed out again — which pays nobody twice, so it is only ever "
                "useful after a ladder was fixed.",
            ),
        ),
    ]
