from typing import TYPE_CHECKING

from .models import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


def format_currency(amount: int, shortened: bool = True, bot: "BallsDexBot | None" = None):
    humanized = f"{amount:,}"
    if shortened:
        # the emoji can only be resolved with the bot, so the panel always falls to the symbol
        emoji = settings.currency_emoji(bot) if bot is not None else None
        symbol = settings.currency_symbol or ""
        if emoji or symbol:
            # the symbol hugs the number on the side the setting asks for, and the emoji sits
            # outside it. A dex that fills both therefore shows both, "฿1,000 <:berry:>".
            if not symbol:
                # with no symbol the emoji stands where one would, which is what the setting
                # means to a dex that has only ever had an emoji
                return f"{emoji} {humanized}" if settings.currency_symbol_before else f"{humanized} {emoji}"
            if settings.currency_symbol_before:
                shown = f"{symbol}{humanized}"
                return f"{shown} {emoji}" if emoji else shown
            shown = f"{humanized}{symbol}"
            return f"{emoji} {shown}" if emoji else shown
        # neither an emoji nor a symbol is configured, fall back to the full form
    if amount == 0:
        # "no berries", not "no berry": nothing is a plural everywhere but in the singular form
        return f"no {settings.currency_display_plural(bot)}"
    elif amount == 1:
        return f"{humanized} {settings.currency_display_name(bot)}"
    else:
        return f"{humanized} {settings.currency_display_plural(bot)}"


# separators that `format_currency` may emit, plus the ones a user is likely to type by hand
_CURRENCY_SEPARATORS = str.maketrans("", "", ", _\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}")


def parse_currency(text: str) -> int:
    """
    Parse a user-supplied amount back into an integer, raising `ValueError` if it is not one.
    """
    return int(text.strip().translate(_CURRENCY_SEPARATORS))
