# Staff guide — the Discord commands

What is driven from Discord, in game. Setting things up happens in the panel:
[admin-panel.md](admin-panel.md). What players see: [player.md](player.md).

*Une copie française de ce guide est dans [../fr/admin-discord.md](../fr/admin-discord.md).*

---

## The trap to know about first

**Every `/shop` command needs a pass that is `Active` and inside its dates.** `/shop admin tokens`
included. If the pass is a draft, or only starts next week, the answer is *"No event shop is open
right now"* — and that does not mean the command is broken.

Not to be confused either: the **On sale** column in the panel only looks at the offer itself,
never at the state of the pass. An offer can read "On sale" while nobody can see it.

---

## Snowflakes

### Crediting a player

```
/shop admin tokens user:<@player> amount:1000
```

Staff only. **A negative amount takes it back.** If you take back more than the player holds, the
command refuses and tells you how much they have — it never goes negative. The `event_pass`
parameter is only useful when more than one pass has a currency.

Every movement is recorded in **Pass wallet entries**, with the reason `admin` and your name.

### Checking

```
/shop balance
```

The player's balance, plus their crew's pot if they have one.

```
/shop boosts
```

The boosts **currently running** — not the catalogue. Until somebody buys one, the answer is
*"Nothing is boosted right now"*, and that is correct.

---

## The boost shop

### Setting it up in one go

The script makes the four Christmas boosts, their merchant items and the shop holding them. A dry
run first, which writes nothing:

```bash
docker compose exec -T -e SPECIAL="Christmas 2026" admin-panel \
  python3 -m django shell < scripts/setup_christmas_shop.py
```

Then for real:

```bash
docker compose exec -T -e GO=1 -e SPECIAL="Christmas 2026" admin-panel \
  python3 -m django shell < scripts/setup_christmas_shop.py
```

Run it as often as you like: it updates rather than duplicating. `PASS="…"` picks the pass when
several have a currency, `SHOP="…"` the shop's name (`Christmas shop` by default).

It only ever sets snowflake prices. To sell the same boost for berries, copy the item in the panel
and fill `Prize` instead of `Price in the pass currency`.

### The commands

```
/merchant global shop shop:Christmas shop
/merchant global buy shop:Christmas shop
```

These work **all year**, with no event running: all it takes is enough to pay with.

```
/merchant announce <shop name>
```

Announces the shop in the spawn channels and starts the happy hour set on it.

---

## The Secret Santa

```
/santa admin state
```

Where the event stands: signed up, in the chain, parcels filled, parcels opened, and how many were
filled by hand. Worth running before and after each stage.

```
/santa admin draw
```

**The step to remember.** It draws the chain: who gives to whom. Run it once signups have closed
and before the wrapping window. Until it has run, the panel shows *"Waiting to be drawn"* in red
and nobody can fill their parcel.

The rest takes care of itself: parcels nobody filled are completed by the bot at the end of the
wrapping window, and the opening announces itself on the day.

**Never tell a player whether their parcel was filled by the bot.** That is what guarantees there
is no penalty for not giving.

---

## The sleigh

```
/sleigh admin give user:<@player> count:3
```

Takes gifts out of the sleigh at random and hands them to one player — a crew war prize, a King of
the Seas reward. From 1 to 20.

```
/sleigh admin spawn count:5 channel:#channel
```

Sends gifts from the sleigh back out as spawns, for anyone to catch. Without `channel` they go to
the usual spawn channel. From 1 to 20.

This is how you hand out what is left by hand, when you left `Empty at` blank in the panel.
Otherwise the bot does it in waves.

---

## Crew roles

```
/crew admin syncroles
```

Puts the Discord role right for everyone in a crew, on the main server only. Run it **once** after
filling the `Role id` fields in the panel; after that every crew change handles itself.

The answer reads like *"12 player(s) are in a crew, 8 of them are on this server, and 8 had their
role changed"*. The gap between the first two numbers is the people who picked a crew and never
set foot on the main server, which is normal.

If nothing changes, it is almost always one of two things:

- the bot does not have **Manage Roles**;
- its highest role sits **below** the crew roles in the server's list.

Being an administrator does not fix the second one: Discord applies the role hierarchy even to an
administrator.

```
/crew admin points user:<@player> points:500 reason:…
```

Adds points to a player's crew, for what no rule can see. A negative number takes them off. The
reason is shown to the player as what they last earned.

---

## Frames

Both commands now offer a **dropdown** of the frames available, instead of a name to type.

```
/admin spawning spawn treasure:<treasure> frame:<frame>
```

With `special:Frame` and no frame picked, the frame of the day applies. If the treasure has several
for that date, the bot draws one at random.

```
/admin give treasure:<treasure> user:<@player> frame:<frame>
```

Gives the treasure wearing the frame you picked.

---

## The order of operations on the day

1. `/santa admin state` — check everyone is signed up.
2. Close signups (the date in the panel does that).
3. `/santa admin draw` — **the manual step**.
4. Let the wrapping window run; the bot fills the missing parcels at the end of it.
5. The opening announces itself on the date set.
6. The sleigh empties itself in waves from `Empty at`, or by hand with `/sleigh admin spawn`.
