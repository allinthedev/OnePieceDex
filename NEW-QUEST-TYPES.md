# New quest types

**41 new quest types** for event passes, on top of the 23 that already existed — 64 in all — plus **three new
mechanics**: quest chains, crew-wide counters and a target drawn for each player. Everything the game event bus
already carried and nothing listened to, everything the panel's own packages now say on the bus, and the quests
that read a state instead of counting an action.

Nothing existing changes meaning. The types below appear on their own in the **Event passes → Quests** admin,
with their own settings and help, and in a `load_event_pass` JSON file as a `"type"` value. The format is in
`eventexample/README.md`; `TREASURE_FILTERS` below means the usual `ball`, `special`, `any_special`, `group`,
`min_rarity`, `max_rarity`, `min_attack_bonus`, `min_health_bonus`, `hex_contains`.

---

## 1. Treasures, collection and completion

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `favorite` | Set treasures as favorites | TREASURE_FILTERS | Marking only. Unmarking is not counted in either direction. |
| `own_favorites` | Have *N* favorites at the same time | TREASURE_FILTERS | A state. Unfavoriting afterwards does not undo it. |
| `complete_group` | Complete a group, or *N* groups | `group` | Name a group and the goal becomes its size, worked out from the group itself — the panel never has to be kept in step. Leave it empty and the goal counts whole groups finished. |
| `completion` | Reach *N*% completion of the dex | — | The same figure the completion achievements use, above 100% included. |

```json
{ "name": "Framed and Proud", "type": "own_treasures", "goal": 5, "special": "Frame" }
```

**The `Frame` special now works in pass quests.** As everywhere else in the bot, `"special": "Frame"` does not
look for a special no treasure wears — it picks out the **framed** treasures, whatever special they carry. That
was broken in the pass engine before; `catch`, `own_treasures` and every other treasure quest honour it now.

## 2. Berries and rankings

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `own_currency` | Hold *N* berries at once | — | A goal to reach: spending them afterwards does not undo it. |
| `leaderboard_rank` | Reach a place on the berry leaderboard | `place` | Goal stays at **1** — either they are in it or they are not. Read only when the player runs `/pass view`, because working out a place means counting everybody richer than them and berries move constantly. |

## 3. Playing, and how long

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `activity` | Turn up at all | `main_server_only` | At most once an hour, and **only for commands no other quest is watching** — a command another quest asks about is dispatched as that command, never as activity. For a plain "come and play today", a daily-claim quest is the safer wording. |
| `playtime` | Have been playing for *N* days / months / years | `unit` | Counted from the player's first catch, which the **achievements** package records. Without it nobody has a first catch and this never moves. |
| `vote` | Vote for the bot on Top.gg | — | A vote is allowed every twelve hours, so with `"reset": "daily"` this is the cheapest daily quest there is, and it pays the dex back. Needs the `vote_app` package. |

## 4. Other players

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `trade_partners` | Trade with *N* **different** players | `min_currency`, `must_receive_treasure` | Each person counts once, however many trades they do together. |
| `give_partners` | Give treasures to *N* **different** players | TREASURE_FILTERS | Same idea, for gifts. |

These two are the one shape of quest two friends cannot farm between them. The Discord IDs already counted are
kept on the player's own progress row, so the number and the list it comes from can never drift apart.

## 5. Fighting

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `battle_played` | Take part in *N* battles | `max_lost` | Won or lost, so a small deck is not shut out of a pass. With `max_lost`, a battle given up counts as one loss for both players, so forfeiting is never a clean fight. |
| `boss_played` | Fight *N* bosses, or deal *N* damage | — | `"measure": "amount"` switches the goal to the damage dealt over the fight. Counts anyone who picked at least once, even if the boss killed them. |
| `boss_win` | Win *N* boss fights, or deal *N* damage | — | One player wins a boss, so this belongs on a hidden quest or on a tier nobody is expected to finish. |

`battle_win` gains `max_lost` too: **`"max_lost": 0` asks for a flawless win**, with no treasure lost. A forfeit
always counts as one loss, so a fight that never reached its end is never a flawless win.

```json
{ "name": "Not a Scratch", "type": "battle_win", "max_lost": 0, "reward": { "berries": 5000 } }
```

## 6. Grand Line Royale

| Type | What it asks for | Settings |
| --- | --- | --- |
| `royale_played` | Play *N* matches | `in_crew_war`, `place`, `min_rounds` |
| `royale_win` | Win *N* matches | `in_crew_war` |
| `royale_kill` | Get *N* kills | `in_crew_war` |
| `royale_chest` | Open *N* chests | `in_crew_war` |
| `royale_bounty` | Claim *N* bounties | `in_crew_war` |

A deed in a **crew war raid** arrives on the bus as its own event, so `"in_crew_war": true` asks for the raid
and leaving it out asks for an ordinary match. The two are never mixed: a quest about ordinary matches cannot be
finished in a war nobody outside a crew can enter.

`place` and `min_rounds` are what turn "turn up" into something worth a reward — a podium, or a long survival:

```json
{ "name": "Last Three Standing", "type": "royale_played", "goal": 2, "place": 3 }
```

All five need the royale bridge to be reporting matches (`KOTS-BRIDGE.md`). Without it nothing breaks, the
quests simply never move. The bridge now also carries each player's **place**, **rounds survived** and **damage
dealt**, which it was already sending and this bot was throwing away.

## 7. Christmas: the calendar, the Secret Santa, the sleigh

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `advent_open` | Open *N* doors | `on_time` | A door bought open later with `/advent catchup` counts too — unless `"on_time": true`, which is what tells a player who kept up from one who paid. |
| `advent_complete` | Open every door | — | However they got there. |
| `santa_join` | Sign up for the Secret Santa | — | |
| `santa_wish` | Fill *N* slots of the wishlist | — | Counts **how much of the list is written**, not how many times it was edited: changing the same slot three times is still one wish. |
| `santa_gift` | Fill *N* parcels | TREASURE_FILTERS | |
| `santa_open` | Open the parcel wrapped for you | TREASURE_FILTERS | |
| `sleigh_give` | Put *N* treasures in the sleigh | TREASURE_FILTERS | |
| `sleigh_full` | Be one of the players who filled it | — | |

Two of these are worth more than the command-counting quests they replace.

**`santa_gift` can ask for a present worth opening.** A parcel paid for in the event currency holds no card yet,
only the promise of one, so it carries no treasure to inspect — and a quest naming a treasure or a rarity
therefore only counts a parcel filled with a **real card**:

```json
{ "name": "Don't Be That Person", "type": "santa_gift", "min_rarity": 1, "max_rarity": 80 }
```

**`sleigh_full` is the only collective goal in the bot.** It is not about what the player did but about what the
server managed together, so it completes for **everyone who put something in** the day the sleigh fills up, not
only for whoever dropped the last card in.

There is deliberately **no quest for receiving** a Secret Santa parcel. A player must never learn when or how
their own parcel was filled, and a quest completing at that moment would tell them. `santa_open` is the only
thing the receiver is ever told about.

## 8. Crews

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `crew_join` | Pick a crew in `/player settings` | — | Changing crew counts again; re-picking the one they already fly does not. |
| `in_crew` | Be flying a crew's colours | — | A state, not an action: somebody who leaves their crew loses it again until they claim it. |
| `crew_points` | Score *N* deeds, or bring *N* war points | — | `"measure": "amount"` switches the goal to the points themselves. |
| `crew_rank` | Be among the top contributors of the running war | `place` | Goal stays at **1**. Players tied on points share a place, so two players on 300 are both second and nobody is pushed out of a top ten by a draw they did not lose. |
| `crew_war_win` | Be in the crew that wins the war | — | Completes for every member of the winning crew when a war is settled. A war ends once, so this belongs on a pass that outlives it, or in its final reward. |

`crew_points` scores nothing without a war running, a crew to fly for, and a rule in the panel for the deed —
which is exactly what the crew war already says about itself. Nothing new has to be configured.

## 9. Poneglyph hunts and wanted posters

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `hunt_stone` | Claim *N* poneglyphs | `for_crew` | In a hunt run as a race between crews only the first member to hand a set in claims it, and `"for_crew": true` asks for that one. |
| `hunt_complete` | Finish *N* hunts | `for_crew` | Counts the hunts finished **for** the player: their own, and the crew hunts they were paid a share of. A crew hunt is finished by the crew. |
| `bounty_claim` | Be the first to catch a wanted treasure | TREASURE_FILTERS | `"measure": "amount"` switches the goal to the berries collected. |

Only the first catch of a live bounty collects it, so `bounty_claim` is a race: a good hidden quest, a cruel
mandatory one.

## 10. Shops, crafting and the rest

| Type | What it asks for | Settings | Notes |
| --- | --- | --- | --- |
| `pack_weekly` | Claim the weekly pack | `main_server_only` | There is one a week, so a goal above 1 needs a pass that runs that long. |
| `auction_sold` | Sell *N* treasures on the auction house | TREASURE_FILTERS | The listings that **actually sold**. Listing a treasure is free, so `auction_create` only ever asked for an advert. `"measure": "amount"` counts the berries earned. |
| `event_shop_buy` | Buy from an event pass's own shop | `merchant_item` | What the player buys with the pass's **own currency** rather than with berries. `"measure": "amount"` counts that currency, not berries. The same purchase is still counted by the merchant quests, which count the ones paid in berries too. |
| `augment` | Augment *N* treasures | TREASURE_FILTERS | The treasure goes with the event **with its new stats**, so `min_attack_bonus` asks for an augment that actually worked, not for the money spent trying. |
| `collectible_buy` | Buy *N* collectibles | — | `"measure": "amount"` counts the berries spent. |
| `achievement_unlock` | Unlock *N* achievements | `category` | Only the ones unlocked while the pass runs, not the ones the player already had. |

---

## 11. Three settings that change who the counter belongs to

These are not types. They apply on top of a type, and each one does something no type could express on its own.

### `after` — quest chains

A quest can name other quests of the same pass that must be completed first. Until they are, it is shown
**locked**, says what it waits for, and does not progress — exactly like a quest in a locked tier. `after_logic`
is `all` (default) or `any`.

```json
{ "name": "The First Door", "type": "command", "command": "advent view" },
{ "name": "Now Open It",    "type": "advent_open", "after": ["The First Door"] },
{ "name": "Twenty Doors",   "type": "advent_open", "goal": 20, "after": ["Now Open It"] }
```

The names may belong to any tier, including a later one, because chains are linked once the whole file is read.
A quest waiting on itself, or a loop of quests waiting on each other, is refused rather than loaded — a tier
nobody can finish is worse than a file that will not load. A chained quest that is also `mandatory` is still
needed to finish its tier: the chain decides the **order**, not whether it counts.

### `shared_with_crew` — crew-wide quests

The counter belongs to the crew. Every member's deeds add to one total, and it completes for all of them.

```json
{ "name": "A Thousand Between Us", "type": "catch", "goal": 1000, "shared_with_crew": true }
```

The crew's row (`CrewQuest`) is the truth and each member's own progress mirrors it, which is what lets
claiming, daily resets and tier completion work exactly as they do for a quest nobody shares. The total moves
with an `F()` expression, so two members scoring at the same moment both count. A member sees it move when they
next do something, or when they open the pass.

A player **with no crew cannot move it and cannot finish it** — there is no counter for them to be part of — so
a crew-wide quest belongs among the optional ones, or the pass should also hold a `crew_join` quest. It is
refused on the types that read what a player owns, holds or ranks at: those are theirs alone and cannot be added
up across a crew. Staff can correct a crew's total in **Event passes → Crew quests**.

### `draw_treasure` — a different target for every player

Instead of accepting any treasure matching the filters, one of them is drawn for each player and the quest asks
for **that one**.

```json
{ "name": "Your Mark", "type": "catch", "group": "Logia", "max_rarity": 90, "draw_treasure": true }
```

The filters are the pool it is drawn from, so a group or a rarity range is required: drawing out of the whole
dex hands people a target nobody could reasonably catch. The draw is **flat**, not weighted by rarity — a
weighted draw would give almost everybody the commonest treasure in the pool, which is not a target, it is a
formality. It happens the first time the player opens the pass, it is kept on their progress row, and it never
changes, so nobody can reroll a target they do not like by waiting. The pass tells them which treasure is
theirs. Only `catch`, `obtain` and `own_treasures` can draw, and a drawn target cannot be shared with a crew.

Nobody can copy anybody's answer, which is the point — and it sends people looking for each other's spares.

## Two things that work differently now

**`"measure": "amount"` is no longer only berries.** It is war points for `crew_points`, damage for the boss
types, and the pass's own currency for `event_shop_buy`. Each type's goal label in the admin says which.

**"Only in the main server" no longer switches quests off in silence.** A type whose events cannot name a server
— a crew war scored by a background task, a vote arriving over a webhook, an achievement unlocked by an engine,
or a collection the player simply *has* — is exempt from it. Before this, such a quest on a main-server pass
could never progress and nothing said why. This also fixes `battle_win`, whose event never carried a server
either.

## What each type needs installed

The admin already warns next to a quest whose package is missing, and `/pass diagnostics` lists the whole
picture. Four new packages are now declared there: **boss fights** (`boss`), **augment** (`augment_app`),
**collectibles** (`collectible_app`) and **Top.gg votes** (`vote_app`).

The panel's own packages — the advent calendar, the Secret Santa, the sleigh, crews, hunts, achievements, the
event shop — are always installed, so their quests need no integration check. What they do need is **content**:
no calendar means no doors, no running war means no points, and the quest simply waits.

## What is not here

- **`own_collector` as a type** — it would be a strictly worse duplicate. A claimed collector card *is* a
  treasure wearing that craft's special, so `own_treasures` already asks for it. What it could not do was name
  the craft instead of the special, which is fragile because a special can be renamed — so `own_treasures` now
  takes **`craft_type`** too: `{"type": "own_treasures", "goal": 3, "craft_type": "Tier 2"}`.
- **Quests with a time of day** — `starts_at` / `ends_at` work in dates; "only between 8pm and 10pm" would
  make quests that follow a server's busy hour possible.
- **Quests of restraint** — "finish the day without selling anything to Buggy". Checkable at the end of a
  period, and unlike anything else in the bot.
- **A free partner in a chain** — `partner_discord_id` names one person. A "do it with whoever you did the last
  one with" would make quests for pairs. `trade_partners` and `give_partners` already cover "different people".
- The achievements engine has the same **`Frame` special** gap the pass engine had, and the same
  **main-server** blind spot. Both were left alone here: this change is about the pass.
