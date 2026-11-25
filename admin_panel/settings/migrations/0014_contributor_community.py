from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("settings", "0013_settings_main_server_id")]

    operations = [
        migrations.AlterField(
            model_name="settings",
            name="artist_credits_url",
            field=models.URLField(
                blank=True,
                default="",
                help_text="Link to the page crediting the people behind the dex — the artists, the patrons who "
                "have donated and the helpers along the way (a GitHub file for instance). Shown in /about and "
                "when displaying a card.",
                verbose_name="contributor community URL",
            ),
        )
    ]
