# Christmas event — player guide

Written to be posted on the server. The staff guides sit beside it: [admin-panel.md](admin-panel.md)
and [admin-discord.md](admin-discord.md), with French copies in [../fr/](../fr/).

---

## Snowflakes ❄️

Snowflakes are the currency of the Christmas event. They buy boosts for the whole server, they can
fill a Secret Santa parcel, and they can be given to your crew.

**Where they come from**

- **`/daily`** — your usual daily berries now come with snowflakes on top, for as long as the event
  runs. Nothing to do differently.
- **The Christmas pass** — most of them. Quests hand out about 1,880 snowflakes over December.

**Where to check**

```
/shop balance
```

What you hold.

```
/money give user:<@someone> amount:500 event_pass:Christmas 2026
```

Gives some of your snowflakes to another player. Leave `event_pass` out and the same command gives berries, the way it
always has. Whoever you send them to has to accept money from you — the same setting that guards
berries guards these.

---

## The Christmas pass

```
/pass view
```

Four weekly tiers, forty-two quests, from December 1st to the 31st. A tier opens when the previous
one is finished **and** its date has come: the 1st, the 8th, the 15th and the 22nd.

- Only the **mandatory** quests count towards finishing a tier. The others are extra.
- Some quests are **hidden**: you only ever see them once you have completed them. They never block
  a tier.
- Rewards can be claimed until **January 7th**, a week after the event ends.

Finish every tier and the pass hands over its final reward.

---

## The advent calendar

```
/advent view
```

The grid, and which doors you have opened.

```
/advent open
```

One door a day. A day runs to **midnight UTC**, so everyone's day turns over at the same moment.

```
/advent catchup day:7
```

Missed a day? You can buy that door open, in **berries**. It is the only way to catch up.

Two things worth knowing:

- Opening doors several days in a row earns **streak rewards**, on top of what the doors give.
- A door can also fire a **surprise**. It never replaces what the door gives, it is added to it.

Careful if you are doing the pass quests: **`/advent catchup` does not count** towards them. Only
doors opened on their own day do. That is why the last tier asks for twenty doors and not
twenty-five.

---

## Secret Santa

You are given someone to make a present for, and someone else is making one for you. Nobody knows
who their Santa is until the parcels are opened.

**1. Sign up**

```
/santa join
```

**2. Say what you would like**

```
/santa wish slot:1 treasure:<a treasure>
/santa wishlist
```

Three slots. You cannot ask for anything **rarer than T10** — the list refuses it.

**3. Find out who you are giving to**

```
/santa target
```

Their wishlist. Keep it to yourself.

**4. Fill your parcel**, either way:

```
/santa gift card:<one of your cards>
```

You give a card of your own. **It is your choice** — it does not have to be one from their list.

```
/santa pay treasure:<a treasure>
```

Or you pay in snowflakes and name the treasure to wrap.

**5. Open yours**

```
/santa open
```

From Christmas Day. Every card in a parcel comes out with the Christmas special on it.

**Nobody is punished for not giving.** If a parcel has not been filled by the end of the wrapping
window, it gets filled anyway. You will never know which is which, and neither will anyone else.

---

## The crew sleigh

```
/sleigh view
```

How full it is, how much you have put in, and when the next wave goes out.

```
/sleigh give card:<one of your cards>
```

Put a card in. **It is consumed** — it leaves your collection for good.

```
/sleigh top
```

Which crews have given the most.

The points go to **your crew**, in the crew war. The rarer the card, the more it is worth: the
point of it is to reward being generous, not being busy. There is a limit to how many you can give
per day, and it resets at midnight UTC.

**On the 26th**, everything still in the sleigh is spawned back out, a card at a time, in several
waves spread over the day so every timezone gets a shot. Those spawns are for **everyone**, whether
or not you put anything in.

---

## Boosts

Boosts apply to the **main server**, whatever server you buy them from.

```
/merchant global shop shop:Christmas shop
/merchant global buy shop:Christmas shop
```

Four of them, paid in snowflakes:

| | |
|---|---|
| 🌨️ **Blizzard** | rarer treasures across the server, for an hour |
| 🎄 **Christmas spirit** | the Christmas special turns up more often, for an hour |
| 🎁 **Gift rain** | five treasures spawn one after another |
| 💰 **Full purse** | catches pay more berries, for an hour |

```
/shop boosts
```

What is running right now, and until when.

Two rules:

- Buying a boost of a kind that is **already running** does not start a second one — it **adds its
  time** to the one in progress.
- Boosts of **different** kinds all run at the same time.

---

## Christmas frames

Treasures caught during the event can come with a Christmas frame. Some characters have **several
different frames** for the same day — which one you get is drawn at random when it spawns. Worth
collecting more than one.

---

## Quick reference

| Command | |
|---|---|
| `/pass view` | the Christmas pass and its quests |
| `/daily` | berries **and** snowflakes |
| `/shop balance` | how many snowflakes you hold |
| `/money give … event_pass:` | give snowflakes to another player |
| `/shop boosts` | what is boosted right now |
| `/advent view` · `open` · `catchup` | the calendar |
| `/santa join` · `wish` · `wishlist` · `target` · `gift` · `pay` · `open` | Secret Santa |
| `/sleigh view` · `give` · `top` | the crew sleigh |
| `/merchant global shop` · `buy` | buy boosts |
