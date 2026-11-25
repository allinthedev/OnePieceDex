# Staff guide — the panel

Everything that is set up in the admin panel for the Christmas event and the features that came
with it. The Discord commands are in [admin-discord.md](admin-discord.md), and what players see is
in [player.md](player.md).

*Une copie française de ce guide est dans [../fr/admin-panel.md](../fr/admin-panel.md).*

Throughout: **times are UTC**, and a **lower rarity is rarer** (T10 is rarer than T200).

---

## The order to build the event in

Each step needs the one before it. Out of order, it jams.

1. **The special** — `Specials → Add`. Without it the pass will not load, and neither the Santa nor
   the sleigh knows what to make.
2. **The pass and its currency** — the currency is what opens the wallet and the snowflake prices.
3. **The calendar, the Secret Santa, the sleigh** — each points at the special.
4. **The boosts and the merchant shop** — independent of all the rest.
5. **Publish the pass** by setting it to `Active`.

---

## The pass

`Event passes → Christmas 2026`.

### The sections of the page

| Section | What matters |
|---|---|
| (top) | name, emoji, description, banner, colour, **position** |
| **When** | `Starts at`, `Ends at`, `Claim until` — quests only progress between the first two, claiming can stay open longer |
| **Where** | `Main server only`, `Main server id` |
| **Who** | the access conditions. None means open to everyone |
| **Its own currency** | `Currency name`, `Currency emoji`, `Daily currency` |
| **End of the pass** | the final reward and its message |
| **Publication** | `Status`, the packages the quests need, the notes |

### The currency

This is the field the whole event economy hangs on.

- **Currency name** — `Snowflakes`. **While it is empty the pass has no wallet**: no balance, no
  snowflake prices, no gift to a crew.
- **Currency emoji** — `❄️`, or a Discord emoji pasted whole (`<:flake:123…>`).
- **Daily currency** — what `/daily` hands out on top of the berries while the pass runs. `10` is
  what the file sets. At 0 the daily gives none.

### Draft or published

A pass is created as a **Draft**: only staff see it in `/pass view`, and nothing progresses. That
is the state to test it in. Setting it to **Active** opens it to everyone, and that is the moment
`/daily` starts handing out snowflakes.

**Position** decides which pass `/pass view` opens when the player names none: the lowest number
among those running.

### Loading it from the file

Rather than clicking forty-two quests together, `eventexample/christmas_2026.json` describes them
all. See `eventexample/README.md`. The pass arrives as a draft, and reloading the file updates that
draft without duplicating anything. A pass already `Active` is refused by the loader: move it back
to draft first.

### The pages to read

- **Pass wallets** — what each player holds.
- **Pass wallet entries** — the ledger: every movement, its reason (`pass`, `daily`, `shop`,
  `gift_sent`, `gift_received`, `admin`, `refund`) and the balance after it. A jump between one row's balance and
  the next means currency moved somewhere that bypassed the ledger.

---

## The advent calendar

`Advent calendars → Add`. The doors, the streak rewards and the surprises are edited **on the
calendar's own page**, not on separate ones.

| Section | What to know |
|---|---|
| (top) | the pass it belongs to, the name, the emoji, `Enabled`, and the state it works out |
| **When** | `Starts on` and `Door count`. Door 1 opens on the starting day, door 2 the day after. A day runs to midnight UTC, so everyone's day turns over at the same moment |
| **Catching up** | `Catch up price` in berries and `Catch up until`. It is the one way to catch up on a missed day, and the only place the event takes berries back out of the economy. **A price of zero means a day missed is missed for good** |
| **Surprises** | `Surprise chance`, between 0 and 1. A surprise is added to the door, it never replaces it |
| **Looks** | the grid's background image |

Then, in the tables at the bottom of the same page:

- **Doors** — one row per day: the number, the reward, the message.
- **Streak rewards** — what is given once N doors have been opened.
- **Surprises** — name, emoji, **weight** (which decides which one is drawn), reward or boost,
  `Once per player`.

Pages to read: **Advent openings** (every door opened, whether it was paid for, which surprise
fired) and **Advent streak grants**, where the action *"Let the selected players earn these again"*
hands a streak reward back.

---

## The Secret Santa

`Secret Santas → Add`.

| Section | What to know |
|---|---|
| **What it hands out** | `Special` (every card in a parcel comes out wearing it), `Event pass` (where the currency comes from) and `Price`. **A price of zero turns off paying** instead of giving a card |
| **The stages** | in order: `Signup opens at`, `Signup closes at`, `Wrap until`, `Opens at`, `Closes at`. Between signing up and wrapping, `/santa admin draw` has to be run |
| **The lists** | `Wishlist size` and `Min rarity`. **Lower is rarer**, so this field is the *rarest* card anyone may ask for: put your T10's rarity there and nothing rarer can be wished for |
| **Parcels nobody filled** | `Fill the rest` — **leave it on** |

### The rule never to break

The **Santa gifts** page has a `kind` column saying whether a parcel was filled by its giver, paid
for, or filled in by the bot because nobody turned up.

**That must never leave the panel.** It is what makes "no penalty for not giving" true: to everyone
but you, a parcel the bot filled and a parcel a player filled are identical. Telling anyone would
turn the absence of a penalty into one.

### The pages to read

- **Santa entries** — who is in, who they give to, how many wishes, parcel filled or not. The
  chain, laid out. Wishes are edited in the table on the entry.
- **Santa gifts** — every parcel. The action *"Let the selected parcels be opened again"* is for a
  parcel whose card was lost to something going wrong; the old card is not taken back.

---

## The sleigh

`Sleighs → Add`.

| Section | What to know |
|---|---|
| (top) | the `Special` the cards given turn into |
| **When** | `Opens at`, `Closes at`, `Per day` (each player's allowance, turning over at midnight UTC), `Goal` — **the goal is only the bar players see**, the sleigh keeps taking gifts past it |
| **What a gift is worth** | `Points base`, `Points pivot`, `Points cap`. Points go to the giver's crew in the running crew war: base × pivot ÷ rarity, capped. A card ten times rarer than the pivot is worth ten times the base. **No war running means no points** — and the gift still goes in |
| **Emptying it again** | `Empty at`, `Wave count`, `Wave hours`, `Spawn channel id`. Once that time passes, whatever is left is split into waves and spawned back out, one card at a time, for anyone to catch. Four waves six hours apart give every timezone a fair shot. **Leave `Empty at` empty to hand the gifts out by hand** |

Pages to read: **Sleigh cards** — every gift, with its points and where it is. The giver's own card
was consumed, so this is the only record of it. And **Sleigh waves**, written by the bot: one card
goes out a minute, and the actions let you announce a wave again or stop it (its cards then stay in
the sleigh).

---

## Boosts and the shop

**Boosts are sold by the merchant, not by the pass.** A boost needs no event to run, so locking it
behind an event shop would have made it unbuyable the rest of the year.

It takes three pages.

### 1. `Event shop → Boosts` — what the boost does

| Field | |
|---|---|
| **Name**, **Emoji**, **Description**, **Enabled** | what the player reads |
| **Kind** | `Chance of a special`, `Rarer treasures`, `A burst of spawns`, `Berries per catch` |
| **Magnitude**, **Duration minutes** | how strong and how long. A boost whose kind is already running **extends** it rather than starting a second one; different kinds all run at once |
| **Special** | read **only** by a `Chance of a special` |
| **Spawns**, **Channel id** | read **only** by a `A burst of spawns` |
| **Announce** | a public announcement when it fires |

A `Chance of a special` boost sold all year will point at a special that no longer spawns in
February: it will run and do nothing. For something permanent, prefer the other three kinds.

### 2. `Merchant → Merchant items` — what is bought

| Field | |
|---|---|
| **Kind** | `A boost for the whole server` |
| **Boost** | the one from step 1. Leave `Ball` and `Special` empty |
| **Rarity** | set `0`: it is the weight of the random rotation's draw, and a boost has no business there |
| **Prize** | the price in **berries** |
| **Event pass** + **Price in the pass currency** | the price in **snowflakes**, and the wallet it comes out of |
| **Stock**, **Limit per player** | empty means unlimited |
| **Time range** | optional |

**An item carries one price or the other, never both** — the page refuses to save it otherwise. To
sell the same boost both ways, **make the item a second time**: each copy then has its own stock
and its own limit per player.

### 3. `Merchant → Global shops` — where it is sold

Make a shop (`Christmas shop`) and tick the items into it. That is what players open with
`/merchant global shop`. The banner, the announcement text and the happy hour are set here; the
happy hour applies to a snowflake price just as it does to a berry one.

`scripts/setup_christmas_shop.py` does all three steps at once for the four Christmas boosts — see
the Discord guide.

### Reading

**Event shop → Active boosts**: what is running. The actions let you stop one or announce it again.
The bot rebuilds its own picture every thirty seconds, so stopping one is felt within that.

---

## Crew roles

`Crews → <a crew> → Role id`: the Discord role that crew carries.

The role is only ever given on the **main server** (`Settings → Main server id`), nowhere else. For
it to work the bot needs **Manage Roles**, and its own highest role has to sit **above** the crew
roles in the server's list.

Filling the field hands nothing out retroactively: `/crew admin syncroles` has to be run once (see
the Discord guide). After that, every crew change updates the role on its own.

---

## Frames

`Treasures → <a treasure> → Frames`.

A treasure can carry **several frames on the same day**: give them different names. When more than
one matches the same date, the bot draws one at random on every spawn. That is what lets a single
character have three Christmas illustrations.

The **Frames (name, then date MM-DD-YYYY)** column in the treasure list shows what each one holds.

---

## Repeatable claims

`Collectors → Collector tier levels → <a level> → Repeatable`.

Ticked, a player can claim that level **as many times as they can meet its requirements**. It is
meant for a level whose cards are consumed, like the elementals: each claim costs the cards again.
Left off, a level is claimed once and never again.

The column is editable straight from the list of levels too.

---

## Card credits

- The "opdex contributor community" line at the bottom of a card points at the URL set in
  `Settings → contributor community URL`.
- The **colour** is set per special: `Specials → <a special> → Credits colour`, in hex
  (`#FFFFFF`). Left empty, the default colour applies.
