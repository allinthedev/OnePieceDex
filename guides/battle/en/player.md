# Battle mode — player guide

Written to be posted on the server, one block at a time: every block between two lines fits in a single
Discord message. The figures in it (turn timer, heal uses, the +10% of a full set, health counted three
times) are the default settings: if they are changed in the panel, change them here too.

---

## ⚔️ Battles — the short version

Challenge another player, build a deck of **characters**, arm them with **weapons** and **devil fruits**,
and fight turn by turn until one deck is down.

**1.** `/battle start` — challenge someone
**2.** `/battle add` — put your characters in
**3.** `/battle equip` — give each of them a weapon and a fruit
**4.** Press **✔ Ready** — and fight

---

## 1 · Start a battle

```
/battle start opponent:@someone
```

A **Battle Plan** appears, showing both decks. That is all you need. Two extras, both optional:

- `max_size` — how many characters each deck holds (4 by default, 10 at most).
- `wager` — berries you both put on the table. Winner takes all. They leave both wallets the moment the
  fight begins. Leave it out and you play for nothing but the win.

You can only be in one battle at a time. **✖ Cancel** closes the plan, and so does `/battle leave`.
Invited to a battle you do not want? Press Cancel, or just start your own: that turns the invitation down.

---

## 2 · Build your deck

```
/battle add
/battle remove
```

**Only characters fight.** A sword or a devil fruit does not fight on its own: it is equipment, and that
is the next step. Ships and crews sit battles out for now, and so do treasures retired from the dex.

---

## 3 · Arm your characters

```
/battle equip item:<weapon or fruit> character:<someone in your deck>
/battle unequip item:<weapon or fruit>
```

Each character holds **one weapon** and **one devil fruit**. An item adds its own attack and health to
whoever holds it — but how much of it depends on **who** that is:

- **Their own item** — Zoro with Wado Ichimonji, Luffy with the Gomu Gomu: **200%** of its stats.
- **A kind they master** — a swordsman with somebody else's blade: **110 to 150%**.
- **Anything else** — **50%**.
- **Something they cannot use** — Luffy with a sword, Sanji with any weapon at all: even less.

Hand a character both a weapon and a fruit and they get **+10%** on top of everything.

The Battle Plan shows what everybody holds, and at what percent. Putting items back in the hands of their
rightful owners is where battles are won.

---

## 4 · Fight

Once both players press **✔ Ready**, the battle starts. The challenger plays first, then you take turns.
Your first character still standing faces theirs.

In a battle everybody has **three times** the health written on their card, what they hold included:
a fight is an exchange of blows, not a single one.

On your turn — you have 60 seconds, after which you simply attack:

- ⚔ **Attack** — a plain hit.
- 🎲 **Crit Gamble** — a coin flip: double damage, or half.
- ❤ **Heal** — gives back 25 to 45% of your character's health. Twice per character.
- **Capacity** — your character's own special move, under its own name. Once per character.
- 🎒 **Item** — use something you bought in the 🛒 **Shop**.
- **Forfeit** — give up. Your opponent takes the win. This one works at any time, your turn or not.

Any hit can be dodged, now and then. When a character falls, the next one steps in. The last deck
standing wins.

Lost the message, or stuck waiting? `/battle leave` gets you out from anywhere: it cancels a battle that
has not started, and forfeits one that has.

---

## What changes the damage

- **Rarity** — a rarer character hits a little harder against a more common one. Never by more than 10%.
- **Who is fighting whom** — rivals hit each other harder, crewmates hold back. Akainu against Ace hurts.
  Hancock can hardly bring herself to strike Luffy.
- **What they hold** — equipment changes what hurts you. Whoever holds the Gomu Gomu shrugs off lightning
  and blunt weapons. Fire loses to magma.

---

## Rewards and ranking

- **The wager** — the winner takes both stakes.
- **Berries** — your first wins of the day pay a flat reward. After that, the stronger the deck you beat,
  the more you earn. Beating the same player again and again only pays once a day.

```
/battle leaderboard
```

The top 10, with everybody's wins and losses.
