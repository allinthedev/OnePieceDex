"""
An emoji typed into the admin panel, turned into something Discord will accept.

A select option carrying an emoji Discord does not recognise is refused outright, and the
refusal takes the whole command with it: one mistyped row in the panel and `/player settings`
stops working for every player. So an emoji that cannot be resolved is dropped here instead of
being sent and argued about.
"""

import re
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

# `<a:name:id>` as Discord writes it. The bounds are Discord's own: a name of 2 to 32
# characters, and a snowflake, which has been 18 digits since 2016 and will not shrink.
CUSTOM_EMOJI = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:(?P<id>[0-9]{15,21})>")


def usable_emoji(bot: "BallsDexBot", raw: str | None) -> "discord.Emoji | str | None":
    """
    The emoji to put on a component, or None when there is nothing safe to put there.

    A unicode character is handed back as it is. A custom emoji is resolved against the bot,
    whose `get_emoji` covers both the servers it is in and its own application emojis; one it
    cannot reach would be refused by Discord, so it is dropped. Anything shaped like a custom
    emoji without being one — mistyped, or cut short by a field that was too small — is
    dropped as well, rather than being sent as a unicode character it is not.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if match := CUSTOM_EMOJI.fullmatch(raw):
        return bot.get_emoji(int(match["id"]))
    if any(character in raw for character in "<>:"):
        return None
    return raw
