from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("bd_models", "0020_playerdatadeletion")]

    operations = [
        migrations.AddField(
            model_name="special",
            name="layer",
            field=models.CharField(
                choices=[
                    ("background", "Background (behind the card art)"),
                    ("foreground", "Foreground (over the card art)"),
                ],
                default="background",
                help_text="Where the image above is drawn. A background replaces the regime's one and the card art "
                "goes over it; a foreground is laid over the finished card, so it needs transparency. The name, "
                "ability, stats and credits always stay on top of both.",
                max_length=16,
            ),
        )
    ]
