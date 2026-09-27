import asyncio
import os
import sys

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ballsdex.core.image_generator.image_gen import draw_card
from bd_models.enums import SpecialLayer
from bd_models.models import Ball, BallInstance, Special, specials
from settings.models import settings

from ...utils import refresh_cache


class Command(BaseCommand):
    help = (
        "Generate a local preview of a card. This will use the system's image viewer "
        "or print to stdout if the output is being piped."
    )

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            "--ball",
            help=f"The name of the {settings.collectible_name} you want to generate. "
            "If not provided, the first entry is used.",
        )
        parser.add_argument(
            "--special", help="The special event's background you want to use, otherwise regime is used"
        )
        parser.add_argument(
            "--layer",
            choices=SpecialLayer.values,
            help="Draw the special's image behind the card art or over it, whatever the special is set to. "
            "Only for this preview, nothing is saved.",
        )

    async def generate_preview(self, *args, **options):
        await refresh_cache()

        if ball_name := options.get("ball"):
            try:
                ball = await Ball.objects.aget(country__iexact=ball_name)
            except Ball.DoesNotExist as e:
                raise CommandError(f'No {settings.collectible_name} found with the name "{ball_name}"') from e
        else:
            ball = await Ball.objects.afirst()
            if ball is None:
                raise CommandError(f"You need at least one {settings.collectible_name} created.")

        special: Special | None = None
        if special_name := options.get("special"):
            try:
                special = await Special.objects.aget(name__iexact=special_name)
            except Special.DoesNotExist as e:
                raise CommandError(f'No special found with the name "{special_name}"') from e

        if layer := options.get("layer"):
            if special is None:
                raise CommandError("--layer only means something along with --special.")
            # the card generator reads specials from the cache refreshed above, so the override goes there
            specials[special.pk].layer = layer

        # use stderr to avoid piping
        self.stderr.write(
            self.style.SUCCESS(f"Generating card for {ball.country}" + (f" ({special.name})" if special else ""))
        )

        instance = BallInstance(ball=ball, special=special)
        image, kwargs = draw_card(instance)

        if sys.stdout.isatty():
            # only the viewer needs a display: piping the image to a file works anywhere, Docker included
            if sys.platform not in ("win32", "darwin") and not os.environ.get("DISPLAY"):
                self.stderr.write(
                    self.style.WARNING(
                        "\nThis command displays the generated card using your system's image viewer, "
                        "but no display was detected. Are you running this inside Docker?\n"
                        'You can append "> image.png" at the end of your command to instead write the '
                        "image to disk, which you can then open manually.\n"
                    )
                )
                raise CommandError("No display detected.")
            if kwargs.get("save_all", False):
                self.stderr.write(
                    self.style.WARNING(
                        "You are trying to generate an animation, which is not supported in "
                        "your OS viewer (only the first frame will show). Pipe to a file instead "
                        "to generate a viewable animation file."
                    )
                )
            image.show(title=ball.country)
        else:
            image.save(sys.stdout.buffer, **kwargs)

    def handle(self, *args, **options):
        # Python 3.14 no longer hands out an implicit loop, so the command makes its own
        asyncio.run(self.generate_preview(*args, **options))
