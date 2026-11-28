"""
Everything that moves berries or closes a battle, each step as one database transaction.

A battle is opened, started and closed from several places at once: two players clicking, a turn timer,
a command, a restart. Whatever order those land in, a wager has to leave each wallet once and come back
once. So nothing here trusts what its caller read a moment ago: every function locks the row it is about
to change, looks at the status that row really has, and then does its whole job or none of it.

The functions are plain synchronous Django, because a transaction is; the cog calls the `a...` wrappers.
"""

from datetime import timedelta

from asgiref.sync import sync_to_async
from currency_app.ledger import adjust_money
from currency_app.models import BerryTransaction
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from bd_models.models import Player

from ..models import BattleItem, BattleRecord, BattleSession, BattleSessionStatus, PlayerBattleItem

OPEN = (BattleSessionStatus.PROPOSED, BattleSessionStatus.ACTIVE)
# how long a battle can go without anybody touching it before it is taken for abandoned. A battle being
# played never gets there, its turn timer plays for whoever is away; a plan nobody completes does
STALE_AFTER = timedelta(minutes=30)

STARTED = "started"
GONE = "gone"
BROKE = "broke"

Reason = BerryTransaction.Reason


def _locked(session_id: int) -> BattleSession | None:
    return BattleSession.objects.select_for_update().filter(pk=session_id).first()


def start(session_id: int, state: dict) -> str:
    """
    Turn a plan into a battle, taking the wager from both players.

    Returns `STARTED`, `GONE` when the plan is no longer one (already started, or cancelled), or `BROKE`
    when one of the two cannot pay: then nobody is charged and the plan is left as it was.
    """
    with transaction.atomic():
        session = _locked(session_id)
        if session is None or session.status != BattleSessionStatus.PROPOSED:
            return GONE
        if session.wager_amount:
            try:
                # its own savepoint: when the second player cannot pay, the first one gets their stake back
                with transaction.atomic():
                    # always in the same order, so two battles starting at once cannot lock each other out
                    for player_id in sorted((session.player1_id, session.player2_id)):
                        adjust_money(
                            player_id,
                            -session.wager_amount,
                            reason=Reason.BATTLE_WAGER_HOLD,
                            description=f"Battle #{session.pk}",
                        )
            except ValueError:
                return BROKE
        session.status = BattleSessionStatus.ACTIVE
        session.state = state
        session.save(update_fields=("status", "state", "updated_at"))
    return STARTED


def advance(session_id: int, turn: int, state: dict) -> bool:
    """
    Store the state a turn leaves behind, if that turn is still the one to play.

    The turn number is the token: whoever writes turn 3 first has played it, and anybody else holding a
    state built on turn 3 writes nothing. False means exactly that.
    """
    return (
        BattleSession.objects.filter(pk=session_id, status=BattleSessionStatus.ACTIVE, state__turn=turn).update(
            state=state, updated_at=timezone.now()
        )
        == 1
    )


def close(session_id: int, state: dict, winner_id: int, earnings: int) -> bool:
    """
    End a battle: the pot and the reward to the winner, and the record of it, all or nothing.

    False when the battle was not running any more, which is what the second of two final blows landing
    together gets: the first one has already paid.
    """
    with transaction.atomic():
        session = _locked(session_id)
        if session is None or session.status != BattleSessionStatus.ACTIVE:
            return False
        session.status = BattleSessionStatus.FINISHED
        session.state = state
        session.save(update_fields=("status", "state", "updated_at"))
        if session.wager_amount:
            adjust_money(
                winner_id,
                session.wager_amount * 2,
                reason=Reason.BATTLE_PAYOUT,
                description=f"Wager of battle #{session.pk}",
            )
        if earnings:
            adjust_money(
                winner_id, earnings, reason=Reason.BATTLE_PAYOUT, description=f"Reward of battle #{session.pk}"
            )
        BattleRecord.objects.create(
            player1_id=session.player1_id,
            player2_id=session.player2_id,
            winner_id=winner_id,
            wager_amount=session.wager_amount,
            winner_earnings=earnings,
            turns=state.get("turn", 0),
        )
    return True


def cancel(session_id: int, only: tuple = OPEN) -> str | None:
    """
    Call a battle off, giving back a wager that had already been taken.

    Returns the status it was in, or None when there was nothing to call off: it was over already, or it
    was not in one of the `only` statuses (a Cancel button has no business ending a battle that started).
    """
    with transaction.atomic():
        session = _locked(session_id)
        if session is None or session.status not in only:
            return None
        was = session.status
        session.status = BattleSessionStatus.CANCELLED
        session.save(update_fields=("status", "updated_at"))
        # the wager only ever leaves the wallets when the battle starts
        if was == BattleSessionStatus.ACTIVE and session.wager_amount:
            for player_id in sorted((session.player1_id, session.player2_id)):
                adjust_money(
                    player_id,
                    session.wager_amount,
                    reason=Reason.BATTLE_WAGER_REFUND,
                    description=f"Battle #{session.pk} called off",
                )
    return was


def cancel_all(stale_only: bool) -> list[int]:
    """
    Call off the battles nothing will ever finish, and return their ids.

    After a restart that is every battle still open: the buttons of a board are gone with the process that
    posted them. After a reload of the package the boards still answer, so only the battles nobody touched
    for `STALE_AFTER` are closed.
    """
    sessions = BattleSession.objects.filter(status__in=OPEN)
    if stale_only:
        sessions = sessions.filter(updated_at__lt=timezone.now() - STALE_AFTER)
    return [pk for pk in sessions.values_list("pk", flat=True) if cancel(pk) is not None]


class ItemGone(Exception):
    """The item was withdrawn from the shop."""


def buy(player_id: int, item_id: int) -> tuple[BattleItem, int, int]:
    """
    Sell one item of the shop: what was bought, how many of it the player now owns, and their balance.

    Raises `ItemGone`, or the ledger's `ValueError` when the player cannot pay. Paying and receiving are
    one transaction on the player's locked row, so two purchases landing together are two purchases.
    """
    with transaction.atomic():
        balance = Player.objects.select_for_update().values_list("money", flat=True).get(pk=player_id)
        item = BattleItem.objects.filter(pk=item_id, enabled=True).first()
        if item is None:
            raise ItemGone
        if item.price:
            balance = adjust_money(player_id, -item.price, reason=Reason.BATTLE_ITEM_BUY, description=item.name)
        owned, _ = PlayerBattleItem.objects.get_or_create(player_id=player_id, item=item)
        PlayerBattleItem.objects.filter(pk=owned.pk).update(quantity=F("quantity") + 1)
        owned.refresh_from_db(fields=("quantity",))
    return item, owned.quantity, balance


def spend_item(player_id: int, item_id: int) -> bool:
    """Use up one copy of an item. False when the player has none left, and then nothing changed."""
    with transaction.atomic():
        spent = PlayerBattleItem.objects.filter(player_id=player_id, item_id=item_id, quantity__gte=1).update(
            quantity=F("quantity") - 1
        )
        PlayerBattleItem.objects.filter(player_id=player_id, item_id=item_id, quantity__lte=0).delete()
    return spent == 1


astart = sync_to_async(start)
aadvance = sync_to_async(advance)
aclose = sync_to_async(close)
acancel = sync_to_async(cancel)
acancel_all = sync_to_async(cancel_all)
abuy = sync_to_async(buy)
aspend_item = sync_to_async(spend_item)
