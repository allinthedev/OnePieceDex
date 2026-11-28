import logging
import random
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async
from currency_app.models import BerryTransaction
from discord.utils import format_dt
from django.db.models import F
from django.utils import timezone
from eventpass_app import wallet
from eventpass_app.models import PassWalletEntry
from eventshop_app.boosts import buy_or_extend, describe
from eventshop_app.models import ActiveBoost, BoostKind
from merchant_app.models import GlobalShop, MerchantItem, MerchantPurchase, merchant_items

from ballsdex.core.game_events import Event, EventContext, bus
from bd_models.models import BallInstance, Player
from settings.models import settings
from settings.utils import format_currency

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger(__name__)

# what the player walks away with: a card, or an hour of boost on the main server
Bought = BallInstance | ActiveBoost


class PurchaseError(Exception):
    """
    The purchase could not go through, the message is meant to be shown to the player.
    """


async def _release_player_claim(claimed: bool, player: Player, item: MerchantItem) -> None:
    """
    Give a player their slot back when a purchase that had claimed one fails, so a failed buy does not eat
    into their allowance.
    """
    if not claimed:
        return
    await MerchantPurchase.objects.filter(player=player, item=item, count__gt=0).aupdate(count=F("count") - 1)


async def _release_stock(item: MerchantItem):
    await MerchantItem.objects.filter(pk=item.pk, stock__isnull=False).aupdate(stock=F("stock") + 1)


async def _refresh_cached_stock(item: MerchantItem):
    stock = await MerchantItem.objects.filter(pk=item.pk).values_list("stock", flat=True).afirst()
    item.stock = stock
    if cached := merchant_items.get(item.pk):
        cached.stock = stock


async def _event_pass(item: MerchantItem):
    """
    The pass whose wallet pays for this item, fetched safely from async code.

    Reading a foreign key the caller did not select_related would open a connection on the event loop, which
    Django refuses. Going through sync_to_async works whether it was loaded ahead or not.
    """
    return await sync_to_async(lambda: item.event_pass)()


async def _boost(item: MerchantItem):
    """The boost this item sells, fetched the same careful way."""
    return await sync_to_async(lambda: item.boost)()


def _price(item: MerchantItem, discount_percent: int) -> int:
    """What this costs after the shop's happy hour, in whichever of the two prices it carries."""
    asked = item.price_currency if item.paid_in_currency else item.prize
    return GlobalShop.discounted(asked, discount_percent)


async def buy_item(
    bot: "BallsDexBot", player: Player, item: MerchantItem, *, server_id: int | None = None, discount_percent: int = 0
) -> Bought:
    """
    Buy a merchant item for a player: take one unit of stock if the item is limited, take the price,
    then hand over what was bought. Every step is reverted if a later one fails.

    An item is paid in berries or in an event pass's own currency, never both — which of the two is decided
    by the item, not by the player. An item that sells a boost makes no card: it starts the boost on the main
    server, or adds its time to the one of its kind already running, and that boost needs no event to be live.

    `discount_percent` is the shop's happy hour, if one is running. It is taken off here rather than by the
    caller so that what is charged, the ledger line and the refund can never disagree about the price.

    Raises
    ------
    PurchaseError
        The purchase failed, with a message explaining why.
    """
    in_currency = item.paid_in_currency
    price = _price(item, discount_percent)
    event_pass = await _event_pass(item) if in_currency else None

    claimed = False
    if item.per_player_limit is not None:
        # raising the count only while it is under the limit is atomic, the same way the stock is:
        # two clicks from the same player cannot both get through
        row, _ = await MerchantPurchase.objects.aget_or_create(player=player, item=item)
        claimed = (
            await MerchantPurchase.objects.filter(pk=row.pk, count__lt=item.per_player_limit).aupdate(
                count=F("count") + 1
            )
            > 0
        )
        if not claimed:
            raise PurchaseError(
                f"You have already bought **{item.name}** "
                f"{item.per_player_limit} time{'s' if item.per_player_limit > 1 else ''}."
            )

    reserved = False
    if item.stock is not None:
        # decrementing only when some stock is left is atomic, two players can't buy the last unit
        reserved = await MerchantItem.objects.filter(pk=item.pk, stock__gt=0).aupdate(stock=F("stock") - 1) > 0
        if not reserved:
            await _release_player_claim(claimed, player, item)
            await _refresh_cached_stock(item)
            raise PurchaseError(f"**{item.name}** is sold out!")

    try:
        if price:
            if in_currency:
                try:
                    await wallet.aadjust(
                        player.pk,
                        item.event_pass_id,
                        -price,
                        reason=PassWalletEntry.Reason.SHOP,
                        description=f"Bought {item.name} from the merchant"[
                            : PassWalletEntry.DESCRIPTION_MAX_LENGTH
                        ],
                    )
                except wallet.NotEnough as error:
                    raise PurchaseError(
                        f"You don't have enough to buy **{item.name}**\n"
                        f"You hold {wallet.format_tokens(event_pass, error.held)}."
                    )
            else:
                try:
                    await player.remove_money(
                        price,
                        reason=BerryTransaction.Reason.MERCHANT_BUY,
                        description=f"Bought {item.name} from the merchant"
                        + (f" ({discount_percent}% off)" if discount_percent and item.prize else ""),
                        server_id=server_id,
                    )
                except ValueError:
                    await player.arefresh_from_db(fields=("money",))
                    raise PurchaseError(
                        f"You don't have enough {settings.currency_display_plural(bot)} to buy **{item.name}**\n"
                        f"Your actual balance: {format_currency(player.money, False, bot)}"
                    )

        try:
            if item.is_boost:
                boost = await _boost(item)
                if boost is None:
                    raise PurchaseError(f"**{item.name}** has no boost set up behind it. Tell the staff.")
                bought: Bought = await sync_to_async(buy_or_extend)(boost, player.pk, label=item.name)
            else:
                bought = await BallInstance.objects.acreate(
                    player=player,
                    ball=item.cached_ball,
                    special=item.cached_special,
                    health_bonus=random.randint(-settings.max_health_bonus, settings.max_health_bonus),
                    attack_bonus=random.randint(-settings.max_attack_bonus, settings.max_attack_bonus),
                    catch_date=timezone.now(),
                    server_id=server_id,
                )
        except PurchaseError:
            if price:
                await _refund(bot, player, item, price, in_currency, server_id)
            raise
        except Exception:
            log.exception("Failed to hand over a merchant item while a user was buying it.")
            if price:
                await _refund(bot, player, item, price, in_currency, server_id)
            raise PurchaseError("An error occurred while trying to buy the item.")
    except PurchaseError:
        if reserved:
            await _release_stock(item)
        await _release_player_claim(claimed, player, item)
        raise

    if reserved:
        await _refresh_cached_stock(item)
    await bus.dispatch(
        player,
        Event.MERCHANT_BUY,
        context=EventContext(
            instances=[bought] if isinstance(bought, BallInstance) else [],
            merchant_item_id=item.pk,
            # a quest that counts berries must not be fed a price paid in snowflakes, so an item paid in a
            # pass's currency moves no berries here. It still counts as one purchase
            price=0 if in_currency else price,
            amount=0 if in_currency else -price,
            server_id=server_id,
        ),
    )
    if in_currency:
        # the same purchase said a second way: paid out of an event pass's own purse rather than in berries,
        # which is the one thing a quest about that pass's shop wants to count
        await bus.dispatch(
            player,
            Event.EVENT_SHOP_BUY,
            context=EventContext(
                instances=[bought] if isinstance(bought, BallInstance) else [],
                merchant_item_id=item.pk,
                tokens=price,
                server_id=server_id,
            ),
        )
    return bought


async def _refund(
    bot: "BallsDexBot", player: Player, item: MerchantItem, price: int, in_currency: bool, server_id: int | None
) -> None:
    """Give the price back on whichever side it was taken from."""
    if in_currency:
        await wallet.aadjust(
            player.pk,
            item.event_pass_id,
            price,
            reason=PassWalletEntry.Reason.REFUND,
            description=f"Refunded {item.name}, the purchase failed"[: PassWalletEntry.DESCRIPTION_MAX_LENGTH],
        )
        return
    await player.add_money(
        price,
        reason=BerryTransaction.Reason.MERCHANT_BUY,
        description=f"Refunded {item.name}, the purchase failed",
        server_id=server_id,
    )


async def price_label(bot: "BallsDexBot", item: MerchantItem, amount: int) -> str:
    """An amount written in the currency this item is paid in."""
    if not amount:
        return "**free!**"
    if item.paid_in_currency:
        event_pass = await _event_pass(item)
        return f"**{wallet.format_tokens(event_pass, amount)}!**"
    return f"**{format_currency(amount, False, bot)}!**"


async def purchase_message(
    bot: "BallsDexBot", item: MerchantItem, bought: Bought, *, discount_percent: int = 0
) -> str:
    paid = _price(item, discount_percent)
    price = await price_label(bot, item, paid)
    if isinstance(bought, ActiveBoost):
        what = describe(bought.kind, bought.magnitude, bought.spawns_left)
        if bought.kind == BoostKind.SPAWN_PARTY:
            line = f"{what} — {bought.spawns_left} on their way."
        else:
            line = f"{what}, until {format_dt(bought.ends_at, style='R')}."
        text = f"You've bought {item.name} for {price}\n{line}\n-# Boosts only ever apply to the main server."
    else:
        text = f"You've bought {item.name} for {price}\n{bought.description(include_emoji=True, bot=bot)}"
    asked = item.price_currency if item.paid_in_currency else item.prize
    if discount_percent and asked and paid != asked:
        shown = (
            wallet.format_tokens(await _event_pass(item), asked)
            if item.paid_in_currency
            else format_currency(asked, False, bot)
        )
        text += f"\n-# Happy hour: {discount_percent}% off, down from {shown}."
    if item.stock is not None:
        text += f"\n-# {item.stock_text}"
    return text
