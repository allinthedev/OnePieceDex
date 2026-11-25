"""
The calendar drawn as a grid of doors, so a player sees at a glance what is open, what is theirs today, and
what is still shut.

Pillow only, no browser and no template: this is drawn in a thread and handed to Discord as a PNG, the same way
a card is. Everything on it is derived from the door count, so a 24 door calendar and a 25 door one both come
out looking deliberate.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ballsdex.core.image_generator.image_gen import SOURCES_PATH, open_image

PADDING = 40
HEADER = 120
CELL = 200
CELL_GAP = 18
RADIUS = 24

BACKDROP = (16, 24, 32, 255)
SHUT = (38, 52, 66, 255)
SHUT_EDGE = (60, 80, 98, 255)
OPENED = (28, 72, 52, 255)
OPENED_EDGE = (74, 158, 112, 255)
TODAY_EDGE = (242, 196, 92, 255)
MISSED_EDGE = (176, 84, 84, 255)
NUMBER = (236, 242, 248, 255)
NUMBER_SHUT = (150, 170, 188, 255)
TITLE = (248, 250, 252, 255)
SUBTITLE = (168, 186, 202, 255)

title_font = ImageFont.truetype(str(SOURCES_PATH / "ArsenicaTrial-Extrabold.ttf"), 52)
subtitle_font = ImageFont.truetype(str(SOURCES_PATH / "OpenSans-Semibold.ttf"), 28)
number_font = ImageFont.truetype(str(SOURCES_PATH / "OpenSans-Bold.ttf"), 72)


def columns_for(doors: int) -> int:
    """
    How wide the grid is. Kept between four and six columns so the image stays readable on a phone, and chosen
    so the last row is as full as it can be — a grid with one lonely door in its bottom row looks like a bug.
    """
    best, best_waste = 5, None
    for candidate in (4, 5, 6):
        rows = -(-doors // candidate)
        waste = rows * candidate - doors
        # `<=` so a tie goes to the wider grid: 24 doors read better as 6 by 4 than as 4 by 6
        if best_waste is None or waste <= best_waste:
            best, best_waste = candidate, waste
    return best


def draw_calendar(
    doors: int,
    opened: set[int],
    today: int,
    *,
    title: str = "",
    subtitle: str = "",
    background=None,
    can_catch_up: bool = False,
) -> BytesIO:
    """
    Draw the grid. `today` is the door of the day, 0 when the calendar is not running.

    A door is one of four things, and each reads differently: opened, open to you right now, missed (outlined in
    red, and only when the calendar lets you catch up), or still shut.
    """
    cols = columns_for(doors)
    rows = -(-doors // cols)
    width = PADDING * 2 + cols * CELL + (cols - 1) * CELL_GAP
    height = PADDING * 2 + HEADER + rows * CELL + (rows - 1) * CELL_GAP

    image = Image.new("RGBA", (width, height), BACKDROP)
    if background:
        try:
            # through the card generator's own loader, so the file descriptor is released like everywhere
            # else and a storage that is not the local disk still works
            with open_image(background) as art:
                backdrop = ImageOps.fit(art, (width, height))
            # darkened, so white numbers stay readable over any picture
            image.alpha_composite(Image.blend(backdrop, Image.new("RGBA", (width, height), BACKDROP), 0.55))
        except (OSError, ValueError):
            pass

    draw = ImageDraw.Draw(image)
    if title:
        draw.text((PADDING, PADDING - 6), title, font=title_font, fill=TITLE)
    if subtitle:
        draw.text((PADDING, PADDING + 56), subtitle, font=subtitle_font, fill=SUBTITLE)

    for index in range(doors):
        day = index + 1
        column, row = index % cols, index // cols
        left = PADDING + column * (CELL + CELL_GAP)
        top = PADDING + HEADER + row * (CELL + CELL_GAP)
        box = (left, top, left + CELL, top + CELL)

        is_open = day in opened
        is_today = day == today
        missed = not is_open and today and day < today and can_catch_up

        if is_open:
            fill, edge, ink, thickness = OPENED, OPENED_EDGE, NUMBER, 4
        elif is_today:
            fill, edge, ink, thickness = SHUT, TODAY_EDGE, NUMBER, 7
        elif missed:
            fill, edge, ink, thickness = SHUT, MISSED_EDGE, NUMBER_SHUT, 4
        else:
            fill, edge, ink, thickness = SHUT, SHUT_EDGE, NUMBER_SHUT, 3

        draw.rounded_rectangle(box, radius=RADIUS, fill=fill, outline=edge, width=thickness)
        draw.text((left + CELL / 2, top + CELL / 2), str(day), font=number_font, fill=ink, anchor="mm")
        if is_open:
            _tick(draw, left + CELL - 46, top + 30, OPENED_EDGE)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    image.close()
    return buffer


def _tick(draw: ImageDraw.ImageDraw, x: float, y: float, colour: tuple) -> None:
    """
    A check mark drawn with two lines rather than written with a glyph: not every font in here carries one, and
    a missing glyph comes out as a hollow box on the card.
    """
    draw.line([(x, y + 10), (x + 9, y + 20), (x + 26, y)], fill=colour, width=7, joint="curve")
