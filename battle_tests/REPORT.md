# Mode combat : rapport de test

Troisième passe, le 28 novembre 2026, sur `extra/battle/battle_app` : les 24 bugs de la première passe sont
corrigés, et deux nouveautés sont couvertes, le multiplicateur de vie et les listes d'autocomplétion. Toujours
sans Discord : le vrai cog, piloté par de fausses interactions, sur la base `battle_test`. Aucun fichier
modifié hors de `battle_tests/`.

## 1. Bilan

| | |
|---|---|
| Tests | **579** |
| Passent | **579** |
| Échouent | **0** |
| Bugs de la première passe | 24, **tous corrigés et vérifiés** (un test de non-régression chacun, section 3) |
| Nouveau bug bloquant | aucun ; un défaut mineur de recherche hérité du reste du bot (section 4) |

Rejouer tout (4 min 10) :

```
bash battle_tests/run_all.sh
```

Rejouer une partie : `bash battle_tests/run_all.sh t09 t10`. La sortie complète de chaque fichier reste dans
`battle_tests/out/<fichier>.txt`. Les tests écrits pour un bug gardent son étiquette : si le bug revient, la
ligne `FAIL` la porte, par exemple `[B06]`.

| Fichier | Tests | Sujet |
|---|---|---|
| `test_loadout.py`, `test_capacity.py` | 52 | règles pures (tenus par la session principale) |
| `t00_django` (dans `run_all.sh`) | 3 | `manage.py check`, migrations à jour, chargeur d'équipement à blanc |
| `t01_proposal_deck.py` | 74 | `/battle start`, `/battle leave`, `/battle add`, `/battle remove`, cartes perdues |
| `t02_equipment.py` | 53 | `/battle equip`, `/battle unequip`, les trois couches |
| `t03_start.py` | 47 | Ready, séquestre de la mise, clics simultanés |
| `t04_turns.py` | 93 | actions, esquive, soin, Capacity, objets, mort, fin |
| `t05_multipliers.py` | 56 | paliers, paires, liens de groupe, résistances |
| `t06_end.py` | 65 | paiement, gains, `BattleRecord`, événements, forfait, horloge, classement |
| `t07_robustness.py` | 65 | redémarrage, rechargement, clics simultanés, menus, messages supprimés, jeton de 15 minutes |
| `t08_balance.py` | 5 | simulation d'équilibrage, aux réglages de la base |
| `t09_health.py` | 33 | multiplicateur de vie |
| `t10_arguments.py` | 33 | listes d'autocomplétion des cinq arguments |

### Style

`ruff check battle_tests` et `ruff format --check battle_tests` passent tous les deux (ruff 0.14.1, la version
du projet, installé sur ce PC seulement, à la demande de l'utilisateur ; rien n'a été ajouté à l'image).

### Les réglages ont bougé pendant les tests

Deux réglages ont changé à la demande de l'utilisateur, et un troisième en cours de passe :

- **Barème de rareté** : 0.9 / 0.925 / 0.95 / 0.975 / 1.0, soit 10 % d'écart au plus, au lieu de 0.7 à 1.0.
- **Multiplicateur de vie** : nouveau réglage, d'abord à 2 puis fixé à **3** par l'utilisateur (modèle,
  migration `0008` et base).

Pour ne plus dépendre de la valeur du jour, tous les tests de règles tiennent le multiplicateur de vie à 1
(leurs chiffres sont ceux des cartes), `t09` le règle lui-même à 2, à 3 et à 1,5, et seule la simulation
(`t08`) joue avec ce que la base contient.

## 2. Ce qui est couvert

**Proposition.** Refus contre soi-même et contre un bot, mise impayable, taille de deck négative ou au-delà de
10. Joueur déjà engagé refusé des deux côtés. Un joueur seulement invité peut lancer son propre combat, ce qui
ferme l'invitation ; dès qu'il a ajouté une carte, il est engagé. Un plan intouché depuis 31 minutes ne bloque
plus un nouveau combat. `/battle leave` : annule un plan, abandonne un combat.

**Deck.** Seuls les personnages actifs entrent, messages vérifiés mot pour mot. Deck plein, même exemplaire
deux fois, carte d'un autre, modification après « prêt ». Une carte donnée, un objet donné ou une carte
supprimée après `/battle add` sont retirés au Ready, chez soi comme chez l'adversaire.

**Équipement (53).** Emplacements, remplacement, objet déjà porté, objet désactivé, gel après « prêt ».
Pourcentages demandés et 1 684 paires comparées à une relecture indépendante de la table. Stats avant, pendant
et après, bonus de set compris.

**Démarrage.** Séquestre une fois chez chacun. Mise impayable par l'un ou par l'autre : personne n'est débité.
Deck vide refusé au Ready. Deux Ready simultanés, Ready recliqué pendant celui de l'autre, Ready et
`/battle add` au même moment : un seul combat, un seul tableau, un seul prélèvement.

**Tours.** Attaque aux deux bouts de la fourchette, critique, esquive, soin borné et compté par carte, boutons
grisés une fois épuisés, attaque de repli réelle. Capacity par défaut et les trois effets de `Buff`, esquive
d'une Capacity offensive. Les trois objets de boutique.

**Multiplicateurs (56).** Cinq paliers et leurs bornes, paires, liens de groupe, miroir neutre, résistances et
leur plancher, « (lore advantage!) » seulement quand la relation avantage.

**Fin.** Pot et récompense payés une fois, un seul `BattleRecord`, événements avec le bon `lost_count`.
Anti-abus. Forfait permis aux deux joueurs. Horloge du cog. Classement paginé sans doublon.

**Robustesse.** État JSON relu à l'identique. `setup()` réel au démarrage et au rechargement. Deux actions sur
un tour, coup fatal en double, clic au moment où l'horloge tombe : une seule action. Tableau supprimé : le
combat continue ailleurs. Jeton d'interaction expiré : l'horloge édite toujours le tableau en place.

**Multiplicateur de vie (33, nouveau).**

- Le cog lit bien la valeur de la base, qui est celle par défaut du modèle. Le panneau accepte 0,5 à 10 et
  refuse 0,4 et 10,5 ; la contrainte de la base refuse les mêmes (essais faits dans une transaction annulée).
- À ×2, Luffy (310/301) entre à 310/602 : la vie double, l'attaque ne bouge pas. Le bonus de la carte, le bonus
  de spécial et la vie fixe d'un `Buff` sont dans ce qui est multiplié. Une fraction est arrondie (390 × 1,5 =
  585).
- Objets : Enma à 200 % sur Zoro donne « +490 ATK, +812 HP » à ×2 (Zoro à 786/1288) et « +490 ATK,
  +1218 HP » à ×3 (Zoro à 786/1932). Luffy avec Gomu Gomu et
  Wado : 1803 d'attaque et 3146 de vie, le bonus de set pris sur le total multiplié. Retrait d'un objet, puis
  objet donné à un autre joueur : les stats se recalculent, toujours doublées.
- Le réglage est lu à l'entrée dans le deck : une carte entrée à ×2 garde ses 602 quand le réglage passe à 3,
  la suivante entre à ×3, et un combat lancé garde sa vie quoi qu'on règle ensuite.
- En combat, un coup vaut ce qu'il valait (294), un soin est une part de la vie multipliée (25 % de 780 = 195).
- Luffy contre Kaido, meilleur tirage à chaque coup : **2 tours à ×1, 4 à ×2, 6 à ×3**.
- Gains : le rapport de puissance compte la vie multipliée. La victoire contre un deck plus lourd paie 37 à ×2
  contre 36 à ×1, le plancher reste 15.

**Listes d'autocomplétion (33, nouveau).** Chaque liste est demandée comme Discord la demande, par
l'`autocomplete` du paramètre de la commande.

- Les cinq arguments ont chacun leur liste, et aucun ne change la lecture ni le contrôle de ce qui est choisi.
- `/battle add` : les personnages du joueur, les plus rares d'abord, le meilleur exemplaire d'abord ; ni arme,
  ni fruit, ni bateau, ni personnage retiré, ni carte d'un autre, ni carte supprimée. Recherche par morceau de
  nom, par identifiant, par `=Nom` exact. Trente candidats : 25 choix.
- `/battle equip item` : armes et fruits seulement, objet retiré exclu.
- `/battle equip character` et `/battle remove` : le deck en préparation, libellé « Roronoa Zoro — 786 ATK /
  1288 HP — holds Enma ». `/battle unequip` : « Enma — held by Roronoa Zoro (200%) ».
- Rien sans combat en préparation, rien pendant un combat lancé, rien du deck adverse. Recherche par nom, par
  objet porté, par identifiant en majuscules ou minuscules. Un libellé de plus de 100 caractères est coupé à
  100 et reste trouvable par ce que la coupe a enlevé.

## 3. Les 24 bugs de la première passe : corrigés

| | Ce que c'était | Ce qui le garde maintenant |
|---|---|---|
| **B01** | le menu d'objets jouait le tour de l'adversaire | `t07` « an item picked during the opponent's turn… », `t04` « one that was already on its way… » |
| **B02** | combat bloqué, mise séquestrée après un redémarrage | `t07` « after a restart the running battle is closed… » |
| **B03** | cartes et « prêt » perdus par écritures simultanées | `t01` « both players adding at once », `t03` « both pressing Ready… » |
| **B04** | tableau supprimé = combat bloqué | `t07` « a deleted board: the battle goes on… » |
| **B05** | Ready avec un deck vide = impasse | `t03` « Ready with an empty deck is refused on the spot » |
| **B06** | « attacks instead » n'attaquait pas | `t04` « "attacks instead" is a real attack » |
| **B07** | double Ready = double séquestre, deux tableaux | `t03` « the wager was taken ONCE from each » |
| **B08** | `Buff.save()` plantait | `t04` « a Buff row can be saved » |
| **B09** | `updated_at` figé, rechargement qui annulait un combat en cours | `t07` « a long battle still being played is not cancelled by a reload » |
| **B10** | une proposition verrouillait l'invité | `t01` « a player who was only INVITED can start a battle of their own » |
| **B11** | deux `/battle start` simultanés = deux sessions | `t01` « two /battle start at once… » |
| **B12** | aucune commande pour sortir d'un combat | `t01`, `t06`, `t07` « /battle leave… » |
| **B13** | carte donnée après `/battle add` qui se battait quand même | `t01` « cards that left their owner » |
| **B14** | `max_size` sans plafond | `t01` « a deck of 11 is refused » |
| **B15** | ✅ resté affiché après un refus de mise | `t03` « the proposal no longer shows anybody as ready » |
| **B16** | Capacity jamais esquivée | `t04` « a damaging Capacity is dodged like any other hit » |
| **B17** | erreur non rattrapée sur un objet épuisé | `t07` « an item that is gone: said plainly… » |
| **B18** | double achat = un objet pour deux paiements | `t07` « two purchases at once: two items, paid twice » |
| **B19** | clic sans réponse sur un combat clos | `t07` « a click on the board of a closed battle gets an answer » |
| **B20** | horloge repoussée à chaque clic, pas de forfait hors tour | `t07` « stalling », `t06` « forfeit by the player whose turn it is not… » |
| **B21** | deux actions sur un tour = double paiement, boutons fantômes | `t07` « actions landing together » |
| **B22** | classement : page 2 polluée, doublon au retour | `t06` « page 2 shows page 2 only » |
| **B23** | vue de proposition jamais libérée | `t06` « nothing of the battle is left listening… » |
| **B24** | mouvements de berries inscrits « unknown » | `t03`, `t04`, `t06`, `t07` (les quatre motifs) |

## 4. Remarques (aucun test en échec)

Deux remarques de la deuxième passe ont été reprises par la session principale et sont testées : les boutons
de tour d'avant un rechargement sont arrêtés une fois le tour joué, et le panneau refuse une durée de tour sous
10 secondes.

Nouveau dans cette passe :

- **Un nom à point ne se trouve pas en le tapant en entier.** Dans `/battle add` et dans l'objet de
  `/battle equip`, taper « Monkey D. Luffy » ne trouve rien ; « luffy » trouve la carte. La recherche retire
  les points de ce qui est tapé mais pas des noms (`battle_ext/arguments.py`, `value.replace(".", "")`). C'est
  la recherche du reste du bot, reprise telle quelle, donc le défaut existe partout ; ici il touche **27
  personnages actifs**, dont Luffy, Ace, Barbe Noire et Roger. Les listes lues dans le deck, elles, trouvent
  « Monkey D. Luffy » tapé en entier.
- **Un `flat_damage` de `Buff` ne suit pas le multiplicateur de vie** : c'est un montant fixe. À ×3 il pèse
  trois fois moins face à la vie adverse, alors qu'un `heal_percent` suit puisqu'il est en pourcentage.
- **Le rapport de puissance des gains change un peu** avec le multiplicateur (36 → 37 dans le scénario), la
  vie comptant double ou triple dans attaque + vie.
- **Le spécial d'une carte pèse davantage côté vie** : un Shiny ajoute 1000 d'attaque et 1000 × le
  multiplicateur de vie.

Toujours vrai :

- Un joueur invité reste « occupé » pour les tiers tant que l'invitation tient, au plus 30 minutes.
- Un forfait avant le premier tour paie la récompense entière (50), une fois par adversaire et par jour.
- Une victoire non payée consomme une des trois victoires garanties.
- Le spécial d'un objet ne compte pas.
- Le dump ne contient ni `Buff` ni `BattleItem` : la boutique répond « empty ».

## 5. Équilibrage

Simulateur : `engine.resolve_action` avec les multiplicateurs du cog, sur des cartes construites par
`serialize_ball`, `equip_percent`, `serialize_item` et `apply_equipment`. Vérifié contre le vrai cog : mêmes
decks, même graine, même politique → même gagnant au même tour, 12 combats sur 12. Chaque chiffre porte sur
1 000 combats, les deux decks ouvrant à tour de rôle sauf mention contraire.

Réglages : ceux de la base au dernier passage, donc **vie ×3**, barème de rareté de 0.9 à 1.0, Capacity
esquivable.

Decks types, choisis par règle : dans un palier, les quatre personnages actifs dotés d'un fruit canonique les
plus proches de la médiane du palier. Politique : attaque sûre si elle suffit à tuer, sinon Capacity, sinon Crit
Gamble.

| Palier | Deck | Puissance nue | Avec leurs fruits |
|---|---|---|---|
| T1-15 | Loki, Kuzan, Barbe Noire, Kizaru | 5 188 | 22 805 |
| T16-35 | Ace, Kuma, Saturn, Sengoku | 2 898 | 13 984 |
| T36-85 | Morley, Perona, Jabra, Ivankov | 1 462 | 5 472 |
| T86-140 | Caribou, Shinobu, Caesar Clown, Hina | 1 132 | 5 584 |
| T141-180 | Streusen, Tamago, Pekoms, Machvise | 973 | 3 163 |
| T181+ | Babe, Tama, Miss Merry Christmas, Alvida | 669 | 2 443 |

(Puissance = attaque + vie de tout le deck, vie multipliée par 3.)

**Ce que le multiplicateur de vie change.** Mêmes decks contre eux-mêmes :

| | Durée, T1-15 nu | Celui qui ouvre gagne | Durée, T1-15 équipé | Celui qui ouvre gagne | Se soigner sous 35 % |
|---|---|---|---|---|---|
| ×1 | 10,5 tours | 60,4 % | 8,8 tours | 78,4 % | 38,5 % de victoires |
| ×2 | 21,3 tours | 56,9 % | 16,6 tours | 59,2 % | 39,5 % |
| ×3 | 29,8 tours | 55,3 % | 22,4 tours | 58,6 % | 54,9 % |

Le réglage fait ce qu'on lui demande : à ×3 un combat à quatre cartes dure trois fois plus longtemps, l'avantage
de celui qui ouvre retombe de 78 % à 59 % entre decks équipés, et se soigner cesse d'être une erreur. Il ne
change rien au rapport de force entre decks : T36-85 dans ses fruits contre T1-15 nu reste à 56-57 % aux trois
valeurs.

**La rareté seule.** Sans équipement, un deck bat le palier du dessous à 100 % jusqu'à T36-85, puis à 98,8 %,
91,1 % et 99,9 %. Des combats plus longs laissent moins de place à la chance.

**L'équipement rattrape-t-il un deck rare ? Seulement s'il est nu.**

| Deck modeste | Deck rare | Victoires du modeste | Puissances |
|---|---|---|---|
| T36-85, ses fruits | T16-35 nu | 100,0 % | 5 472 / 2 898 |
| T36-85, ses fruits | T1-15 nu | 56,7 % | 5 472 / 5 188 |
| T36-85, ses fruits + une arme | T1-15 nu | 94,6 % | 6 689 / 5 188 |
| T36-85, objets quelconques | T16-35 nu | 82,6 % | 3 361 / 2 898 |
| T36-85, objets quelconques | T1-15 nu | 0,0 % | 3 361 / 5 188 |
| T141-180, ses fruits | T36-85 nu | 100,0 % | 3 163 / 1 462 |
| T141-180, ses fruits | T16-35 nu | 64,0 % | 3 163 / 2 898 |
| T141-180, ses fruits | T1-15 nu | 0,0 % | 3 163 / 5 188 |
| T36-85, ses fruits | T1-15, objets quelconques | 0,0 % | 5 472 / 12 022 |
| T36-85, ses fruits | T1-15, ses fruits | 0,0 % | 5 472 / 22 805 |
| T16-35, ses fruits | T1-15, ses fruits | 0,0 % | 13 984 / 22 805 |
| T141-180, ses fruits | T36-85, objets quelconques | 26,4 % | 3 163 / 3 361 |
| T141-180, objets T1-15 à 50 % | T1-15 nu | 90,1 % | 6 494 / 5 188 |
| T141-180, objets T1-15 à 50 % | T1-15, ses fruits | 0,0 % | 6 494 / 22 805 |

Un deck modeste dans ses propres fruits remonte d'environ deux paliers face à des decks nus. Dès que le deck
rare porte quoi que ce soit, même des objets qui ne sont pas les siens, le modeste retombe à 0 %. L'équipement
multiplie la puissance par 4,4 en T1-15 contre 3,3 en T141-180 : il creuse l'écart, parce que les fruits des
personnages rares sont eux-mêmes les plus forts.

**Objet canonique contre objet quelconque.** Mêmes personnages, mêmes fruits, distribués à leur propriétaire
(200 %) ou au voisin (50 %) : le canonique gagne 100 %. N'importe quel objet contre rien : 100 %. Ajouter une
arme à son fruit : 79,6 % en T1-15, 88,7 à 96,5 % ailleurs.

**La puissance totale prédit le résultat**, plus nettement encore qu'à ×1. Sur 304 confrontations de decks :

| Rapport de puissance | Victoires |
|---|---|
| 0,50 à 0,70 | 0,1 % |
| 0,70 à 0,85 | 5,1 % |
| 0,85 à 0,95 | 26,8 % |
| 0,95 à 1,05 | 50,0 % |
| 1,05 à 1,18 | 78,8 % |
| 1,18 à 1,43 | 94,5 % |
| 1,43 à 2,00 | 100,0 % |

**Déroulement d'un combat à ×3 (deck contre lui-même).**

- Durée : 22 à 34 tours à quatre cartes contre quatre. Avec une horloge de 60 secondes, un combat où les deux
  joueurs laissent filer chaque tour dure donc une demi-heure.
- Celui qui ouvre gagne 52,7 % à 58,6 % selon le palier et l'équipement. C'est toujours l'auteur de
  `/battle start` qui ouvre.
- Crit Gamble à chaque tour bat Attack à chaque tour 78,7 % du temps : sur un combat long, le bouton Attack
  n'a plus d'intérêt que pour achever.
- Un joueur présent bat un joueur absent (l'horloge attaque pour lui) 88,1 % du temps.
- Se soigner sous 35 % de vie est devenu légèrement payant : 54,9 % de victoires contre la même politique sans
  soin.

## 6. Ce qui n'a pas été testé

- **L'API Discord réelle.** Permissions, limites de débit, refus côté serveur. L'expiration du jeton
  d'interaction et les limites des listes (25 choix, 100 caractères) sont vérifiées sur ce que le code produit,
  pas sur ce que Discord accepte.
- **Les courses entre clics** sont reproduites dans une seule boucle d'événements, avec une latence simulée.
- **Un vrai redémarrage.** Simulé en rappelant le `setup()` du package avec un bot non connecté.
- **Deux processus** servant le même combat : les verrous du cog sont en mémoire, seules les transactions de
  `sessions.py` protègent entre processus.
- **La liste noire** (le faux bot laisse passer tout le monde) et **les emojis** (`get_emoji` ne rend rien ici,
  donc les libellés des listes sont testés sans emoji).
- **L'admin** au-delà de `manage.py check`, et **le chargeur d'équipement** autrement qu'à blanc.
- **Les écouteurs du bus** (succès, pass) : seul l'envoi de `BATTLE_WIN` et `BATTLE_PLAYED` est vérifié.
- **L'équilibrage avec `Buff` et objets de boutique** : les deux tables sont vides dans le dump.

## 7. Le harnais

`battle_tests/harness.py` : `django.setup()`, les caches remplis comme `BallsDexBot.load_cache`, puis de faux
objets Discord qui enregistrent ce que le cog envoie et refusent ce que Discord refuserait : répondre deux fois
à une interaction, suivre avant d'avoir répondu, éditer un message supprimé, cliquer un bouton grisé, éditer un
message de suivi quinze minutes après. Un clic passe par `View._scheduled_task` de discord.py ; les horloges de
tour sont les vraies tâches du cog.

Un argument de commande est lu par le transformateur que le cog a donné à ce paramètre, et sa liste
d'autocomplétion est demandée à ce même paramètre.

Le hasard du moteur est remplacé par une suite de tirages écrite d'avance dans les tests de règles, et rendu au
vrai `random` avec une graine dans la simulation. Les réglages ne sont jamais modifiés en base : un test qui en
veut d'autres les surcharge pour son cog seulement, et le multiplicateur de vie est tenu à 1 par défaut.

Un seul fichier de test tourne à la fois sur la base : chacun prend un verrou PostgreSQL (`pg_advisory_lock`)
avant de commencer et attend son tour s'il est pris. Sans cela, deux sessions qui rejouent la suite en même
temps se font échouer l'une l'autre.

Chaque fichier possède mille identifiants Discord à partir de 9 000 000 000 000 000 000 et efface ses joueurs
avant et après (cartes, sessions, combats, registre de berries suivent en cascade). Les lignes `Buff` créées par
les tests portent une marque dans `capacity_value` (partie décimale 0,0625), les objets de boutique le préfixe
`ZZTEST ` ; les deux sont effacés avant et après.
