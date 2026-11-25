"""
The draw, the wrapping and the opening.

Nothing here ever tells a player who their giver was, or how their parcel came to be filled. Every path below
ends with the same `SantaGift`, differing only in a `kind` the commands never show: that is what makes "no
penalty for not giving" true rather than merely stated.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone
from eventpass_app import wallet
from eventpass_app.models import PassWalletEntry

from bd_models.models import BallInstance, mark_no_frame
from settings.models import settings

from .models import SantaEntry, SantaGift, SantaWish, SecretSanta

log = logging.getLogger("santa")

# a chain of two is just a pair giving to each other, which is the one thing a chain is meant to avoid
MIN_PLAYERS = 3
# as the trade package treats a stale lock
TRADE_LOCK = timedelta(minutes=30)


class Refused(Exception):
    """Something that cannot be done, carrying the line to show the player."""


@dataclass
class Opened:
    gift: SantaGift
    instance: BallInstance


def _entry_of(santa: SecretSanta, player_id: int) -> SantaEntry:
    entry = SantaEntry.objects.filter(santa=santa, player_id=player_id).first()
    if entry is None:
        raise Refused("You are not in this one.")
    return entry


def _wished_balls(entry: SantaEntry) -> dict[int, SantaWish]:
    return {wish.ball_id: wish for wish in entry.wishes.all()}


# ── signing up ──────────────────────────────────────────────────────────────────────────────────


def join(santa_id: int, player_id: int) -> SantaEntry:
    """Sign a player up. Doing it twice is not an error, it just hands back the entry they already had."""
    with transaction.atomic():
        santa = SecretSanta.objects.filter(pk=santa_id).first()
        if santa is None or not santa.signups_open():
            raise Refused("Sign-ups are closed.")
        entry, _ = SantaEntry.objects.get_or_create(santa=santa, player_id=player_id)
    return entry


def set_wish(santa_id: int, player_id: int, ball_id: int, position: int) -> SantaWish:
    """
    Put a card on a player's list, in one of its slots. Replaces whatever was in that slot.

    A list can be changed right up to the draw, and never after it: a Santa who has already read the list must
    not find it has moved under them.
    """
    from bd_models.models import Ball

    with transaction.atomic():
        santa = SecretSanta.objects.filter(pk=santa_id).first()
        if santa is None or not santa.enabled:
            raise Refused("This Secret Santa is closed.")
        if santa.drawn_at is not None:
            raise Refused("The chain has been drawn, so the lists are settled now.")
        if not 1 <= position <= santa.wishlist_size:
            raise Refused(f"You have {santa.wishlist_size} slots, numbered 1 to {santa.wishlist_size}.")
        entry = _entry_of(santa, player_id)
        ball = Ball.objects.filter(pk=ball_id).first()
        if ball is None:
            raise Refused("No such treasure.")
        if not santa.may_be_wished(ball):
            raise Refused(
                f"**{ball.country}** is too rare to ask for. Pick something more common — that is what keeps "
                f"the lists fair to whoever draws you."
            )
        clash = entry.wishes.filter(ball_id=ball_id).exclude(position=position).first()
        if clash is not None:
            raise Refused(f"**{ball.country}** is already in slot {clash.position} of your list.")
        entry.wishes.filter(position=position).delete()
        return SantaWish.objects.create(entry=entry, ball_id=ball_id, position=position)


# ── the draw ────────────────────────────────────────────────────────────────────────────────────


def draw(santa_id: int) -> int:
    """
    Shuffle everyone who has a list into one single chain. Returns how many were drawn in.

    Players who never wrote anything down are left out rather than drawn in: their Santa would have nothing to
    pick from, and the chain has to be unbroken to work.
    """
    with transaction.atomic():
        santa = SecretSanta.objects.select_for_update().filter(pk=santa_id).first()
        if santa is None:
            raise Refused("That Secret Santa is gone.")
        if santa.drawn_at is not None:
            raise Refused("It has already been drawn. Clear the draw date first if you really mean to redraw.")
        entries = list(SantaEntry.objects.filter(santa=santa).annotate(listed=Count("wishes")).filter(listed__gte=1))
        if len(entries) < MIN_PLAYERS:
            raise Refused(
                f"Only {len(entries)} player(s) wrote a list. A chain needs at least {MIN_PLAYERS}, or it is "
                f"just two people giving to each other."
            )
        random.shuffle(entries)
        # cleared in its own statement first, so assigning the new chain cannot collide with the old one
        SantaEntry.objects.filter(santa=santa).update(gives_to=None)
        for index, entry in enumerate(entries):
            entry.gives_to = entries[(index + 1) % len(entries)]
        SantaEntry.objects.bulk_update(entries, ["gives_to"])
        santa.drawn_at = timezone.now()
        santa.save(update_fields=("drawn_at",))
    log.info("santa %s: drew a chain of %s", santa_id, len(entries))
    return len(entries)


# ── filling a parcel ────────────────────────────────────────────────────────────────────────────


def _ready_to_wrap(santa_id: int, player_id: int) -> tuple[SecretSanta, SantaEntry, SantaEntry]:
    """The santa, the giver's entry and the receiver's, or a refusal saying why it cannot be wrapped."""
    santa = SecretSanta.objects.select_related("special", "event_pass").filter(pk=santa_id).first()
    if santa is None or not santa.enabled:
        raise Refused("This Secret Santa is closed.")
    if santa.drawn_at is None:
        raise Refused("The chain has not been drawn yet.")
    if not santa.wrapping_open():
        raise Refused("It is too late to fill your parcel.")
    giver = _entry_of(santa, player_id)
    if giver.gives_to_id is None:
        raise Refused("You were not drawn into the chain, so you owe nobody a parcel.")
    if SantaGift.objects.filter(santa=santa, giver=giver).exists():
        raise Refused("Your parcel is already filled. One each.")
    receiver = SantaEntry.objects.filter(pk=giver.gives_to_id).first()
    if receiver is None:
        raise Refused("Whoever you were drawn to give to is no longer taking part.")
    return santa, giver, receiver


def _wrap_card(santa_id: int, player_id: int, instance_pk: int) -> SantaGift:
    """Fill the parcel with one of the giver's own cards. The card is consumed."""
    now = timezone.now()
    with transaction.atomic():
        santa, giver, receiver = _ready_to_wrap(santa_id, player_id)
        wished = _wished_balls(receiver)
        if not wished:
            raise Refused("They never wrote a list, so there is nothing to give them.")

        instance = (
            BallInstance.objects.select_for_update()
            .select_related("ball")
            .filter(pk=instance_pk, player_id=player_id, deleted=False)
            .first()
        )
        if instance is None:
            raise Refused("That card is not yours, or it is already gone.")
        if instance.ball_id not in wished:
            raise Refused("That is not on their list. Use `/santa target` to see what they asked for.")
        if instance.special_id is not None:
            raise Refused(
                "A card that already carries a special cannot go in a parcel — it comes out as the event's "
                "special. A framed one can, and keeps its frame."
            )
        if not instance.tradeable or not instance.ball.tradeable:
            raise Refused("That card cannot be given away.")
        if instance.favorite:
            raise Refused("That one is a favourite. Unfavourite it first: a parcel is never given back.")
        if instance.locked and instance.locked > now - TRADE_LOCK:
            raise Refused("That card is locked in a trade right now.")

        gift = SantaGift.objects.create(
            santa=santa,
            giver=giver,
            receiver=receiver,
            ball_id=instance.ball_id,
            kind=SantaGift.Kind.CARD,
            attack_bonus=instance.attack_bonus,
            health_bonus=instance.health_bonus,
            roll_bonuses=False,
            frame=dict(instance.extra_data) if isinstance(instance.extra_data, dict) else {},
        )
        BallInstance.objects.filter(pk=instance.pk).update(deleted=True, favorite=False)
    return gift


def _wrap_paid(santa_id: int, player_id: int, ball_id: int) -> SantaGift:
    """Fill the parcel by paying for it, with the card the giver chose off the list."""
    with transaction.atomic():
        santa, giver, receiver = _ready_to_wrap(santa_id, player_id)
        if not santa.price:
            raise Refused("Paying for a parcel is not allowed here. Give one of your own cards.")
        wished = _wished_balls(receiver)
        if ball_id not in wished:
            raise Refused("That is not on their list.")
        try:
            wallet.adjust(
                player_id,
                santa.event_pass_id,
                -santa.price,
                reason=PassWalletEntry.Reason.SHOP,
                description=f"{santa.name}: a parcel"[: PassWalletEntry.DESCRIPTION_MAX_LENGTH],
            )
        except wallet.NotEnough as error:
            raise Refused(
                f"You hold {wallet.format_tokens(santa.event_pass, error.held)}, and a parcel costs "
                f"{wallet.format_tokens(santa.event_pass, santa.price)}."
            ) from error
        return SantaGift.objects.create(
            santa=santa, giver=giver, receiver=receiver, ball_id=ball_id, kind=SantaGift.Kind.PAID, roll_bonuses=True
        )


def _fill_the_rest(santa_id: int) -> int:
    """
    Fill every parcel still empty once the wrapping time is up. Returns how many were filled.

    Drawn from the receiver's own list, so what arrives is something they asked for, and written as the same
    kind of row as any other parcel. Nobody is told this ran, which is the entire point: a parcel nobody filled
    and a parcel somebody filled must be impossible to tell apart.
    """
    now = timezone.now()
    filled = 0
    with transaction.atomic():
        santa = SecretSanta.objects.select_for_update().filter(pk=santa_id).first()
        if santa is None or not santa.fill_the_rest or santa.drawn_at is None:
            return 0
        if now <= santa.wrap_until or santa.filled_at is not None:
            return 0
        owing = (
            SantaEntry.objects.filter(santa=santa, gives_to__isnull=False, gift_given__isnull=True)
            .select_related("gives_to")
            .prefetch_related("gives_to__wishes")
        )
        for giver in owing:
            receiver = giver.gives_to
            if receiver is None:
                continue
            wishes = list(receiver.wishes.all())
            if not wishes:
                continue
            wish = random.choice(wishes)
            try:
                # its own savepoint: an IntegrityError would otherwise poison the whole transaction and the
                # next parcel of the loop would fail rather than simply being skipped
                with transaction.atomic():
                    SantaGift.objects.create(
                        santa=santa,
                        giver=giver,
                        receiver=receiver,
                        ball_id=wish.ball_id,
                        kind=SantaGift.Kind.FILLED,
                        roll_bonuses=True,
                    )
            except IntegrityError:
                continue  # it was filled in the meantime
            filled += 1
        santa.filled_at = now
        santa.save(update_fields=("filled_at",))
    if filled:
        log.info("santa %s: filled %s empty parcel(s)", santa_id, filled)
    return filled


# ── opening it ──────────────────────────────────────────────────────────────────────────────────


def _open(santa_id: int, player_id: int, server_id: int | None) -> Opened:
    """
    Turn the parcel into a real card. The card is made here and not before, so nothing can be traded early.
    """
    with transaction.atomic():
        santa = SecretSanta.objects.select_related("special").filter(pk=santa_id).first()
        if santa is None or not santa.enabled:
            raise Refused("This Secret Santa is closed.")
        if not santa.opening_open():
            if timezone.now() < santa.opens_at:
                raise Refused("Not yet. Parcels open on Christmas morning.")
            raise Refused("It is too late to open it.")
        entry = _entry_of(santa, player_id)
        gift = SantaGift.objects.select_for_update().filter(santa=santa, receiver=entry, opened_at__isnull=True).first()
        if gift is None:
            if SantaGift.objects.filter(santa=santa, receiver=entry).exists():
                raise Refused("You have already opened yours.")
            raise Refused("There is no parcel for you.")

        if gift.roll_bonuses:
            attack = random.randint(-settings.max_attack_bonus, settings.max_attack_bonus)
            health = random.randint(-settings.max_health_bonus, settings.max_health_bonus)
        else:
            attack, health = gift.attack_bonus, gift.health_bonus

        instance = BallInstance(
            player_id=player_id,
            ball_id=gift.ball_id,
            special_id=santa.special_id,
            attack_bonus=attack,
            health_bonus=health,
            tradeable=True,
            server_id=server_id,
            extra_data=dict(gift.frame) if isinstance(gift.frame, dict) else {},
        )
        if not instance.extra_data:
            # a card that went in plain comes out plain: the frames package would otherwise dress it in
            # whatever frame happens to be running on Christmas morning
            mark_no_frame(instance)
        instance.save()
        gift.opened_at = timezone.now()
        gift.instance = instance
        gift.save(update_fields=("opened_at", "instance"))
    return Opened(gift=gift, instance=instance)


# ── the async faces of all of the above ─────────────────────────────────────────────────────────


async def ajoin(santa_id: int, player_id: int) -> SantaEntry:
    return await sync_to_async(join)(santa_id, player_id)


async def aset_wish(santa_id: int, player_id: int, ball_id: int, position: int) -> SantaWish:
    return await sync_to_async(set_wish)(santa_id, player_id, ball_id, position)


async def adraw(santa_id: int) -> int:
    return await sync_to_async(draw)(santa_id)


async def awrap_card(santa_id: int, player_id: int, instance_pk: int) -> SantaGift:
    return await sync_to_async(_wrap_card)(santa_id, player_id, instance_pk)


async def awrap_paid(santa_id: int, player_id: int, ball_id: int) -> SantaGift:
    return await sync_to_async(_wrap_paid)(santa_id, player_id, ball_id)


async def afill_the_rest(santa_id: int) -> int:
    return await sync_to_async(_fill_the_rest)(santa_id)


async def aopen(santa_id: int, player_id: int, *, server_id: int | None = None) -> Opened:
    return await sync_to_async(_open)(santa_id, player_id, server_id)
