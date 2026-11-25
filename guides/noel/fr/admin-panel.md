# Guide admin — le panel

Tout ce qui se règle dans le panneau d'administration pour l'événement de Noël et les features qui
sont arrivées avec. Les commandes Discord sont dans [admin-discord.md](admin-discord.md),
et ce que voient les joueurs dans [../en/player.md](../en/player.md).

*An English copy of this guide is at [../en/admin-panel.md](../en/admin-panel.md).*

Partout : **les heures sont en UTC**, et une rareté **plus basse est plus rare** (T10 est plus rare
que T200).

---

## L'ordre dans lequel monter l'événement

Chaque étape a besoin de la précédente. Dans le désordre, ça coince.

1. **Le special** — `Specials → Add`. Sans lui, le pass ne se charge pas et ni le Santa ni le
   traîneau ne savent quoi fabriquer.
2. **Le pass et sa monnaie** — c'est la monnaie qui débloque le portefeuille et les prix en flocons.
3. **Le calendrier, le Secret Santa, le traîneau** — chacun pointe sur le special.
4. **Les boosts et la boutique du merchant** — indépendants de tout le reste.
5. **Publier le pass** en le passant en `Active`.

---

## Le pass

`Event passes → Christmas 2026`.

### Les sections de la page

| Section | Ce qui compte |
|---|---|
| (en haut) | nom, emoji, description, bannière, couleur, **position** |
| **When** | `Starts at`, `Ends at`, `Claim until` — les quêtes n'avancent qu'entre les deux premières, la réclamation peut durer plus longtemps |
| **Where** | `Main server only`, `Main server id` |
| **Who** | les conditions d'accès. Aucune = ouvert à tous |
| **Its own currency** | `Currency name`, `Currency emoji`, `Daily currency` |
| **End of the pass** | la récompense finale et son message |
| **Publication** | `Status`, les paquets requis par les quêtes, les notes |

### La monnaie

C'est le champ qui commande tout le reste de l'économie de l'événement.

- **Currency name** — `Snowflakes`. **Tant qu'il est vide, le pass n'a pas de portefeuille** : pas
  de solde, pas de prix en flocons, pas de don au crew.
- **Currency emoji** — `❄️`, ou un emoji Discord collé en entier (`<:flocon:123…>`).
- **Daily currency** — ce que `/daily` ajoute aux berries tant que le pass tourne. `10` est le
  réglage du fichier. À 0, le daily ne donne rien.

### Brouillon ou publié

Un pass créé est en **Draft** : seul le staff le voit dans `/pass view`, et rien ne progresse.
C'est l'état dans lequel tester tranquillement. Le passer en **Active** l'ouvre à tout le monde,
et c'est à ce moment-là que `/daily` commence à distribuer des flocons.

**Position** décide quel pass `/pass view` ouvre quand le joueur n'en nomme aucun : le plus petit
numéro parmi ceux qui tournent.

### Le charger depuis le fichier

Plutôt que de cliquer 42 quêtes, `eventexample/christmas_2026.json` les décrit toutes. Voir
`eventexample/README.md`. Le pass arrive en brouillon, et recharger le fichier met le brouillon à
jour sans rien dupliquer. Un pass déjà `Active` est refusé par le chargeur : repasse-le en Draft
d'abord.

### Les pages de lecture

- **Pass wallets** — ce que chaque joueur détient.
- **Pass wallet entries** — le journal : chaque mouvement, sa raison (`pass`, `daily`, `shop`,
  `gift_sent`, `gift_received`, `admin`, `refund`) et son solde après coup. Un écart entre deux lignes successives
  veut dire que de la monnaie a bougé sans passer par le journal.

---

## Le calendrier de l'avent

`Advent calendars → Add`. Les portes, les paliers de série et les surprises s'éditent **sur la page
du calendrier**, pas sur des pages séparées.

| Section | Ce qu'il faut savoir |
|---|---|
| (en haut) | le pass rattaché, le nom, l'emoji, `Enabled`, et l'état calculé |
| **When** | `Starts on` et `Door count`. La porte 1 s'ouvre le jour de départ, la 2 le lendemain. Une journée va jusqu'à minuit UTC, donc tout le monde change de jour au même instant |
| **Catching up** | `Catch up price` en berries et `Catch up until`. C'est la seule façon de rattraper un jour manqué, et le seul endroit où l'événement retire des berries de l'économie. **Un prix à 0 veut dire qu'un jour manqué est perdu** |
| **Surprises** | `Surprise chance`, entre 0 et 1. La surprise s'ajoute à la porte, elle ne la remplace jamais |
| **Looks** | l'image de fond de la grille |

Puis, dans les tableaux en bas de la même page :

- **Doors** — une ligne par jour : le numéro, le lot, le message.
- **Streak rewards** — le lot donné à partir de N portes ouvertes.
- **Surprises** — nom, emoji, **poids** (c'est lui qui décide laquelle sort), lot ou boost,
  `Once per player`.

Pages de lecture : **Advent openings** (chaque porte ouverte, si elle a été payée, quelle surprise
est tombée) et **Advent streak grants** — où l'action *« Let the selected players earn these
again »* permet de redonner un palier de série.

---

## Le Secret Santa

`Secret Santas → Add`.

| Section | Ce qu'il faut savoir |
|---|---|
| **What it hands out** | `Special` (toute carte d'un colis en sort marquée), `Event pass` (d'où vient la monnaie) et `Price`. **Un prix à 0 supprime la possibilité de payer** au lieu de donner une carte |
| **The stages** | dans l'ordre : `Signup opens at`, `Signup closes at`, `Wrap until`, `Opens at`, `Closes at`. Entre l'inscription et l'emballage, il faut lancer `/santa admin draw` |
| **The lists** | `Wishlist size` et `Min rarity`. **Plus bas = plus rare**, donc ce champ est la carte *la plus rare* qu'on puisse demander : mets-y la rareté de ton T10 et personne ne peut souhaiter plus rare |
| **Parcels nobody filled** | `Fill the rest` — **laisse-le activé** |

### La règle à ne jamais casser

La page **Santa gifts** a une colonne `kind` qui dit si un colis a été rempli par son donneur, payé,
ou complété par le bot parce que personne ne s'en est occupé.

**Cette information ne doit jamais sortir du panel.** C'est elle qui rend vrai le « aucune punition
si tu ne donnes pas » : pour tout le monde sauf toi, un colis rempli par le bot et un colis rempli
par un joueur sont identiques. Le dire transformerait l'absence de punition en punition.

### Les pages de lecture

- **Santa entries** — qui participe, à qui il donne, combien de vœux, colis rempli ou non. C'est la
  chaîne, à plat. Les vœux s'éditent dans le tableau de la fiche.
- **Santa gifts** — chaque colis. L'action *« Let the selected parcels be opened again »* sert quand
  une carte a été perdue par un incident ; l'ancienne carte n'est pas reprise.

---

## Le traîneau

`Sleighs → Add`.

| Section | Ce qu'il faut savoir |
|---|---|
| (en haut) | le `Special` que deviennent les cartes données |
| **When** | `Opens at`, `Closes at`, `Per day` (quota par joueur, remis à zéro à minuit UTC), `Goal` — **le goal n'est que la barre affichée**, le traîneau continue d'accepter des cadeaux après |
| **What a gift is worth** | `Points base`, `Points pivot`, `Points cap`. Les points vont au crew du donneur, dans la guerre de crew en cours : base × pivot ÷ rareté, plafonné. Une carte dix fois plus rare que le pivot vaut dix fois la base. **Sans guerre en cours, pas de points** — et le cadeau part quand même |
| **Emptying it again** | `Empty at`, `Wave count`, `Wave hours`, `Spawn channel id`. Passé l'heure, ce qui reste est découpé en vagues et respawné, une carte à la fois, pour tout le monde. Quatre vagues espacées de six heures donnent sa chance à chaque fuseau. **Laisse `Empty at` vide pour distribuer à la main** |

Pages de lecture : **Sleigh cards** — chaque cadeau, avec ses points et où il en est. La carte du
donneur a été consommée, donc c'est la seule trace qu'il en reste. Et **Sleigh waves**, écrites par
le bot : une carte part par minute, et les actions permettent de réannoncer une vague ou de
l'arrêter (ses cartes restent alors dans le traîneau).

---

## Les boosts et la boutique

**Les boosts se vendent chez le merchant, pas dans le pass.** Un boost n'a besoin d'aucun événement
pour tourner, donc l'enfermer derrière une boutique d'événement l'aurait rendu inachetable le reste
de l'année.

Ça se fait en trois pages.

### 1. `Event shop → Boosts` — ce que fait le boost

| Champ | |
|---|---|
| **Name**, **Emoji**, **Description**, **Enabled** | ce que le joueur lit |
| **Kind** | `Chance of a special`, `Rarer treasures`, `A burst of spawns`, `Berries per catch` |
| **Magnitude**, **Duration minutes** | la force et la durée. Un boost d'un type déjà en cours **prolonge** celui-là au lieu d'en lancer un second ; des types différents tournent tous en parallèle |
| **Special** | lu **uniquement** par un `Chance of a special` |
| **Spawns**, **Channel id** | lus **uniquement** par un `A burst of spawns` |
| **Announce** | annonce publique au déclenchement |

Un boost de type `Chance of a special` vendu toute l'année pointera sur un special qui ne spawn
plus en février : il tournera sans rien faire. Pour du permanent, préfère les trois autres types.

### 2. `Merchant → Merchant items` — ce qu'on achète

| Champ | |
|---|---|
| **Kind** | `A boost for the whole server` |
| **Boost** | celui de l'étape 1. Laisse `Ball` et `Special` vides |
| **Rarity** | mets `0` : c'est le poids du tirage aléatoire de la rotation, et un boost n'a rien à y faire |
| **Prize** | le prix en **berries** |
| **Event pass** + **Price in the pass currency** | le prix en **flocons**, et le portefeuille d'où il sort |
| **Stock**, **Limit per player** | vides = illimités |
| **Time range** | optionnel |

**Un item porte un prix OU l'autre, jamais les deux** — la page refuse de l'enregistrer sinon. Pour
vendre le même boost des deux façons, **crée l'item une deuxième fois** : chaque copie a alors son
propre stock et sa propre limite par joueur.

### 3. `Merchant → Global shops` — où il est vendu

Crée une boutique (`Christmas shop`), et coche les items dedans. C'est elle que les joueurs ouvrent
avec `/merchant global shop`. La bannière, le texte d'annonce et le happy hour se règlent ici ; le
happy hour s'applique aussi bien à un prix en berries qu'à un prix en flocons.

Le script `scripts/setup_christmas_shop.py` fait les trois étapes d'un coup pour les quatre boosts
de Noël — voir le guide Discord.

### Lecture

**Event shop → Active boosts** : ce qui tourne. Les actions permettent d'en arrêter un ou de le
réannoncer. Le bot relit son instantané toutes les 30 secondes, donc un arrêt se sent dans la
demi-minute.

---

## Les rôles d'équipage

`Crews → <un crew> → Role id` : l'identifiant du rôle Discord que porte cet équipage.

Le rôle n'est donné que sur le **serveur principal** (`Settings → Main server id`), et nulle part
ailleurs. Pour que ça marche, le bot a besoin de **Manage Roles**, et son propre rôle le plus haut
doit être **au-dessus** des rôles d'équipage dans la liste du serveur.

Remplir le champ ne distribue rien rétroactivement : il faut lancer `/crew admin syncroles` une
fois (voir le guide Discord). Ensuite, chaque changement d'équipage met le rôle à jour tout seul.

---

## Les frames

`Treasures → <une carte> → Frames`.

Une carte peut porter **plusieurs frames le même jour** : il suffit de leur donner des noms
différents. Quand plusieurs correspondent à la même date, le bot en tire une au hasard à chaque
spawn. C'est ce qui permet d'avoir trois illustrations de Noël pour un même personnage.

La colonne **Frames (name, then date MM-DD-YYYY)** de la liste des cartes montre ce que chacune
porte.

---

## Les réclamations répétables

`Collectors → Collector tier levels → <un niveau> → Repeatable`.

Coché, un joueur peut réclamer ce niveau **autant de fois qu'il réunit les cartes demandées**.
C'est fait pour les niveaux dont les cartes sont consommées, comme les élémentaires : chaque
réclamation recoûte les cartes. Décoché, le niveau se réclame une fois et plus jamais.

La colonne est aussi modifiable directement depuis la liste des niveaux.

---

## Les crédits sur les cartes

- Le texte « opdex contributor community » en bas de carte pointe sur l'URL réglée dans
  `Settings → contributor community URL`.
- La **couleur** se règle par special : `Specials → <un special> → Credits colour`, en hexadécimal
  (`#FFFFFF`). Laissée vide, la couleur par défaut s'applique.
