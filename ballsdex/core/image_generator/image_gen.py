import os
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from settings.models import settings

if TYPE_CHECKING:
    from django.db.models.fields.files import ImageFieldFile

    from bd_models.models import BallInstance


SOURCES_PATH = Path(os.path.dirname(os.path.abspath(__file__)), "./src")
WIDTH = 1500
HEIGHT = 2000

RECTANGLE_WIDTH = WIDTH - 40
RECTANGLE_HEIGHT = (HEIGHT // 5) * 2

CORNERS = ((34, 261), (1393, 992))
artwork_size = [b - a for a, b in zip(*CORNERS)]

# ===== TIP =====
#
# If you want to quickly test the image generation, there is a CLI tool to quickly generate
# test images locally, without the bot or the admin panel running:
#
# With Docker: "docker compose run admin-panel django-admin preview > image.png"
# Without: "DJANGO_SETTINGS_MODULE=admin_panel.settings python3 -m django preview"
#
# This will either create a file named "image.png" or directly display it using your system's
# image viewer. There are options available to specify the ball or the special background,
# use the "--help" flag to view all options.

title_font = ImageFont.truetype(str(SOURCES_PATH / "ArsenicaTrial-Extrabold.ttf"), 170)
capacity_name_font = ImageFont.truetype(str(SOURCES_PATH / "Bobby Jones Soft.otf"), 110)
capacity_description_font = ImageFont.truetype(str(SOURCES_PATH / "OpenSans-Semibold.ttf"), 75)
stats_font = ImageFont.truetype(str(SOURCES_PATH / "Bobby Jones Soft.otf"), 130)
credits_font = ImageFont.truetype(str(SOURCES_PATH / "arial.ttf"), 40)

credits_color_cache = {}


def open_image(image_file: "ImageFieldFile") -> Image.Image:
    """
    Load an image from a model's file field as RGBA, releasing the underlying file descriptor.

    Pillow only takes ownership of the file (and closes it once the image is loaded) when it is
    given a path. Handing it the field file directly makes Pillow treat it as a borrowed file
    object, and the descriptor stays open on the model instance instead. Balls, regimes,
    economies and specials are kept in caches living for the whole lifetime of the bot, so those
    descriptors would never be released, eventually exhausting the process' limit.
    """
    return Image.open(image_file.path).convert("RGBA")


def get_credit_color(image: Image.Image, region: tuple) -> tuple:
    image = image.crop(region)
    brightness = sum(image.convert("L").getdata()) / image.width / image.height  # type: ignore
    return (0, 0, 0, 255) if brightness > 100 else (255, 255, 255, 255)


def draw_card(
    ball_instance: "BallInstance",
    *,
    artwork: str | None = None,
    full_art: str | None = None,
    artwork_credits: str | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    """
    Draw the card of a countryball instance.

    The card is stacked in layers: a background (the regime's, the special's or a full art), the card art in its
    square, then the special's own art when it asked to sit over the card rather than behind it. The name,
    ability, stats, credits and economy icon are written last, above every layer.

    Parameters
    ----------
    artwork: str | None
        Path of an image drawn in the artwork square instead of the countryball's card art.
    full_art: str | None
        Path of an image covering the whole card, drawn instead of the background and the artwork square. The name,
        ability, stats and credits are written over it.
    artwork_credits: str | None
        Author of the artwork drawn, instead of the countryball's artwork author.
    """
    ball = ball_instance.countryball
    ball_health = (237, 115, 101, 255)
    ball_credits = artwork_credits or ball.credits
    special = ball_instance.specialcard
    special_name = special.name if special else ""
    special_credits = f" • Special Author: {special.credits}" if special and special.credits else ""
    overlay = ball_instance.special_overlay

    # the credits color is read from the finished card and cached under this name, one per look
    card_name: str | None
    if background := ball_instance.special_background:
        image = open_image(background)
        card_name = special_name or ball.cached_regime.name
    else:
        image = open_image(ball.cached_regime.background)
        # an overlay hides part of the background, the credits strip included, so the two layers together are
        # the look the credits color is cached for
        card_name = f"{ball.cached_regime.name} + {special_name}" if overlay else ball.cached_regime.name
    if full_art:
        with Image.open(full_art) as art:
            image = ImageOps.fit(art.convert("RGBA"), image.size)
        # the background of the special isn't shown, and every full art needs its own credits color
        card_name = None
        if not overlay:
            special_credits = ""
    icon = open_image(ball.cached_economy.icon) if ball.cached_economy else None

    if not full_art:
        # the collection card is a model file field, so it goes through open_image to release its
        # descriptor; `artwork` is a plain path, which Pillow closes on its own
        with Image.open(artwork) if artwork else open_image(ball.collection_card) as art:
            image.paste(ImageOps.fit(art.convert("RGBA"), artwork_size), CORNERS[0])  # type: ignore
    if overlay:
        # the special's upper layer covers the background and the card art, but not what is written next
        with open_image(overlay) as layer:
            image.alpha_composite(ImageOps.fit(layer, image.size))

    draw = ImageDraw.Draw(image)
    draw.text((50, 20), ball.short_name or ball.country, font=title_font, stroke_width=2, stroke_fill=(0, 0, 0, 255))

    cap_name = textwrap.wrap(ball.capacity_name, width=26)

    for i, line in enumerate(cap_name):
        draw.text(
            (100, 1050 + 100 * i),
            line,
            font=capacity_name_font,
            fill=(230, 230, 230, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255),
        )

    capacity_description_lines = (
        wrapped_line
        for newline in ball.capacity_description.splitlines()
        for wrapped_line in textwrap.wrap(newline, 32)
    )

    for i, line in enumerate(capacity_description_lines):
        draw.text(
            (60, 1100 + 100 * len(cap_name) + 80 * i),
            line,
            font=capacity_description_font,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )

    draw.text(
        (320, 1670),
        str(ball_instance.health),
        font=stats_font,
        fill=ball_health,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
    )
    draw.text(
        (1120, 1670),
        str(ball_instance.attack),
        font=stats_font,
        fill=(252, 194, 76, 255),
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
        anchor="ra",
    )
    if settings.show_rarity:
        draw.text((1200, 50), str(ball.rarity), font=stats_font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
    if card_name is not None and card_name in credits_color_cache:
        credits_color = credits_color_cache[card_name]
    else:
        credits_color = get_credit_color(image, (0, int(image.height * 0.8), image.width, image.height))
        if card_name is not None:
            credits_color_cache[card_name] = credits_color
    draw.text(
        (30, 1870),
        # Modifying the line below is breaking the licence as you are removing credits
        # If you don't want to receive a DMCA, just don't
        f"Created by El Laggron{special_credits}\nArtwork author: {ball_credits}",
        font=credits_font,
        fill=credits_color,
        stroke_width=0,
        stroke_fill=(255, 255, 255, 255),
    )

    if icon:
        icon = ImageOps.fit(icon, (192, 192))
        image.paste(icon, (1200, 30), mask=icon)
        icon.close()

    return image, {"format": "WEBP"}
