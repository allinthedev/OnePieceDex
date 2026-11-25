"""
The Christmas boosts, and the merchant shop that sells them.

Boosts are sold by the merchant, not by the event pass. That is on purpose: a boost needs no event to be
running, so putting it behind an event shop would have made it unbuyable the rest of the year. The merchant
already has stock, limits per player and a happy hour, and its listing is a name and a price, which is
exactly what a boost is.

Nothing here is priced in berries. The currency is the one place the event's snowflakes are worth something,
and letting berries in would make the whole pass optional. To sell the same boost for berries as well, copy
the item in the admin and fill the berry price instead of the currency one — an item carries one price or
the other, never both, and the two copies then have their own stock and their own limit per player.

Run it against the stack:

    docker compose exec -T admin-panel python3 -m django shell < scripts/setup_christmas_shop.py

That is a dry run: it says what it would make and writes nothing. To make it happen:

    docker compose exec -T -e GO=1 admin-panel python3 -m django shell < scripts/setup_christmas_shop.py

Run it as often as you like. It matches on names, so a second run updates what it made the first time rather
than making a second copy — which also means renaming a boost here creates a new one and leaves the old.

The pass whose currency pays for it is the one named in PASS, or the only pass that has a currency when
there is just one. SHOP names the merchant shop, and SPECIAL the special the spirit boost raises:

    docker compose exec -T -e GO=1 -e PASS="Christmas 2026" -e SPECIAL="Christmas 2026" \
        admin-panel python3 -m django shell < scripts/setup_christmas_shop.py
"""

import os

from eventpass_app.models import EventPass
from eventshop_app.models import Boost, BoostKind
from merchant_app.models import GlobalShop, MerchantItem

GO = bool(os.environ.get("GO"))
WANTED_PASS = os.environ.get("PASS", "").strip()
SHOP_NAME = os.environ.get("SHOP", "Christmas shop").strip()
# the special whose chance the "Christmas spirit" boost raises. Set it to your Christmas special.
SPECIAL_NAME = os.environ.get("SPECIAL", "").strip()

report: list[str] = []


def say(line: str = ""):
    report.append(line)


# ── which pass ──────────────────────────────────────────────────────────────────────────────────

carrying = list(EventPass.objects.exclude(currency_name="").order_by("position", "pk"))
if WANTED_PASS:
    event_pass = next((item for item in carrying if item.name == WANTED_PASS), None)
    if event_pass is None:
        raise SystemExit(f"No pass named {WANTED_PASS!r} has a currency.")
elif not carrying:
    raise SystemExit("No pass has a currency yet. Give one a currency name in the admin and run this again.")
elif len(carrying) > 1:
    names = ", ".join(item.name for item in carrying)
    raise SystemExit(f"Several passes have a currency, so name the one you mean with PASS. ({names})")
else:
    event_pass = carrying[0]

currency = f"{event_pass.currency_emoji} {event_pass.currency_name}".strip()
say(f"Pass    : {event_pass.name}")
say(f"Currency: {currency}")
say(f"Shop    : {SHOP_NAME}")

# ── the special the spirit boost raises ─────────────────────────────────────────────────────────

special = None
if SPECIAL_NAME:
    from bd_models.models import Special

    special = Special.objects.filter(name=SPECIAL_NAME).first()
    if special is None:
        raise SystemExit(f"No special named {SPECIAL_NAME!r}.")
    say(f"Special : {special.name}")
else:
    say("Special : none given, so the Christmas spirit boost raises every special running at the time.")
    say('          Re-run with SPECIAL="..." once the Christmas special exists, or set it in the panel.')
say()

# ── what is sold ────────────────────────────────────────────────────────────────────────────────

# The numbers below are a starting point, not a balance. Everything is editable in the admin panel, and the
# pass is what sets the pace: the quests hand out about 1880 snowflakes over December, plus the daily claim.
BOOSTS = [
    {
        "name": "Blizzard",
        "emoji": "\N{CLOUD WITH SNOW}\N{VARIATION SELECTOR-16}",
        "kind": BoostKind.RARITY,
        "description": "Rarer treasures across the whole server for an hour.",
        "magnitude": 30,
        "duration_minutes": 60,
        "price": 250,
        "per_player": 0,
    },
    {
        "name": "Christmas spirit",
        "emoji": "\N{CHRISTMAS TREE}",
        "kind": BoostKind.SPECIAL,
        "description": "The event's special turns up more often for an hour.",
        "magnitude": 50,
        "duration_minutes": 60,
        "special": special,
        "price": 200,
        "per_player": 0,
    },
    {
        "name": "Gift rain",
        "emoji": "\N{WRAPPED PRESENT}",
        "kind": BoostKind.SPAWN_PARTY,
        "description": "Five treasures spawn one after another in the spawn channel.",
        "magnitude": 0,
        "duration_minutes": 20,
        "spawns": 5,
        "price": 150,
        "per_player": 2,
    },
    {
        "name": "Full purse",
        "emoji": "\N{MONEY BAG}",
        "kind": BoostKind.BERRIES,
        "description": "Catches pay more berries for an hour.",
        "magnitude": 50,
        "duration_minutes": 60,
        "price": 100,
        "per_player": 0,
    },
]

shop = None
if GO:
    shop, made_shop = GlobalShop.objects.get_or_create(name=SHOP_NAME)
    say(f"Shop {SHOP_NAME!r} {'created' if made_shop else 'reused'}.")
    say()

for spec in BOOSTS:
    spec = dict(spec)
    price = spec.pop("price")
    per_player = spec.pop("per_player")
    name = spec.pop("name")
    say(f"  {spec['emoji']} {name} — {price} {event_pass.currency_name}")
    say(f"      {spec['description']}")
    if not GO:
        continue

    boost, made = Boost.objects.update_or_create(name=name, defaults={**spec, "enabled": True, "announce": True})
    item, made_item = MerchantItem.objects.update_or_create(
        name=name,
        defaults={
            "kind": MerchantItem.Kind.BOOST,
            "boost": boost,
            "ball": None,
            "special": None,
            # the merchant's random rotation weighs items by rarity. Zero keeps a boost out of it, so it is
            # only ever sold from the shop below, where everyone sees the same list
            "rarity": 0,
            "event_pass": event_pass,
            "price_currency": price,
            # left empty on purpose: this shop does not take berries
            "prize": None,
            "per_player_limit": per_player or None,
        },
    )
    shop.items.add(item)
    say(f"      boost {'created' if made else 'updated'}, item {'created' if made_item else 'updated'}")

say()
if GO:
    say(f"Done. The boosts are on sale with /merchant global shop {SHOP_NAME} and /merchant global buy.")
    say("They need no event to be running: only enough currency in the buyer's wallet.")
else:
    say("Dry run: nothing was written. Re-run with GO=1 to make it happen.")

print("\n".join(report))
