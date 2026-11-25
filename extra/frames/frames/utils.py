"""
Frames live in `Ball.capacity_logic`, under two kinds of key.

A **dated** frame is "MM-DD-YYYY" for every treasure of the ball, "MM-DD-YYYY:<special id>" for the treasures of
that special only, and "MM-DD-YYYY:0" for the treasures without special only. Those are the ones a catch can roll:
on its day, a new treasure may get the art.

A **named** frame is a plain slug, like "haki". It has no day, so nothing ever rolls it — it is only given on
purpose, as a pass reward or by an admin spawn. That is what makes it easy to point at: a reward asks for "haki"
rather than for "09-20-2026:3".

Both kinds can carry a `name`, the label players and staff read, and an `emoji` shown next to it. A dated frame
with a name can be handed out by that name too, so an event does not have to spell out a date.
"""

from __future__ import annotations

import random
import re
from datetime import date
from typing import Any

# a dated frame: the day, optionally the special it is for, optionally the slug of its own name.
# The name is what lets two different frames run on the same day for the same treasure.
FRAME_KEY_RE = re.compile(r"^(\d{2}-\d{2}-\d{4})(?::(\d+))?(?:#([a-z0-9][a-z0-9_-]{0,31}))?$")
# a named frame: lowercase, no spaces, so it is easy to type in a reward
NAME_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
# in place of a special ID: the treasures without special
NO_SPECIAL = 0


def frame_key(day: date, special_id: int | None = None, variant: str = "") -> str:
    """
    The key of a frame: for every treasure with `special_id` None, else for the treasures of that special, or
    without special with `NO_SPECIAL`.

    `variant` is the slug of the frame's own name, and only has to be given when another frame already
    holds the plain key for that day — which is how two frames can run on the same day.
    """
    key = day.strftime("%m-%d-%Y")
    if special_id is not None:
        key = f"{key}:{special_id}"
    return f"{key}#{variant}" if variant else key


def parse_frame_key(key: str) -> tuple[str, int | None] | None:
    """
    The date (MM-DD-YYYY) and the special ID of a frame key, None if it isn't a frame key.
    """
    match = FRAME_KEY_RE.match(key)
    if match is None:
        return None
    return match.group(1), None if match.group(2) is None else int(match.group(2))


def frame_variant(key: str) -> str:
    """The name slug a dated key carries, empty when it carries none."""
    match = FRAME_KEY_RE.match(key)
    return (match.group(3) or "") if match else ""


def frames_of_day(capacity_logic: Any, day: date, special_id: int | None) -> list[dict]:
    """
    Every frame stored for this day and this scope, however many there are.

    The scope is the whole of it: `None` means the frames of every treasure, a special's ID means the ones
    of that special, `NO_SPECIAL` the ones of the treasures without special. Two frames in the same scope
    on the same day are both returned, which is what makes a draw between them possible.
    """
    if not isinstance(capacity_logic, dict):
        return []
    wanted = (day.strftime("%m-%d-%Y"), special_id)
    return [entry for key, entry in capacity_logic.items() if is_frame_entry(entry) and parse_frame_key(key) == wanted]


def is_frame_entry(value: Any) -> bool:
    return isinstance(value, dict) and bool({"card", "spawn", "credits", "catch"} & value.keys())


def slugify_frame_name(name: str) -> str:
    """
    The key a named frame is stored under: "Haki Aura" becomes "haki-aura".
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:32].rstrip("-")


def is_named_key(key: str) -> bool:
    """
    Whether this key is a named frame rather than a dated one.
    """
    return bool(NAME_KEY_RE.match(key)) and FRAME_KEY_RE.match(key) is None


def iter_frames(capacity_logic: Any):
    """
    Every frame stored on a treasure, as (key, entry) pairs, dated or named.
    """
    if not isinstance(capacity_logic, dict):
        return
    for key, value in capacity_logic.items():
        if is_frame_entry(value) and (parse_frame_key(key) is not None or is_named_key(key)):
            yield key, value


def frame_label(key: str, entry: dict) -> str:
    """
    What a frame is called: its name when it has one, else its key.
    """
    name = entry.get("name")
    return str(name) if name else key


def frame_mark(entry: dict | None, fallback: str = "") -> str:
    """
    The emoji and name shown next to a framed treasure, like "<:Haki:123> Haki".
    """
    if not isinstance(entry, dict):
        return fallback
    parts = [str(entry.get("emoji") or ""), str(entry.get("name") or fallback)]
    return " ".join(part for part in parts if part)


def frames_depend_on_special(capacity_logic: Any, day: date) -> bool:
    """
    Whether some frames of this day only go to the treasures of a special, or to the treasures without special.
    """
    if not isinstance(capacity_logic, dict):
        return False
    prefix = frame_key(day) + ":"
    return any(key.startswith(prefix) and is_frame_entry(value) for key, value in capacity_logic.items())


def pick_frame(capacity_logic: Any, special_id: int | None, day: date) -> dict | None:
    """
    The frame a new treasure of this special, None without special, gets on this day.

    The frames of its special, or of the treasures without special, come first; the frames of every
    treasure only get a look in afterwards. Within one of those two groups the order is shuffled, so that
    when several frames run on the same day none of them is quietly favoured by how its key sorts — each
    is then offered its own chance in turn, and the first to land is the one given.
    """
    if not isinstance(capacity_logic, dict):
        return None
    for scope in (NO_SPECIAL if special_id is None else special_id, None):
        candidates = frames_of_day(capacity_logic, day, scope)
        random.shuffle(candidates)
        for entry in candidates:
            if _roll(entry):
                return entry
    return None


def _roll(entry: dict) -> bool:
    chance = entry.get("chance", 100)
    return isinstance(chance, int) and 1 <= chance <= 100 and random.randint(1, 100) <= chance
