from django.core.validators import RegexValidator
from django.db import migrations, models

# frozen on purpose: a migration never reads the live model, so editing the help text later cannot rewrite history
HELP = (
    "Colour of the credits line at the bottom of the card, as #RRGGBB. Left empty, the bot reads the "
    "bottom of the finished card and writes them in black or white, which can clash with the art or "
    "disappear into it. A special sets this for its own cards; a regime for the cards that show its "
    "background."
)


class Migration(migrations.Migration):
    dependencies = [("bd_models", "0025_special_counts_toward_collectors")]

    operations = [
        migrations.AddField(
            model_name=model,
            name="credits_colour",
            field=models.CharField(
                blank=True,
                default="",
                help_text=HELP,
                max_length=7,
                validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", message="Enter a hex colour such as #FFFFFF.")],
                verbose_name="credits colour",
            ),
        )
        for model in ("regime", "special")
    ]
