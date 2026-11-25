# Guide admin — les commandes Discord

Ce qui se pilote depuis Discord, en jeu. La mise en place se fait dans le panel :
[admin-panel.md](admin-panel.md). Ce que voient les joueurs :
[../en/player.md](../en/player.md).

*An English copy of this guide is at [../en/admin-discord.md](../en/admin-discord.md).*

---

## Le piège à connaître d'abord

**Toutes les commandes `/shop` exigent un pass `Active` et dans ses dates.** Y compris
`/shop admin tokens`. Si le pass est en brouillon ou qu'il ne commence que la semaine prochaine,
la réponse est *« No event shop is open right now »* — et ça ne veut pas dire que la commande est
cassée.

À ne pas confondre non plus : la colonne **On sale** du panel ne regarde que l'offre elle-même,
jamais l'état du pass. Une offre peut afficher « On sale » alors que personne ne peut la voir.

---

## Les flocons

### Créditer un joueur

```
/shop admin tokens user:<@joueur> amount:1000
```

Staff uniquement. **Un montant négatif reprend** les flocons. Si tu reprends plus que ce que le
joueur détient, la commande refuse et te dit combien il a — elle ne descend jamais en négatif.
Le paramètre `event_pass` n'est utile que si plusieurs pass ont une monnaie.

Chaque mouvement est tracé dans **Pass wallet entries**, avec la raison `admin` et ton nom.

### Vérifier

```
/shop balance
```

Le solde du joueur dans la monnaie de l'événement.

```
/shop boosts
```

Les boosts **en cours d'exécution** — pas le catalogue. Tant que personne n'en a acheté, la réponse
est *« Nothing is boosted right now »*, et c'est normal.

---

## La boutique de boosts

### La monter d'un coup

Le script crée les quatre boosts de Noël, leurs items marchands et la boutique qui les contient.
À blanc d'abord, il n'écrit rien :

```bash
docker compose exec -T -e SPECIAL="Christmas 2026" admin-panel \
  python3 -m django shell < scripts/setup_christmas_shop.py
```

Puis pour de vrai :

```bash
docker compose exec -T -e GO=1 -e SPECIAL="Christmas 2026" admin-panel \
  python3 -m django shell < scripts/setup_christmas_shop.py
```

Relançable autant de fois que tu veux : il met à jour au lieu de dupliquer. `PASS="…"` choisit le
pass si plusieurs ont une monnaie, `SHOP="…"` le nom de la boutique (`Christmas shop` par défaut).

Il ne crée **que** des prix en flocons. Pour vendre le même boost en berries, duplique l'item dans
le panel et remplis `Prize` au lieu de `Price in the pass currency`.

### Les commandes

```
/merchant global shop shop:Christmas shop
/merchant global buy shop:Christmas shop
```

Elles marchent **toute l'année**, sans aucun événement en cours : il suffit d'avoir de quoi payer.

```
/merchant announce <nom de la boutique>
```

Annonce la boutique dans les salons de spawn et démarre le happy hour réglé sur elle.

---

## Le Secret Santa

```
/santa admin state
```

Où en est l'événement : inscrits, membres dans la chaîne, colis remplis, colis ouverts, et combien
ont été remplis à la main. À lancer avant et après chaque étape.

```
/santa admin draw
```

**L'étape qu'il faut penser à faire.** Elle tire la chaîne : qui offre à qui. À lancer une fois les
inscriptions fermées, avant la période d'emballage. Tant qu'elle n'est pas passée, le panel affiche
*« Waiting to be drawn »* en rouge et personne ne peut remplir son colis.

Le reste se fait tout seul : les colis que personne n'a remplis sont complétés par le bot à la fin
de la période d'emballage, et l'ouverture s'annonce d'elle-même le jour venu.

**Ne dis jamais à un joueur si son colis a été rempli par le bot.** C'est ce qui garantit qu'il n'y
a aucune punition à ne pas donner.

---

## Le traîneau

```
/sleigh admin give user:<@joueur> count:3
```

Sort des cadeaux du traîneau au hasard et les donne à un joueur — pour un prix de guerre de crew,
une récompense de King of the Seas. De 1 à 20.

```
/sleigh admin spawn count:5 channel:#salon
```

Renvoie des cadeaux du traîneau en spawns, à attraper par n'importe qui. Sans `channel`, ça part
dans le salon de spawn habituel. De 1 à 20.

C'est la façon de distribuer à la main ce qui reste, quand tu as laissé `Empty at` vide dans le
panel. Sinon le bot s'en charge en vagues.

---

## Les rôles d'équipage

```
/crew admin syncroles
```

Met à jour le rôle Discord de tous ceux qui sont dans un équipage, sur le serveur principal
uniquement. À lancer **une fois** après avoir rempli les `Role id` dans le panel ; ensuite chaque
changement d'équipage se gère tout seul.

La réponse ressemble à : *« 12 player(s) are in a crew, 8 of them are on this server, and 8 had
their role changed »*. L'écart entre les deux premiers chiffres, ce sont les gens qui ont choisi un
équipage sans jamais mettre les pieds sur le serveur principal — c'est normal.

Si ça ne change rien, la cause est presque toujours l'une des deux :

- le bot n'a pas **Manage Roles** ;
- son rôle le plus haut est **en dessous** des rôles d'équipage dans la liste du serveur.

Être administrateur ne suffit pas à régler le second point : Discord applique la hiérarchie des
rôles même à un administrateur.

```
/crew admin points user:<@joueur> points:500 reason:…
```

Ajoute des points à l'équipage d'un joueur, pour ce qu'aucune règle ne peut voir. Un nombre négatif
en retire. La raison est montrée au joueur comme son dernier gain.

---

## Les frames

Les deux commandes ont maintenant une **liste déroulante** des frames disponibles, au lieu d'un nom
à taper.

```
/admin spawning spawn treasure:<carte> frame:<frame>
```

Avec `special:Frame` et aucune frame choisie, c'est la frame du jour qui s'applique. Si la carte en
a plusieurs pour la même date, le bot en tire une au hasard.

```
/admin give treasure:<carte> user:<@joueur> frame:<frame>
```

Donne la carte en lui mettant la frame choisie.

---

## L'ordre des opérations, le jour J

1. `/santa admin state` — vérifier que tout le monde est inscrit.
2. Fermer les inscriptions (c'est la date dans le panel qui le fait).
3. `/santa admin draw` — **l'étape manuelle**.
4. Laisser la période d'emballage se dérouler ; le bot complète les colis manquants à la fin.
5. L'ouverture s'annonce toute seule à la date prévue.
6. Le traîneau se vide en vagues à partir de `Empty at`, ou à la main avec `/sleigh admin spawn`.
