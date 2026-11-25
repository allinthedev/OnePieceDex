"""
The Christmas shop: the boosts players can buy, and what they cost in the pass's own currency.

Nothing here is priced in berries on purpose — the shop is the one place the event's currency is worth
something, and letting berries in would make the whole pass optional. The offers carry a berry price field all
the same, so you can open that door later from the admin panel without touching this.

Run it against the stack:

    docker compose exec -T admin-panel python3 -m django shell < scripts/setup_christmas_shop.py

That is a dry run: it says what it would make and writes nothing. To make it happen:

    docker compose exec -T -e GO=1 admin-panel python3 -m django shell < scripts/setup_christmas_shop.py

Run it as often as you like. It matches on names, so a second run updates what it made the first time rather
than making a second copy — which also means renaming a boost here creates a new one and leaves the old.

The pass it attaches to is the one named in PASS, or the only pass that has a currency when there is just one:

    docker compose exec -T -e GO=1 -e PASS="Noel 2026" admin-panel python3 -m django shell < scripts/...
"""

import os

from eventpass_app.models import EventPass
from eventshop_app.models import Boost, BoostKind, ShopOffer

GO = bool(os.environ.get("GO"))
WANTED_PASS = os.environ.get("PASS", "").strip()
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
        names = ", ".join(item.name for item in carrying) or "none"
        raise SystemExit(f"No pass named {WANTED_PASS!r} has a currency. Passes with one: {names}")
elif len(carrying) == 1:
    event_pass = carrying[0]
elif not carrying:
    raise SystemExit("No event pass has a currency of its own. Give one a currency name first.")
else:
    names = ", ".join(item.name for item in carrying)
    raise SystemExit(f"Several passes have a currency, so name the one you mean with PASS. ({names})")

currency = f"{event_pass.currency_emoji} {event_pass.currency_name}".strip()
say(f"Pass    : {event_pass.name}")
say(f"Currency: {currency}")

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
# daily claim is what sets the pace: at 50 a day, the cheapest boost here is two days of simply turning up.
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

for position, spec in enumerate(BOOSTS, start=1):
    spec = dict(spec)
    price = spec.pop("price")
    per_player = spec.pop("per_player")
    name = spec.pop("name")
    say(f"  {spec['emoji']} {name} — {price} {event_pass.currency_name}")
    say(f"      {spec['description']}")
    if GO:
        boost, made = Boost.objects.update_or_create(name=name, defaults={**spec, "enabled": True, "announce": True})
        ShopOffer.objects.update_or_create(
            event_pass=event_pass,
            name=name,
            defaults={
                "kind": ShopOffer.Kind.BOOST,
                "boost": boost,
                "reward": None,
                "emoji": spec["emoji"],
                "description": spec["description"],
                "price": price,
                # left empty on purpose: this shop does not take berries
                "price_berries": None,
                "per_player": per_player,
                "position": position,
                "enabled": True,
            },
        )
        say(f"      {'created' if made else 'updated'}")

say()
if GO:
    say("Done. The offers are live in /shop as soon as the pass is.")
else:
    say("Dry run: nothing was written. Re-run with GO=1 to make it happen.")

print("\n".join(report))
