# OnePieceDex — Patch notes

Everything below is new. Nothing here has been deployed yet.

---

## For players

### 🗿 Poneglyph hunts — `/hunt`

A hunt is a set of poneglyphs. Each stone asks for a handful of specific treasures: bring them
all and the stone is yours. Collect every stone in the hunt and you take the reward.

- Each stone announces itself in the spawn channels when it opens, listing exactly what it
  wants. Stones can open on different days, so a hunt can release one a week.
- Open `/hunt` to see which stones you hold, pick one from the menu to see what it still needs,
  and hand the set in when you are ready.
- Some treasures are **consumed** when you hand them in — the ones that are say so plainly,
  next to the requirement. The rest you keep.
- A requirement can ask for a specific special, and for more than one copy.
- Hunts run either **per player** or **as a race between crews**. In crew mode, the first
  member to hand a set in claims that stone for the whole crew, and nobody else has to gather
  the same treasures again.

### 🏴‍☠️ Crews — `/crew info`, `/crew war`

Pick a crew in `/player settings`. You fly one flag at a time.

- `/crew info` shows your crew, how many members it has, and what you have brought it.
- `/crew war` shows the standings of the current war and the top contributors.
- Points come from what you do: winning a battle, taking part in one, fighting a boss, winning
  a boss, catching a wanted treasure, claiming a poneglyph, finishing a hunt. What each is
  worth is set per war, and some deeds have a daily cap so nobody can farm them all evening.
- A deed only scores while a war is running, and only if you are in a crew.

### 🏴 Wanted posters

A bounty can be put on a treasure. The **first player to catch it** while the bounty is live
takes the reward in berries — and the card comes out already carrying the bounty's special, so
it is marked from the moment you catch it.

- The poster goes out in the spawn channels when the bounty opens.
- Only the first catch collects it. Everyone else gets an ordinary catch.

### 📦 Packs — `/pack open`

Packs are no longer one treasure at a time.

- A pack can hold any number of treasures, and you can open several at once when the pack
  allows it.
- **Luck bonus**: every pack of a kind that comes out without a rare treasure makes rare ones
  likelier in your next one. It resets the moment you get one.
- **Guarantee**: after a set number of dry packs, the next one is guaranteed to hold a rare
  treasure.
- Rare treasures are starred in the results, and the footer tells you where your luck bonus
  stands.
- Specials roll per treasure inside a pack, at a rate the pack decides — they can be made
  rarer in packs than in the wild.
- `/pack shop` now shows how many treasures a pack holds, what counts as rare in it, and your
  current luck bonus before you buy.

### 🐙 The merchant

- When a global shop restocks, it now **announces itself in the spawn channels**, with its
  banner and the number of items on sale.
- A shop can run a **happy hour**: a discount for a set number of minutes after it is
  announced. Prices show struck through, with a countdown, and the discount is applied when you
  buy — not merely advertised.
- A shop can be set to announce itself **every week on a chosen day and hour**, so a Sunday
  evening restock happens without anyone being around.

### 💰 Berries

`/player settings` now lets you decide **who can send you berries**: anyone, friends only, only
with your approval, or nobody. Approval asks you in the channel before anything moves.

---

## For admins

### Treasure values in the panel

Every treasure now shows what the Hotel de Vente pays for it, in the list and on its own page:
the flat price at 0/0 stats and the spread between the worst and best stat rolls. The same
figure appears on merchant items, next to the price you are setting.

No more giving yourself a copy and selling it to Buggy to find out what something is worth.

### Pack configuration

Packs are configured on the item itself, under **Pack contents and odds**:

| Setting | What it does |
| --- | --- |
| `cards` | How many treasures the pack hands over |
| `packs_per_command` | How many a player may open in one `/pack open` |
| `rarity_flatten` | Bends the draw. 1.0 is spawn odds; **below 1 makes rare treasures more common** |
| `rare_rarity` | What counts as rare: the star, the luck bonus and the guarantee |
| `luck_ramp` | How much likelier rares get after a dry pack (0.4 = +40%) |
| `pity_every` | Dry packs before a rare is guaranteed |
| `special_chance_factor` | Multiplies special odds for this pack (0.5 = twice as rare as catching) |

Left alone, a pack behaves exactly as it did before: one treasure, spawn odds.

A pack's page also shows a **suggested price**, worked out from what the Hotel says its contents
are worth plus a house margin you set in the currency settings. The suggestion accounts for the
luck bonus and the guarantee — ignoring them understates a small, generous pack by about a
quarter. It is only a suggestion; the price you charge stays yours.

### `/admin balls bulkgive`

Hand out treasures in bulk.

- To **one player**, or to **everyone holding a role**.
- A specific treasure, or drawn at random — optionally restricted to a **group** (Logia, Zoan,
  Straw Hats...) or to a **rarity range**.
- Specials three ways: none, **rolled per card exactly like a spawn**, or one forced on every
  card.
- Each player gets their own draw, so a role does not hand out the same cards to everybody.
- Above 25 cards it shows what it is about to do and waits for a yes. Above 5000 it refuses.
- Disabled treasures and ones at rarity 0 are never drawn at random.

> Giving to a whole role needs the privileged members intent. Tick **Server Members Intent** in
> the Discord developer portal, then add `--enable-members-intent` to the bot's start command.
> Until then the command says so instead of silently giving to nobody.

### Wanted posters

**Bounties** in the panel: a treasure, a reward, a special to put on the winning card, and a
window. A column tells you where each bounty stands — opening, live, claimed, or expired.

The special works best as a **foreground** special, laid over the finished card. Note that none
of the current specials use that layer; they are all backgrounds, where the card art would
cover the poster.

Clearing the claim puts a bounty back up for grabs. Clearing the announcement date re-announces
it.

### Hunts and crews

**Hunts** hold poneglyphs; poneglyphs hold the treasures they ask for. You can write a set out
by hand, or select stones in the list and run **Draw the treasures** — the bot picks them at
random inside the rarity range you set, and you can edit the result before the stone opens.

Each requirement has its own `consume` switch, off by default.

One picture of a stone is reused for every poneglyph in a hunt, so nine poneglyphs need one
illustration rather than nine. Animated GIFs work on the hunt banner, on the completion image
and on crew flags.

**Crews** are set up in the panel: name, emoji, description, flag. Players pick one in
`/player settings`. **Crew wars** are a season with rules: one row per kind of deed, what it is
worth, and an optional daily cap per player. Every deed is kept as a line, so the standings can
always be explained.

### The merchant

Global shops gained an **Announcement** section (text, happy hour length, discount percentage)
and a **Weekly schedule** (day and hour, UTC). Announce by hand with
`<prefix>merchant announce <shop name>`, or let the schedule do it. A shop announced in the
last twelve hours is skipped, so a slot cannot fire twice.

### Boss fights — automatic mode

`/boss admin auto` plays a whole fight out on its own.

- **Damage climbs** in a straight line from a minimum on the first attack to a maximum on the
  last, so the fight gets heavier as it goes instead of swinging at random.
- Choose the order: **attack, defend, attack, defend**, or **random** — and random never lets
  the boss attack more than twice in a row, so nobody gets wiped before they can hit back.
- Set how many attacking rounds (8 by default) and how long players get to pick each round.
- It stops early if the boss dies or everyone is out, and it never concludes the fight itself:
  handing out rewards stays a deliberate `/boss admin conclude`.
- `/boss admin autostop` hands control back at any time.

The boss package now lives in the repository instead of being pulled from a pinned commit, so
it can be changed like everything else.

---

## Fixes

- **`/admin` could stop the whole command tree from syncing.** The guard meant to shorten its
  descriptions when it grew too long was measuring nothing at all — it walked the cog's own
  commands, while every `/admin` subgroup is attached at runtime. It always read zero, so it
  never fired. It now measures what Discord actually measures. `/admin` currently sits at
  **7852 characters of the 8000 allowed**: the next option added anywhere under it will trip
  the fallback and blank every description, so something needs trimming before it grows.
- **The Hotel's price curve breaks below rarity 1.** It raises a negative number to a
  fractional power and comes back with a complex number, and divides by zero at exactly 0.9627.
  Nothing sits in that range today and the Hotel refuses rarity 0 anyway, so it has never
  fired, but it is a trap for whoever first sets a rarity of 0.5. The panel now reports "not
  sellable" instead of breaking.
- **Boss: `_defeat_boss` reached for a variable it never had** and would have raised the moment
  anything called it. Nothing does yet, so it was a landmine rather than a live bug.
- Merchant purchases now record the **discount actually charged** in the berry ledger, and a
  happy hour that expires while a player is browsing no longer takes money off at the click.
- A pack bought from the shop with a treasure list is now **charged when the treasure is
  picked**, not when the button is pressed: closing the picker no longer costs berries.
- Treasures at rarity 0 can no longer come out of a pack.
- Pack purchases record a proper reason in the berry ledger instead of an unexplained movement.
