"""
Single entry point for every movement of a pass's own currency — the snowflakes of a Christmas pass.

Every change goes through `adjust` (or the async `aadjust`), which moves the balance and writes the matching
`PassWalletEntry` in the same transaction, the same way `currency_app.ledger` does it for berries. The wallet row
is locked for the duration, so the recorded `balance_after` is always the real balance and two spends cannot
interleave — which is what stops a player buying the same boost twice with one balance.

A gift to a crew is one movement out of a player's wallet and one into the crew's pot, both inside one
transaction: the pot can never hold what a player still has.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async
from django.db import transaction

if TYPE_CHECKING:
    from .models import EventPass


class NotEnough(Exception):
    """A wallet was asked for more than it holds. Carries what was missing, for the message shown."""

    def __init__(self, held: int, asked: int):
        self.held = held
        self.asked = asked
        super().__init__(f"holds {held}, asked for {asked}")


def wallet_of(player_id: int, event_pass_id: int):
    """The player's wallet for this pass, created empty the first time it is needed."""
    from .models import PassWallet

    wallet, _ = PassWallet.objects.get_or_create(player_id=player_id, event_pass_id=event_pass_id)
    return wallet


def crew_wallet_of(crew_id: int, event_pass_id: int):
    """The crew's pot for this pass, created empty the first time it is needed."""
    from .models import CrewPassWallet

    pot, _ = CrewPassWallet.objects.get_or_create(crew_id=crew_id, event_pass_id=event_pass_id)
    return pot


def balance(player_id: int, event_pass_id: int) -> int:
    from .models import PassWallet

    return (
        PassWallet.objects.filter(player_id=player_id, event_pass_id=event_pass_id)
        .values_list("balance", flat=True)
        .first()
        or 0
    )


async def abalance(player_id: int, event_pass_id: int) -> int:
    from .models import PassWallet

    held = (
        await PassWallet.objects.filter(player_id=player_id, event_pass_id=event_pass_id)
        .values_list("balance", flat=True)
        .afirst()
    )
    return held or 0


async def acrew_balance(crew_id: int, event_pass_id: int) -> int:
    from .models import CrewPassWallet

    held = (
        await CrewPassWallet.objects.filter(crew_id=crew_id, event_pass_id=event_pass_id)
        .values_list("balance", flat=True)
        .afirst()
    )
    return held or 0


def adjust(player_id: int, event_pass_id: int, amount: int, *, reason: str = "", description: str = "") -> int:
    """
    Apply a signed change to a player's wallet and record it. Returns the new balance.

    `amount` is signed: positive credits, negative debits. Raises `NotEnough` on a debit the wallet cannot
    cover, so a caller never has to check the balance first and then hope nothing happened in between.
    """
    from .models import PassWallet, PassWalletEntry

    with transaction.atomic():
        wallet_of(player_id, event_pass_id)
        locked = PassWallet.objects.select_for_update().get(player_id=player_id, event_pass_id=event_pass_id)
        new_balance = locked.balance + amount
        if new_balance < 0:
            raise NotEnough(locked.balance, -amount)

        locked.balance = new_balance
        if amount > 0:
            locked.earned += amount
        locked.save(update_fields=("balance", "earned", "updated_at"))

        PassWalletEntry.objects.create(
            wallet=locked,
            amount=amount,
            balance_after=new_balance,
            reason=reason or PassWalletEntry.Reason.ADMIN,
            description=description[: PassWalletEntry.DESCRIPTION_MAX_LENGTH],
        )
    return new_balance


async def aadjust(player_id: int, event_pass_id: int, amount: int, *, reason: str = "", description: str = "") -> int:
    """Async wrapper around [`adjust`][]."""
    return await sync_to_async(adjust)(player_id, event_pass_id, amount, reason=reason, description=description)


def adjust_crew(crew_id: int, event_pass_id: int, amount: int, *, reason: str = "", description: str = "") -> int:
    """The same as [`adjust`][], for a crew's pot."""
    from .models import CrewPassWallet, PassWalletEntry

    with transaction.atomic():
        crew_wallet_of(crew_id, event_pass_id)
        locked = CrewPassWallet.objects.select_for_update().get(crew_id=crew_id, event_pass_id=event_pass_id)
        new_balance = locked.balance + amount
        if new_balance < 0:
            raise NotEnough(locked.balance, -amount)

        locked.balance = new_balance
        if amount > 0:
            locked.received += amount
        locked.save(update_fields=("balance", "received", "updated_at"))

        PassWalletEntry.objects.create(
            crew_wallet=locked,
            amount=amount,
            balance_after=new_balance,
            reason=reason or PassWalletEntry.Reason.ADMIN,
            description=description[: PassWalletEntry.DESCRIPTION_MAX_LENGTH],
        )
    return new_balance


async def aadjust_crew(
    crew_id: int, event_pass_id: int, amount: int, *, reason: str = "", description: str = ""
) -> int:
    """Async wrapper around [`adjust_crew`][]."""
    return await sync_to_async(adjust_crew)(crew_id, event_pass_id, amount, reason=reason, description=description)


def give_to_crew(player_id: int, crew_id: int, event_pass_id: int, amount: int, *, label: str = "") -> int:
    """
    Move currency from a player's wallet into their crew's pot. Returns the pot's new balance.

    Both movements happen in one transaction: the pot never holds what the player still has, and a gift that
    cannot be covered leaves both sides untouched.
    """
    from .models import PassWalletEntry

    if amount <= 0:
        raise ValueError("A gift has to be worth something")
    with transaction.atomic():
        adjust(
            player_id,
            event_pass_id,
            -amount,
            reason=PassWalletEntry.Reason.CREW_GIFT,
            description=label or "Given to the crew",
        )
        return adjust_crew(
            crew_id,
            event_pass_id,
            amount,
            reason=PassWalletEntry.Reason.CREW_GIFT,
            description=label or f"From player {player_id}",
        )


async def agive_to_crew(player_id: int, crew_id: int, event_pass_id: int, amount: int, *, label: str = "") -> int:
    """Async wrapper around [`give_to_crew`][]."""
    return await sync_to_async(give_to_crew)(player_id, crew_id, event_pass_id, amount, label=label)


def give_to_player(sender_id: int, receiver_id: int, event_pass_id: int, amount: int, *, label: str = "") -> int:
    """
    Move currency from one player's wallet to another's. Returns the receiver's new balance.

    Both movements happen in one transaction, so the currency is never in two wallets at once and never in
    none: a gift the sender cannot cover leaves both sides exactly as they were.
    """
    from .models import PassWalletEntry

    if amount <= 0:
        raise ValueError("A gift has to be worth something")
    if sender_id == receiver_id:
        raise ValueError("A player cannot give to themselves")
    with transaction.atomic():
        adjust(
            sender_id,
            event_pass_id,
            -amount,
            reason=PassWalletEntry.Reason.GIFT_SENT,
            description=label or f"Given to player {receiver_id}",
        )
        return adjust(
            receiver_id,
            event_pass_id,
            amount,
            reason=PassWalletEntry.Reason.GIFT_RECEIVED,
            description=label or f"From player {sender_id}",
        )


async def agive_to_player(
    sender_id: int, receiver_id: int, event_pass_id: int, amount: int, *, label: str = ""
) -> int:
    """Async wrapper around [`give_to_player`][]."""
    return await sync_to_async(give_to_player)(sender_id, receiver_id, event_pass_id, amount, label=label)


async def adaily_grant(player_id: int, *, label: str = "") -> list[tuple["EventPass", int]]:
    """
    Hand out the daily currency of every pass running right now. Returns what each pass gave.

    This is deliberately open to everybody who claims: a pass meant to be earned gates its tiers, not the few
    snowflakes a daily claim drops. A pass that hands out none, or never named a currency, gives nothing.
    """
    from django.utils import timezone

    from .models import EventPass, PassWalletEntry

    now = timezone.now()
    given: list[tuple[EventPass, int]] = []
    passes = (
        EventPass.objects.filter(status=EventPass.Status.ACTIVE, daily_currency__gt=0)
        .exclude(currency_name="")
        .order_by("position", "pk")
    )
    async for event_pass in passes:
        if event_pass.starts_at and now < event_pass.starts_at:
            continue
        if event_pass.ends_at and now > event_pass.ends_at:
            continue
        await aadjust(
            player_id,
            event_pass.pk,
            event_pass.daily_currency,
            reason=PassWalletEntry.Reason.DAILY,
            description=label or "Daily claim",
        )
        given.append((event_pass, event_pass.daily_currency))
    return given


def format_tokens(event_pass: "EventPass", amount: int) -> str:
    """
    An amount written the way the pass names its currency: "1,200 ❄️ Snowflakes".

    A pass that named no currency still reads sensibly, which keeps every message that shows a price safe on a
    pass that was set up without one.
    """
    name = (event_pass.currency_name or "tokens").strip()
    emoji = (event_pass.currency_emoji or "").strip()
    return f"{amount:,} {emoji} {name}".replace("  ", " ").strip()
