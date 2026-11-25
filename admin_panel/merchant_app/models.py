from datetime import datetime, timedelta

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone

from bd_models.models import Ball, Player, Special, balls, specials

merchant_items: dict[int, "MerchantItem"] = {}
global_shops: dict[int, "GlobalShop"] = {}


class MerchantSettings(models.Model):
    rotation = models.PositiveIntegerField(
        help_text="Duration of the items in minutes. Default to 24 hours.", default=1440
    )
    items = models.PositiveBigIntegerField(
        help_text="How many items will be in the store. Default to 3 items.", default=3
    )
    token_ball = models.OneToOneField(
        Ball,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="for /merchant convert_token, set the ball to use as a token",
    )
    token_ball_id: int | None
    token_conversion_rate = models.PositiveIntegerField(
        help_text=(
            "Coins received for each token converted when using /merchant convert_token\nExample: 1 token = 100 coins"
        ),
        default=1500,
    )

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    async def aload(cls):
        return await sync_to_async(cls.load)()

    @property
    def cached_token_ball(self) -> "Ball | None":
        return balls.get(self.token_ball_id) or self.token_ball if self.token_ball_id else None

    @property
    def rotation_delta(self) -> timedelta:
        return timedelta(minutes=self.rotation)

    class Meta:
        managed = True
        db_table = "merchantsettings"

    def __str__(self) -> str:
        return "Merchant Settings"


class MerchantItem(models.Model):
    class Kind(models.TextChoices):
        TREASURE = "treasure", "A treasure"
        BOOST = "boost", "A boost for the whole server"

    name = models.CharField(unique=True, max_length=64)
    kind = models.CharField(
        max_length=8,
        choices=Kind.choices,
        default=Kind.TREASURE,
        help_text="What the player walks away with. A boost needs no treasure and makes no card.",
    )
    prize = models.PositiveIntegerField(null=True, blank=True)
    start_date = models.DateTimeField(
        help_text="Start time of the item. If blank, starts immediately", null=True, blank=True
    )
    end_date = models.DateTimeField(
        help_text="End time of the item. If blank, the item is permanent", null=True, blank=True
    )
    rarity = models.FloatField(help_text="Value between 0 and 1, determine if a item is rarest than other")
    ball = models.ForeignKey(Ball, null=True, blank=True, on_delete=models.CASCADE)
    ball_id: int | None
    special = models.ForeignKey(Special, null=True, blank=True, on_delete=models.SET_NULL)
    special_id: int | None
    boost = models.ForeignKey(
        "eventshop_app.Boost",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="merchant_items",
        help_text="The boost this item starts, for an item that sells one. Boosts run on the main server "
        "and never need an event to be running.",
    )
    boost_id: int | None
    event_pass = models.ForeignKey(
        "eventpass_app.EventPass",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merchant_items",
        help_text="Which wallet the price below is taken from. Only read when there is a price in a "
        "currency.",
    )
    event_pass_id: int | None
    price_currency = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        verbose_name="price in the pass currency",
        help_text="What it costs in the event pass's own currency, like Snowflakes. Fill this one OR the "
        "berry price, never both: to sell the same thing both ways, make the item twice.",
    )
    stock = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="How many of this item can still be bought, all players combined. It goes down with every "
        "purchase and the item can't be bought anymore once it reaches 0. Leave empty for an unlimited stock.",
    )
    per_player_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="limit per player",
        help_text="How many of this item one player may ever buy. Counted per player and kept for good, so a "
        "limit of 1 makes the item a one-off. It works on its own or alongside the shop stock above: with "
        "both, the item runs out when either is reached. Leave empty for no limit."
        ,
    )
    created_at = models.DateTimeField(editable=False, auto_now_add=True)

    @property
    def cached_ball(self) -> "Ball | None":
        if self.ball_id is None:
            return None
        return balls.get(self.ball_id) or self.ball

    @property
    def is_boost(self) -> bool:
        return self.kind == self.Kind.BOOST

    @property
    def paid_in_currency(self) -> bool:
        """Whether this item is paid out of an event pass's wallet rather than in berries."""
        return bool(self.price_currency and self.event_pass_id)

    @property
    def cached_special(self) -> "Special | None":
        return specials.get(self.special_id) or self.special if self.special_id else None

    @property
    def sold_out(self) -> bool:
        return self.stock is not None and self.stock <= 0

    @property
    def enabled(self) -> bool:
        """
        Checks if this item is active and still in stock.
        """
        if self.sold_out:
            return False
        return (
            (self.start_date or datetime.min.replace(tzinfo=timezone.get_default_timezone()))
            <= timezone.now()
            <= (self.end_date or datetime.max.replace(tzinfo=timezone.get_default_timezone()))
        )

    @property
    def stock_text(self) -> str:
        """
        A short text describing the remaining stock, empty for unlimited items.
        """
        if self.stock is None:
            return ""
        if self.stock <= 0:
            return "Sold out"
        return f"{self.stock} left"

    def clean(self):
        """
        Keep an item coherent: what it sells matches its kind, and it has exactly one price.

        Two prices would mean asking the player which to pay with, which is a menu nobody asked for. Selling
        the same boost both ways is done by making the item twice, which also lets the two have their own
        stock and their own limits.
        """
        errors: dict[str, str] = {}
        if self.kind == self.Kind.BOOST:
            if self.boost_id is None:
                errors["boost"] = "An item that sells a boost has to name one."
            if self.ball_id is not None:
                errors["ball"] = "A boost gives no treasure. Leave this empty."
        else:
            if self.ball_id is None:
                errors["ball"] = "An item that sells a treasure has to name one."
            if self.boost_id is not None:
                errors["boost"] = "Only an item of kind boost sells a boost. Leave this empty."
        if self.prize and self.price_currency:
            errors["price_currency"] = (
                "Give it a price in berries or in a pass's currency, not both. To sell it both ways, make "
                "the item a second time."
            )
        if self.price_currency and self.event_pass_id is None:
            errors["event_pass"] = "A price in a currency needs the pass whose wallet it comes out of."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return self.name

    class Meta:
        managed = True
        db_table = "merchantitem"


class MerchantInstance(models.Model):
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name="merchant")
    items = models.ManyToManyField(MerchantItem, blank=True)
    rotation_ends_at = models.DateTimeField()

    @property
    def rotation_expired(self) -> bool:
        """
        Check if the rotation has ended.
        """
        return self.rotation_ends_at <= timezone.now()

    class Meta:
        managed = True
        db_table = "merchantinstance"


class GlobalShop(models.Model):
    name = models.CharField(max_length=64, unique=True)
    banner = models.ImageField(null=True, blank=True, help_text="An optional promotional banner for this shop.")
    items = models.ManyToManyField(MerchantItem, blank=True)

    announcement_text = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="What the announcement says when this shop is announced in the spawn channels. Left empty, "
        "the shop simply says it has new stock.",
    )
    happy_hour_minutes = models.PositiveIntegerField(
        default=0,
        help_text="How long the discount below runs after the shop is announced, in minutes. 0 turns the happy "
        "hour off.",
    )
    happy_hour_discount_percent = models.PositiveIntegerField(
        default=0,
        validators=(MaxValueValidator(100),),
        help_text="Taken off every price in this shop during the happy hour, in percent.",
    )
    announced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this shop was last announced. The happy hour is counted from here, so clearing this "
        "ends it early.",
    )

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    auto_announce_weekday = models.SmallIntegerField(
        choices=Weekday.choices,
        null=True,
        blank=True,
        help_text="Announce this shop by itself every week on this day. Leave empty to only ever announce it "
        "by hand.",
    )
    auto_announce_hour = models.PositiveSmallIntegerField(
        default=20,
        validators=(MaxValueValidator(23),),
        help_text="The hour, UTC, of the weekly announcement above. 20 is 8pm UTC, so 9pm in Paris in winter.",
    )

    def due_for_announcement(self, now: datetime) -> bool:
        """
        Whether the weekly announcement should go out right now.

        The check is loose on the minute and strict on the day: the loop runs every few minutes,
        and the last announcement is what stops it from firing again within the same hour.
        """
        if self.auto_announce_weekday is None:
            return False
        if now.weekday() != self.auto_announce_weekday or now.hour != self.auto_announce_hour:
            return False
        return self.announced_at is None or now - self.announced_at >= timedelta(hours=12)

    @property
    def happy_hour_ends_at(self) -> datetime | None:
        """When the discount stops, or None when this shop has no happy hour running."""
        if not (self.announced_at and self.happy_hour_minutes and self.happy_hour_discount_percent):
            return None
        return self.announced_at + timedelta(minutes=self.happy_hour_minutes)

    def discount_now(self) -> int:
        """The discount running in this shop right now, in percent. 0 outside the happy hour."""
        ends_at = self.happy_hour_ends_at
        if ends_at is None or timezone.now() >= ends_at:
            return 0
        return min(self.happy_hour_discount_percent, 100)

    @staticmethod
    def discounted(price: int | None, percent: int) -> int:
        """What `price` costs once `percent` is taken off it."""
        if not price or not percent:
            return price or 0
        return max(0, round(price * (1 - min(percent, 100) / 100)))

    class Meta:
        managed = True
        db_table = "globalshop"


class MerchantPurchase(models.Model):
    """
    How many times one player has bought one merchant item.

    A running count rather than one row per sale: the limit only ever needs the total, and a counter can be
    raised and checked in a single statement, which is what stops two clicks from both slipping through.
    """

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="merchant_purchases")
    player_id: int
    item = models.ForeignKey(MerchantItem, on_delete=models.CASCADE, related_name="purchases")
    item_id: int
    count = models.PositiveIntegerField(default=0, help_text="How many the player has bought so far.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.count}x {self.item_id} by {self.player_id}"

    class Meta:
        managed = True
        db_table = "merchantpurchase"
        unique_together = (("player", "item"),)
