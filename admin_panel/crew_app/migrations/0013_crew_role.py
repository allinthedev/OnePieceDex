from django.db import migrations, models

HELP = (
    "Discord role given to this crew's members, on the main server only. Paste the role's ID. The bot "
    "needs Manage Roles, and its own highest role has to sit above this one or Discord refuses. "
    "Left empty, the crew carries no role."
)


class Migration(migrations.Migration):
    dependencies = [("crew_app", "0012_sleigh_gift")]

    operations = [
        migrations.AddField(
            model_name="crew",
            name="role_id",
            field=models.BigIntegerField(blank=True, help_text=HELP, null=True, verbose_name="Discord role"),
        )
    ]
